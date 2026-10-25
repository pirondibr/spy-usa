# -*- coding: utf-8 -*-
"""TikTok influencers via Apify (apidojo/tiktok-scraper) + brand filter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

import requests

from tiktok_brand_filter import classify_all, resolve_brand, search_query

ACTOR_ID = "5K30i8aFccKNF5ICs"
APIFY_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
_COST_PER_POST = 0.30 / 1000
_HANDLE_RE = re.compile(r"tiktok\.com/@([^/?#]+)", flags=re.I)
_MAX_DEFAULT = 25


def _api_token() -> str:
    return (
        os.environ.get("APIFY_TOKEN")
        or os.environ.get("APIFY_API_TOKEN")
        or os.environ.get("APIFY_API_KEY")
        or ""
    ).strip()


def has_tiktok_apify() -> bool:
    return bool(_api_token())


def handle_from_url(url: str) -> str:
    m = _HANDLE_RE.search(url or "")
    return (m.group(1) if m else "").strip().lower()


def official_hint_from_url(url: str) -> Optional[dict]:
    handle = handle_from_url(url)
    if not handle:
        return None
    return {"name": f"@{handle}", "url": f"https://www.tiktok.com/@{handle}"}


def _max_items() -> int:
    raw = (os.environ.get("SPY_TIKTOK_MAX_ITEMS") or str(_MAX_DEFAULT)).strip()
    try:
        n = int(raw)
    except ValueError:
        n = _MAX_DEFAULT
    return max(10, min(100, n))


def _cache_dir() -> Path:
    root = (
        os.environ.get("RADAR_DATA_DIR")
        or os.environ.get("SPY_DATA_DIR")
        or ""
    ).strip()
    base = Path(root) if root else Path(__file__).resolve().parents[2] / "data"
    return base / "cache" / "tiktok-apify"


def _cache_key(query: str, sort_type: str, max_items: int, location: str) -> str:
    raw = "|".join([query.lower(), sort_type, str(max_items), location, date.today().isoformat()])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _cache_get(key: str) -> Optional[list[dict[str, Any]]]:
    path = _cache_dir() / date.today().isoformat() / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    posts = data.get("posts") if isinstance(data, dict) else data
    return posts if isinstance(posts, list) else None


def _cache_put(key: str, posts: list[dict[str, Any]]) -> None:
    folder = _cache_dir() / date.today().isoformat()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{key}.json").write_text(
            json.dumps({"posts": posts}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        return


def _run_apify(
    query: str,
    *,
    max_items: int,
    sort_type: str,
    location: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    token = _api_token()
    if not token:
        raise RuntimeError("Missing APIFY_TOKEN for TikTok Apify")
    body = {
        "keywords": [query],
        "maxItems": max_items,
        "sortType": sort_type,
        "includeSearchKeywords": False,
    }
    if location:
        body["location"] = location
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    last_err = ""
    for attempt in range(2):
        t0 = time.time()
        try:
            r = requests.post(
                APIFY_SYNC_URL,
                params={"timeout": 150},
                headers=headers,
                json=body,
                timeout=160,
            )
            elapsed = round(time.time() - t0, 2)
            if r.status_code >= 500 and attempt == 0:
                last_err = f"HTTP {r.status_code}"
                time.sleep(1.5)
                continue
            r.raise_for_status()
            payload = r.json() if r.content else []
            posts = payload if isinstance(payload, list) else []
            posts = [p for p in posts if isinstance(p, dict)]
            return posts, {
                "ok": True,
                "http_status": r.status_code,
                "elapsed_sec": elapsed,
                "attempt": attempt + 1,
                "error": None,
            }
        except Exception as e:
            last_err = str(e)
            if attempt == 0:
                time.sleep(1.5)
                continue
            return [], {
                "ok": False,
                "http_status": None,
                "elapsed_sec": round(time.time() - t0, 2),
                "attempt": attempt + 1,
                "error": last_err,
            }
    return [], {"ok": False, "error": last_err}


def _row_to_video(row: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    ch = post.get("channel") if isinstance(post.get("channel"), dict) else {}
    handle = str(row.get("user") or ch.get("username") or "").lstrip("@")
    return {
        "id": row.get("id") or post.get("id") or "",
        "title": row.get("title") or post.get("title") or (f"@{handle}" if handle else "TikTok"),
        "url": row.get("link") or post.get("postPage") or "",
        "handle": handle,
        "channel_name": f"@{handle}" if handle else "",
        "verified": bool(row.get("verified") or ch.get("verified")),
        "followers": row.get("followers") if row.get("followers") is not None else ch.get("followers"),
        "views": row.get("views") if row.get("views") is not None else post.get("views"),
        "likes": row.get("likes") if row.get("likes") is not None else post.get("likes"),
        "comments": row.get("comments") if row.get("comments") is not None else post.get("comments"),
        "shares": row.get("shares") if row.get("shares") is not None else post.get("shares"),
        "upload_age": row.get("uploaded") or post.get("uploadedAtFormatted") or "",
        "is_official": bool(row.get("official")),
        "label": row.get("label"),
        "score": row.get("score"),
        "reasons": row.get("reasons") or [],
        "flags": row.get("flags") or [],
        "about_reason": ",".join(row.get("reasons") or []) or row.get("label"),
        "description": str(
            post.get("text")
            or post.get("subtitle_text")
            or post.get("description")
            or ""
        )[:400],
    }


def analyze_company(
    company: str,
    *,
    domain: str = "",
    market: str = "us",
    query: str | None = None,
    official_hint: Optional[dict] = None,
) -> dict[str, Any]:
    t0 = time.time()
    name = (company or (domain.split(".")[0] if domain else "")).strip()
    hint_handle = handle_from_url(str((official_hint or {}).get("url") or ""))
    if not hint_handle:
        hint_handle = str((official_hint or {}).get("name") or "").lstrip("@").lower()
    cfg = resolve_brand(name, domain=domain, official_handle=hint_handle)
    q = (query or search_query(name, domain=domain)).strip()
    loc = "US" if not (market or "us").lower().startswith("br") else "BR"
    max_items = _max_items()
    sort_type = (os.environ.get("SPY_TIKTOK_SORT") or "RELEVANCE").strip().upper() or "RELEVANCE"
    if sort_type not in {"RELEVANCE", "MOST_LIKED", "DATE_POSTED"}:
        sort_type = "RELEVANCE"

    cached = False
    cache_key = _cache_key(q, sort_type, max_items, loc)
    posts = _cache_get(cache_key)
    fetch_meta: dict[str, Any] = {"ok": True, "error": None, "elapsed_sec": 0}
    if posts is None:
        if not has_tiktok_apify():
            posts = []
            fetch_meta = {"ok": False, "error": "APIFY_TOKEN missing"}
        else:
            posts, fetch_meta = _run_apify(
                q, max_items=max_items, sort_type=sort_type, location=loc
            )
            if fetch_meta.get("ok") and posts:
                _cache_put(cache_key, posts)
    else:
        cached = True

    classified = classify_all(
        posts,
        name,
        with_subtitles=True,
        domain=domain,
        official_handle=hint_handle,
    )
    by_id = {str(p.get("id") or ""): p for p in posts if p.get("id")}
    videos = [_row_to_video(row, by_id.get(str(row.get("id") or ""), {})) for row in classified]

    confirmed = [v for v in videos if v.get("label") == "confirmed"]
    probable = [v for v in videos if v.get("label") == "probable"]
    unrelated = [v for v in videos if v.get("label") == "unrelated"]
    official_pool = [v for v in confirmed if v.get("is_official")]
    other_pool = [v for v in confirmed if not v.get("is_official")]

    def _top(items: list[dict], limit: int = 5) -> list[dict]:
        return sorted(items, key=lambda x: int(x.get("views") or 0), reverse=True)[:limit]

    official_views = sum(int(v.get("views") or 0) for v in official_pool)
    other_views = sum(int(v.get("views") or 0) for v in other_pool)
    confirmed_views = official_views + other_views
    probable_views = sum(int(v.get("views") or 0) for v in probable)
    billed = max(len(posts), 10) if posts and not cached else 0
    cost = round(billed * _COST_PER_POST, 6) if not cached else 0.0
    search_url = f"https://www.tiktok.com/search?q={quote_plus(q)}"

    return {
        "ok": bool(confirmed or probable or (fetch_meta.get("ok") and posts)),
        "company": name,
        "domain": domain,
        "query": q,
        "search_url": search_url,
        "official_channel": official_hint or (
            official_hint_from_url(f"https://www.tiktok.com/@{hint_handle}") if hint_handle else None
        ),
        "brand": {
            "name": cfg.get("name"),
            "ambiguous": bool(cfg.get("ambiguous")),
            "query": q,
        },
        "views_official": official_views,
        "views_unofficial": other_views,
        "views_confirmed": confirmed_views,
        "views_probable": probable_views,
        "about_count": len(confirmed),
        "page_count": len(posts),
        "top5": _top(confirmed or probable),
        "top5_official": _top(official_pool),
        "top5_unofficial": _top(other_pool),
        "top5_probable": _top(probable),
        "videos_about_product": confirmed,
        "videos_confirmed": confirmed,
        "videos_probable": probable,
        "videos_unrelated": unrelated,
        "videos_fetched": videos,
        "counts": {
            "search_page": len(posts),
            "about_product": len(confirmed),
            "confirmed": len(confirmed),
            "probable": len(probable),
            "unrelated": len(unrelated),
            "official": len(official_pool),
            "unofficial": len(other_pool),
        },
        "usage": {
            "source": "apify_tiktok" if (posts or fetch_meta.get("ok")) else "",
            "actor": ACTOR_ID,
            "cached": cached,
            "estimated_usd": cost,
            "search_cost_usd": cost,
            "posts": len(posts),
            "sort_type": sort_type,
            "max_items": max_items,
            "location": loc,
            "elapsed_fetch_sec": fetch_meta.get("elapsed_sec"),
            "note": (
                "Apify apidojo/tiktok-scraper keyword search. "
                "Brand filter confirmed/probable/unrelated. Subtitles from CDN, no video open."
            ),
        },
        "elapsed_sec": round(time.time() - t0, 2),
        "error": None if (posts or cached) else (fetch_meta.get("error") or "TikTok Apify returned no posts"),
    }
