# -*- coding: utf-8 -*-
"""Spy USA pipeline: briefing → (concorrentes?) → SEO + channels in parallel."""

from __future__ import annotations

import contextvars
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
SCRIPT_METRICAS = FINAL_DIR / "5 - metricas concorrentes.py"
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
SCRIPT_TT_INFLUENCERS = FINAL_DIR / "5n - tiktok influencers.py"
SCRIPT_X_INFLUENCERS = FINAL_DIR / "5o - twitter influencers.py"
SCRIPT_REDDIT = FINAL_DIR / "5k - reddit mentions.py"
SCRIPT_TWITTER = FINAL_DIR / "5l - twitter profile.py"
SCRIPT_LI_PROFILE = FINAL_DIR / "5m - linkedin profile.py"

_DATA_DIR = (os.environ.get("RADAR_DATA_DIR") or os.environ.get("SPY_DATA_DIR") or "").strip()
_OUT_ROOT = (Path(_DATA_DIR) / "outputs") if _DATA_DIR else (APP_DIR / "outputs")
METRICAS_DIR = _OUT_ROOT / "metricas"
BRIEFING_DIR = _OUT_ROOT / "entender"
CONCORRENTES_DIR = _OUT_ROOT / "concorrentes"
RUNS_DIR = _OUT_ROOT / "runs"


def _enable_llm_log(run_id: str) -> str:
    if not run_id:
        return ""
    path = RUNS_DIR / run_id / "llm.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["SPY_LLM_LOG"] = str(path)
    return str(path)


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
    {"id": "google_ads", "label": "Google Ads Library (anywhere)", "index": 6, "eta_live": 180},
    {"id": "meta", "label": "Meta Ads (US)", "index": 7, "eta_live": 180},
    {"id": "linkedin", "label": "LinkedIn Ads Library (US)", "index": 8, "eta_live": 240},
    {"id": "instagram", "label": "Instagram", "index": 9, "eta_live": 120},
    {"id": "youtube", "label": "YouTube", "index": 10, "eta_live": 20},
    {"id": "tiktok", "label": "TikTok", "index": 11, "eta_live": 40},
    {"id": "youtube_influencers", "label": "YouTube Influencers", "index": 12, "eta_live": 90},
    {"id": "instagram_influencers", "label": "Instagram Influencers", "index": 13, "eta_live": 60},
    {"id": "tiktok_influencers", "label": "TikTok Influencers", "index": 14, "eta_live": 40},
    {"id": "twitter_influencers", "label": "X Influencers", "index": 15, "eta_live": 40},
    {"id": "reddit", "label": "Reddit", "index": 16, "eta_live": 45},
    {"id": "twitter", "label": "Twitter / X", "index": 17, "eta_live": 40},
    {"id": "linkedin_profile", "label": "LinkedIn Profile", "index": 18, "eta_live": 20},
]
TOTAL_STEPS = len(STEP_DEFS)
# Wall-clock guess from recent live runs (extras run in parallel). Not the
# sequential sum of eta_live, which inflated the bar to 8–16 min.
ANALYSIS_WALL_SEC = 180
FIND_WALL_SEC = 180

_STEP_CLOCK: contextvars.ContextVar[Optional["StepClock"]] = contextvars.ContextVar(
    "spy_step_clock", default=None,
)

_OPTIONAL_STEP_FLAGS = {
    "google_ads": "include_google_ads",
    "linkedin": "include_linkedin",
    "youtube_influencers": "include_youtube_influencers",
    "instagram_influencers": "include_instagram_influencers",
    "tiktok_influencers": "include_tiktok_influencers",
    "twitter_influencers": "include_twitter_influencers",
    "reddit": "include_reddit",
    "twitter": "include_twitter",
    "linkedin_profile": "include_linkedin_profile",
}


def _planned_analysis_steps(**flags: Any) -> list[dict]:
    out: list[dict] = []
    for s in STEP_DEFS:
        flag = _OPTIONAL_STEP_FLAGS.get(s["id"])
        if flag and not flags.get(flag):
            continue
        out.append(s)
    return out


