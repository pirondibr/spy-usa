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
    home = f"https://{dom}/" if dom else ""
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
            analyzed = analyze_similarity(home, client_url, briefing) or analyzed
    except Exception as e:
        analyzed["motivo"] = f"Added manually (classify failed: {e})"
    sim = forced or normalize_similarity(analyzed.get("similaridade") or "") or "Medio"

    page_title = ""
    try:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.get(
            home,
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
        "url": home,
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


def delete_competitors(run_id: str, domains: list[str] | tuple[str, ...] | str) -> dict[str, Any]:
    report = _load(run_id)
    if isinstance(domains, str):
        raw = [domains]
    else:
        raw = list(domains or [])
    want = {_domain_of(d) for d in raw}
    want.discard("")
    if not want:
        raise ValueError("Select at least one competitor")
    rows = _rows_of(report)
    kept: list[dict[str, Any]] = []
    removed: list[str] = []
    for row in rows:
        dom = _domain_of(row.get("domain") or "")
        if row.get("is_client") or dom not in want:
            kept.append(row)
            continue
        removed.append(dom)
    if not removed:
        raise ValueError("No matching competitors to delete")
    _recheck_brand_fp(report, kept)
    _refresh_rows(report, kept)
    persist_report(run_id, report)
    return {
        "ok": True,
        "deleted": removed,
        "count": len(removed),
        "html_url": f"/runs/{run_id}/report.html",
    }


def _fold_token(value: str) -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = raw.replace("www.", "")
    raw = re.sub(r"[^a-z0-9]+", "", raw)
    return raw


def _phrase_words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _brand_hints(row: dict[str, Any]) -> set[str]:
    hints: set[str] = set()
    domain = _domain_of(row.get("domain") or "")
    token = domain.split(".")[0] if domain else ""
    for raw in (
        row.get("brand_keyword"),
        row.get("name"),
        token,
        domain,
    ):
        t = _fold_token(str(raw or ""))
        if len(t) >= 3:
            hints.add(t)
    return hints


def _brand_parts(row: dict[str, Any]) -> tuple[str, str, str]:
    domain = _domain_of(row.get("domain") or "")
    brand = (domain.split(".")[0] if domain else "") or _fold_token(row.get("brand_keyword") or "")
    tld = domain.split(".")[-1] if "." in domain else ""
    return domain, brand, tld


def _keyword_specificity(phrase: str, row: dict[str, Any]) -> int:
    """Higher = more like a real brand query, not a generic category word."""
    _vendor_path()
    from brand_false_positive import GENERIC_BRAND_WORDS  # noqa: E402

    _domain, brand, tld = _brand_parts(row)
    folded = _fold_token(phrase)
    words = _phrase_words(phrase)
    if not folded or not brand:
        return 0
    if tld and folded == brand + tld:
        return 100
    if tld and brand in words and tld in words:
        return 90
    if folded == brand or words == [brand]:
        return 10 if brand in GENERIC_BRAND_WORDS else 60
    if brand in words or brand in folded:
        extra = [w for w in words if w != brand]
        if extra and any(w not in GENERIC_BRAND_WORDS for w in extra):
            return 70
        return 25
    return 0


def _phrase_tiebreak(phrase: str, row: dict[str, Any]) -> int:
    """Among equally specific hits, prefer 'dropship io' then 'dropship.io'."""
    _domain, brand, tld = _brand_parts(row)
    compact = re.sub(r"\s+", " ", phrase.lower().strip())
    if tld and compact == f"{brand} {tld}":
        return 3
    if tld and compact == f"{brand}.{tld}":
        return 2
    if tld and _fold_token(compact) == brand + tld:
        return 1
    return 0


def _pick_brand_keyword(keywords: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any] | None:
    hints = _brand_hints(row)
    if not hints:
        return None
    best = None
    best_key = (-1, -1, -1)
    for item in keywords or []:
        phrase = str(item.get("phrase") or item.get("palavra_chave") or "").strip()
        folded = _fold_token(phrase)
        if len(folded) < 3:
            continue
        if not any(h in folded or folded in h for h in hints):
            continue
        try:
            vol = int(item.get("volume") or 0)
        except (TypeError, ValueError):
            vol = 0
        score = _keyword_specificity(phrase, row)
        if score <= 0:
            continue
        key = (score, _phrase_tiebreak(phrase, row), vol)
        if key > best_key:
            best = {**item, "phrase": phrase, "volume": vol}
            best_key = key
    return best


def _series_field(series: list[dict[str, Any]], ym: str, field: str) -> Any:
    for p in series or []:
        if str(p.get("date") or "") == ym:
            try:
                return int(p.get(field) or 0)
            except (TypeError, ValueError):
                return 0
    return None


def fetch_semrush_brand_extra(run_id: str, domain: str, kind: str) -> dict[str, Any]:
    """Manual per-row Semrush brand extras: branded traffic or top-10 brand keyword."""
    want = _domain_of(domain)
    if not want:
        raise ValueError("Domain is required")
    mode = (kind or "").strip().lower()
    if mode not in ("marca", "pesquisar"):
        raise ValueError("kind must be marca or pesquisar")
    report = _load(run_id)
    rows = _rows_of(report)
    row = next((c for c in rows if _domain_of(c.get("domain") or "") == want), None)
    if not row:
        raise ValueError(f"Competitor not found: {want}")

    _vendor_path()
    market = str(report.get("market") or "").strip().lower() or "us"
    db = "br" if market == "br" else "us"

    if mode == "marca":
        from seo_pipeline import fetch_semrush_monthly_trend  # noqa: E402

        series = fetch_semrush_monthly_trend(want, db=db)
        if not series:
            raise ValueError(f"Semrush MonthlyTrend empty for {want}")
        row["sm_marca_aug_2026"] = _series_field(series, "2026-08", "branded")
        row["sm_marca_aug_2025"] = _series_field(series, "2025-08", "branded")
        row["sm_marca_aug_2024"] = _series_field(series, "2024-08", "branded")
        row["sm_marca_source"] = "semrush_branded"
    else:
        from semrush_keywords import fetch_top_keywords  # noqa: E402
        from brand_dataforseo import august_windows, fetch_brand_volumes  # noqa: E402

        keywords = fetch_top_keywords(want, db=db, limit=20)
        unique: list[dict[str, Any]] = []
        seen_kw: set[str] = set()
        for item in keywords:
            phrase = str(item.get("phrase") or "").strip().lower()
            if not phrase or phrase in seen_kw:
                continue
            seen_kw.add(phrase)
            unique.append(item)
            if len(unique) >= 10:
                break
        picked = _pick_brand_keyword(unique, row)
        if not picked:
            raise ValueError(f"No brand keyword in Semrush top 10 for {want}")
        phrase = str(picked.get("phrase") or "").strip()
        volumes = fetch_brand_volumes([phrase])
        data = volumes.get(phrase.lower()) or {}
        aug = august_windows(data.get("monthly") or [])
        row["sm_kw"] = phrase
        row["sm_kw_volume"] = picked.get("volume")
        row["sm_kw_aug_2026"] = aug.get("vol_2026_08")
        row["sm_kw_aug_2025"] = aug.get("vol_2025_08")
        row["sm_kw_aug_2024"] = aug.get("vol_2024_08")
        if row["sm_kw_aug_2026"] is None and picked.get("volume") is not None:
            row["sm_kw_aug_2026"] = picked.get("volume")
        row["sm_kw_source"] = "semrush_top10"

    persist_report(run_id, report)
    return {
        "ok": True,
        "kind": mode,
        "domain": want,
        "keyword": row.get("sm_kw") or "",
        "html_url": f"/runs/{run_id}/report.html",
    }


def _sw_missing(row: dict[str, Any]) -> bool:
    if not _domain_of(row.get("domain") or row.get("url") or ""):
        return False
    return row.get("similarweb_visits") in (None, "")


def _apply_similarweb_row(row: dict[str, Any], sw: dict[str, Any]) -> None:
    visits = sw.get("traffic")
    if visits is None:
        visits = sw.get("latest_visits")
    if visits is None:
        visits = 0
    row["similarweb_visits"] = visits
    row["similarweb_fmt"] = sw.get("traffic_fmt") or ""
    row["similarweb_error"] = sw.get("error") or ""
    row["similarweb_checked"] = True


def fetch_missing_similarweb(run_id: str, *, limit: int = 6) -> dict[str, Any]:
    """Fill the next chunk of competitor rows that never got SimilarWeb."""
    report = _load(run_id)
    rows = _rows_of(report)
    pending = [c for c in rows if _sw_missing(c)]
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = 6
    cap = max(1, min(cap, 12))
    batch = pending[:cap]
    if not batch:
        return {
            "ok": True,
            "checked": 0,
            "remaining": 0,
            "domains": [],
            "html_url": f"/runs/{run_id}/report.html",
        }

    _vendor_path()
    from similarweb_traffic import traffic_reports_batch  # noqa: E402

    try:
        sw_rows = traffic_reports_batch(batch)
        batch_error = ""
    except Exception as e:
        sw_rows = []
        batch_error = str(e)
    by_dom = {(_domain_of(r.get("domain") or "") or ""): r for r in sw_rows}
    checked: list[str] = []
    for row in batch:
        dom = _domain_of(row.get("domain") or row.get("url") or "")
        sw = by_dom.get(dom) or {}
        if not sw and batch_error:
            _apply_similarweb_row(row, {"traffic": 0, "traffic_fmt": "—", "error": batch_error})
        else:
            _apply_similarweb_row(row, sw)
        if dom:
            checked.append(dom)

    report["include_similarweb_alto"] = True
    _refresh_rows(report, rows)
    persist_report(run_id, report)
    remaining = sum(1 for c in rows if _sw_missing(c))
    return {
        "ok": True,
        "checked": len(checked),
        "remaining": remaining,
        "error": batch_error,
        "domains": checked,
        "html_url": f"/runs/{run_id}/report.html",
    }
