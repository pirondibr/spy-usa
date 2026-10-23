# -*- coding: utf-8 -*-
"""Spy USA pipeline: briefing → (concorrentes?) → SEO → Brand → Google Ads → Meta → Social."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional  # noqa: F401 — Any used in helpers

from parse_input import ParsedInput, normalize_url, slugify_client
from report_builder import build_early_briefing_competitors, build_report_from_xlsx
from report_html import render_report_html
from report_merge import (
    assemble_compare_all_report,
    companies_from_primary_and_peers,
    load_company_report,
)
from run_log import RunRecorder, attach_run_log, write_run_log_files

APP_DIR = Path(__file__).resolve().parent
FINAL_DIR = APP_DIR / "scripts"
SCRIPT_ENTENDER = FINAL_DIR / "1- entender o cliente.py"
SCRIPT_CONCORRENTES = FINAL_DIR / "3 - concorrentes Geral.py"
SCRIPT_SEO = FINAL_DIR / "5b - seo organico.py"
SCRIPT_BRAND = FINAL_DIR / "5c - brand search.py"
SCRIPT_GOOGLE = FINAL_DIR / "5a - google ads.py"
SCRIPT_META = FINAL_DIR / "5d - meta ads.py"
SCRIPT_LINKEDIN = FINAL_DIR / "5e - linkedin ads.py"
SCRIPT_BRAND_DFS = FINAL_DIR / "5g - brand dataforseo.py"
SCRIPT_SIMILARWEB = FINAL_DIR / "5h - similarweb.py"
SCRIPT_SOCIAL = FINAL_DIR / "5f - social ig yt.py"
SCRIPT_YT_INFLUENCERS = FINAL_DIR / "5i - youtube influencers.py"
SCRIPT_IG_INFLUENCERS = FINAL_DIR / "5j - instagram influencers.py"
SCRIPT_REDDIT = FINAL_DIR / "5k - reddit mentions.py"
SCRIPT_TWITTER = FINAL_DIR / "5l - twitter profile.py"
SCRIPT_LI_PROFILE = FINAL_DIR / "5m - linkedin profile.py"

_DATA_DIR = (os.environ.get("RADAR_DATA_DIR") or os.environ.get("SPY_DATA_DIR") or "").strip()
_OUT_ROOT = (Path(_DATA_DIR) / "outputs") if _DATA_DIR else (APP_DIR / "outputs")
METRICAS_DIR = _OUT_ROOT / "metricas"
BRIEFING_DIR = _OUT_ROOT / "entender"
CONCORRENTES_DIR = _OUT_ROOT / "concorrentes"
RUNS_DIR = _OUT_ROOT / "runs"

EmitFn = Callable[..., None]

COMPETITORS_ONLY_STEPS = [
    {"id": "briefing_concorrentes", "label": "Briefing", "index": 1, "eta_live": 180},
    {"id": "competitors_discover", "label": "Find competitors", "index": 2, "eta_live": 360},
    {"id": "brand_growth", "label": "Brand growth (Aug 26/25/24)", "index": 3, "eta_live": 40},
    {"id": "similarweb_alto", "label": "SimilarWeb (Alto)", "index": 4, "eta_live": 60},
]

STEP_DEFS = [
    {"id": "briefing_concorrentes", "label": "Briefing (+ competitors)", "index": 1, "eta_live": 180},
    {"id": "seo", "label": "SEO organic (US)", "index": 2, "eta_live": 30},
    {"id": "brand", "label": "Brand search Semrush (US)", "index": 3, "eta_live": 30},
    {"id": "brand_dfs", "label": "Brand DataForSEO (US)", "index": 4, "eta_live": 40},
    {"id": "similarweb", "label": "SimilarWeb Traffic", "index": 5, "eta_live": 60},
    {"id": "google_ads", "label": "Google Ads Library (US)", "index": 6, "eta_live": 180},
    {"id": "meta", "label": "Meta Ads (US)", "index": 7, "eta_live": 180},
    {"id": "linkedin", "label": "LinkedIn Ads Library (US)", "index": 8, "eta_live": 240},
    {"id": "instagram", "label": "Instagram", "index": 9, "eta_live": 120},
    {"id": "youtube", "label": "YouTube", "index": 10, "eta_live": 20},
    {"id": "tiktok", "label": "TikTok", "index": 11, "eta_live": 40},
    {"id": "youtube_influencers", "label": "YouTube Influencers", "index": 12, "eta_live": 90},
    {"id": "instagram_influencers", "label": "Instagram Influencers", "index": 13, "eta_live": 60},
    {"id": "reddit", "label": "Reddit", "index": 14, "eta_live": 45},
    {"id": "twitter", "label": "Twitter / X", "index": 15, "eta_live": 40},
    {"id": "linkedin_profile", "label": "LinkedIn Profile", "index": 16, "eta_live": 20},
]
TOTAL_STEPS = len(STEP_DEFS)


def _load_brand_dfs(slug: str) -> Optional[dict]:
    path = METRICAS_DIR / slug / f"brand-dataforseo-{slug}.json"
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _attach_brand_dfs(report: dict, slug: str) -> dict:
    data = _load_brand_dfs(slug)
    if not data:
        return report
    rows_raw = data.get("rows") or []
    from urllib.parse import quote

    try:
        sys.path.insert(0, str(FINAL_DIR))
        from market import SEMRUSH_DB, MARKET_SHORT  # noqa: E402
        db = SEMRUSH_DB or "us"
        mkt = MARKET_SHORT or "US"
    except Exception:
        db = "us"
        mkt = "US"

    def _dfs_growth(new, old):
        """Same rule as brand_dataforseo._pct: 0/missing baseline → floor 100."""
        if new is None:
            return None
        try:
            new_i = int(new)
        except (TypeError, ValueError):
            return None
        if old is None or old == 0:
            if new_i == 0:
                return 0.0
            return round(((new_i - 100) / 100) * 100, 2)
        try:
            old_i = int(old)
        except (TypeError, ValueError):
            return None
        if old_i == 0:
            return round(((new_i - 100) / 100) * 100, 2) if new_i else 0.0
        return round(((new_i - old_i) / old_i) * 100, 2)

    def _fmt_g(g):
        return f"{g:+.1f}%" if isinstance(g, (int, float)) else "n/a"

    rows = []
    for r in rows_raw:
        vol = r.get("latest_volume")
        # Recompute growth so 0-baseline brands get a rate (volume stays 0 in report)
        g1 = _dfs_growth(vol, r.get("volume_1y"))
        g2 = _dfs_growth(vol, r.get("volume_2y"))
        g3 = _dfs_growth(vol, r.get("volume_3y"))
        g5 = _dfs_growth(vol, r.get("volume_5y"))
        kw = (r.get("brand_keyword") or "").strip()
        kw_url = (
            f"https://www.semrush.com/analytics/keywordoverview/?q={quote(kw)}&db={db}"
            if kw
            else ""
        )
        rows.append({
            "name": r.get("name") or r.get("brand_keyword"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "brand_keyword": r.get("brand_keyword"),
            "traffic": vol or 0,
            "traffic_fmt": f"{vol:,}" if isinstance(vol, int) else (str(vol) if vol is not None else "—"),
            "growth_fmt": _fmt_g(g1),
            "latest_label": r.get("latest_label"),
            "volume_1y": r.get("volume_1y"),
            "volume_2y": r.get("volume_2y"),
            "volume_3y": r.get("volume_3y"),
            "volume_5y": r.get("volume_5y"),
            "growth_1y_pct": g1,
            "growth_2y_pct": g2,
            "growth_3y_pct": g3,
            "growth_5y_pct": g5,
            "site_title": r.get("site_title"),
            "url": kw_url,
        })
    client = next((r for r in rows if r.get("is_client")), rows[0] if rows else {})
    client_raw = next((r for r in rows_raw if r.get("is_client")), rows_raw[0] if rows_raw else {})
    report["brand_dataforseo"] = {
        "source": "dataforseo",
        "market": mkt,
        "latest_label": data.get("latest_label") or client_raw.get("latest_label"),
        "client_keyword": data.get("client_keyword") or client_raw.get("brand_keyword"),
        "leader": (rows[0].get("name") if rows else "—"),
        "total_traffic_fmt": client.get("traffic_fmt") if client else (rows[0].get("traffic_fmt") if rows else "—"),
        "growth_fmt": client.get("growth_fmt") if client else "n/a",
        "growth_1y_pct": client.get("growth_1y_pct") if client else None,
        "unit": "monthly searches",
        "rows": rows,
        "insight": (
            f"Brand keyword «{data.get('client_keyword') or client_raw.get('brand_keyword') or '—'}» "
            f"· latest month {data.get('latest_label') or client_raw.get('latest_label') or 'n/a'} "
            f"· growth 1y {client.get('growth_fmt') or 'n/a'} "
            f"(DataForSEO Google Ads {mkt}). "
            f"Baseline 0 treated as 100 for growth math only."
        ),
        "analysis_title": "Brand Search — DataForSEO",
        "raw": data,
    }
    return report


def _load_similarweb(slug: str) -> Optional[dict]:
    path = METRICAS_DIR / slug / f"similarweb-{slug}.json"
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _attach_similarweb(report: dict, slug: str) -> dict:
    data = _load_similarweb(slug)
    if not data:
        return report
    rows_raw = data.get("rows") or []
    rows: list[dict] = []
    for r in rows_raw:
        rows.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": r.get("traffic") or r.get("latest_visits") or 0,
            "traffic_fmt": r.get("traffic_fmt") or "—",
            "snapshot_date": r.get("snapshot_date"),
            "snapshot_label": r.get("snapshot_label") or "—",
            "bounce_fmt": r.get("bounce_fmt") or "—",
            "pages_fmt": r.get("pages_fmt") or "—",
            "time_fmt": r.get("time_fmt") or "—",
            "is_data_from_ga": bool(r.get("is_data_from_ga")),
            "visits_monthly": r.get("visits_monthly") or [],
            "sources": r.get("sources") or [],
            "countries": r.get("countries") or [],
            "error": r.get("error"),
            "url": r.get("url") or (f"https://{r.get('domain')}/" if r.get("domain") else ""),
        })
    client = next((r for r in rows if r.get("is_client")), rows[0] if rows else {})
    ok_rows = [r for r in rows if not r.get("error")]
    leader = ok_rows[0] if ok_rows else client
    report["similarweb"] = {
        "source": data.get("source") or "apify_similarweb",
        "market": "global",
        "latest_label": data.get("latest_label") or client.get("snapshot_label"),
        "client_domain": data.get("client_domain") or client.get("domain"),
        "leader": leader.get("name") if leader else "—",
        "total_traffic_fmt": (client.get("traffic_fmt") if client else "—"),
        "unit": "visits/mo",
        "rows": rows,
        "insight": (
            f"SimilarWeb traffic for «{client.get('domain') or '—'}» "
            f"· snapshot {client.get('snapshot_label') or data.get('latest_label') or 'n/a'} "
            f"· bounce {client.get('bounce_fmt') or '—'} · "
            f"{client.get('pages_fmt') or '—'} pages/visit · "
            f"{client.get('time_fmt') or '—'} on site."
        ),
        "analysis_title": "SimilarWeb Traffic",
    }
    return report


def _fmt_views(n: Any) -> str:
    try:
        v = int(n or 0)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return f"{v:,}"


def _load_youtube_influencers(slug: str) -> Optional[dict]:
    path = METRICAS_DIR / slug / f"youtube-influencers-{slug}.json"
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _attach_youtube_influencers(report: dict, slug: str) -> dict:
    data = _load_youtube_influencers(slug)
    if not data:
        return report
    rows_out: list[dict] = []
    for r in data.get("rows") or []:
        off = int(r.get("views_official") or 0)
        unoff = int(r.get("views_unofficial") or 0)
        total = off + unoff
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": total,
            "traffic_fmt": _fmt_views(total),
            "views_official": off,
            "views_official_fmt": _fmt_views(off),
            "views_unofficial": unoff,
            "views_unofficial_fmt": _fmt_views(unoff),
            "views_30d": int(r.get("views_30d") or 0),
            "views_30d_fmt": _fmt_views(r.get("views_30d") or 0),
            "views_6m": int(r.get("views_6m") or 0),
            "views_6m_fmt": _fmt_views(r.get("views_6m") or 0),
            "views_1y_plus": int(r.get("views_1y_plus") or 0),
            "views_1y_plus_fmt": _fmt_views(r.get("views_1y_plus") or 0),
            "about_count": r.get("about_count") or 0,
            "page_count": r.get("page_count") or 0,
            "top5": r.get("top5") or [],
            "top5_official": r.get("top5_official") or [],
            "top5_unofficial": r.get("top5_unofficial") or [],
            "url": r.get("search_url") or "",
            "usage": r.get("usage") or {},
            "error": r.get("error"),
        })
    client = next((r for r in rows_out if r.get("is_client")), rows_out[0] if rows_out else {})
    usage = data.get("usage_total") or {}
    report["youtube_influencers"] = {
        "source": "scrapingbee",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("traffic_fmt") if client else "—",
        "unit": "views (1st page)",
        "rows": rows_out,
        "usage_total": usage,
        "insight": (
            f"YouTube 1st-page search for «{client.get('name') or '—'}»: "
            f"official {_fmt_views(client.get('views_official'))} · "
            f"unofficial {_fmt_views(client.get('views_unofficial'))} · "
            f"30d {_fmt_views(client.get('views_30d'))} / "
            f"6m {_fmt_views(client.get('views_6m'))} / "
            f"1y+ {_fmt_views(client.get('views_1y_plus'))} "
            f"(product-relevant only; ScrapingBee credits={usage.get('scrapingbee_credits', '—')})."
        ),
        "analysis_title": "YouTube Influencers",
        "pro_hook": "Na versão Pro mapeamos creators, scripts e oportunidades de menção no YouTube.",
    }
    return report


def _load_instagram_influencers(slug: str) -> Optional[dict]:
    path = METRICAS_DIR / slug / f"instagram-influencers-{slug}.json"
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _attach_instagram_influencers(report: dict, slug: str) -> dict:
    data = _load_instagram_influencers(slug)
    if not data:
        return report
    rows_out: list[dict] = []
    for r in data.get("rows") or []:
        total_likes = int(r.get("total_likes") or 0)
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": total_likes,
            "traffic_fmt": _fmt_views(total_likes),
            "total_influencers": int(r.get("total_influencers") or 0),
            "influencer_posts": int(r.get("influencer_posts") or 0),
            "own_posts": int(r.get("own_posts") or 0),
            "posts_first_page": int(r.get("posts_first_page") or 0),
            "total_likes": total_likes,
            "total_likes_fmt": _fmt_views(total_likes),
            "own_likes_fmt": _fmt_views(r.get("own_likes") or 0),
            "influencer_likes_fmt": _fmt_views(r.get("influencer_likes") or 0),
            "influencer_handles": r.get("influencer_handles") or [],
            "top5": r.get("top5") or [],
            "top5_page": r.get("top5_page") or [],
            "top5_influencers": r.get("top5_influencers") or [],
            "handle": r.get("handle") or "",
            "url": r.get("profile_url") or "",
            "followers_label": r.get("followers_label"),
            "error": r.get("error"),
        })
    client = next((r for r in rows_out if r.get("is_client")), rows_out[0] if rows_out else {})
    usage = data.get("usage_total") or {}
    report["instagram_influencers"] = {
        "source": "tinyfish_search+fetch",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("total_likes_fmt") if client else "—",
        "unit": "likes (1st page)",
        "rows": rows_out,
        "usage_total": usage,
        "insight": (
            f"Instagram @{client.get('handle') or '—'}: "
            f"{client.get('total_influencers') or 0} influencers on 1st page · "
            f"{_fmt_views(client.get('total_likes'))} total likes · "
            f"own {client.get('own_posts') or 0} / influencer posts {client.get('influencer_posts') or 0} "
            f"(Search+Fetch download)."
        ),
        "analysis_title": "Instagram Influencers",
        "pro_hook": "Na versão Pro avaliamos creators, frequência de collabs e custo estimado por menção.",
    }
    return report


def _load_json_metric(slug: str, filename: str) -> Optional[dict]:
    path = METRICAS_DIR / slug / filename
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _attach_reddit(report: dict, slug: str) -> dict:
    data = _load_json_metric(slug, f"reddit-mentions-{slug}.json")
    if not data:
        return report
    rows_out: list[dict] = []
    for r in data.get("rows") or []:
        comments = int(r.get("total_comments") or 0)
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": comments,
            "traffic_fmt": _fmt_views(comments),
            "total_comments": comments,
            "total_comments_fmt": _fmt_views(comments),
            "posts_first_page": int(r.get("posts_first_page") or 0),
            "total_results": r.get("total_results"),
            "total_results_fmt": _fmt_views(r.get("total_results")) if r.get("total_results") is not None else "n/d",
            "top_posts": r.get("top_posts") or [],
            "url": r.get("search_url") or "",
            "query": r.get("query") or "",
            "error": r.get("error"),
        })
    client = next((r for r in rows_out if r.get("is_client")), rows_out[0] if rows_out else {})
    usage = data.get("usage_total") or {}
    report["reddit"] = {
        "source": data.get("source") or "tinyfish",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("total_comments_fmt") if client else "—",
        "unit": "comments (1st page)",
        "rows": rows_out,
        "usage_total": usage,
        "insight": (
            f"Reddit site:reddit.com «{client.get('name') or '—'}»: "
            f"{client.get('posts_first_page') or 0} posts on 1st page · "
            f"{_fmt_views(client.get('total_comments'))} comments · "
            f"Google total {client.get('total_results_fmt') or 'n/d'}."
        ),
        "analysis_title": "Reddit",
    }
    return report


def _attach_twitter(report: dict, slug: str) -> dict:
    data = _load_json_metric(slug, f"twitter-profile-{slug}.json")
    if not data:
        return report
    rows_out: list[dict] = []
    for r in data.get("rows") or []:
        followers = r.get("followers")
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": int(followers or 0),
            "traffic_fmt": r.get("followers_text") or _fmt_views(followers or 0),
            "followers": followers,
            "followers_fmt": r.get("followers_text") or (_fmt_views(followers) if followers is not None else "—"),
            "handle": r.get("handle") or "",
            "url": r.get("profile_url") or "",
            "search_url": r.get("search_url") or "",
            "followers_source": r.get("followers_source"),
            "error": r.get("error"),
        })
    client = next((r for r in rows_out if r.get("is_client")), rows_out[0] if rows_out else {})
    usage = data.get("usage_total") or {}
    report["twitter"] = {
        "source": data.get("source") or "tinyfish+scrapingbee",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("followers_fmt") if client else "—",
        "unit": "followers",
        "rows": rows_out,
        "usage_total": usage,
        "insight": (
            f"X/Twitter @{client.get('handle') or '—'}: "
            f"{client.get('followers_fmt') or '—'} followers"
            f"{(' · via ' + str(client.get('followers_source'))) if client.get('followers_source') else ''}."
        ),
        "analysis_title": "Twitter / X",
    }
    return report


def _attach_linkedin_profile(report: dict, slug: str) -> dict:
    data = _load_json_metric(slug, f"linkedin-profile-{slug}.json")
    if not data:
        return report
    rows_out: list[dict] = []
    for r in data.get("rows") or []:
        followers = r.get("followers")
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": int(followers or 0),
            "traffic_fmt": r.get("followers_text") or _fmt_views(followers or 0),
            "followers": followers,
            "followers_fmt": r.get("followers_text") or (_fmt_views(followers) if followers is not None else "—"),
            "kind": r.get("kind") or "",
            "url": r.get("profile_url") or "",
            "search_url": r.get("search_url") or "",
            "title": r.get("title") or "",
            "snippet": r.get("snippet") or "",
            "followers_source": r.get("followers_source"),
            "error": r.get("error"),
        })
    client = next((r for r in rows_out if r.get("is_client")), rows_out[0] if rows_out else {})
    report["linkedin_profile"] = {
        "source": data.get("source") or "tinyfish_search",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("followers_fmt") if client else "—",
        "unit": "followers",
        "rows": rows_out,
        "usage_total": data.get("usage_total") or {},
        "insight": (
            f"LinkedIn {client.get('kind') or 'profile'}: "
            f"{client.get('followers_fmt') or '—'} followers"
            f"{(' · ' + str(client.get('title'))) if client.get('title') else ''}."
        ),
        "analysis_title": "LinkedIn Profile",
    }
    return report

def find_metricas_xlsx(slug: str) -> Optional[Path]:
    folder = METRICAS_DIR / slug
    if not folder.exists():
        return None
    files = sorted(
        folder.glob(f"metricas-concorrentes-{slug}*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        files = sorted(folder.glob("metricas-concorrentes-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def find_briefing_xlsx(slug: str) -> Optional[Path]:
    folder = BRIEFING_DIR / slug
    if not folder.exists():
        return None
    files = sorted(
        folder.glob(f"briefing-cliente-{slug}*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        files = sorted(folder.glob("briefing-cliente-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def find_concorrentes_xlsx(slug: str) -> Optional[Path]:
    folder = CONCORRENTES_DIR / slug
    if not folder.exists():
        return None
    nacional = sorted(
        folder.glob(f"concorrentes-all-{slug}-nacional*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if nacional:
        return nacional[0]
    files = sorted(
        folder.glob(f"concorrentes-all-{slug}*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        files = sorted(folder.glob("concorrentes-all-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def clear_slug_cache(slug: str) -> dict[str, Any]:
    import re
    import shutil

    safe = re.sub(r"[^a-z0-9_-]+", "", (slug or "").strip().lower())[:80]
    if not safe:
        raise ValueError("Invalid slug")
    deleted: list[str] = []
    for base in (METRICAS_DIR, BRIEFING_DIR, CONCORRENTES_DIR):
        folder = (base / safe).resolve()
        try:
            folder.relative_to(base.resolve())
        except ValueError as e:
            raise ValueError(f"Path outside outputs: {folder}") from e
        if folder.exists() and folder.is_dir():
            shutil.rmtree(folder)
            deleted.append(str(folder))
    return {"slug": safe, "deleted": deleted, "cleared": bool(deleted)}


def _normalize_market(market: str) -> str:
    m = (market or "us").strip().lower()
    if m in ("br", "brazil", "brasil", "bra"):
        return "br"
    return "us"


def build_solo_national_xlsx(
    slug: str,
    client_url: str,
    client_name: str,
    *,
    peer_urls: Optional[list[str]] = None,
    market: str = "us",
) -> Path:
    """Concorrentes XLSX sem discovery: só o cliente, ou cliente + peers (modo All)."""
    sys.path.insert(0, str(FINAL_DIR))
    sys.path.insert(0, str(FINAL_DIR / "vendor"))
    from workspace_paths import setup_workspace  # noqa: E402

    setup_workspace()
    from find_concorrentes import build_3period_traffic, normalize_domain  # noqa: E402
    from find_concorrentes_all import _write_growth_sheet, _write_traffic_sheet  # noqa: E402
    from find_concorrentes import read_briefing_from_xlsx  # noqa: E402
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from datetime import datetime

    market = _normalize_market(market)
    briefing_path = find_briefing_xlsx(slug)
    if not briefing_path:
        raise RuntimeError(f"Briefing not found for solo mode: {slug}")
    briefing = read_briefing_from_xlsx(briefing_path)
    url = briefing.get("url") or client_url
    profile = briefing.get("perfil") or "—"
    client_dom = normalize_domain(url)

    peers: list[dict] = []
    seen: set[str] = {client_dom} if client_dom else set()
    for raw in peer_urls or []:
        dom = normalize_domain(raw or "")
        if not dom or dom in seen:
            continue
        seen.add(dom)
        peers.append({
            "domain": dom,
            "url": f"https://{dom}/",
            "titulo": dom,
            "similaridade": "Alto",
            "perfil": "—",
            "fonte": "input",
            "nicho": "—",
        })
        if len(peers) >= 11:  # primary + up to 11 peers (MAX_COMPANIES=12)
            break

    mode_label = "compare_all" if peers else "site_only"
    print(
        f"[SOLO] Semrush traffic ({market}) for {url} + {len(peers)} peer(s) [{mode_label}]",
        flush=True,
    )
    traffic = build_3period_traffic(url, peers, profile)

    out_dir = CONCORRENTES_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"concorrentes-all-{slug}-nacional.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.append(["Spy — site only / compare all (no discovery)"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(["Cliente", client_name])
    ws.append(["URL", url])
    ws.append(["Slug", slug])
    ws.append(["Mode", mode_label])
    ws.append(["Market", market.upper()])
    ws.append(["Peers", str(len(peers))])
    ws.append(["Data", datetime.now().strftime("%d/%m/%Y %H:%M")])

    ws_c = wb.create_sheet("Concorrentes Unificado")
    ws_c.append(["Dominio", "URL", "Titulo", "Similaridade", "Perfil", "Fonte", "Nicho (LLM)"])
    for p in peers:
        ws_c.append([
            p["domain"],
            p["url"],
            p["titulo"],
            p["similaridade"],
            p["perfil"],
            p["fonte"],
            p["nicho"],
        ])

    _write_traffic_sheet(wb, traffic)
    _write_growth_sheet(wb, traffic)
    wb.save(out_path)
    print(f"[SOLO] Saved {out_path}", flush=True)
    return out_path


def _run_script(
    cmd: list[str],
    cwd: Path,
    on_log: Optional[Callable[[str], None]] = None,
    timeout_sec: Optional[int] = None,
    env: Optional[dict[str, str]] = None,
) -> None:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=run_env,
    )
    assert proc.stdout is not None
    tail: list[str] = []

    def _reader() -> None:
        for line in proc.stdout:
            line = line.rstrip("\n\r")
            if not line:
                continue
            tail.append(line)
            if len(tail) > 40:
                del tail[:-40]
            if on_log:
                on_log(line)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    reader.join(timeout=timeout_sec)
    if reader.is_alive():
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        hint = ("\n--- last lines ---\n" + "\n".join(tail[-15:])) if tail else ""
        raise TimeoutError(f"Command exceeded {timeout_sec}s: {' '.join(cmd)}{hint}")
    proc.wait()
    if proc.returncode != 0:
        hint = ("\n--- last lines ---\n" + "\n".join(tail[-20:])) if tail else ""
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}{hint}")


def _fmt_eta(seconds: int) -> str:
    if seconds >= 60:
        return f"~{max(1, round(seconds / 60))} min"
    return f"~{seconds}s"


def _wrap_emit_logger(emit: EmitFn, recorder: RunRecorder) -> EmitFn:
    def _emit(event: str, **payload: Any) -> None:
        if event == "log" and payload.get("line") is not None:
            recorder.add_line(str(payload.get("line") or ""))
        emit(event, **payload)

    return _emit


def _wrap_set_step_timer(set_step: EmitFn, recorder: RunRecorder) -> EmitFn:
    def _set(step_id: str, state: str, detail: str = "") -> None:
        meta = next((s for s in STEP_DEFS if s["id"] == step_id), None)
        recorder.mark_step(
            step_id,
            state,
            detail=detail,
            label=(meta or {}).get("label") or step_id,
        )
        set_step(step_id, state, detail)

    return _set


def _emit_progress(
    emit: EmitFn,
    set_step: EmitFn,
    step_id: str,
    state: str,
    detail: str,
    *,
    steps: Optional[list[dict]] = None,
) -> None:
    defs = steps or STEP_DEFS
    meta = next((s for s in defs if s["id"] == step_id), None)
    index = int(meta["index"]) if meta else 0
    total = len(defs) if steps else TOTAL_STEPS
    eta = int(meta.get("eta_live") or 60) if meta else 60
    set_step(step_id, state, detail)
    emit(
        "progress",
        step_id=step_id,
        state=state,
        detail=detail,
        index=index,
        total=total,
        label=meta["label"] if meta else step_id,
        eta_seconds=eta,
        eta_label=_fmt_eta(eta),
        progress_label=f"Step {index}/{total}",
    )


def _persist_report_with_log(
    run_id: str,
    report: dict,
    parsed: ParsedInput,
    recorder: RunRecorder,
    **save_kw: Any,
) -> Path:
    attach_run_log(report, recorder)
    path = _save_report(run_id, report, parsed, **save_kw)
    try:
        write_run_log_files(RUNS_DIR / run_id, report.get("run_log") or {})
    except Exception as e:
        print(f"[RUN_LOG] persist failed: {e}", flush=True)
    return path


def _save_report(
    run_id: str,
    report: dict,
    parsed: ParsedInput,
    *,
    site_only: bool = False,
    include_google_ads: bool = True,
    include_linkedin: bool = True,
    include_youtube_influencers: bool = False,
    include_instagram_influencers: bool = False,
    include_reddit: bool = False,
    include_twitter: bool = False,
    include_linkedin_profile: bool = False,
    force: bool = False,
    market: str = "us",
    compare_all: bool = False,
    competitors_only: bool = False,
    include_brand_growth: bool = False,
    include_similarweb_alto: bool = False,
) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    import json
    from datetime import datetime, timezone

    market = _normalize_market(market)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "id": run_id,
        "slug": parsed.slug,
        "url": parsed.url,
        "company": parsed.company,
        "status": "done",
        "market": market.upper(),
        "site_only": bool(site_only),
        "compare_all": bool(compare_all),
        "competitors_only": bool(competitors_only),
        "include_brand_growth": bool(include_brand_growth),
        "include_similarweb_alto": bool(include_similarweb_alto),
        "peer_urls": list(parsed.competitors or []),
        "include_google_ads": bool(include_google_ads),
        "include_linkedin": bool(include_linkedin),
        "include_youtube_influencers": bool(include_youtube_influencers),
        "include_instagram_influencers": bool(include_instagram_influencers),
        "include_reddit": bool(include_reddit),
        "include_twitter": bool(include_twitter),
        "include_linkedin_profile": bool(include_linkedin_profile),
        "force": bool(force),
        "created_at": created_at,
        "html_url": f"/runs/{run_id}/report.html",
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    html = render_report_html(report, run_meta=meta)
    html_path = run_dir / "report.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


def _attach_all_sidecars(report: dict, slug: str) -> dict:
    report = _attach_brand_dfs(report, slug)
    report = _attach_similarweb(report, slug)
    report = _attach_youtube_influencers(report, slug)
    report = _attach_instagram_influencers(report, slug)
    report = _attach_reddit(report, slug)
    report = _attach_twitter(report, slug)
    report = _attach_linkedin_profile(report, slug)
    return report


def _run_compare_all_pipeline(
    parsed: ParsedInput,
    emit: EmitFn,
    set_step: EmitFn,
    *,
    run_id: str = "",
    force: bool = False,
    include_google_ads: bool = True,
    include_linkedin: bool = True,
    include_youtube_influencers: bool = False,
    include_instagram_influencers: bool = False,
    include_reddit: bool = False,
    include_twitter: bool = False,
    include_linkedin_profile: bool = False,
    market: str = "us",
) -> dict:
    """Ensure per-slug caches, then merge into one compare_all report (no multi-peer scrape)."""
    market = _normalize_market(market)
    os.environ["SPY_MARKET"] = market
    url = normalize_url(parsed.url) or parsed.url
    if not url:
        raise ValueError("Company URL is required.")
    slug = parsed.slug or slugify_client(url)
    client_name = parsed.company or slug
    companies = companies_from_primary_and_peers(
        url, client_name, slug, list(parsed.competitors or []),
    )
    if not companies:
        raise ValueError("No companies for All mode.")

    recorder = RunRecorder()
    ui_set_step = set_step
    emit = _wrap_emit_logger(emit, recorder)
    set_step = _wrap_set_step_timer(ui_set_step, recorder)

    emit(
        "pipeline_meta",
        mode="live",
        market=market.upper(),
        site_only=True,
        compare_all=True,
        include_google_ads=include_google_ads,
        include_linkedin=include_linkedin,
        include_youtube_influencers=include_youtube_influencers,
        include_instagram_influencers=include_instagram_influencers,
        include_reddit=include_reddit,
        include_twitter=include_twitter,
        include_linkedin_profile=include_linkedin_profile,
        total_steps=TOTAL_STEPS,
        eta_label=f"All · {len(companies)} empresas (cache merge)",
    )
    _emit_progress(
        emit, set_step, "briefing_concorrentes", "running",
        f"All: ensuring caches ({len(companies)} empresas)",
    )

    def _child_emit(event: str, **payload: Any) -> None:
        # Nested individual runs must not finish/close the parent All job
        if event in ("done", "pipeline_meta"):
            return
        emit(event, **payload)

    fetched = 0
    cached = 0
    for i, company in enumerate(companies):
        c_slug = company["slug"]
        c_url = company["url"]
        c_name = company["name"]
        has_cache = bool(find_metricas_xlsx(c_slug))
        need_fetch = bool(force) or not has_cache
        if need_fetch:
            emit(
                "log",
                line=(
                    f"[ALL] ({i + 1}/{len(companies)}) Fetching {c_name} ({c_slug})"
                    + (" · force" if force else " · no cache")
                ),
            )
            _emit_progress(
                emit, set_step, "briefing_concorrentes", "running",
                f"All: fetching {c_name} ({i + 1}/{len(companies)})",
            )
            child = ParsedInput(
                company=c_name,
                url=c_url,
                slug=c_slug,
                competitors=[],
            )
            run_pipeline(
                child,
                _child_emit,
                ui_set_step,  # child timings must not overwrite All channel timers
                run_id="",  # writes metricas cache only; All run saved later
                force=force,
                site_only=True,
                include_google_ads=include_google_ads,
                include_linkedin=include_linkedin,
                include_youtube_influencers=include_youtube_influencers,
                include_instagram_influencers=include_instagram_influencers,
                include_reddit=include_reddit,
                include_twitter=include_twitter,
                include_linkedin_profile=include_linkedin_profile,
                market=market,
                compare_all=False,
            )
            fetched += 1
        else:
            cached += 1
            emit("log", line=f"[ALL] ({i + 1}/{len(companies)}) Cache hit {c_name} ({c_slug})")

    _emit_progress(
        emit, set_step, "briefing_concorrentes", "done",
        f"All: {len(companies)} empresas · fetched={fetched} cached={cached}",
    )
    emit("log", line=f"[ALL] Merging {len(companies)} company reports…")
    _emit_progress(emit, set_step, "seo", "running", "Merging All report…")

    attach_fns = [_attach_all_sidecars]
    per_reports: list[dict] = []
    for company in companies:
        try:
            per_reports.append(
                load_company_report(
                    company["slug"],
                    url=company["url"],
                    name=company["name"],
                    find_metricas_xlsx=find_metricas_xlsx,
                    build_report_from_xlsx=build_report_from_xlsx,
                    attach_fns=attach_fns,
                )
            )
        except Exception as e:
            emit("log", line=f"[ALL] WARN load {company['slug']}: {e}")
            per_reports.append({
                "client": company["name"],
                "briefing": {"url": company["url"], "summary": f"Cache incomplete: {e}"},
            })

    report = assemble_compare_all_report(companies, per_reports, market=market.upper())
    report["compare_all"] = True
    report["market"] = market.upper()

    optional_off = {
        "google_ads": not include_google_ads,
        "linkedin": not include_linkedin,
        "youtube_influencers": not include_youtube_influencers,
        "instagram_influencers": not include_instagram_influencers,
        "reddit": not include_reddit,
        "twitter": not include_twitter,
        "linkedin_profile": not include_linkedin_profile,
    }
    for sid in (
        "seo", "brand", "brand_dfs", "similarweb", "google_ads", "meta",
        "linkedin", "instagram", "youtube", "tiktok",
        "youtube_influencers", "instagram_influencers",
        "reddit", "twitter", "linkedin_profile",
    ):
        has = bool((report.get(sid) or {}).get("rows"))
        if optional_off.get(sid):
            detail = "Skipped"
        elif has:
            detail = "Merged"
        else:
            detail = "No data"
        _emit_progress(emit, set_step, sid, "done", detail)
        if has:
            emit("partial", section=sid, data=report.get(sid) or {}, client=client_name)

    early = {
        "briefing": report.get("briefing") or {},
        "competitors": report.get("competitors") or [],
        "competitors_count": report.get("competitors_count") or 0,
        "competitors_note": report.get("competitors_note") or "",
    }
    emit("partial", section="briefing_concorrentes", data=early, client=client_name)

    html_url = ""
    if run_id:
        _persist_report_with_log(
            run_id, report, parsed, recorder,
            site_only=True,
            include_google_ads=include_google_ads,
            include_linkedin=include_linkedin,
            include_youtube_influencers=include_youtube_influencers,
            include_instagram_influencers=include_instagram_influencers,
            include_reddit=include_reddit,
            include_twitter=include_twitter,
            include_linkedin_profile=include_linkedin_profile,
            force=force,
            market=market,
            compare_all=True,
        )
        html_url = f"/runs/{run_id}/report.html"
    else:
        attach_run_log(report, recorder)

    emit("done", report=report, html_url=html_url)
    return report


def _comp_sort_key(c: dict) -> tuple:
    if c.get("is_client"):
        return (0, 0, "")
    sim = str(c.get("similaridade") or "").strip().lower().replace("é", "e")
    rank = 1 if sim == "alto" else 2 if sim == "medio" else 3
    return (1, rank, str(c.get("name") or c.get("domain") or "").lower())


def _enrich_competitors_brand_sw(
    report: dict,
    *,
    include_brand_growth: bool,
    include_similarweb_alto: bool,
    emit: Optional[EmitFn] = None,
) -> dict:
    """Attach DataForSEO Aug volumes and SimilarWeb visits onto competitor rows."""
    rows = list(report.get("competitors") or [])
    if not rows:
        return report

    def _log(line: str) -> None:
        if emit:
            emit("log", line=line)

    sys.path.insert(0, str(FINAL_DIR))
    sys.path.insert(0, str(FINAL_DIR / "vendor"))

    if include_brand_growth:
        try:
            from brand_dataforseo import brand_reports_batch  # noqa: E402

            entities = []
            for c in rows:
                entities.append({
                    "name": c.get("name") or c.get("domain") or "",
                    "company": c.get("name") or "",
                    "domain": c.get("domain") or "",
                    "url": c.get("url") or "",
                    "title": c.get("title") or "",
                    "is_client": bool(c.get("is_client")),
                    "similaridade": c.get("similaridade") or "",
                })
            brand_rows = brand_reports_batch(entities)
            by_dom = {(r.get("domain") or "").lower(): r for r in brand_rows}
            for c in rows:
                br = by_dom.get((c.get("domain") or "").lower()) or {}
                c["brand_keyword"] = br.get("brand_keyword") or ""
                c["brand_aug_2026"] = br.get("vol_2026_08")
                c["brand_aug_2025"] = br.get("vol_2025_08")
                c["brand_aug_2024"] = br.get("vol_2024_08")
                c["brand_growth_26_24"] = br.get("growth_26_24_pct")
            report["include_brand_growth"] = True
            _log(f"[BRAND] DataForSEO agosto 2026/25/24 em {len(brand_rows)} empresas")
            try:
                from brand_false_positive import flag_brand_false_positives  # noqa: E402

                n_fp = flag_brand_false_positives(rows, emit=_log)
                report["brand_fp_checked"] = True
                _log(f"[BRAND-FP] {n_fp} possível(is) falso(s) positivo(s)")
            except Exception as e:
                _log(f"[BRAND-FP] Falhou: {e}")
        except Exception as e:
            _log(f"[BRAND] Falhou: {e}")
            report["include_brand_growth"] = True
            report["brand_growth_error"] = str(e)

    if include_similarweb_alto:
        try:
            from similarweb_traffic import traffic_reports_batch  # noqa: E402

            targets = []
            for c in rows:
                sim = str(c.get("similaridade") or "").strip().lower().replace("é", "e")
                if c.get("is_client") or sim == "alto":
                    targets.append(c)
            if targets:
                names = ", ".join(
                    (t.get("domain") or t.get("name") or "?") for t in targets[:12]
                )
                _log(f"[SIMILARWEB] Apify start ({len(targets)}): {names}")
                sw_rows = traffic_reports_batch(targets)
                by_dom = {(r.get("domain") or "").lower(): r for r in sw_rows}
                for c in rows:
                    sw = by_dom.get((c.get("domain") or "").lower()) or {}
                    if not sw:
                        continue
                    c["similarweb_visits"] = sw.get("traffic") or sw.get("latest_visits")
                    c["similarweb_fmt"] = sw.get("traffic_fmt") or ""
                    c["similarweb_error"] = sw.get("error") or ""
            report["include_similarweb_alto"] = True
            _log(f"[SIMILARWEB] Alto+cliente: {len(targets)} domínio(s)")
        except Exception as e:
            _log(f"[SIMILARWEB] Falhou: {e}")
            report["include_similarweb_alto"] = True
            report["similarweb_error"] = str(e)

    rows.sort(key=_comp_sort_key)
    report["competitors"] = rows
    report["competitors_raw"] = rows
    return report


def _enrich_started(report: dict, *, emit: Optional[EmitFn] = None) -> dict:
    """Attach Semrush first-traffic month onto competitor rows."""
    rows = list(report.get("competitors_raw") or report.get("competitors") or [])
    if not rows:
        return report

    def _log(line: str) -> None:
        if emit:
            emit("log", line=line)

    sys.path.insert(0, str(FINAL_DIR))
    sys.path.insert(0, str(FINAL_DIR / "vendor"))
    try:
        from semrush_started import attach_started_batch  # noqa: E402

        attach_started_batch(
            rows,
            market=str(report.get("market") or os.environ.get("SPY_MARKET") or "us"),
            only_missing=True,
            emit=_log,
        )
        report["started_checked"] = True
        report["competitors"] = rows
        report["competitors_raw"] = rows
    except Exception as e:
        _log(f"[STARTED] Falhou: {e}")
        report["started_error"] = str(e)
    return report


def _competitors_only_report(
    slug: str,
    url: str,
    client_name: str,
    preferred: Optional[list[str]] = None,
) -> dict:
    early = build_early_briefing_competitors(
        find_briefing_xlsx(slug),
        find_concorrentes_xlsx(slug),
        client_name=client_name,
        preferred_competitors=preferred or [],
        fallback_url=url,
    )
    raw = list(early.get("competitors_raw") or early.get("competitors") or [])
    shown = raw or list(early.get("competitors") or [])
    shown.sort(key=_comp_sort_key)
    stats = early.get("competitors_stats") or {}
    count = len([c for c in shown if not c.get("is_client")])
    alto = stats.get("alto") or stats.get("Alto") or 0
    medio = stats.get("medio") or stats.get("Médio") or stats.get("Medio") or 0
    try:
        vendor = FINAL_DIR / "vendor"
        if str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        from seo_pipeline import fill_missing_titles  # noqa: E402

        n_titles = fill_missing_titles(shown)
        if n_titles:
            print(f"[TITLE/LLM] competitors_only filled {n_titles}", flush=True)
    except Exception as e:
        print(f"[TITLE/LLM] competitors_only skipped: {e}", flush=True)

    report = {
        "client": early.get("client") or client_name,
        "briefing": early.get("briefing") or {},
        "competitors": shown,
        "competitors_note": (
            f"Modo isolado — discovery nacional {(os.environ.get('SPY_MARKET') or 'us').upper()} "
            f"(SEO SERP + LLM + Semrush top 5). {count} encontrados · Alto={alto} · Médio={medio}."
        ),
        "competitors_stats": stats,
        "competitors_raw": raw,
        "display_tier": "all",
        "competitors_only": True,
        "market": (os.environ.get("SPY_MARKET") or "us").upper(),
        "compare_all": False,
    }
    return report


def run_competitors_only_pipeline(
    parsed: ParsedInput,
    emit: EmitFn,
    set_step: EmitFn,
    *,
    run_id: str = "",
    force: bool = False,
    market: str = "us",
    include_brand_growth: bool = False,
    include_similarweb_alto: bool = False,
) -> dict:
    """Briefing + discovery nacional (SEO + LLM + Semrush). Sem métricas de canal."""
    required = (
        "OPENROUTER_API_KEY",
        "SCRAPINGBEE_API_KEY",
        "DATAFORSEO_USER",
        "DATAFORSEO_PASS",
        "SEMRUSH_API_KEY",
    )
    missing = [k for k in required if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError("Missing API keys: " + ", ".join(missing))

    market = _normalize_market(market)
    os.environ["SPY_MARKET"] = market
    url = normalize_url(parsed.url) or parsed.url
    if not url:
        raise ValueError("Company URL is required.")
    slug = parsed.slug or slugify_client(url)
    client_name = parsed.company or slug
    script_env = {"SPY_SITE_ONLY": "0", "SPY_MARKET": market, "SPY_COMPARE_ALL": "0"}
    steps = [s for s in COMPETITORS_ONLY_STEPS if s["id"] in {
        "briefing_concorrentes", "competitors_discover",
    } or (s["id"] == "brand_growth" and include_brand_growth)
      or (s["id"] == "similarweb_alto" and include_similarweb_alto)]
    for i, s in enumerate(steps, 1):
        s = dict(s)
        s["index"] = i
        steps[i - 1] = s

    recorder = RunRecorder()
    emit = _wrap_emit_logger(emit, recorder)
    set_step = _wrap_set_step_timer(set_step, recorder)

    def on_log(line: str) -> None:
        emit("log", line=line)

    def _prog(step_id: str, state: str, detail: str) -> None:
        _emit_progress(emit, set_step, step_id, state, detail, steps=steps)

    def _save_kw() -> dict[str, Any]:
        return dict(
            site_only=False,
            include_google_ads=False,
            include_linkedin=False,
            include_youtube_influencers=False,
            include_instagram_influencers=False,
            include_reddit=False,
            include_twitter=False,
            include_linkedin_profile=False,
            force=force,
            market=market,
            compare_all=False,
            competitors_only=True,
            include_brand_growth=include_brand_growth,
            include_similarweb_alto=include_similarweb_alto,
        )

    emit(
        "pipeline_meta",
        mode="competitors_only",
        market=market.upper(),
        site_only=False,
        compare_all=False,
        competitors_only=True,
        include_brand_growth=include_brand_growth,
        include_similarweb_alto=include_similarweb_alto,
        total_steps=len(steps),
        eta_label="~3–8 min",
    )

    if force:
        import re
        import shutil

        safe = re.sub(r"[^a-z0-9_-]+", "", (slug or "").strip().lower())[:80]
        for base in (BRIEFING_DIR, CONCORRENTES_DIR):
            folder = (base / safe).resolve()
            try:
                folder.relative_to(base.resolve())
            except ValueError:
                continue
            if folder.exists() and folder.is_dir():
                shutil.rmtree(folder)
                emit("log", line=f"[CACHE] Cleared {folder}")

    briefing_xlsx = find_briefing_xlsx(slug)
    conc_xlsx = find_concorrentes_xlsx(slug)
    if briefing_xlsx and conc_xlsx and not force:
        emit("log", line=f"[CACHE] Using briefing + competitors: {conc_xlsx.name}")
        _prog("briefing_concorrentes", "done", "Cached briefing")
        _prog("competitors_discover", "done", "Cached competitors")
        report = _competitors_only_report(slug, url, client_name, parsed.competitors)
        if include_brand_growth:
            _prog("brand_growth", "running", "DataForSEO marca ago/2026–2024…")
            report = _enrich_competitors_brand_sw(
                report, include_brand_growth=True, include_similarweb_alto=False, emit=emit,
            )
            _prog("brand_growth", "done", "Brand growth ready")
        report = _enrich_started(report, emit=emit)
        html_url = f"/runs/{run_id}/report.html" if run_id else ""
        if run_id:
            _persist_report_with_log(run_id, report, parsed, recorder, **_save_kw())
            emit("report_ready", html_url=html_url, status="running",
                 detail="Relatório pronto — SimilarWeb ainda pode rodar")
            emit("log", line=f"[REPORT] Página pronta: {html_url}")
        if include_similarweb_alto:
            _prog("similarweb_alto", "running", "SimilarWeb só Alto…")
            report = _enrich_competitors_brand_sw(
                report, include_brand_growth=False, include_similarweb_alto=True, emit=emit,
            )
            _prog("similarweb_alto", "done", "SimilarWeb ready")
        if run_id:
            _persist_report_with_log(run_id, report, parsed, recorder, **_save_kw())
        else:
            attach_run_log(report, recorder)
        emit("partial", section="briefing_concorrentes", data=report, client=client_name)
        emit("done", report=report, html_url=html_url)
        return report

    _prog("briefing_concorrentes", "running", f"Briefing US: {url}")
    if not briefing_xlsx or force:
        _run_script(
            [sys.executable, str(SCRIPT_ENTENDER), url],
            FINAL_DIR,
            on_log,
            timeout_sec=300,
            env=script_env,
        )
        briefing_xlsx = find_briefing_xlsx(slug)
    else:
        emit("log", line=f"[CACHE] Reusing briefing: {briefing_xlsx.name}")
    if not briefing_xlsx:
        raise RuntimeError(f"Briefing not generated for '{slug}'.")
    _prog("briefing_concorrentes", "done", "Briefing ready")

    _prog("competitors_discover", "running", f"Discovery nacional {market.upper()} (SEO + LLM + Semrush)…")
    _run_script(
        [sys.executable, str(SCRIPT_CONCORRENTES), slug, "nacional"],
        FINAL_DIR,
        on_log,
        timeout_sec=600,
        env=script_env,
    )
    report = _competitors_only_report(slug, url, client_name, parsed.competitors)
    _prog("competitors_discover", "done", f"{report.get('competitors_count', 0)} competitors")
    if include_brand_growth:
        _prog("brand_growth", "running", "DataForSEO marca ago/2026–2024…")
        report = _enrich_competitors_brand_sw(
            report, include_brand_growth=True, include_similarweb_alto=False, emit=emit,
        )
        _prog("brand_growth", "done", "Brand growth ready")
    report = _enrich_started(report, emit=emit)
    html_url = ""
    if run_id:
        _persist_report_with_log(run_id, report, parsed, recorder, **_save_kw())
        html_url = f"/runs/{run_id}/report.html"
        emit("report_ready", html_url=html_url, status="running",
             detail="Relatório pronto — SimilarWeb ainda pode rodar")
        emit("log", line=f"[REPORT] Página pronta: {html_url}")
    if include_similarweb_alto:
        _prog("similarweb_alto", "running", "SimilarWeb só Alto…")
        report = _enrich_competitors_brand_sw(
            report, include_brand_growth=False, include_similarweb_alto=True, emit=emit,
        )
        _prog("similarweb_alto", "done", "SimilarWeb ready")
    emit("partial", section="briefing_concorrentes", data=report, client=client_name)

    if run_id:
        _persist_report_with_log(run_id, report, parsed, recorder, **_save_kw())
        html_url = f"/runs/{run_id}/report.html"
    else:
        attach_run_log(report, recorder)
        html_url = ""
    emit("done", report=report, html_url=html_url)
    return report


def run_pipeline(
    parsed: ParsedInput,
    emit: EmitFn,
    set_step: EmitFn,
    run_id: str = "",
    force: bool = False,
    site_only: bool = False,
    include_google_ads: bool = True,
    include_linkedin: bool = True,
    include_youtube_influencers: bool = False,
    include_instagram_influencers: bool = False,
    include_reddit: bool = False,
    include_twitter: bool = False,
    include_linkedin_profile: bool = False,
    market: str = "us",
    compare_all: bool = False,
    competitors_only: bool = False,
    include_brand_growth: bool = False,
    include_similarweb_alto: bool = False,
) -> dict:
    required = (
        "OPENROUTER_API_KEY",
        "SCRAPINGBEE_API_KEY",
        "DATAFORSEO_USER",
        "DATAFORSEO_PASS",
        "SEMRUSH_API_KEY",
    )
    missing = [k for k in required if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError("Missing API keys: " + ", ".join(missing))

    if competitors_only:
        return run_competitors_only_pipeline(
            parsed, emit, set_step, run_id=run_id, force=force, market=market,
            include_brand_growth=include_brand_growth,
            include_similarweb_alto=include_similarweb_alto,
        )

    market = _normalize_market(market)
    if compare_all:
        return _run_compare_all_pipeline(
            parsed,
            emit,
            set_step,
            run_id=run_id,
            force=force,
            include_google_ads=include_google_ads,
            include_linkedin=include_linkedin,
            include_youtube_influencers=include_youtube_influencers,
            include_instagram_influencers=include_instagram_influencers,
            include_reddit=include_reddit,
            include_twitter=include_twitter,
            include_linkedin_profile=include_linkedin_profile,
            market=market,
        )

    url = normalize_url(parsed.url) or parsed.url
    if not url:
        raise ValueError("Company URL is required.")
    slug = parsed.slug or slugify_client(url)
    client_name = parsed.company or slug
    peer_urls = list(parsed.competitors or []) if site_only else list(parsed.competitors or [])
    # site_only peers only used by legacy solo xlsx path (All uses cache merge)
    script_env = {
        "SPY_SITE_ONLY": "1" if site_only else "0",
        "SPY_MARKET": market,
        "SPY_COMPARE_ALL": "0",
    }
    # Ensure parent process market helpers (report_builder) see the same market
    os.environ["SPY_MARKET"] = market

    recorder = RunRecorder()
    emit = _wrap_emit_logger(emit, recorder)
    set_step = _wrap_set_step_timer(set_step, recorder)

    def on_log(line: str) -> None:
        emit("log", line=line)

    def _tag_report(report: dict) -> dict:
        report["market"] = market.upper()
        report["compare_all"] = bool(compare_all)
        return report

    def _save_kw() -> dict[str, Any]:
        return dict(
            site_only=site_only,
            include_google_ads=include_google_ads,
            include_linkedin=include_linkedin,
            include_youtube_influencers=include_youtube_influencers,
            include_instagram_influencers=include_instagram_influencers,
            include_reddit=include_reddit,
            include_twitter=include_twitter,
            include_linkedin_profile=include_linkedin_profile,
            force=force,
            market=market,
            compare_all=compare_all,
            competitors_only=False,
        )

    if force:
        clear_slug_cache(slug)

    existing = find_metricas_xlsx(slug)
    if existing and existing.exists() and not force:
        emit("log", line=f"[CACHE] Using existing metrics: {existing.name}")
        report = build_report_from_xlsx(
            existing,
            client_name=client_name,
            preferred_competitors=parsed.competitors,
        )
        _emit_progress(emit, set_step, "briefing_concorrentes", "done", "Cached report")
        for sid in (
            "seo", "brand", "brand_dfs", "similarweb", "google_ads", "meta",
            "linkedin", "instagram", "youtube", "tiktok",
            "youtube_influencers", "instagram_influencers",
            "reddit", "twitter", "linkedin_profile",
        ):
            _emit_progress(emit, set_step, sid, "done", "Cached")
        report = _attach_brand_dfs(report, slug)
        report = _attach_similarweb(report, slug)
        report = _attach_youtube_influencers(report, slug)
        report = _attach_instagram_influencers(report, slug)
        report = _attach_reddit(report, slug)
        report = _attach_twitter(report, slug)
        report = _attach_linkedin_profile(report, slug)
        report = _tag_report(report)
        if run_id:
            _persist_report_with_log(run_id, report, parsed, recorder, **_save_kw())
        else:
            attach_run_log(report, recorder)
        emit("done", report=report, html_url=f"/runs/{run_id}/report.html" if run_id else "")
        return report

    emit(
        "pipeline_meta",
        mode="live",
        market=market.upper(),
        site_only=site_only,
        compare_all=compare_all,
        include_google_ads=include_google_ads,
        include_linkedin=include_linkedin,
        include_youtube_influencers=include_youtube_influencers,
        include_instagram_influencers=include_instagram_influencers,
        include_reddit=include_reddit,
        include_twitter=include_twitter,
        include_linkedin_profile=include_linkedin_profile,
        total_steps=TOTAL_STEPS,
        eta_label="~3–8 min" if site_only else "~10–15 min",
    )

    # 1) Briefing + optional competitors
    if site_only:
        detail = (
            f"Briefing + All ({1 + len(peer_urls)} empresas): {url}"
            if compare_all and peer_urls
            else f"Briefing + modo sem concorrentes: {url}"
        )
        _emit_progress(emit, set_step, "briefing_concorrentes", "running", detail)
    else:
        _emit_progress(
            emit, set_step, "briefing_concorrentes", "running",
            f"Briefing + {market.upper()} competitors: {url}",
        )

    _run_script(
        [sys.executable, str(SCRIPT_ENTENDER), url],
        FINAL_DIR,
        on_log,
        timeout_sec=300,
        env=script_env,
    )
    briefing_xlsx = find_briefing_xlsx(slug)
    if not briefing_xlsx:
        raise RuntimeError(f"Briefing not generated for '{slug}'.")

    if site_only:
        peers_for_xlsx = peer_urls if compare_all else []
        build_solo_national_xlsx(
            slug, url, client_name,
            peer_urls=peers_for_xlsx,
            market=market,
        )
        early = build_early_briefing_competitors(
            find_briefing_xlsx(slug),
            find_concorrentes_xlsx(slug),
            client_name=client_name,
            preferred_competitors=peers_for_xlsx,
            fallback_url=url,
        )
        if compare_all and peers_for_xlsx:
            early["competitors_note"] = (
                f"Modo All — {len(peers_for_xlsx)} empresa(s) informada(s) na mesma tabela (sem discovery)."
            )
            early["competitors_count"] = len(peers_for_xlsx)
            done_msg = f"All: {1 + len(peers_for_xlsx)} empresas"
        else:
            early["competitors_note"] = "Modo sem pesquisar concorrentes — discovery skipped."
            early["competitors_count"] = 0
            done_msg = "Sem concorrentes (0)"
        emit("partial", section="briefing_concorrentes", data=early, client=client_name)
        _emit_progress(emit, set_step, "briefing_concorrentes", "done", done_msg)
    else:
        _run_script(
            [sys.executable, str(SCRIPT_CONCORRENTES), slug, "nacional"],
            FINAL_DIR,
            on_log,
            timeout_sec=600,
            env=script_env,
        )
        early = build_early_briefing_competitors(
            find_briefing_xlsx(slug),
            find_concorrentes_xlsx(slug),
            client_name=client_name,
            preferred_competitors=parsed.competitors,
            fallback_url=url,
        )
        emit("partial", section="briefing_concorrentes", data=early, client=client_name)
        _emit_progress(
            emit, set_step, "briefing_concorrentes", "done",
            f"{early.get('competitors_count', 0)} competitors",
        )

    # 2) SEO
    _emit_progress(emit, set_step, "seo", "running", "Building US SEO ranking...")
    _run_script(
        [sys.executable, str(SCRIPT_SEO), slug],
        FINAL_DIR,
        on_log,
        timeout_sec=180,
        env=script_env,
    )
    xlsx = find_metricas_xlsx(slug)
    if not xlsx:
        raise FileNotFoundError(f"Metrics XLSX not generated for '{slug}'")
    report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
    emit("partial", section="seo", data=report.get("seo") or {}, client=client_name)
    _emit_progress(emit, set_step, "seo", "done", "SEO ready")

    # 3) Brand
    _emit_progress(emit, set_step, "brand", "running", "Building brand ranking...")
    _run_script(
        [sys.executable, str(SCRIPT_BRAND), slug],
        FINAL_DIR,
        on_log,
        timeout_sec=180,
        env=script_env,
    )
    xlsx = find_metricas_xlsx(slug) or xlsx
    report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
    emit("partial", section="brand", data=report.get("brand") or {}, client=client_name)
    _emit_progress(emit, set_step, "brand", "done", "Brand Semrush ready")

    # 3b) Brand DataForSEO (keyword from domain+title, monthly history)
    _emit_progress(emit, set_step, "brand_dfs", "running", "Brand DataForSEO US (1y/2y/3y/5y)...")
    try:
        _run_script(
            [sys.executable, str(SCRIPT_BRAND_DFS), slug],
            FINAL_DIR,
            on_log,
            timeout_sec=180,
            env=script_env,
        )
    except Exception as e:
        emit("log", line=f"[BRAND/DFS] Partial failure: {e}")
    report = _attach_brand_dfs(report, slug)
    emit(
        "partial",
        section="brand_dataforseo",
        data=report.get("brand_dataforseo") or {},
        client=client_name,
    )
    _emit_progress(emit, set_step, "brand_dfs", "done", "Brand DataForSEO ready")

    # 3c) SimilarWeb Traffic (Apify)
    _emit_progress(emit, set_step, "similarweb", "running", "SimilarWeb Traffic (Apify)...")
    try:
        _run_script(
            [sys.executable, str(SCRIPT_SIMILARWEB), slug],
            FINAL_DIR,
            on_log,
            timeout_sec=180,
            env=script_env,
        )
    except Exception as e:
        emit("log", line=f"[SIMILARWEB] Partial failure: {e}")
    report = _attach_similarweb(report, slug)
    emit(
        "partial",
        section="similarweb",
        data=report.get("similarweb") or {},
        client=client_name,
    )
    _emit_progress(emit, set_step, "similarweb", "done", "SimilarWeb ready")

    # 4) Google Ads Library (optional)
    if include_google_ads:
        _emit_progress(emit, set_step, "google_ads", "running", "Google Ads Transparency (US)...")
        try:
            _run_script(
                [sys.executable, str(SCRIPT_GOOGLE), slug],
                FINAL_DIR,
                on_log,
                timeout_sec=420,
                env=script_env,
            )
        except Exception as e:
            emit("log", line=f"[GOOGLE] Partial failure: {e}")
        xlsx = find_metricas_xlsx(slug) or xlsx
        report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
        emit("partial", section="google_ads", data=report.get("google_ads") or {}, client=client_name)
        _emit_progress(emit, set_step, "google_ads", "done", "Google Ads ready")
    else:
        _emit_progress(emit, set_step, "google_ads", "done", "Skipped")

    # 5) Meta
    _emit_progress(emit, set_step, "meta", "running", "Meta Ads Library (US)...")
    try:
        _run_script(
            [sys.executable, str(SCRIPT_META), slug],
            FINAL_DIR,
            on_log,
            timeout_sec=420,
            env=script_env,
        )
    except Exception as e:
        emit("log", line=f"[META] Partial failure: {e}")
    xlsx = find_metricas_xlsx(slug) or xlsx
    report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
    emit("partial", section="meta", data=report.get("meta") or {}, client=client_name)
    _emit_progress(emit, set_step, "meta", "done", "Meta ready")

    # 6) LinkedIn Ads Library (optional) — empresa → ad → pagante → total
    if include_linkedin:
        _emit_progress(
            emit, set_step, "linkedin", "running",
            "LinkedIn Ads Library (US): find ad → payer → total...",
        )
        try:
            _run_script(
                [sys.executable, str(SCRIPT_LINKEDIN), slug],
                FINAL_DIR,
                on_log,
                timeout_sec=600,
                env=script_env,
            )
        except Exception as e:
            emit("log", line=f"[LINKEDIN] Partial failure: {e}")
        xlsx = find_metricas_xlsx(slug) or xlsx
        report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
        emit("partial", section="linkedin", data=report.get("linkedin") or {}, client=client_name)
        _emit_progress(emit, set_step, "linkedin", "done", "LinkedIn ready")
    else:
        _emit_progress(emit, set_step, "linkedin", "done", "Skipped")

    # 7–9) Social
    _emit_progress(emit, set_step, "instagram", "running", "Instagram / YouTube / TikTok...")
    try:
        _run_script(
            [sys.executable, str(SCRIPT_SOCIAL), slug],
            FINAL_DIR,
            on_log,
            timeout_sec=600,
            env=script_env,
        )
    except Exception as e:
        emit("log", line=f"[SOCIAL] Partial failure: {e}")
    xlsx = find_metricas_xlsx(slug) or xlsx
    report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
    report = _attach_brand_dfs(report, slug)
    report = _attach_similarweb(report, slug)
    report = _tag_report(report)
    for sid in ("instagram", "youtube", "tiktok"):
        emit("partial", section=sid, data=report.get(sid) or {}, client=client_name)
        _emit_progress(emit, set_step, sid, "done", f"{sid} ready")

    # 10) YouTube Influencers (optional) — ScrapingBee fetch + ytInitialData parse
    if include_youtube_influencers:
        if not (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip():
            emit("log", line="[YT-INF] Skipped: SCRAPINGBEE_API_KEY missing")
            _emit_progress(emit, set_step, "youtube_influencers", "done", "Skipped (no ScrapingBee key)")
        else:
            _emit_progress(
                emit, set_step, "youtube_influencers", "running",
                "YouTube Influencers (ScrapingBee + parse)...",
            )
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_YT_INFLUENCERS), slug],
                    FINAL_DIR,
                    on_log,
                    timeout_sec=240,
                    env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[YT-INF] Partial failure: {e}")
            report = _attach_youtube_influencers(report, slug)
            report = _tag_report(report)
            emit(
                "partial",
                section="youtube_influencers",
                data=report.get("youtube_influencers") or {},
                client=client_name,
            )
            _emit_progress(emit, set_step, "youtube_influencers", "done", "YouTube Influencers ready")
    else:
        _emit_progress(emit, set_step, "youtube_influencers", "done", "Skipped")

    # 11) Instagram Influencers (optional) — Search + Fetch download
    if include_instagram_influencers:
        if not (os.environ.get("TINYFISH_API_KEY") or "").strip():
            emit("log", line="[IG-INF] Skipped: TINYFISH_API_KEY missing")
            _emit_progress(emit, set_step, "instagram_influencers", "done", "Skipped (no TinyFish key)")
        else:
            _emit_progress(
                emit, set_step, "instagram_influencers", "running",
                "Instagram Influencers (Search + page download)...",
            )
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_IG_INFLUENCERS), slug],
                    FINAL_DIR,
                    on_log,
                    timeout_sec=600,
                    env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[IG-INF] Partial failure: {e}")
            report = _attach_instagram_influencers(report, slug)
            report = _tag_report(report)
            emit(
                "partial",
                section="instagram_influencers",
                data=report.get("instagram_influencers") or {},
                client=client_name,
            )
            _emit_progress(emit, set_step, "instagram_influencers", "done", "Instagram Influencers ready")
    else:
        _emit_progress(emit, set_step, "instagram_influencers", "done", "Skipped")

    # 12) Reddit mentions (optional)
    if include_reddit:
        if not (os.environ.get("TINYFISH_API_KEY") or "").strip():
            emit("log", line="[REDDIT] Skipped: TINYFISH_API_KEY missing")
            _emit_progress(emit, set_step, "reddit", "done", "Skipped (no TinyFish key)")
        else:
            _emit_progress(emit, set_step, "reddit", "running", "Reddit (site:reddit.com + comments)...")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_REDDIT), slug],
                    FINAL_DIR, on_log, timeout_sec=240, env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[REDDIT] Partial failure: {e}")
            report = _attach_reddit(report, slug)
            report = _tag_report(report)
            emit("partial", section="reddit", data=report.get("reddit") or {}, client=client_name)
            _emit_progress(emit, set_step, "reddit", "done", "Reddit ready")
    else:
        _emit_progress(emit, set_step, "reddit", "done", "Skipped")

    # 13) Twitter / X profile (optional)
    if include_twitter:
        if not (os.environ.get("TINYFISH_API_KEY") or "").strip():
            emit("log", line="[TW] Skipped: TINYFISH_API_KEY missing")
            _emit_progress(emit, set_step, "twitter", "done", "Skipped (no TinyFish key)")
        else:
            _emit_progress(emit, set_step, "twitter", "running", "Twitter/X profile...")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_TWITTER), slug],
                    FINAL_DIR, on_log, timeout_sec=180, env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[TW] Partial failure: {e}")
            report = _attach_twitter(report, slug)
            report = _tag_report(report)
            emit("partial", section="twitter", data=report.get("twitter") or {}, client=client_name)
            _emit_progress(emit, set_step, "twitter", "done", "Twitter ready")
    else:
        _emit_progress(emit, set_step, "twitter", "done", "Skipped")

    # 14) LinkedIn company/profile (optional)
    if include_linkedin_profile:
        if not (os.environ.get("TINYFISH_API_KEY") or "").strip():
            emit("log", line="[LI] Skipped: TINYFISH_API_KEY missing")
            _emit_progress(emit, set_step, "linkedin_profile", "done", "Skipped (no TinyFish key)")
        else:
            _emit_progress(emit, set_step, "linkedin_profile", "running", "LinkedIn profile...")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_LI_PROFILE), slug],
                    FINAL_DIR, on_log, timeout_sec=120, env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[LI] Partial failure: {e}")
            report = _attach_linkedin_profile(report, slug)
            report = _tag_report(report)
            emit(
                "partial",
                section="linkedin_profile",
                data=report.get("linkedin_profile") or {},
                client=client_name,
            )
            _emit_progress(emit, set_step, "linkedin_profile", "done", "LinkedIn Profile ready")
    else:
        _emit_progress(emit, set_step, "linkedin_profile", "done", "Skipped")

    html_url = ""
    if run_id:
        _persist_report_with_log(run_id, report, parsed, recorder, **_save_kw())
        html_url = f"/runs/{run_id}/report.html"
    else:
        attach_run_log(report, recorder)

    emit("done", report=report, html_url=html_url)
    return report
