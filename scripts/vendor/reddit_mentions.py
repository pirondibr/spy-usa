# -*- coding: utf-8 -*-
"""Reddit mentions — Google site:reddit.com + comment counts.

1) TinyFish Search: site:reddit.com "company"
2) ScrapingBee Google (try) for total result count (often null lately)
3) TinyFish Fetch first-page post .json → num_comments
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus, urlparse

import requests

TINYFISH_SEARCH = "https://api.search.tinyfish.ai"
TINYFISH_FETCH = "https://api.fetch.tinyfish.ai"
SCRAPINGBEE_GOOGLE = "https://app.scrapingbee.com/api/v1/google"

POST_RE = re.compile(
    r"https?://(?:www\.)?reddit\.com/r/([^/]+)/comments/([a-z0-9]+)/",
    flags=re.I,
)
COMMENTS_SNIPPET_RE = re.compile(r"([\d][\d,]*)\s+comments?", flags=re.I)


def _tf_key() -> str:
    key = (os.environ.get("TINYFISH_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("TINYFISH_API_KEY ausente")
    return key


def _sb_key() -> str:
    return (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip()


def normalize_post_url(url: str) -> str:
    m = POST_RE.search(url or "")
    if not m:
        return ""
    return f"https://www.reddit.com/r/{m.group(1)}/comments/{m.group(2)}/"


def post_json_url(url: str) -> str:
    clean = normalize_post_url(url)
    return (clean.rstrip("/") + ".json") if clean else ""


def parse_comment_hint(text: str) -> Optional[int]:
    m = COMMENTS_SNIPPET_RE.search(text or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def tinyfish_search_reddit(company: str, *, location: str = "US") -> dict[str, Any]:
    t0 = time.time()
    q = f'site:reddit.com "{company}"'
    r = requests.get(
        TINYFISH_SEARCH,
        params={
            "query": q,
            "location": location,
            "language": "en" if location.upper() == "US" else "pt",
            "page": 0,
        },
        headers={"X-API-Key": _tf_key()},
        timeout=45,
    )
    r.raise_for_status()
    data = r.json() if r.content else {}
    results = data.get("results") or data.get("organic") or []
    posts: list[dict] = []
    seen: set[str] = set()
    for item in results:
        url = normalize_post_url(str(item.get("url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or item.get("description") or "")
        m = POST_RE.search(url)
        posts.append({
            "url": url,
            "title": title,
            "snippet": snippet,
            "subreddit": m.group(1) if m else "",
            "post_id": m.group(2) if m else "",
            "date": item.get("date") or "",
            "comments_hint": parse_comment_hint(f"{title} {snippet}"),
            "position": item.get("position"),
        })
    total = data.get("total_results")
    if isinstance(total, int) and total <= len(posts):
        total = None  # TinyFish often returns page size, not Google total
    return {
        "ok": bool(posts),
        "query": q,
        "posts": posts,
        "total_results": total if isinstance(total, int) else None,
        "elapsed_sec": round(time.time() - t0, 2),
        "source": "tinyfish_search",
    }


def scrapingbee_google_total(query: str, *, country: str = "us") -> dict[str, Any]:
    """Try ScrapingBee Google for number_of_results (often null)."""
    key = _sb_key()
    if not key:
        return {"ok": False, "total_results": None, "error": "no ScrapingBee key", "credits": 0}
    t0 = time.time()
    try:
        r = requests.get(
            SCRAPINGBEE_GOOGLE,
            params={
                "api_key": key,
                "search": query,
                "country_code": (country or "us").lower()[:2],
                "language": "en",
                "nb_results": 10,
            },
            timeout=90,
        )
    except requests.RequestException as e:
        return {"ok": False, "total_results": None, "error": str(e)[:200], "credits": 0,
                "elapsed_sec": round(time.time() - t0, 2)}
    credits = 0
    for h in ("Spb-cost", "Spb-credits-cost", "spb-cost"):
        if r.headers.get(h):
            try:
                credits = int(float(r.headers[h]))
            except Exception:
                pass
            break
    if not r.ok:
        return {
            "ok": False,
            "total_results": None,
            "error": f"HTTP {r.status_code}",
            "credits": credits,
            "elapsed_sec": round(time.time() - t0, 2),
        }
    data = r.json() if r.content else {}
    meta = data.get("meta_data") or data.get("search_information") or {}
    total = meta.get("number_of_results")
    if isinstance(total, str):
        digits = re.sub(r"[^\d]", "", total)
        total = int(digits) if digits else None
    if not isinstance(total, int):
        total = None
    organic = data.get("organic_results") or []
    return {
        "ok": True,
        "total_results": total,
        "organic_count": len(organic),
        "credits": credits,
        "elapsed_sec": round(time.time() - t0, 2),
        "note": None if total is not None else "Google total results unavailable (null)",
    }


def tinyfish_fetch_reddit_json(urls: list[str]) -> dict[str, Any]:
    json_urls = [post_json_url(u) for u in urls if post_json_url(u)]
    json_urls = json_urls[:10]
    if not json_urls:
        return {"results": {}, "errors": [], "fetch_urls": 0}
    r = requests.post(
        TINYFISH_FETCH,
        headers={
            "X-API-Key": _tf_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "urls": json_urls,
            "format": "markdown",
            "links": False,
            "page_metadata": False,
            "ttl": 0,
            "per_url_timeout_ms": 45000,
            "purpose": "Extract Reddit num_comments and score from post .json",
        },
        timeout=150,
    )
    r.raise_for_status()
    data = r.json() if r.content else {}
    by_id: dict[str, dict] = {}
    for page in data.get("results") or []:
        raw = page.get("text") or ""
        # strip markdown code fences if present
        raw = re.sub(r"^```\w*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
        try:
            parsed = json.loads(raw)
        except Exception:
            # sometimes wrapped
            m = re.search(r"(\[.*\])", raw, flags=re.S)
            if not m:
                continue
            try:
                parsed = json.loads(m.group(1))
            except Exception:
                continue
        if not isinstance(parsed, list) or not parsed:
            continue
        post = ((parsed[0] or {}).get("data") or {}).get("children") or []
        if not post:
            continue
        pdata = (post[0] or {}).get("data") or {}
        pid = str(pdata.get("id") or "")
        permalink = str(pdata.get("permalink") or "")
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        by_id[pid] = {
            "post_id": pid,
            "url": normalize_post_url(url) or url,
            "title": pdata.get("title") or "",
            "subreddit": pdata.get("subreddit") or "",
            "comments": int(pdata.get("num_comments") or 0),
            "score": int(pdata.get("score") or 0),
            "author": pdata.get("author") or "",
        }
    return {
        "results": by_id,
        "errors": data.get("errors") or [],
        "fetch_urls": len(json_urls),
    }


def analyze_company(
    company: str,
    *,
    domain: str = "",
    market: str = "us",
    query: str | None = None,
) -> dict[str, Any]:
    t_all = time.time()
    q = (query or company or domain.split(".")[0] if domain else "").strip()
    if not q:
        raise ValueError("company/query required")
    loc = "US" if (market or "us").lower().startswith("us") else "BR"
    usage = {
        "search_cost_usd": 0.0,
        "fetch_urls": 0,
        "scrapingbee_credits": 0,
        "source": "tinyfish_search+fetch + scrapingbee_google_try",
    }

    search = tinyfish_search_reddit(q, location=loc)
    posts = list(search.get("posts") or [])

    google_q = search.get("query") or f'site:reddit.com "{q}"'
    sb = scrapingbee_google_total(google_q, country=loc.lower()[:2])
    usage["scrapingbee_credits"] = int(sb.get("credits") or 0)
    total_results = sb.get("total_results")
    if total_results is None:
        total_results = search.get("total_results")

    enriched = []
    if posts:
        fetched = tinyfish_fetch_reddit_json([p["url"] for p in posts])
        usage["fetch_urls"] = int(fetched.get("fetch_urls") or 0)
        by_id = fetched.get("results") or {}
        for p in posts:
            pid = p.get("post_id") or ""
            detail = by_id.get(pid) or {}
            comments = detail.get("comments")
            if comments is None:
                comments = p.get("comments_hint")
            item = {
                **p,
                "title": detail.get("title") or p.get("title"),
                "comments": comments,
                "score": detail.get("score"),
                "author": detail.get("author") or "",
                "subreddit": detail.get("subreddit") or p.get("subreddit"),
            }
            enriched.append(item)
    else:
        enriched = posts

    with_comments = [p for p in enriched if isinstance(p.get("comments"), int)]
    total_comments = sum(int(p["comments"]) for p in with_comments)
    top = sorted(
        enriched,
        key=lambda x: (x.get("comments") is not None, x.get("comments") or 0, x.get("score") or 0),
        reverse=True,
    )

    return {
        "ok": bool(enriched) or search.get("ok"),
        "company": company,
        "domain": domain,
        "query": google_q,
        "search_url": f"https://www.google.com/search?q={quote_plus(google_q)}",
        "total_results": total_results,
        "total_results_note": sb.get("note") if total_results is None else None,
        "posts_first_page": len(enriched),
        "total_comments": total_comments,
        "comments_known": len(with_comments),
        "top_posts": [
            {
                "title": p.get("title"),
                "url": p.get("url"),
                "subreddit": p.get("subreddit"),
                "comments": p.get("comments"),
                "score": p.get("score"),
                "date": p.get("date"),
            }
            for p in top[:8]
        ],
        "posts": enriched,
        "usage": usage,
        "elapsed_sec": round(time.time() - t_all, 2),
        "error": None if enriched else "No Reddit posts found",
    }
