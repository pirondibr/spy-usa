# -*- coding: utf-8 -*-
"""Assemble a compare_all report by merging per-slug individual caches."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from parse_input import normalize_url, slugify_client

# Channel keys that hold a `rows` list of company metrics
CHANNEL_KEYS = (
    "google_ads",
    "meta",
    "linkedin",
    "brand",
    "seo",
    "similarweb",
    "brand_dataforseo",
    "youtube",
    "youtube_influencers",
    "instagram",
    "instagram_influencers",
    "tiktok",
    "reddit",
    "twitter",
    "linkedin_profile",
)


def company_meta(url: str, name: str = "", slug: str = "") -> dict[str, str]:
    """Normalize one company entry for All merge."""
    nu = normalize_url(url) or (url or "").strip()
    s = (slug or slugify_client(nu or name or url)).strip()
    host = ""
    if nu:
        try:
            host = (urlparse(nu).netloc or "").replace("www.", "").lower()
        except Exception:
            host = ""
    display = (name or "").strip() or (host.split(".")[0].capitalize() if host else s)
    domain = host or s
    return {
        "slug": s,
        "url": nu or f"https://{domain}/",
        "name": display,
        "domain": domain,
    }


def companies_from_primary_and_peers(
    primary_url: str,
    primary_name: str,
    primary_slug: str,
    peer_urls: list[str],
) -> list[dict[str, str]]:
    """Ordered list: primary first, then peers (deduped by slug)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_url, name, slug in [
        (primary_url, primary_name, primary_slug),
        *[(p, "", "") for p in (peer_urls or [])],
    ]:
        meta = company_meta(raw_url, name=name, slug=slug)
        key = meta["slug"]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(meta)
    return out


