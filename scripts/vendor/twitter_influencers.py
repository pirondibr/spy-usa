# -*- coding: utf-8 -*-
"""X / Twitter influencers via Apify tweet-scraper + brand filter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

from tiktok_brand_filter import classify_all, resolve_brand

ACTOR_ID = "61RPP7dywgiy0JPD0"
APIFY_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
_COST_PER_TWEET = 0.40 / 1000
_HANDLE_RE = re.compile(r"(?:x|twitter)\.com/([^/?#]+)", flags=re.I)
_MIN_LIKES = 50
_MAX_DEFAULT = 50  # actor minimum per query
_PAGE_SHOW = 20


def _api_token() -> str:
    return (
        os.environ.get("APIFY_TOKEN")
        or os.environ.get("APIFY_API_TOKEN")
        or os.environ.get("APIFY_API_KEY")
        or ""
    ).strip()


def has_twitter_apify() -> bool:
    return bool(_api_token())


def handle_from_url(url: str) -> str:
    m = _HANDLE_RE.search(url or "")
    if not m:
        return ""
    slug = (m.group(1) or "").strip().lstrip("@").lower()
    if slug in {"search", "i", "home", "explore", "intent", "share", "hashtag"}:
        return ""
    return slug


def official_hint_from_url(url: str) -> Optional[dict]:
    handle = handle_from_url(url)
    if not handle:
        return None
    return {"name": f"@{handle}", "url": f"https://x.com/{handle}"}


def _max_items() -> int:
    raw = (os.environ.get("SPY_X_MAX_ITEMS") or str(_MAX_DEFAULT)).strip()
    try:
        n = int(raw)
    except ValueError:
        n = _MAX_DEFAULT
    return max(50, min(200, n))


def _min_likes() -> int:
    raw = (os.environ.get("SPY_X_MIN_LIKES") or str(_MIN_LIKES)).strip()
    try:
        n = int(raw)
    except ValueError:
        n = _MIN_LIKES
    return max(0, min(10_000, n))


def search_term(brand: str, *, domain: str = "", min_likes: int = _MIN_LIKES) -> str:
    cfg = resolve_brand(brand, domain=domain)
    name = re.sub(r"\s+ai$", "", str(cfg.get("name") or brand).strip(), flags=re.I)
    if not name:
        name = (domain.split(".")[0] if domain else brand).strip()
    if " " in name:
        q = f'"{name}" min_faves:{min_likes}'
    else:
        q = f"{name} min_faves:{min_likes}"
    return q


def search_url(term: str) -> str:
    return f"https://x.com/search?q={quote(term)}&src=typed_query"


def _cache_dir() -> Path:
    root = (os.environ.get("RADAR_DATA_DIR") or os.environ.get("SPY_DATA_DIR") or "").strip()
    base = Path(root) if root else Path(__file__).resolve().parents[2] / "data"
    return base / "cache" / "twitter-apify"


def _cache_key(query: str, sort_type: str, max_items: int, lang: str) -> str:
    raw = "|".join([query.lower(), sort_type, str(max_items), lang, date.today().isoformat()])
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
    term: str,
    *,
    max_items: int,
    sort_type: str,
    lang: str,
    min_likes: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    token = _api_token()
    if not token:
        raise RuntimeError("Missing APIFY_TOKEN for X Apify")
    body: dict[str, Any] = {
        "searchTerms": [term],
        "maxItems": max_items,
        "sort": sort_type,
        "minimumFavorites": min_likes,
    }
    if lang:
        body["tweetLanguage"] = lang
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
                "elapsed_sec": round(time.time() - t0, 2),
                "attempt": attempt + 1,
                "error": last_err,
            }
    return [], {"ok": False, "error": last_err}


def _tweet_to_post(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    text = str(item.get("text") or item.get("full_text") or "")
    tags = [t.lstrip("#") for t in re.findall(r"#([A-Za-z0-9_]+)", text)]
    handle = str(author.get("userName") or author.get("username") or "").lstrip("@")
    likes = item.get("likeCount")
    if likes is None:
        likes = item.get("likes")
    return {
        "id": str(item.get("id") or ""),
        "title": text,
        "hashtags": tags,
        "views": likes,
        "likes": likes,
        "comments": item.get("replyCount"),
        "shares": item.get("retweetCount"),
        "postPage": str(item.get("url") or item.get("twitterUrl") or ""),
        "uploadedAtFormatted": str(item.get("createdAt") or ""),
        "isRetweet": bool(item.get("isRetweet")),
        "channel": {
            "username": handle,
            "verified": bool(author.get("isVerified") or author.get("isBlueVerified")),
            "followers": author.get("followers"),
            "name": author.get("name") or "",
            "url": author.get("url") or (f"https://x.com/{handle}" if handle else ""),
        },
    }


def _row_to_video(row: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    ch = post.get("channel") if isinstance(post.get("channel"), dict) else {}
    handle = str(row.get("user") or ch.get("username") or "").lstrip("@")
    likes = row.get("likes") if row.get("likes") is not None else post.get("likes")
    return {
        "id": row.get("id") or post.get("id") or "",
        "title": row.get("title") or post.get("title") or (f"@{handle}" if handle else "X"),
        "url": row.get("link") or post.get("postPage") or "",
        "handle": handle,
        "channel_name": f"@{handle}" if handle else "",
        "verified": bool(row.get("verified") or ch.get("verified")),
        "followers": row.get("followers") if row.get("followers") is not None else ch.get("followers"),
        "views": likes,
        "likes": likes,
        "comments": row.get("comments") if row.get("comments") is not None else post.get("comments"),
        "shares": row.get("shares") if row.get("shares") is not None else post.get("shares"),
        "upload_age": row.get("uploaded") or post.get("uploadedAtFormatted") or "",
        "is_official": bool(row.get("official")),
        "is_retweet": bool(post.get("isRetweet")),
        "label": row.get("label"),
        "score": row.get("score"),
        "reasons": row.get("reasons") or [],
        "flags": row.get("flags") or [],
        "about_reason": ",".join(row.get("reasons") or []) or row.get("label"),
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
    min_likes = _min_likes()
    term = (query or search_term(name, domain=domain, min_likes=min_likes)).strip()
    if "min_faves" not in term.lower():
        term = f"{term} min_faves:{min_likes}"
    lang = "en" if not (market or "us").lower().startswith("br") else ""
    max_items = _max_items()
    sort_type = (os.environ.get("SPY_X_SORT") or "Latest").strip() or "Latest"
    if sort_type not in {"Latest", "Top", "Latest + Top"}:
        sort_type = "Latest"

    cached = False
    cache_key = _cache_key(term, sort_type, max_items, lang)
    raw = _cache_get(cache_key)
    fetch_meta: dict[str, Any] = {"ok": True, "error": None, "elapsed_sec": 0}
    if raw is None:
        if not has_twitter_apify():
            raw = []
            fetch_meta = {"ok": False, "error": "APIFY_TOKEN missing"}
        else:
            raw, fetch_meta = _run_apify(
                term, max_items=max_items, sort_type=sort_type, lang=lang, min_likes=min_likes
            )
            if fetch_meta.get("ok") and raw:
                _cache_put(cache_key, raw)
    else:
        cached = True

    posts = [_tweet_to_post(it) for it in raw]
    posts = [p for p in posts if int(p.get("likes") or 0) >= min_likes]
    classified = classify_all(
        posts,
        name,
        with_subtitles=False,
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
        return sorted(items, key=lambda x: int(x.get("likes") or 0), reverse=True)[:limit]

    official_likes = sum(int(v.get("likes") or 0) for v in official_pool)
    other_likes = sum(int(v.get("likes") or 0) for v in other_pool)
    billed = max(len(raw), 50) if raw and not cached else 0
    cost = round(billed * _COST_PER_TWEET, 6) if not cached else 0.0

    return {
        "ok": bool(confirmed or probable or (fetch_meta.get("ok") and raw)),
        "company": name,
        "domain": domain,
        "query": term,
        "search_url": search_url(term),
        "official_channel": official_hint or (
            official_hint_from_url(f"https://x.com/{hint_handle}") if hint_handle else None
        ),
        "brand": {
            "name": cfg.get("name"),
            "ambiguous": bool(cfg.get("ambiguous")),
            "query": term,
        },
        "views_official": official_likes,
        "views_unofficial": other_likes,
        "views_confirmed": official_likes + other_likes,
        "views_probable": sum(int(v.get("likes") or 0) for v in probable),
        "about_count": len(confirmed),
        "page_count": len(raw),
        "top5": _top(confirmed or probable),
        "top5_official": _top(official_pool),
        "top5_unofficial": _top(other_pool),
        "top5_probable": _top(probable),
        "videos_confirmed": sorted(confirmed, key=lambda x: int(x.get("likes") or 0), reverse=True)[:_PAGE_SHOW],
        "videos_probable": sorted(probable, key=lambda x: int(x.get("likes") or 0), reverse=True)[:_PAGE_SHOW],
        "videos_unrelated": unrelated,
        "counts": {
            "search_page": len(raw),
            "about_product": len(confirmed),
            "confirmed": len(confirmed),
            "probable": len(probable),
            "unrelated": len(unrelated),
            "official": len(official_pool),
            "unofficial": len(other_pool),
        },
        "usage": {
            "source": "apify_tweet" if (raw or fetch_meta.get("ok")) else "",
            "actor": ACTOR_ID,
            "cached": cached,
            "estimated_usd": cost,
            "search_cost_usd": cost,
            "posts": len(raw),
            "sort_type": sort_type,
            "max_items": max_items,
            "min_likes": min_likes,
            "elapsed_fetch_sec": fetch_meta.get("elapsed_sec"),
            "note": (
                "Apify apidojo/tweet-scraper. Query “{brand} min_faves:50”. "
                "Actor minimum is 50 tweets (~$0.02). Brand filter hides unrelated."
            ),
        },
        "elapsed_sec": round(time.time() - t0, 2),
        "error": None if (raw or cached) else (fetch_meta.get("error") or "X Apify returned no tweets"),
    }