def _fmt_clock(seconds: float) -> str:
    sec = max(0, int(round(seconds)))
    m, s = divmod(sec, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class StepClock:
    """Count finished steps (not catalog order) + elapsed vs projected time."""

    def __init__(self, steps: list[dict], *, eta_total: Optional[int] = None):
        self.steps = [dict(s) for s in steps]
        self.ids = {s["id"] for s in self.steps}
        self.done: set[str] = set()
        self.t0 = time.time()
        self.company_total = 0
        self.company_done = 0
        if eta_total is not None:
            self.eta_total = max(1, int(eta_total))
        else:
            self.eta_total = ANALYSIS_WALL_SEC

    def set_companies(self, total: int, done: int = 0) -> None:
        self.company_total = max(0, int(total))
        self.company_done = max(0, min(int(done), self.company_total))

    def mark(self, step_id: str, state: str) -> None:
        if state == "done" and step_id in self.ids:
            self.done.add(step_id)

    def lookup(self, step_id: str) -> Optional[dict]:
        return next((s for s in self.steps if s["id"] == step_id), None)

    def snapshot(self) -> dict[str, Any]:
        elapsed = max(0.0, time.time() - self.t0)
        eta = self.eta_total
        pct = round(100.0 * elapsed / max(1, eta), 1)
        n_done = len(self.done)
        n_total = len(self.steps)
        if self.company_total:
            n_done = self.company_done
            n_total = self.company_total
            label = f"{n_done}/{n_total} companies"
        else:
            label = f"{n_done}/{n_total} steps"
        out = {
            "done_count": n_done,
            "total": n_total,
            "index": n_done,
            "progress_label": label,
            "elapsed_sec": int(round(elapsed)),
            "eta_seconds": eta,
            "eta_label": _fmt_eta(eta) if eta else "",
            "time_label": f"{_fmt_clock(elapsed)} / {_fmt_clock(eta)}",
            "pct": pct,
        }
        if self.company_total:
            out["company_done"] = self.company_done
            out["company_total"] = self.company_total
        return out

    def meta_payload(self) -> dict[str, Any]:
        out = {
            "total_steps": len(self.steps),
            "eta_seconds": self.eta_total,
            "eta_label": _fmt_eta(self.eta_total) if self.eta_total else "",
            "steps": [
                {
                    "id": s["id"],
                    "label": s.get("label") or s["id"],
                    "eta_live": int(s.get("eta_live") or 60),
                }
                for s in self.steps
            ],
        }
        if self.company_total:
            out["company_total"] = self.company_total
            out["company_done"] = self.company_done
            out["total_steps"] = self.company_total
        return out


def _bind_step_clock(
    steps: list[dict],
    *,
    replace: bool = True,
    eta_total: Optional[int] = None,
) -> tuple["StepClock", Any]:
    existing = _STEP_CLOCK.get()
    if existing is not None and not replace:
        return existing, None
    clock = StepClock(steps, eta_total=eta_total)
    token = _STEP_CLOCK.set(clock)
    return clock, token


def _unbind_step_clock(token: Any) -> None:
    if token is not None:
        _STEP_CLOCK.reset(token)


def _prime_brand_keyword(slug: str, url: str, name: str, emit: EmitFn) -> str:
    vendor = FINAL_DIR / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        from brand_dataforseo import ensure_brand_search_keyword

        meta = ensure_brand_search_keyword(slug, url=url, company=name)
        kw = str((meta or {}).get("keyword") or "").strip()
        if kw:
            emit(
                "log",
                line=f"[BRAND/KW] search term={kw!r} method={meta.get('keyword_method') or '—'}",
            )
        return kw
    except Exception as e:
        emit("log", line=f"[BRAND/KW] resolve failed: {e}")
        return ""


def _brand_dfs_needs_llm(slug: str) -> bool:
    data = _load_brand_dfs(slug)
    if data is None:
        return False
    method = str(data.get("keyword_method") or "")
    return method not in ("llm_title_desc", "semrush_top", "semrush_top+llm")


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
        """Same rule as brand_dataforseo._pct: missing/0 baseline → n/d."""
        if new is None:
            return None
        try:
            new_i = int(new)
        except (TypeError, ValueError):
            return None
        if old is None or old == 0:
            return None
        try:
            old_i = int(old)
        except (TypeError, ValueError):
            return None
        if old_i == 0:
            return None
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
        src = str(r.get("source") or "dataforseo_labs")
        sm_db = str(r.get("semrush_db") or db or "us")
        domain = str(r.get("domain") or "").strip()
        if src == "semrush_branded" and domain:
            kw_url = (
                f"https://www.semrush.com/analytics/overview/"
                f"?q={quote(domain)}&searchType=domain&db={quote(sm_db)}"
            )
        elif kw:
            kw_url = (
                f"https://www.semrush.com/analytics/keywordoverview/?q={quote(kw)}&db={db}"
            )
        else:
            kw_url = ""
        rows.append({
            "name": r.get("name") or r.get("brand_keyword"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "brand_keyword": r.get("brand_keyword"),
            "keyword_method": r.get("keyword_method") or "",
            "keyword_reason": r.get("keyword_reason") or "",
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
            "source": src,
            "semrush_db": sm_db,
        })
    client = next((r for r in rows if r.get("is_client")), rows[0] if rows else {})
    client_raw = next((r for r in rows_raw if r.get("is_client")), rows_raw[0] if rows_raw else {})
    client_src = str(client_raw.get("source") or "dataforseo_labs")
    used_sm = client_src == "semrush_branded"
    used_fallback = client_src == "dataforseo_google_ads"
    sm_db = str(client_raw.get("semrush_db") or db)
    src_label = (
        f"Semrush Domain Overview branded ({sm_db})"
        if used_sm
        else (
            f"DataForSEO Google Ads {mkt} (fallback)"
            if used_fallback
            else f"DataForSEO Labs {mkt}"
        )
    )
    usage = dict(data.get("usage_total") or {})
    report["brand_dataforseo"] = {
        "source": (
            "semrush_branded" if used_sm
            else ("dataforseo_google_ads" if used_fallback else "dataforseo_labs")
        ),
        "market": "ALL" if sm_db == "all" else mkt,
        "latest_label": data.get("latest_label") or client_raw.get("latest_label"),
        "client_keyword": data.get("client_keyword") or client_raw.get("brand_keyword"),
        "leader": (rows[0].get("name") if rows else "—"),
        "total_traffic_fmt": client.get("traffic_fmt") if client else (rows[0].get("traffic_fmt") if rows else "—"),
        "growth_fmt": client.get("growth_fmt") if client else "n/a",
        "growth_1y_pct": client.get("growth_1y_pct") if client else None,
        "unit": "branded visits" if used_sm else "monthly searches",
        "rows": rows,
        "usage_total": usage,
        "insight": (
            f"Brand keyword «{data.get('client_keyword') or client_raw.get('brand_keyword') or '—'}» "
            f"· latest month {data.get('latest_label') or client_raw.get('latest_label') or 'n/a'} "
            f"· growth 1y {client.get('growth_fmt') or 'n/a'} "
            f"({src_label}"
            f"{'; DataForSEO volume was 0' if used_sm else ''}). "
            f"Same month last year; n/d when the baseline is 0."
        ),
        "analysis_title": (
            "Brand Search — Semrush branded" if used_sm else "Brand Search — DataForSEO Labs"
        ),
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
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": unoff,
            "traffic_fmt": _fmt_views(unoff),
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
            "videos_about_product": r.get("videos_about_product") or [],
            "videos_probable": r.get("videos_probable") or [],
            "videos_unrelated": r.get("videos_unrelated") or [],
            "videos_fetched": r.get("videos_fetched") or [],
            "official_channel": r.get("official_channel"),
            "query": r.get("query") or "",
            "url": r.get("search_url") or "",
            "usage": r.get("usage") or {},
            "error": r.get("error"),
        })
    client = next((r for r in rows_out if r.get("is_client")), rows_out[0] if rows_out else {})
    usage = dict(data.get("usage_total") or {})
    if data.get("elapsed_sec") and not usage.get("elapsed_sec"):
        usage["elapsed_sec"] = data.get("elapsed_sec")
    report["youtube_influencers"] = {
        "source": data.get("source") or "scrapingbee_youtube_njs",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("traffic_fmt") if client else "—",
        "unit": "views (1st page)",
        "rows": rows_out,
        "usage_total": usage,
        "elapsed_sec": data.get("elapsed_sec") or usage.get("elapsed_sec"),
        "insight": (
            f"YouTube «{client.get('query') or client.get('name') or '—'}» ScrapingBee no-JS "
            f"({(client.get('usage') or {}).get('sort') or 'popular'}"
            f"{' +relevance' if (client.get('usage') or {}).get('sort_fallback') else ''}): "
            f"official {_fmt_views(client.get('views_official'))} · "
            f"unofficial {_fmt_views(client.get('views_unofficial'))} · "
            f"30d {_fmt_views(client.get('views_30d'))} / "
            f"6m {_fmt_views(client.get('views_6m'))} / "
            f"1y+ {_fmt_views(client.get('views_1y_plus'))} "
            f"(title + card snippet; SB {usage.get('scrapingbee_credits', '—')} credits)."
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
        inf_likes = int(r.get("influencer_likes") or 0)
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": inf_likes,
            "traffic_fmt": _fmt_views(inf_likes),
            "total_influencers": int(r.get("total_influencers") or 0),
            "influencer_posts": int(r.get("influencer_posts") or 0),
            "own_posts": int(r.get("own_posts") or 0),
            "posts_first_page": int(r.get("posts_first_page") or 0),
            "total_likes": total_likes,
            "total_likes_fmt": _fmt_views(total_likes),
            "own_likes": int(r.get("own_likes") or 0),
            "own_likes_fmt": _fmt_views(r.get("own_likes") or 0),
            "influencer_likes": int(r.get("influencer_likes") or 0),
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
    usage = dict(data.get("usage_total") or {})
    if data.get("elapsed_sec") and not usage.get("elapsed_sec"):
        usage["elapsed_sec"] = data.get("elapsed_sec")
    report["instagram_influencers"] = {
        "source": "tinyfish_search+fetch",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("influencer_likes_fmt") if client else "—",
        "unit": "likes (1st page)",
        "rows": rows_out,
        "usage_total": usage,
        "elapsed_sec": data.get("elapsed_sec") or usage.get("elapsed_sec"),
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


def _load_tiktok_influencers(slug: str) -> Optional[dict]:
    path = METRICAS_DIR / slug / f"tiktok-influencers-{slug}.json"
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _tt_json_missing(slug: str) -> bool:
    data = _load_tiktok_influencers(slug)
    if data is None:
        return True
    if "v2_neg_strong_brand" not in str(data.get("brand_filter") or ""):
        return True
    if not bool(data.get("llm_title_filter")):
        return True
    return _inf_query_stale(data, slug)


def _attach_tiktok_influencers(report: dict, slug: str) -> dict:
    data = _load_tiktok_influencers(slug)
    if not data:
        return report
    rows_out: list[dict] = []
    for r in data.get("rows") or []:
        off = int(r.get("views_official") or 0)
        unoff = int(r.get("views_unofficial") or 0)
        confirmed_n = int(r.get("confirmed_count") or r.get("about_count") or 0)
        probable_n = int(r.get("probable_count") or 0)
        unrelated_n = int(r.get("unrelated_count") or 0)
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": unoff,
            "traffic_fmt": _fmt_views(unoff),
            "views_official": off,
            "views_official_fmt": _fmt_views(off),
            "views_unofficial": unoff,
            "views_unofficial_fmt": _fmt_views(unoff),
            "views_confirmed": int(r.get("views_confirmed") or (off + unoff)),
            "views_confirmed_fmt": _fmt_views(int(r.get("views_confirmed") or (off + unoff))),
            "views_probable": int(r.get("views_probable") or 0),
            "views_probable_fmt": _fmt_views(int(r.get("views_probable") or 0)),
            "about_count": confirmed_n,
            "page_count": r.get("page_count") or 0,
            "confirmed_count": confirmed_n,
            "probable_count": probable_n,
            "unrelated_count": unrelated_n,
            "top5": r.get("top5") or [],
            "top5_official": r.get("top5_official") or [],
            "top5_unofficial": r.get("top5_unofficial") or [],
            "top5_probable": r.get("top5_probable") or [],
            "videos_confirmed": r.get("videos_confirmed") or [],
            "videos_probable": r.get("videos_probable") or [],
            "videos_unrelated": r.get("videos_unrelated") or [],
            "videos_fetched": r.get("videos_fetched") or [],
            "official_channel": r.get("official_channel"),
            "brand": r.get("brand") or {},
            "query": r.get("query") or "",
            "url": r.get("search_url") or "",
            "usage": r.get("usage") or {},
            "error": r.get("error"),
        })
    client = next((r for r in rows_out if r.get("is_client")), rows_out[0] if rows_out else {})
    usage = dict(data.get("usage_total") or {})
    if data.get("elapsed_sec") and not usage.get("elapsed_sec"):
        usage["elapsed_sec"] = data.get("elapsed_sec")
    amb = bool((client.get("brand") or {}).get("ambiguous"))
    report["tiktok_influencers"] = {
        "source": data.get("source") or "apify_tiktok",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("views_unofficial_fmt") if client else "—",
        "unit": "confirmed other-creator views",
        "rows": rows_out,
        "usage_total": usage,
        "elapsed_sec": data.get("elapsed_sec") or usage.get("elapsed_sec"),
        "insight": (
            f"TikTok Apify «{client.get('query') or client.get('name') or '—'}»: "
            f"{client.get('confirmed_count') or 0} confirmed · "
            f"{client.get('probable_count') or 0} probable · "
            f"{client.get('unrelated_count') or 0} discarded · "
            f"other {_fmt_views(client.get('views_unofficial'))} views"
            f"{' · ambiguous brand (review probable)' if amb else ''}."
        ),
        "analysis_title": "TikTok Influencers",
        "pro_hook": "Na versão Pro mapeamos creators e formatos que geram views no TikTok do nicho.",
    }
    return report


def _load_twitter_influencers(slug: str) -> Optional[dict]:
    path = METRICAS_DIR / slug / f"twitter-influencers-{slug}.json"
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _x_inf_json_missing(slug: str) -> bool:
    data = _load_twitter_influencers(slug)
    if data is None:
        return True
    if not bool(data.get("llm_title_filter")):
        return True
    return _inf_query_stale(data, slug)


def _attach_twitter_influencers(report: dict, slug: str) -> dict:
    data = _load_twitter_influencers(slug)
    if not data:
        return report
    rows_out: list[dict] = []
    for r in data.get("rows") or []:
        off = int(r.get("views_official") or 0)
        unoff = int(r.get("views_unofficial") or 0)
        confirmed_n = int(r.get("confirmed_count") or r.get("about_count") or 0)
        probable_n = int(r.get("probable_count") or 0)
        unrelated_n = int(r.get("unrelated_count") or 0)
        rows_out.append({
            "name": r.get("name") or r.get("domain"),
            "domain": r.get("domain"),
            "is_client": bool(r.get("is_client")),
            "similaridade": r.get("similaridade") or ("Cliente" if r.get("is_client") else "—"),
            "traffic": unoff,
            "traffic_fmt": _fmt_views(unoff),
            "views_official": off,
            "views_official_fmt": _fmt_views(off),
            "views_unofficial": unoff,
            "views_unofficial_fmt": _fmt_views(unoff),
            "views_confirmed": int(r.get("views_confirmed") or (off + unoff)),
            "views_confirmed_fmt": _fmt_views(int(r.get("views_confirmed") or (off + unoff))),
            "views_probable": int(r.get("views_probable") or 0),
            "views_probable_fmt": _fmt_views(int(r.get("views_probable") or 0)),
            "about_count": confirmed_n,
            "page_count": r.get("page_count") or 0,
            "confirmed_count": confirmed_n,
            "probable_count": probable_n,
            "unrelated_count": unrelated_n,
            "top5": r.get("top5") or [],
            "top5_official": r.get("top5_official") or [],
            "top5_unofficial": r.get("top5_unofficial") or [],
            "top5_probable": r.get("top5_probable") or [],
            "videos_confirmed": r.get("videos_confirmed") or [],
            "videos_probable": r.get("videos_probable") or [],
            "videos_unrelated": r.get("videos_unrelated") or [],
            "official_channel": r.get("official_channel"),
            "brand": r.get("brand") or {},
            "query": r.get("query") or "",
            "url": r.get("search_url") or "",
            "usage": r.get("usage") or {},
            "error": r.get("error"),
        })
    client = next((r for r in rows_out if r.get("is_client")), rows_out[0] if rows_out else {})
    usage = data.get("usage_total") or {}
    amb = bool((client.get("brand") or {}).get("ambiguous"))
    report["twitter_influencers"] = {
        "source": data.get("source") or "apify_tweet",
        "market": data.get("market") or "US",
        "leader": client.get("name") if client else "—",
        "total_traffic_fmt": client.get("views_unofficial_fmt") if client else "—",
        "unit": "confirmed other-author likes (≥50)",
        "rows": rows_out,
        "usage_total": usage,
        "insight": (
            f"X Apify «{client.get('query') or client.get('name') or '—'}»: "
            f"{client.get('confirmed_count') or 0} confirmed · "
            f"{client.get('probable_count') or 0} probable · "
            f"{client.get('unrelated_count') or 0} discarded · "
            f"other {_fmt_views(client.get('views_unofficial'))} likes"
            f"{' · ambiguous brand (review probable)' if amb else ''}."
        ),
        "analysis_title": "X Influencers",
        "pro_hook": "Na versão Pro mapeamos creators e formatos que geram likes no X do nicho.",
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


def _yt_json_needs_llm_filter(slug: str) -> bool:
    path = METRICAS_DIR / slug / f"youtube-influencers-{slug}.json"
    if not path.exists():
        return True
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("rows") or []
        if not rows:
            return True
        src = str(data.get("source") or "").lower()
        if "scrapingbee" not in src or "njs" not in src:
            return True
        if "title_desc" not in str(data.get("brand_filter") or ""):
            return True
        if not data.get("llm_title_filter"):
            return True
        if _inf_query_stale(data, slug):
            return True
        if not any(int(r.get("about_count") or 0) > 0 for r in rows):
            return True
        fetched = []
        for r in rows:
            fetched.extend(r.get("videos_fetched") or r.get("videos_unrelated") or [])
        empty = 0
        for v in fetched:
            if not isinstance(v, dict):
                continue
            title = str(v.get("title") or "").strip()
            if not title or title.lower() == "youtube":
                empty += 1
        if fetched and empty >= max(3, len(fetched) // 3):
            return True
        return False
    except Exception:
        return True


def _saved_brand_keyword(slug: str) -> str:
    for name in (f"brand-keyword-{slug}.json", f"brand-dataforseo-{slug}.json"):
        path = METRICAS_DIR / slug / name
        if not path.exists():
            continue
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        kw = str(data.get("keyword") or data.get("client_keyword") or "").strip()
        if kw:
            return kw
    return ""


def _inf_query_stale(data: Optional[dict], slug: str) -> bool:
    kw = _saved_brand_keyword(slug).lower()
    if not kw or not data:
        return False
    rows = data.get("rows") or []
    if not rows:
        return True
    row = next((r for r in rows if r.get("is_client")), rows[0])
    q = str((row or {}).get("query") or "").lower()
    return kw not in q


def _yt_official_needs_llm(slug: str) -> bool:
    path = METRICAS_DIR / slug / f"official-socials-{slug}.json"
    yt = METRICAS_DIR / slug / f"youtube-official-{slug}.json"
    try:
        import json

        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            yt = data.get("youtube") or {}
            if str(yt.get("pick_rule") or "") != "brand_handle":
                return True
            for plat in ("instagram", "tiktok", "youtube"):
                row = data.get(plat) or {}
                if not bool(row.get("llm_confirm")):
                    return True
            return False
        if yt.exists():
            data = json.loads(yt.read_text(encoding="utf-8"))
            return not bool(data.get("llm_confirm"))
    except Exception:
        return True
    return True


def _xlsx_needs_meta_ig_method(xlsx: Optional[Path]) -> bool:
    """Old metricas sheets lack Meta Method — refresh Meta via Instagram verify."""
    if not xlsx or not xlsx.exists():
        return False
    try:
        from openpyxl import load_workbook

        wb = load_workbook(xlsx, read_only=True, data_only=True)
        if "Metricas Canais" not in wb.sheetnames:
            wb.close()
            return True
        ws = wb["Metricas Canais"]
        headers = [str(c.value or "").strip().lower() for c in next(ws.iter_rows(max_row=1))]
        wb.close()
        return "meta method" not in headers
    except Exception:
        return True


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


def _extra_workers(n: int) -> int:
    raw = (os.environ.get("SPY_EXTRA_WORKERS") or "6").strip()
    try:
        want = int(raw)
    except ValueError:
        want = 6
    return max(1, min(want, 8, n))


def _run_independent_extras(
    extras: list[dict[str, Any]],
    *,
    slug: str,
    client_name: str,
    script_env: dict[str, str],
    emit: EmitFn,
    set_step: EmitFn,
    on_log: Callable[[str], None],
    report: dict,
    tag_report: Callable[[dict], dict],
    preferred_competitors: Optional[list] = None,
) -> dict:
    """Run independent channels together (SEO included). Cap at 8. XLSX writers lock+re-merge."""
    lock = threading.Lock()

    def _safe_log(line: str) -> None:
        with lock:
            on_log(line)

    def _steps(ex: dict[str, Any]) -> list[str]:
        raw = ex.get("steps") or [ex.get("step")]
        return [str(s) for s in raw if s]

    def _sections(ex: dict[str, Any]) -> list[str]:
        raw = ex.get("sections") or [ex.get("section")]
        return [str(s) for s in raw if s]

    def _one(ex: dict[str, Any]) -> tuple[dict[str, Any], Optional[str], float]:
        t0 = time.time()
        with lock:
            for sid in _steps(ex):
                _emit_progress(emit, set_step, sid, "running", ex["running"])
            emit("log", line=f"[PARALLEL] start {ex['tag']}")
        err = None
        try:
            argv = list(ex.get("argv") or [slug])
            _run_script(
                [sys.executable, str(ex["script"]), *argv],
                FINAL_DIR,
                _safe_log,
                timeout_sec=ex["timeout"],
                env=script_env,
            )
        except Exception as e:
            err = str(e)
        return ex, err, round(time.time() - t0, 2)

    if not extras:
        return report
    extras = sorted(extras, key=lambda e: int(e.get("priority") or 0), reverse=True)
    workers = _extra_workers(len(extras))
    names = ", ".join(
        f"{ex['tag']}{(' after ' + str(ex['after'])) if ex.get('after') else ''}"
        for ex in extras
    )
    emit("log", line=f"[PARALLEL] {len(extras)} channels · {workers} workers · {names}")
    t0 = time.time()

    def _finish(ex: dict[str, Any], err: Optional[str], elapsed: float) -> None:
        nonlocal report
        if err:
            emit("log", line=f"[{ex['tag']}] Partial failure: {err}")
        emit("log", line=f"[PARALLEL] done {ex['tag']} in {elapsed}s")
        kind = str(ex.get("kind") or "json").lower()
        if kind == "xlsx":
            try:
                xlsx_now = find_metricas_xlsx(slug)
                if xlsx_now:
                    report = build_report_from_xlsx(
                        xlsx_now,
                        client_name=client_name,
                        preferred_competitors=preferred_competitors,
                    )
            except Exception as e:
                emit("log", line=f"[{ex['tag']}] XLSX rebuild skipped: {e}")
            report = _attach_all_sidecars(report, slug)
        elif ex.get("attach"):
            report = ex["attach"](report, slug)
        report = tag_report(report)
        for section in _sections(ex):
            emit(
                "partial",
                section=section,
                data=report.get(section) or {},
                client=client_name,
            )
        for sid in _steps(ex):
            _emit_progress(emit, set_step, sid, "done", ex.get("done") or f"{sid} ready")

    pending = list(extras)
    in_flight: dict[Any, dict[str, Any]] = {}
    done_tags: set[str] = set()

    def _can_start(ex: dict[str, Any]) -> bool:
        dep = str(ex.get("after") or "").strip()
        return not dep or dep in done_tags

    with ThreadPoolExecutor(max_workers=workers) as pool:
        def _submit_ready() -> None:
            still: list[dict[str, Any]] = []
            for ex in pending:
                if _can_start(ex) and len(in_flight) < workers:
                    in_flight[pool.submit(_one, ex)] = ex
                else:
                    still.append(ex)
            pending[:] = still

        _submit_ready()
        while in_flight or pending:
            if not in_flight:
                for ex in pending:
                    emit(
                        "log",
                        line=f"[PARALLEL] skip {ex['tag']}: after={ex.get('after')} never finished",
                    )
                    for sid in _steps(ex):
                        _emit_progress(emit, set_step, sid, "done", "Skipped (dep missing)")
                break
            done_futs, _ = wait(list(in_flight.keys()), return_when=FIRST_COMPLETED)
            for fut in done_futs:
                ex = in_flight.pop(fut)
                _ex, err, elapsed = fut.result()
                _finish(_ex, err, elapsed)
                done_tags.add(str(ex.get("tag") or ""))
            _submit_ready()
    emit(
        "log",
        line=f"[PARALLEL] channels wall {round(time.time() - t0, 2)}s (vs sequential sum of each channel)",
    )
    return report


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
    clock = _STEP_CLOCK.get()
    meta = next((s for s in defs if s["id"] == step_id), None)
    if meta is None and clock is not None:
        meta = clock.lookup(step_id)
    set_step(step_id, state, detail)
    if clock is not None:
        clock.mark(step_id, state)
        snap = clock.snapshot()
        emit(
            "progress",
            step_id=step_id,
            state=state,
            detail=detail,
            label=(meta or {}).get("label") or step_id,
            **snap,
        )
        return
    index = int(meta["index"]) if meta and meta.get("index") is not None else 0
    total = len(defs) if steps else TOTAL_STEPS
    eta = int(meta.get("eta_live") or 60) if meta else 60
    emit(
        "progress",
        step_id=step_id,
        state=state,
        detail=detail,
        index=index,
        total=total,
        done_count=index,
        label=meta["label"] if meta else step_id,
        eta_seconds=eta,
        eta_label=_fmt_eta(eta),
        progress_label=f"{index}/{total} steps",
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
    include_tiktok_influencers: bool = False,
    include_twitter_influencers: bool = False,
    include_reddit: bool = False,
    include_twitter: bool = False,
    include_linkedin_profile: bool = False,
    force: bool = False,
    market: str = "us",
    compare_all: bool = False,
    competitors_only: bool = False,
    include_brand_growth: bool = False,
    include_similarweb_alto: bool = False,
    urls_only: bool = False,
) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    import json
    from datetime import datetime, timezone

    market = _normalize_market(market)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing_meta = run_dir / "meta.json"
    if existing_meta.exists():
        try:
            old = json.loads(existing_meta.read_text(encoding="utf-8"))
            if old.get("created_at"):
                created_at = str(old["created_at"])
        except Exception:
            pass
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
        "urls_only": bool(urls_only),
        "peer_urls": list(parsed.competitors or []),
        "include_google_ads": bool(include_google_ads),
        "include_linkedin": bool(include_linkedin),
        "include_youtube_influencers": bool(include_youtube_influencers),
        "include_instagram_influencers": bool(include_instagram_influencers),
        "include_tiktok_influencers": bool(include_tiktok_influencers),
        "include_twitter_influencers": bool(include_twitter_influencers),
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
    report = _attach_tiktok_influencers(report, slug)
    report = _attach_twitter_influencers(report, slug)
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
    include_tiktok_influencers: bool = False,
    include_twitter_influencers: bool = False,
    include_reddit: bool = False,
    include_twitter: bool = False,
    include_linkedin_profile: bool = False,
    market: str = "us",
) -> dict:
    """Ensure per-slug caches, then merge into one compare_all report (no multi-peer scrape)."""
    market = _normalize_market(market)
    os.environ["SPY_MARKET"] = market
    _enable_llm_log(run_id)
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

    planned = _planned_analysis_steps(
        include_google_ads=include_google_ads,
        include_linkedin=include_linkedin,
        include_youtube_influencers=include_youtube_influencers,
        include_instagram_influencers=include_instagram_influencers,
        include_tiktok_influencers=include_tiktok_influencers,
        include_twitter_influencers=include_twitter_influencers,
        include_reddit=include_reddit,
        include_twitter=include_twitter,
        include_linkedin_profile=include_linkedin_profile,
    )
    n_cos = len(companies)
    n_fetch = sum(
        1 for c in companies if force or not find_metricas_xlsx(c["slug"])
    )
    n_cached = n_cos - n_fetch
    # One company at a time. ~3 min for a full fetch, ~45s when the cache is warm.
    eta = ANALYSIS_WALL_SEC * n_fetch + 45 * n_cached
    if eta < 45:
        eta = 45
    clock, _token = _bind_step_clock(planned, eta_total=eta)
    clock.set_companies(n_cos, 0)

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
        include_tiktok_influencers=include_tiktok_influencers,
        include_twitter_influencers=include_twitter_influencers,
        include_reddit=include_reddit,
        include_twitter=include_twitter,
        include_linkedin_profile=include_linkedin_profile,
        **clock.meta_payload(),
    )
    _emit_progress(
        emit, set_step, "briefing_concorrentes", "running",
        f"All: ensuring caches ({len(companies)} empresas)",
    )

    def _child_emit(event: str, **payload: Any) -> None:
        # Nested individual runs must not finish/close the parent All job,
        # or reset the All timer / 1/5 company counter back to a 3-minute single run.
        if event in ("done", "pipeline_meta"):
            return
        if event == "progress":
            for key in (
                "eta_seconds", "eta_label", "done_count", "total", "total_steps",
                "index", "progress_label", "pct", "time_label",
                "company_done", "company_total",
            ):
                payload.pop(key, None)
        emit(event, **payload)

    fetched = 0
    cached = 0
    for i, company in enumerate(companies):
        c_slug = company["slug"]
        c_url = company["url"]
        c_name = company["name"]
        has_cache = bool(find_metricas_xlsx(c_slug))
        need_fetch = bool(force) or not has_cache
        line_mark = len(recorder.lines)
        clock.set_companies(n_cos, i)
        _emit_progress(
            emit, set_step, "briefing_concorrentes", "running",
            f"All: {c_name} ({i + 1}/{n_cos})",
        )
        if need_fetch:
            emit(
                "log",
                line=(
                    f"[ALL] ({i + 1}/{len(companies)}) Fetching {c_name} ({c_slug})"
                    + (" · force" if force else " · no cache")
                ),
            )
            child = ParsedInput(
                company=c_name,
                url=c_url,
                slug=c_slug,
                competitors=[],
            )
            child_report = run_pipeline(
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
                include_tiktok_influencers=include_tiktok_influencers,
            include_twitter_influencers=include_twitter_influencers,
                include_reddit=include_reddit,
                include_twitter=include_twitter,
                include_linkedin_profile=include_linkedin_profile,
                market=market,
                compare_all=False,
            )
            if isinstance(child_report, dict):
                child_log = child_report.get("run_log") or {}
                recorder.absorb_child_log(child_log)
                recorder.add_company_log(c_slug, c_name, child_log)
            else:
                recorder.add_company_log(c_slug, c_name, extra_lines=[])
            fetched += 1
            _STEP_CLOCK.set(clock)  # child run_pipeline replaces the All clock
        else:
            xlsx = find_metricas_xlsx(c_slug)
            if _xlsx_needs_meta_ig_method(xlsx):
                emit(
                    "log",
                    line=f"[ALL] ({i + 1}/{len(companies)}) Refresh Meta (Instagram verify) {c_name} ({c_slug})",
                )
                _emit_progress(
                    emit, set_step, "meta", "running",
                    f"All: Meta Instagram {c_name} ({i + 1}/{len(companies)})",
                )
                try:
                    _run_script(
                        [sys.executable, str(SCRIPT_META), c_slug],
                        FINAL_DIR,
                        lambda line: emit("log", line=line),
                        timeout_sec=420,
                        env={"SPY_SITE_ONLY": "1", "SPY_MARKET": market, "SPY_COMPARE_ALL": "1"},
                    )
                except Exception as e:
                    emit("log", line=f"[ALL] WARN Meta refresh {c_slug}: {e}")
            if include_youtube_influencers and _yt_json_needs_llm_filter(c_slug):
                emit(
                    "log",
                    line=f"[ALL] ({i + 1}/{len(companies)}) Refresh YouTube titles (LLM) {c_name} ({c_slug})",
                )
                _emit_progress(
                    emit, set_step, "youtube_influencers", "running",
                    f"All: YouTube LLM {c_name} ({i + 1}/{len(companies)})",
                )
                try:
                    _run_script(
                        [sys.executable, str(SCRIPT_YT_INFLUENCERS), c_slug],
                        FINAL_DIR,
                        lambda line: emit("log", line=line),
                        timeout_sec=240,
                        env={"SPY_SITE_ONLY": "1", "SPY_MARKET": market, "SPY_COMPARE_ALL": "1"},
                    )
                except Exception as e:
                    emit("log", line=f"[ALL] WARN YouTube refresh {c_slug}: {e}")
            if include_tiktok_influencers and _tt_json_missing(c_slug):
                emit(
                    "log",
                    line=f"[ALL] ({i + 1}/{len(companies)}) TikTok Apify {c_name} ({c_slug})",
                )
                _emit_progress(
                    emit, set_step, "tiktok_influencers", "running",
                    f"All: TikTok Apify {c_name} ({i + 1}/{len(companies)})",
                )
                try:
                    _run_script(
                        [sys.executable, str(SCRIPT_TT_INFLUENCERS), c_slug],
                        FINAL_DIR,
                        lambda line: emit("log", line=line),
                        timeout_sec=240,
                        env={"SPY_SITE_ONLY": "1", "SPY_MARKET": market, "SPY_COMPARE_ALL": "1"},
                    )
                except Exception as e:
                    emit("log", line=f"[ALL] WARN TikTok refresh {c_slug}: {e}")
            if include_twitter_influencers and _x_inf_json_missing(c_slug):
                emit(
                    "log",
                    line=f"[ALL] ({i + 1}/{len(companies)}) X Apify {c_name} ({c_slug})",
                )
                _emit_progress(
                    emit, set_step, "twitter_influencers", "running",
                    f"All: X Apify {c_name} ({i + 1}/{len(companies)})",
                )
                try:
                    _run_script(
                        [sys.executable, str(SCRIPT_X_INFLUENCERS), c_slug],
                        FINAL_DIR,
                        lambda line: emit("log", line=line),
                        timeout_sec=240,
                        env={"SPY_SITE_ONLY": "1", "SPY_MARKET": market, "SPY_COMPARE_ALL": "1"},
                    )
                except Exception as e:
                    emit("log", line=f"[ALL] WARN X influencers refresh {c_slug}: {e}")
            if _brand_dfs_needs_llm(c_slug):
                emit(
                    "log",
                    line=f"[ALL] ({i + 1}/{len(companies)}) Refresh brand keyword (LLM) {c_name} ({c_slug})",
                )
                _emit_progress(
                    emit, set_step, "brand_dfs", "running",
                    f"All: Brand keyword LLM {c_name} ({i + 1}/{len(companies)})",
                )
                try:
                    _run_script(
                        [sys.executable, str(SCRIPT_BRAND_DFS), c_slug],
                        FINAL_DIR,
                        lambda line: emit("log", line=line),
                        timeout_sec=180,
                        env={"SPY_SITE_ONLY": "1", "SPY_MARKET": market, "SPY_COMPARE_ALL": "1"},
                    )
                except Exception as e:
                    emit("log", line=f"[ALL] WARN brand keyword refresh {c_slug}: {e}")
            if _yt_official_needs_llm(c_slug):
                emit(
                    "log",
                    line=f"[ALL] ({i + 1}/{len(companies)}) Refresh YouTube official (LLM) {c_name} ({c_slug})",
                )
                _emit_progress(
                    emit, set_step, "youtube", "running",
                    f"All: YouTube official LLM {c_name} ({i + 1}/{len(companies)})",
                )
                try:
                    _run_script(
                        [sys.executable, str(SCRIPT_SOCIAL), c_slug],
                        FINAL_DIR,
                        lambda line: emit("log", line=line),
                        timeout_sec=600,
                        env={"SPY_SITE_ONLY": "1", "SPY_MARKET": market, "SPY_COMPARE_ALL": "1"},
                    )
                except Exception as e:
                    emit("log", line=f"[ALL] WARN YouTube official refresh {c_slug}: {e}")
            cached += 1
            emit("log", line=f"[ALL] ({i + 1}/{len(companies)}) Cache hit {c_name} ({c_slug})")
            recorder.add_company_log(
                c_slug,
                c_name,
                extra_lines=recorder.lines[line_mark:],
            )
        clock.set_companies(n_cos, i + 1)
        _emit_progress(
            emit, set_step, "briefing_concorrentes", "running",
            f"All: done {c_name} ({i + 1}/{n_cos})",
        )

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
        "tiktok_influencers": not include_tiktok_influencers,
        "twitter_influencers": not include_twitter_influencers,
        "reddit": not include_reddit,
        "twitter": not include_twitter,
        "linkedin_profile": not include_linkedin_profile,
    }
    for sid in (
        "seo", "brand", "brand_dfs", "similarweb", "google_ads", "meta",
        "linkedin", "instagram", "youtube", "tiktok",
        "youtube_influencers", "instagram_influencers", "tiktok_influencers",
        "twitter_influencers",
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
            include_tiktok_influencers=include_tiktok_influencers,
            include_twitter_influencers=include_twitter_influencers,
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
    similarweb_all: bool = False,
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
            usage = dict(getattr(brand_reports_batch, "last_usage", None) or {})
            if usage:
                report["brand_growth_usage"] = usage
                _log(
                    f"[BRAND] usage cost=${usage.get('cost_usd')} "
                    f"src={usage.get('source')} cached={usage.get('cached')} "
                    f"labs={usage.get('labs')} fallback={usage.get('fallback')}"
                )
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
                if similarweb_all or c.get("is_client") or sim == "alto":
                    if c.get("domain") or c.get("url"):
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
            scope = "lista" if similarweb_all else "Alto+cliente"
            _log(f"[SIMILARWEB] {scope}: {len(targets)} domínio(s)")
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


def _host_of_raw(raw: str) -> str:
    href = normalize_url(raw) or (raw or "").strip()
    if not href:
        return ""
    if "://" not in href:
        href = "https://" + href
    try:
        from urllib.parse import urlparse

        host = (urlparse(href).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host.strip(".")


def _name_from_host(domain: str) -> str:
    token = (domain or "").split(".")[0]
    token = "".join(ch for ch in token if ch.isalnum())
    if not token:
        return domain or "—"
    return token[:1].upper() + token[1:]


def _row_from_url(raw: str, *, is_client: bool) -> dict[str, Any]:
    href = normalize_url(raw) or ""
    if not href and raw:
        href = str(raw).strip()
        if href and "://" not in href:
            href = "https://" + href
        if href and not href.endswith("/"):
            href += "/"
    domain = _host_of_raw(href or raw)
    name = _name_from_host(domain)
    return {
        "name": name,
        "domain": domain,
        "url": href or (f"https://{domain}/" if domain else ""),
        "title": "",
        "similaridade": "Cliente" if is_client else "Alto",
        "perfil": "—",
        "nicho": "—",
        "motivo": "Added by URL — no research",
        "fonte": "manual",
        "is_client": is_client,
        "manual": True,
    }


def _report_from_url_list(
    primary_url: str,
    client_name: str,
    peers: Optional[list[str]] = None,
    market: str = "us",
) -> dict:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    primary = _row_from_url(primary_url, is_client=True)
    if client_name:
        primary["name"] = client_name
    if primary.get("domain"):
        seen.add(primary["domain"])
        rows.append(primary)
    for peer in peers or []:
        row = _row_from_url(peer, is_client=False)
        domain = str(row.get("domain") or "")
        if not domain or domain in seen:
            continue
        seen.add(domain)
        rows.append(row)
    n_peers = sum(1 for r in rows if not r.get("is_client"))
    briefing = {
        "client": client_name or primary.get("name") or "",
        "url": primary.get("url") or primary_url,
        "resumo": "URLs added only — no competitor research.",
        "nicho": "—",
    }
    return {
        "client": briefing["client"],
        "briefing": briefing,
        "competitors": rows,
        "competitors_count": n_peers,
        "competitors_note": (
            f"URLs added only — no research. {n_peers} site(s) from the pasted list."
        ),
        "competitors_stats": {"alto": n_peers, "medio": 0, "baixo": 0, "cliente": 1},
        "competitors_raw": rows,
        "display_tier": "all",
        "competitors_only": True,
        "urls_only": True,
        "market": (market or "us").upper(),
        "compare_all": False,
    }


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
    urls_only: bool = False,
) -> dict:
    """Briefing + discovery nacional (SEO + LLM + Semrush). Sem métricas de canal.

    urls_only=True skips briefing and discovery and scores the pasted URL list.
    """
    required = (
        "OPENROUTER_API_KEY",
        "SCRAPINGBEE_API_KEY",
        "DATAFORSEO_USER",
        "DATAFORSEO_PASS",
        "SEMRUSH_API_KEY",
    )
    if urls_only:
        required = ("SEMRUSH_API_KEY",)
        if include_brand_growth:
            required = required + ("DATAFORSEO_USER", "DATAFORSEO_PASS")
    missing = [k for k in required if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError("Missing API keys: " + ", ".join(missing))

    market = _normalize_market(market)
    os.environ["SPY_MARKET"] = market
    _enable_llm_log(run_id)
    url = normalize_url(parsed.url) or parsed.url
    if not url:
        raise ValueError("Company URL is required.")
    slug = parsed.slug or slugify_client(url)
    client_name = parsed.company or slug
    script_env = {"SPY_SITE_ONLY": "0", "SPY_MARKET": market, "SPY_COMPARE_ALL": "0"}
    n_list = 1 + len(list(parsed.competitors or []))
    if urls_only:
        steps = [{
            "id": "briefing_concorrentes",
            "label": "Load list",
            "index": 1,
            "eta_live": 10,
        }]
        if include_brand_growth:
            steps.append({
                "id": "brand_growth",
                "label": "Brand growth (Aug 26/25/24)",
                "index": 2,
                "eta_live": 40,
            })
        if include_similarweb_alto:
            steps.append({
                "id": "similarweb_alto",
                "label": "SimilarWeb (list)",
                "index": len(steps) + 1,
                "eta_live": max(30, 10 * n_list),
            })
        find_eta = 20 + (40 if include_brand_growth else 0)
        if include_similarweb_alto:
            find_eta += max(30, 10 * n_list)
    else:
        steps = [s for s in COMPETITORS_ONLY_STEPS if s["id"] in {
            "briefing_concorrentes", "competitors_discover",
        } or (s["id"] == "brand_growth" and include_brand_growth)
          or (s["id"] == "similarweb_alto" and include_similarweb_alto)]
        find_eta = FIND_WALL_SEC
    for i, s in enumerate(steps, 1):
        s = dict(s)
        s["index"] = i
        steps[i - 1] = s

    recorder = RunRecorder()
    emit = _wrap_emit_logger(emit, recorder)
    set_step = _wrap_set_step_timer(set_step, recorder)
    clock, _token = _bind_step_clock(steps, eta_total=find_eta)

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
            include_tiktok_influencers=False,
            include_twitter_influencers=False,
            include_reddit=False,
            include_twitter=False,
            include_linkedin_profile=False,
            force=force,
            market=market,
            compare_all=False,
            competitors_only=True,
            include_brand_growth=include_brand_growth,
            include_similarweb_alto=include_similarweb_alto,
            urls_only=urls_only,
        )

    emit(
        "pipeline_meta",
        mode="urls_only" if urls_only else "competitors_only",
        market=market.upper(),
        site_only=False,
        compare_all=False,
        competitors_only=True,
        include_brand_growth=include_brand_growth,
        include_similarweb_alto=include_similarweb_alto,
        urls_only=urls_only,
        **clock.meta_payload(),
    )

    if urls_only:
        _prog("briefing_concorrentes", "running", f"Load list ({n_list} URL{'s' if n_list != 1 else ''})")
        emit("log", line=f"[FIND] URLs only — no research ({n_list} site(s))")
        report = _report_from_url_list(
            url,
            client_name,
            list(parsed.competitors or []),
            market=market,
        )
        n_ready = report.get("competitors_count") or 0
        _prog("briefing_concorrentes", "done", f"{n_ready} site(s) from the list")
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
            _prog("similarweb_alto", "running", "SimilarWeb na lista…")
            report = _enrich_competitors_brand_sw(
                report,
                include_brand_growth=False,
                include_similarweb_alto=True,
                similarweb_all=True,
                emit=emit,
            )
            _prog("similarweb_alto", "done", "SimilarWeb ready")
        if run_id:
            _persist_report_with_log(run_id, report, parsed, recorder, **_save_kw())
        else:
            attach_run_log(report, recorder)
        emit("partial", section="briefing_concorrentes", data=report, client=client_name)
        emit("done", report=report, html_url=html_url)
        return report

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
    include_tiktok_influencers: bool = False,
    include_twitter_influencers: bool = False,
    include_reddit: bool = False,
    include_twitter: bool = False,
    include_linkedin_profile: bool = False,
    market: str = "us",
    compare_all: bool = False,
    competitors_only: bool = False,
    include_brand_growth: bool = False,
    include_similarweb_alto: bool = False,
    urls_only: bool = False,
) -> dict:
    required = (
        "OPENROUTER_API_KEY",
        "SCRAPINGBEE_API_KEY",
        "DATAFORSEO_USER",
        "DATAFORSEO_PASS",
        "SEMRUSH_API_KEY",
    )
    if urls_only and competitors_only:
        required = ("SEMRUSH_API_KEY",)
        if include_brand_growth:
            required = required + ("DATAFORSEO_USER", "DATAFORSEO_PASS")
    missing = [k for k in required if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError("Missing API keys: " + ", ".join(missing))

    if competitors_only:
        return run_competitors_only_pipeline(
            parsed, emit, set_step, run_id=run_id, force=force, market=market,
            include_brand_growth=include_brand_growth,
            include_similarweb_alto=include_similarweb_alto,
            urls_only=urls_only,
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
            include_tiktok_influencers=include_tiktok_influencers,
            include_twitter_influencers=include_twitter_influencers,
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
        "SPY_SLUG": slug,
    }
    # Ensure parent process market helpers (report_builder) see the same market
    os.environ["SPY_MARKET"] = market
    os.environ["SPY_SLUG"] = slug
    os.environ.pop("SPY_BRAND_KEYWORD", None)
    _enable_llm_log(run_id)

    recorder = RunRecorder()
    emit = _wrap_emit_logger(emit, recorder)
    set_step = _wrap_set_step_timer(set_step, recorder)
    planned = _planned_analysis_steps(
        include_google_ads=include_google_ads,
        include_linkedin=include_linkedin,
        include_youtube_influencers=include_youtube_influencers,
        include_instagram_influencers=include_instagram_influencers,
        include_tiktok_influencers=include_tiktok_influencers,
        include_twitter_influencers=include_twitter_influencers,
        include_reddit=include_reddit,
        include_twitter=include_twitter,
        include_linkedin_profile=include_linkedin_profile,
    )
    clock, _token = _bind_step_clock(planned, eta_total=ANALYSIS_WALL_SEC)

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
            include_tiktok_influencers=include_tiktok_influencers,
            include_twitter_influencers=include_twitter_influencers,
            include_reddit=include_reddit,
            include_twitter=include_twitter,
            include_linkedin_profile=include_linkedin_profile,
            force=force,
            market=market,
            compare_all=compare_all,
            competitors_only=False,
        )

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
        include_tiktok_influencers=include_tiktok_influencers,
        include_twitter_influencers=include_twitter_influencers,
        include_reddit=include_reddit,
        include_twitter=include_twitter,
        include_linkedin_profile=include_linkedin_profile,
        **clock.meta_payload(),
    )

    if force:
        clear_slug_cache(slug)

    existing = find_metricas_xlsx(slug)
    if existing and existing.exists() and not force:
        if _xlsx_needs_meta_ig_method(existing):
            emit("log", line=f"[CACHE] Refreshing Meta via Instagram for {slug}")
            _emit_progress(emit, set_step, "meta", "running", "Meta Ads via Instagram…")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_META), slug],
                    FINAL_DIR,
                    on_log,
                    timeout_sec=420,
                    env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[META] Refresh failed: {e}")
            existing = find_metricas_xlsx(slug) or existing
        if include_youtube_influencers and _yt_json_needs_llm_filter(slug):
            emit("log", line=f"[CACHE] Refreshing YouTube titles via LLM for {slug}")
            _emit_progress(emit, set_step, "youtube_influencers", "running", "YouTube titles (LLM)…")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_YT_INFLUENCERS), slug],
                    FINAL_DIR,
                    on_log,
                    timeout_sec=240,
                    env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[YT-INF] Refresh failed: {e}")
        if include_tiktok_influencers and _tt_json_missing(slug):
            emit("log", line=f"[CACHE] Refreshing TikTok titles via LLM for {slug}")
            _emit_progress(emit, set_step, "tiktok_influencers", "running", "TikTok titles (LLM)…")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_TT_INFLUENCERS), slug],
                    FINAL_DIR,
                    on_log,
                    timeout_sec=240,
                    env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[TT-INF] Refresh failed: {e}")
        if include_twitter_influencers and _x_inf_json_missing(slug):
            emit("log", line=f"[CACHE] Refreshing X titles via LLM for {slug}")
            _emit_progress(emit, set_step, "twitter_influencers", "running", "X titles (LLM)…")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_X_INFLUENCERS), slug],
                    FINAL_DIR,
                    on_log,
                    timeout_sec=240,
                    env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[X-INF] Refresh failed: {e}")
        if _yt_official_needs_llm(slug):
            emit("log", line=f"[CACHE] Refreshing YouTube official via LLM for {slug}")
            _emit_progress(emit, set_step, "youtube", "running", "YouTube official (LLM)…")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_SOCIAL), slug],
                    FINAL_DIR,
                    on_log,
                    timeout_sec=600,
                    env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[SOCIAL] YouTube official refresh failed: {e}")
        if _brand_dfs_needs_llm(slug):
            emit("log", line=f"[CACHE] Refreshing brand keyword via LLM for {slug}")
            _emit_progress(emit, set_step, "brand_dfs", "running", "Brand keyword (LLM)…")
            try:
                _run_script(
                    [sys.executable, str(SCRIPT_BRAND_DFS), slug],
                    FINAL_DIR,
                    on_log,
                    timeout_sec=180,
                    env=script_env,
                )
            except Exception as e:
                emit("log", line=f"[BRAND/DFS] keyword refresh failed: {e}")
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
            "youtube_influencers", "instagram_influencers", "tiktok_influencers",
        "twitter_influencers",
            "reddit", "twitter", "linkedin_profile",
        ):
            _emit_progress(emit, set_step, sid, "done", "Cached")
        report = _attach_brand_dfs(report, slug)
        report = _attach_similarweb(report, slug)
        report = _attach_youtube_influencers(report, slug)
        report = _attach_instagram_influencers(report, slug)
        report = _attach_tiktok_influencers(report, slug)
        report = _attach_twitter_influencers(report, slug)
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

    brand_kw = _prime_brand_keyword(slug, url, client_name, emit)
    if brand_kw:
        script_env["SPY_BRAND_KEYWORD"] = brand_kw
        os.environ["SPY_BRAND_KEYWORD"] = brand_kw

    report: dict[str, Any] = {"client": client_name, "url": url}
    xlsx = find_metricas_xlsx(slug)

    # 2+) SEO + independent channels in parallel (XLSX writers lock+re-merge; JSON extras are sidecars)
    _tf = (os.environ.get("TINYFISH_API_KEY") or "").strip()
    _sb = (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip()
    _dfs = bool(
        (os.environ.get("DATAFORSEO_USER") or os.environ.get("DATAFORSEO_LOGIN") or "").strip()
        and (os.environ.get("DATAFORSEO_PASS") or os.environ.get("DATAFORSEO_PASSWORD") or "").strip()
    )
    extras: list[dict[str, Any]] = []

    extras.append({
        "tag": "SEO",
        "step": "seo",
        "section": "seo",
        "script": SCRIPT_SEO,
        "timeout": 180,
        "kind": "xlsx",
        "priority": 95,
        "running": "Building US SEO ranking...",
        "done": "SEO ready",
    })
    extras.append({
        "tag": "BRAND",
        "step": "brand",
        "section": "brand",
        "script": SCRIPT_BRAND,
        "timeout": 180,
        "kind": "xlsx",
        "priority": 10,
        "running": "Building brand ranking...",
        "done": "Brand Semrush ready",
    })
    extras.append({
        "tag": "BRAND/DFS",
        "step": "brand_dfs",
        "section": "brand_dataforseo",
        "script": SCRIPT_BRAND_DFS,
        "timeout": 180,
        "kind": "json",
        "priority": 20,
        "running": "Brand DataForSEO US (1y/2y/3y/5y)...",
        "done": "Brand DataForSEO ready",
        "attach": _attach_brand_dfs,
    })
    extras.append({
        "tag": "SIMILARWEB",
        "step": "similarweb",
        "section": "similarweb",
        "script": SCRIPT_SIMILARWEB,
        "timeout": 180,
        "kind": "json",
        "priority": 40,
        "running": "SimilarWeb Traffic (Apify)...",
        "done": "SimilarWeb ready",
        "attach": _attach_similarweb,
    })
    if include_google_ads:
        extras.append({
            "tag": "GOOGLE",
            "step": "google_ads",
            "section": "google_ads",
            "script": SCRIPT_GOOGLE,
            "timeout": 420,
            "kind": "xlsx",
            "priority": 25,
            "running": "Google Ads Transparency (domain, anywhere)...",
            "done": "Google Ads ready",
        })
    else:
        _emit_progress(emit, set_step, "google_ads", "done", "Skipped")
    extras.append({
        "tag": "META",
        "step": "meta",
        "section": "meta",
        "script": SCRIPT_META,
        "timeout": 420,
        "kind": "xlsx",
        "priority": 30,
        "running": "Meta Ads Library (US)...",
        "done": "Meta ready",
    })
    if include_linkedin:
        extras.append({
            "tag": "LINKEDIN",
            "step": "linkedin",
            "section": "linkedin",
            "script": SCRIPT_LINKEDIN,
            "timeout": 600,
            "kind": "xlsx",
            "priority": 35,
            "running": "LinkedIn Ads Library (US): find ad → payer → total...",
            "done": "LinkedIn ready",
        })
    else:
        _emit_progress(emit, set_step, "linkedin", "done", "Skipped")
    extras.append({
        "tag": "SOCIAL-IG",
        "step": "instagram",
        "section": "instagram",
        "script": SCRIPT_METRICAS,
        "argv": [slug, "social_ig"],
        "timeout": 420,
        "kind": "xlsx",
        "priority": 78,
        "running": "Instagram official...",
        "done": "Instagram ready",
    })
    extras.append({
        "tag": "SOCIAL-YT",
        "step": "youtube",
        "section": "youtube",
        "script": SCRIPT_METRICAS,
        "argv": [slug, "social_yt"],
        "timeout": 420,
        "kind": "xlsx",
        "priority": 76,
        "running": "YouTube official...",
        "done": "YouTube ready",
    })
    extras.append({
        "tag": "SOCIAL-TT",
        "step": "tiktok",
        "section": "tiktok",
        "script": SCRIPT_METRICAS,
        "argv": [slug, "social_tt"],
        "timeout": 420,
        "kind": "xlsx",
        "priority": 74,
        "running": "TikTok official...",
        "done": "TikTok ready",
    })

    if include_youtube_influencers:
        if not (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip():
            emit("log", line="[YT-INF] Skipped: SCRAPINGBEE_API_KEY missing")
            _emit_progress(emit, set_step, "youtube_influencers", "done", "Skipped (no ScrapingBee key)")
        else:
            extras.append({
                "tag": "YT-INF",
                "step": "youtube_influencers",
                "section": "youtube_influencers",
                "script": SCRIPT_YT_INFLUENCERS,
                "timeout": 180,
                "kind": "json",
                "priority": 90,
                "running": "YouTube Influencers (ScrapingBee search)…",
                "done": "YouTube Influencers ready",
                "attach": _attach_youtube_influencers,
            })
    else:
        _emit_progress(emit, set_step, "youtube_influencers", "done", "Skipped")

    if include_instagram_influencers:
        if not _tf:
            emit("log", line="[IG-INF] Skipped: TINYFISH_API_KEY missing")
            _emit_progress(emit, set_step, "instagram_influencers", "done", "Skipped (no TinyFish key)")
        else:
            extras.append({
                "tag": "IG-INF",
                "step": "instagram_influencers",
                "section": "instagram_influencers",
                "script": SCRIPT_IG_INFLUENCERS,
                "timeout": 600,
                "kind": "json",
                "priority": 80,
                "after": "SOCIAL-IG",
                "running": "Instagram Influencers (Search + page download)...",
                "done": "Instagram Influencers ready",
                "attach": _attach_instagram_influencers,
            })
    else:
        _emit_progress(emit, set_step, "instagram_influencers", "done", "Skipped")

    if include_tiktok_influencers:
        _apify = (
            os.environ.get("APIFY_TOKEN")
            or os.environ.get("APIFY_API_TOKEN")
            or os.environ.get("APIFY_API_KEY")
            or ""
        ).strip()
        if not _apify:
            emit("log", line="[TT-INF] Skipped: APIFY_TOKEN missing")
            _emit_progress(emit, set_step, "tiktok_influencers", "done", "Skipped (no Apify key)")
        else:
            extras.append({
                "tag": "TT-INF",
                "step": "tiktok_influencers",
                "section": "tiktok_influencers",
                "script": SCRIPT_TT_INFLUENCERS,
                "timeout": 240,
                "kind": "json",
                "priority": 50,
                "running": "TikTok Influencers (Apify + brand filter)…",
                "done": "TikTok Influencers ready",
                "attach": _attach_tiktok_influencers,
            })
    else:
        _emit_progress(emit, set_step, "tiktok_influencers", "done", "Skipped")

    if include_twitter_influencers:
        _apify_x = (
            os.environ.get("APIFY_TOKEN")
            or os.environ.get("APIFY_API_TOKEN")
            or os.environ.get("APIFY_API_KEY")
            or ""
        ).strip()
        if not _apify_x:
            emit("log", line="[X-INF] Skipped: APIFY_TOKEN missing")
            _emit_progress(emit, set_step, "twitter_influencers", "done", "Skipped (no Apify key)")
        else:
            extras.append({
                "tag": "X-INF",
                "step": "twitter_influencers",
                "section": "twitter_influencers",
                "script": SCRIPT_X_INFLUENCERS,
                "timeout": 240,
                "kind": "json",
                "priority": 48,
                "running": "X Influencers (Apify min_faves:50)…",
                "done": "X Influencers ready",
                "attach": _attach_twitter_influencers,
            })
    else:
        _emit_progress(emit, set_step, "twitter_influencers", "done", "Skipped")

    if include_reddit:
        if not _tf:
            emit("log", line="[REDDIT] Skipped: TINYFISH_API_KEY missing")
            _emit_progress(emit, set_step, "reddit", "done", "Skipped (no TinyFish key)")
        else:
            extras.append({
                "tag": "REDDIT",
                "step": "reddit",
                "section": "reddit",
                "script": SCRIPT_REDDIT,
                "timeout": 240,
                "kind": "json",
                "priority": 55,
                "running": "Reddit (site:reddit.com + comments)...",
                "done": "Reddit ready",
                "attach": _attach_reddit,
            })
    else:
        _emit_progress(emit, set_step, "reddit", "done", "Skipped")

    if include_twitter:
        if not _tf:
            emit("log", line="[TW] Skipped: TINYFISH_API_KEY missing")
            _emit_progress(emit, set_step, "twitter", "done", "Skipped (no TinyFish key)")
        else:
            extras.append({
                "tag": "TW",
                "step": "twitter",
                "section": "twitter",
                "script": SCRIPT_TWITTER,
                "timeout": 180,
                "kind": "json",
                "priority": 45,
                "running": "Twitter/X profile...",
                "done": "Twitter ready",
                "attach": _attach_twitter,
            })
    else:
        _emit_progress(emit, set_step, "twitter", "done", "Skipped")

    _or = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if include_linkedin_profile:
        if not (_tf or _sb or _dfs or _or):
            emit("log", line="[LI] Skipped: no TinyFish / ScrapingBee / DataForSEO / OpenRouter key")
            _emit_progress(emit, set_step, "linkedin_profile", "done", "Skipped (no SERP or OpenRouter key)")
        else:
            extras.append({
                "tag": "LI",
                "step": "linkedin_profile",
                "section": "linkedin_profile",
                "script": SCRIPT_LI_PROFILE,
                "timeout": 180,
                "kind": "json",
                "priority": 15,
                "running": "LinkedIn profile (Google + OpenRouter online)...",
                "done": "LinkedIn Profile ready",
                "attach": _attach_linkedin_profile,
            })
    else:
        _emit_progress(emit, set_step, "linkedin_profile", "done", "Skipped")

    if extras:
        report = _run_independent_extras(
            extras,
            slug=slug,
            client_name=client_name,
            script_env=script_env,
            emit=emit,
            set_step=set_step,
            on_log=on_log,
            report=report,
            tag_report=_tag_report,
            preferred_competitors=parsed.competitors,
        )
        xlsx = find_metricas_xlsx(slug) or xlsx
        if xlsx:
            try:
                report = build_report_from_xlsx(
                    xlsx,
                    client_name=client_name,
                    preferred_competitors=parsed.competitors,
                )
            except Exception as e:
                emit("log", line=f"[PARALLEL] final XLSX rebuild skipped: {e}")
        report = _attach_all_sidecars(report, slug)
        report = _tag_report(report)

    html_url = ""
    if run_id:
        _persist_report_with_log(run_id, report, parsed, recorder, **_save_kw())
        html_url = f"/runs/{run_id}/report.html"
    else:
        attach_run_log(report, recorder)

    emit("done", report=report, html_url=html_url)
    return report