def _pick_client_row(section: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(section, dict):
        return None
    rows = section.get("rows") or []
    for r in rows:
        if r.get("is_client"):
            return deepcopy(r)
    return deepcopy(rows[0]) if len(rows) == 1 else (deepcopy(rows[0]) if rows else None)


def _retag_row(
    row: dict[str, Any],
    *,
    company: dict[str, str],
    is_client: bool,
) -> dict[str, Any]:
    out = deepcopy(row) if row else {}
    out["name"] = company.get("name") or out.get("name") or company.get("slug")
    out["domain"] = company.get("domain") or out.get("domain") or ""
    out["site_url"] = out.get("site_url") or company.get("url") or ""
    out["is_client"] = bool(is_client)
    out["similaridade"] = "Cliente" if is_client else (out.get("similaridade") or "—")
    return out


def merge_section_rows(
    company_sections: list[tuple[dict[str, str], Optional[dict[str, Any]]]],
    *,
    client_index: int = 0,
) -> Optional[dict[str, Any]]:
    """Merge per-company sections into one multi-row section. Returns None if empty."""
    base: Optional[dict[str, Any]] = None
    rows_out: list[dict[str, Any]] = []
    for i, (company, section) in enumerate(company_sections):
        if not isinstance(section, dict):
            continue
        if base is None:
            base = {k: v for k, v in section.items() if k != "rows"}
        row = _pick_client_row(section)
        if not row:
            continue
        rows_out.append(_retag_row(row, company=company, is_client=(i == client_index)))
    if not rows_out:
        return None
    out = dict(base or {})
    out["rows"] = rows_out
    # Prefer primary (client) for summary heroes
    client = rows_out[client_index] if client_index < len(rows_out) else rows_out[0]
    if "total_traffic_fmt" in out or client.get("traffic_fmt") is not None:
        out["total_traffic_fmt"] = (
            client.get("traffic_fmt")
            or client.get("total_likes_fmt")
            or client.get("followers_fmt")
            or client.get("total_comments_fmt")
            or out.get("total_traffic_fmt")
            or "—"
        )
    if "total_ads_fmt" in out or client.get("ads_fmt") is not None:
        out["total_ads_fmt"] = client.get("ads_fmt") or out.get("total_ads_fmt") or "0"
    if "total_fmt" in out or client.get("value_fmt") is not None:
        out["total_fmt"] = client.get("value_fmt") or client.get("ads_fmt") or out.get("total_fmt") or "—"
    if client.get("growth_fmt") is not None:
        out["growth_fmt"] = client.get("growth_fmt")
    if client.get("growth_1y_pct") is not None:
        out["growth_1y_pct"] = client.get("growth_1y_pct")
    out["leader"] = client.get("name") or out.get("leader") or "—"
    return out


def load_company_report(
    slug: str,
    *,
    url: str = "",
    name: str = "",
    find_metricas_xlsx: Callable[[str], Any],
    build_report_from_xlsx: Callable[..., dict],
    attach_fns: list[Callable[[dict, str], dict]],
) -> dict[str, Any]:
    """Load one company's report from its metricas cache + JSON sidecars."""
    xlsx = find_metricas_xlsx(slug)
    if not xlsx:
        raise FileNotFoundError(f"No metrics cache for slug={slug}")
    xlsx_path = xlsx if hasattr(xlsx, "exists") else None
    if xlsx_path is not None and not xlsx_path.exists():
        raise FileNotFoundError(f"No metrics cache for slug={slug}")
    client_name = name or slug
    report = build_report_from_xlsx(
        xlsx,
        client_name=client_name,
        preferred_competitors=[],
    )
    for fn in attach_fns:
        report = fn(report, slug)
    report["client"] = report.get("client") or client_name
    if url and isinstance(report.get("briefing"), dict):
        report["briefing"].setdefault("url", url)
    return report


def assemble_compare_all_report(
    companies: list[dict[str, str]],
    per_company_reports: list[dict[str, Any]],
    *,
    market: str = "US",
) -> dict[str, Any]:
    """Merge N individual reports into one compare_all report (primary = index 0)."""
    if not companies or not per_company_reports:
        raise ValueError("companies and reports required")
    if len(companies) != len(per_company_reports):
        raise ValueError("companies/reports length mismatch")

    primary = companies[0]
    primary_report = per_company_reports[0]
    merged: dict[str, Any] = {
        "client": primary.get("name") or primary.get("slug"),
        "market": (market or "US").upper(),
        "compare_all": True,
        "briefing": deepcopy(primary_report.get("briefing") or {}),
        "competitors": [],
        "competitors_raw": [],
        "competitors_count": max(0, len(companies) - 1),
        "competitors_note": (
            f"Modo All — {len(companies)} empresas (cache merge, sem discovery)."
        ),
        "competitors_stats": {},
        "filter_meta": {"source": "compare_all_cache_merge"},
        "growth_period_label": primary_report.get("growth_period_label"),
        "source_xlsx": "merged-from-individual-caches",
    }
    if isinstance(merged["briefing"], dict):
        merged["briefing"]["url"] = primary.get("url") or merged["briefing"].get("url") or ""

    def _briefing_nicho(briefing: Any) -> str:
        if not isinstance(briefing, dict):
            return ""
        for key in ("nicho_principal", "nicho", "nicho_especifico", "nicho_medio"):
            val = str(briefing.get(key) or "").strip()
            if val and val not in ("—", "-", "n/d"):
                return val
        return ""

    def _client_row(src: dict[str, Any]) -> dict[str, Any]:
        for row in src.get("competitors_raw") or src.get("competitors") or []:
            if isinstance(row, dict) and row.get("is_client"):
                return row
        return {}

    primary_nicho = _briefing_nicho(merged.get("briefing") or {})
    for i, company in enumerate(companies):
        src = per_company_reports[i] if i < len(per_company_reports) and isinstance(per_company_reports[i], dict) else {}
        own = _client_row(src)
        brief = src.get("briefing") if isinstance(src.get("briefing"), dict) else {}
        dfs_rows = ((src.get("brand_dataforseo") or {}).get("rows") or []) if isinstance(src.get("brand_dataforseo"), dict) else []
        dfs_me = next((r for r in dfs_rows if isinstance(r, dict) and r.get("is_client")), dfs_rows[0] if dfs_rows else {})
        if not isinstance(dfs_me, dict):
            dfs_me = {}
        title = str(own.get("title") or dfs_me.get("site_title") or dfs_me.get("title") or "").strip()
        entry = {
            "name": company["name"],
            "domain": company["domain"],
            "url": company["url"],
            "is_client": i == 0,
            "similaridade": "Cliente" if i == 0 else "—",
            "nicho": _briefing_nicho(brief) or own.get("nicho") or primary_nicho or "",
            "title": title,
            "site_title": str(dfs_me.get("site_title") or own.get("site_title") or title or "").strip(),
            "started": own.get("started") or "",
            "started_fmt": own.get("started_fmt") or "",
            "started_truncated": bool(own.get("started_truncated")),
        }
        merged["competitors_raw"].append(entry)
        if i > 0:
            merged["competitors"].append(entry)

    for key in CHANNEL_KEYS:
        pairs = [(companies[i], per_company_reports[i].get(key)) for i in range(len(companies))]
        section = merge_section_rows(pairs, client_index=0)
        if section:
            # Keep insight/title from primary when present
            primary_sec = per_company_reports[0].get(key) or {}
            if isinstance(primary_sec, dict):
                for meta_key in ("unit", "source", "analysis_title", "insight", "latest_label", "client_keyword"):
                    if meta_key in primary_sec and meta_key not in section:
                        section[meta_key] = primary_sec[meta_key]
                if primary_sec.get("insight"):
                    section["insight"] = (
                        f"All merge · {len(section.get('rows') or [])} empresas · "
                        f"{primary_sec.get('insight')}"
                    )
            merged[key] = section

    return merged
