# -*- coding: utf-8 -*-
"""Manual competitor add / similarity edits on a saved run report."""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Optional
from urllib.parse import urlparse

from pipeline import FINAL_DIR, RUNS_DIR, _comp_sort_key
from report_html import load_saved_report

_SIM = {
    "alto": "Alto",
    "alta": "Alto",
    "high": "Alto",
    "medio": "Medio",
    "media": "Medio",
    "medium": "Medio",
    "baixo": "Baixo",
    "baixa": "Baixo",
    "low": "Baixo",
}


def normalize_similarity(value: str) -> str:
    raw = (value or "").strip().lower().replace("é", "e").replace("á", "a")
    raw = re.sub(r"[^a-z]", "", raw)
    return _SIM.get(raw, "")


def _vendor_path() -> None:
    vendor = FINAL_DIR / "vendor"
    if str(FINAL_DIR) not in sys.path:
        sys.path.insert(0, str(FINAL_DIR))
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))


def _domain_of(url_or_domain: str) -> str:
    raw = (url_or_domain or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = (urlparse(raw).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host.strip(".")


def _abs_url(url_or_domain: str) -> str:
    raw = (url_or_domain or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    return raw


def _name_from_domain(domain: str) -> str:
    token = (domain or "").split(".")[0]
    token = re.sub(r"[^a-zA-Z0-9]+", "", token)
    if not token:
        return domain or "—"
    return token[:1].upper() + token[1:]


def _rows_of(report: dict[str, Any]) -> list[dict[str, Any]]:
    return list(report.get("competitors_raw") or report.get("competitors") or [])


def _refresh_rows(report: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    rows.sort(key=_comp_sort_key)
    alto = medio = baixo = 0
    for c in rows:
        if c.get("is_client"):
            continue
        sim = str(c.get("similaridade") or "").strip().lower().replace("é", "e")
        if sim == "alto":
            alto += 1
        elif sim == "medio":
            medio += 1
        elif sim == "baixo":
            baixo += 1
    report["competitors"] = rows
    report["competitors_raw"] = rows
    report["competitors_count"] = sum(1 for c in rows if not c.get("is_client"))
    report["competitors_stats"] = {"alto": alto, "medio": medio, "baixo": baixo}


def persist_report(run_id: str, report: dict[str, Any]) -> None:
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load(run_id: str) -> dict[str, Any]:
    report = load_saved_report(run_id, RUNS_DIR)
    if not report:
        raise ValueError(f"Report not found: {run_id}")
    return report


def _enrich_one(row: dict[str, Any], report: dict[str, Any], *, want_sw: Optional[bool] = None) -> None:
    _vendor_path()
    sim = str(row.get("similaridade") or "").strip().lower().replace("é", "e")
    if report.get("include_brand_growth") and row.get("brand_aug_2026") is None:
        from brand_dataforseo import brand_reports_batch  # noqa: E402

        brand_rows = brand_reports_batch([row])
        br = brand_rows[0] if brand_rows else {}
        row["brand_keyword"] = br.get("brand_keyword") or row.get("brand_keyword") or ""
        row["brand_aug_2026"] = br.get("vol_2026_08")
        row["brand_aug_2025"] = br.get("vol_2025_08")
        row["brand_aug_2024"] = br.get("vol_2024_08")
        row["brand_growth_26_24"] = br.get("growth_26_24_pct")
    fetch_sw = report.get("include_similarweb_alto") and (
        row.get("is_client") or sim == "alto"
    )
    if want_sw is False:
        fetch_sw = False
    if fetch_sw and row.get("similarweb_visits") in (None, ""):
        from similarweb_traffic import traffic_reports_batch  # noqa: E402

        sw_rows = traffic_reports_batch([row])
        sw = sw_rows[0] if sw_rows else {}
        row["similarweb_visits"] = sw.get("traffic") or sw.get("latest_visits")
        row["similarweb_fmt"] = sw.get("traffic_fmt") or ""
        row["similarweb_error"] = sw.get("error") or ""
    if not str(row.get("started") or "").strip():
        from semrush_started import attach_started_batch  # noqa: E402

        attach_started_batch(
            [row],
            market=str(report.get("market") or ""),
            only_missing=True,
        )


def _recheck_brand_fp(report: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not report.get("include_brand_growth"):
        return
    _vendor_path()
    try:
        from brand_false_positive import flag_brand_false_positives  # noqa: E402

        flag_brand_false_positives(rows)
        report["brand_fp_checked"] = True
    except Exception:
        pass


def set_competitor_similarity(run_id: str, domain: str, similaridade: str) -> dict[str, Any]:
    report = _load(run_id)
    want = _domain_of(domain)
    if not want:
        raise ValueError("Domain is required")
    sim = normalize_similarity(similaridade)
    if not sim:
        raise ValueError("Similarity must be Alto, Medio or Baixo")
    rows = _rows_of(report)
    row = next((c for c in rows if _domain_of(c.get("domain") or "") == want), None)
    if not row:
        raise ValueError(f"Competitor not found: {want}")
    if row.get("is_client"):
        raise ValueError("Cannot change the client row")
    row["similaridade"] = sim
    row["similaridade_manual"] = True
    if sim == "Alto":
        _enrich_one(row, report, want_sw=True)
    _refresh_rows(report, rows)
    persist_report(run_id, report)
    return {"ok": True, "domain": want, "similaridade": sim, "html_url": f"/runs/{run_id}/report.html"}


_SITE_SPLIT = re.compile(r"[\s,;|]+")


def parse_site_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        parts = [str(x or "") for x in value]
    else:
        parts = _SITE_SPLIT.split(str(value or ""))
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        raw = part.strip()
        if not raw or raw.startswith("#"):
            continue
        href = _abs_url(raw)
        dom = _domain_of(href)
        if not dom or "." not in dom:
            continue
        if dom in seen:
            continue
        seen.add(dom)
        out.append(href)
    return out


def add_competitor(run_id: str, url: str, similaridade: str = "") -> dict[str, Any]:
    report = _load(run_id)
    href = _abs_url(url)
    dom = _domain_of(href)
    if not dom:
        raise ValueError("A valid website URL is required")
    rows = _rows_of(report)
    if any(_domain_of(c.get("domain") or "") == dom for c in rows):
        return {
            "ok": True,
            "skipped": True,
            "domain": dom,
            "reason": "already",
            "html_url": f"/runs/{run_id}/report.html",
        }

    briefing = report.get("briefing") or {}
    client_url = str(briefing.get("url") or "").strip()
    forced = normalize_similarity(similaridade)
    analyzed = {"nicho": "—", "similaridade": forced or "—", "perfil": "—", "motivo": "Added manually"}
    _vendor_path()
    try:
        from seo_pipeline import analyze_similarity  # noqa: E402

        if client_url:
            analyzed = analyze_similarity(href, client_url, briefing) or analyzed
    except Exception as e:
        analyzed["motivo"] = f"Added manually (classify failed: {e})"
    sim = forced or normalize_similarity(analyzed.get("similaridade") or "") or "Medio"

    page_title = ""
    try:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.get(
            href,
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SpyUSA/1.0)"},
            allow_redirects=True,
        )
        soup = BeautifulSoup(resp.text or "", "html.parser")
        if soup.title and soup.title.string:
            page_title = re.sub(r"\s+", " ", soup.title.string).strip()[:200]
    except Exception:
        page_title = ""

    row = {
        "name": _name_from_domain(dom),
        "domain": dom,
        "url": href if href.endswith("/") else href + "/",
        "title": page_title,
        "similaridade": sim,
        "perfil": analyzed.get("perfil") or "—",
        "nicho": analyzed.get("nicho") or "—",
        "motivo": analyzed.get("motivo") or "Added manually",
        "fonte": "manual",
        "is_client": False,
        "manual": True,
    }
    _enrich_one(row, report)
    rows.append(row)
    _recheck_brand_fp(report, rows)
    _refresh_rows(report, rows)
    persist_report(run_id, report)
    return {
        "ok": True,
        "domain": dom,
        "similaridade": sim,
        "html_url": f"/runs/{run_id}/report.html",
    }
