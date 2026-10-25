# -*- coding: utf-8 -*-
"""Instagram Influencers spy — TinyFish Search + Fetch (page download).

1) Search: "{company} instagram" → official profile URL
2) Fetch profile (links=true) → first-page post URLs
3) Own posts: instagram.com/{company_handle}/...
   Influencer posts on the grid: instagram.com/{other_handle}/...
4) Fetch each first-page post → likes from og:description
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse, unquote

import requests

TINYFISH_SEARCH = "https://api.search.tinyfish.ai"
TINYFISH_FETCH = "https://api.fetch.tinyfish.ai"

POST_PATH_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/([^/?#]+)/(p|reel|tv)/([^/?#]+)/?",
    flags=re.I,
)
PROFILE_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?(?:\?|$|#)",
    flags=re.I,
)
LIKES_RE = re.compile(r"([\d][\d,]*)\s+likes?", flags=re.I)


def _api_key() -> str:
    key = (os.environ.get("TINYFISH_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("TINYFISH_API_KEY ausente")
    return key


def normalize_profile_url(url: str) -> str:
    if not url:
        return ""
    m = PROFILE_RE.match(url.strip())
    if not m:
        # strip /p/ /reel/ down to profile if present
        m2 = POST_PATH_RE.match(url.strip())
        if m2:
            return f"https://www.instagram.com/{m2.group(1)}/"
        return ""
    user = m.group(1)
    skip = {
        "p", "reel", "tv", "stories", "explore", "accounts", "about",
        "legal", "directory", "popular", "web", "developer", "developers",
    }
    if user.lower() in skip:
        return ""
    return f"https://www.instagram.com/{user}/"


def handle_from_profile_url(url: str) -> str:
    m = PROFILE_RE.match((url or "").strip())
    return (m.group(1) if m else "").lower()


def parse_post_link(url: str) -> Optional[dict[str, str]]:
    m = POST_PATH_RE.search(url or "")
    if not m:
        return None
    user, kind, code = m.group(1), m.group(2).lower(), m.group(3)
    skip = {"p", "reel", "tv", "stories", "explore", "accounts"}
    if user.lower() in skip:
        return None
    clean = f"https://www.instagram.com/{user}/{kind}/{code}/"
    return {
        "username": user.lower(),
        "kind": kind,
        "code": code,
        "url": clean,
    }


def parse_likes(text: str) -> Optional[int]:
    if not text:
        return None
    m = LIKES_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def tinyfish_search_instagram(company: str, *, location: str = "US") -> dict[str, Any]:
    """Find Instagram profile via web search: '{company} instagram'."""
    t0 = time.time()
    q = f"{company} instagram"
    r = requests.get(
        TINYFISH_SEARCH,
        params={
            "query": q,
            "location": location,
            "language": "en" if location.upper() == "US" else "pt",
            "page": 0,
        },
        headers={"X-API-Key": _api_key()},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json() if r.content else {}
    results = data.get("results") or data.get("organic") or []

    company_l = re.sub(r"[^a-z0-9]+", "", (company or "").lower())
    best = None
    best_score = -1
    candidates = []
    for item in results:
        url = str(item.get("url") or "")
        if "instagram.com" not in url.lower():
            continue
        # Prefer profile pages over /reel/ or /p/
        if POST_PATH_RE.search(url):
            continue
        prof = normalize_profile_url(url)
        if not prof:
            continue
        handle = handle_from_profile_url(prof)
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or item.get("description") or "")
        score = 0
        handle_c = re.sub(r"[^a-z0-9]+", "", handle)
        if company_l and handle_c == company_l:
            score += 80
        if company_l and company_l in handle_c:
            score += 50
        if company_l and company_l in re.sub(r"[^a-z0-9]+", "", title.lower()):
            score += 20
        if "followers" in snippet.lower() or "posts" in snippet.lower():
            score += 10
        if handle.startswith("_") and company_l and company_l in handle_c:
            score += 5
        candidates.append({"url": prof, "handle": handle, "title": title, "score": score})
        if score > best_score:
            best_score = score
            best = candidates[-1]

    return {
        "ok": bool(best),
        "query": q,
        "profile_url": (best or {}).get("url") or "",
        "handle": (best or {}).get("handle") or "",
        "title": (best or {}).get("title") or "",
        "candidates": candidates[:8],
        "elapsed_sec": round(time.time() - t0, 2),
        "cost_usd": 0.0,
    }


def tinyfish_fetch(
    urls: list[str],
    *,
    links: bool = False,
    format: str = "markdown",
    ttl: int = 0,
    purpose: str = "",
) -> dict[str, Any]:
    if not urls:
        return {"results": [], "errors": []}
    payload: dict[str, Any] = {
        "urls": urls[:10],
        "format": format,
        "links": bool(links),
        "image_links": False,
        "iframe_links": False,
        "page_metadata": True,
        "ttl": ttl,
        "per_url_timeout_ms": 60000,
    }
    if purpose:
        payload["purpose"] = purpose[:2000]
    r = requests.post(
        TINYFISH_FETCH,
        headers={
            "X-API-Key": _api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=150,
    )
    r.raise_for_status()
    return r.json() if r.content else {"results": [], "errors": []}


def extract_posts_from_profile(profile_url: str, handle: str) -> dict[str, Any]:
    """Download profile first page and list post links (own vs influencer)."""
    t0 = time.time()
    data = tinyfish_fetch(
        [profile_url],
        links=True,
        format="html",
        purpose="List first-page Instagram post and reel URLs from the profile grid",
    )
    results = data.get("results") or []
    page = results[0] if results else {}
    link_list = page.get("links") or []
    desc = page.get("description") or ""
    title = page.get("title") or ""

    followers = None
    m = re.search(r"([\d][\d.,]*[KkMm]?)\s+[Ff]ollowers", desc) or re.search(
        r"([\d][\d.,]*[KkMm]?)\s+followers", page.get("text") or ""
    )
    if m:
        followers = m.group(1)

    seen = set()
    posts: list[dict] = []
    for href in link_list:
        parsed = parse_post_link(str(href))
        if not parsed:
            continue
        key = parsed["code"]
        if key in seen:
            continue
        seen.add(key)
        is_own = parsed["username"] == (handle or "").lower()
        posts.append({
            **parsed,
            "is_own": is_own,
            "is_influencer": not is_own,
        })

    return {
        "ok": bool(posts) or bool(page),
        "profile_url": profile_url,
        "handle": handle,
        "title": title,
        "followers_label": followers,
        "posts": posts,
        "elapsed_sec": round(time.time() - t0, 2),
        "fetch_errors": data.get("errors") or [],
        "cost_usd": 0.0,
    }


def enrich_posts_with_likes(posts: list[dict]) -> list[dict]:
    """Fetch each post page (batches of 10) and read likes from og:description."""
    if not posts:
        return posts
    out = [dict(p) for p in posts]
    by_url = {p["url"]: i for i, p in enumerate(out)}
    urls = [p["url"] for p in out]
    t0 = time.time()
    for i in range(0, len(urls), 10):
        chunk = urls[i : i + 10]
        data = tinyfish_fetch(
            chunk,
            links=False,
            format="markdown",
            purpose="Extract Instagram like count from post og:description",
        )
        for page in data.get("results") or []:
            url = normalize_post_url(str(page.get("url") or page.get("final_url") or ""))
            # map back loosely
            idx = None
            for u, j in by_url.items():
                if u.rstrip("/") == url.rstrip("/") or url in u or u in url:
                    idx = j
                    break
            if idx is None:
                # try by code
                parsed = parse_post_link(str(page.get("url") or ""))
                if parsed:
                    for u, j in by_url.items():
                        if parsed["code"] in u:
                            idx = j
                            break
            if idx is None:
                continue
            desc = page.get("description") or ""
            title = page.get("title") or ""
            likes = parse_likes(desc) or parse_likes(title) or parse_likes(page.get("text") or "")
            out[idx]["likes"] = likes
            out[idx]["caption_hint"] = (desc or "")[:180]
        for err in data.get("errors") or []:
            u = str(err.get("url") or "")
            parsed = parse_post_link(u)
            if not parsed:
                continue
            for j, p in enumerate(out):
                if p.get("code") == parsed["code"]:
                    out[j]["likes_error"] = err.get("error") or "fetch_failed"
                    break
    elapsed = round(time.time() - t0, 2)
    for p in out:
        p.setdefault("likes", None)
        p["likes_fetch_elapsed_sec"] = elapsed
    return out


def normalize_post_url(url: str) -> str:
    parsed = parse_post_link(url)
    return parsed["url"] if parsed else (url or "").strip()


def summarize(posts: list[dict], *, handle: str, profile_url: str) -> dict[str, Any]:
    influencer_posts = [p for p in posts if p.get("is_influencer")]
    own_posts = [p for p in posts if p.get("is_own")]
    influencer_handles = sorted({
        p.get("username") for p in influencer_posts if p.get("username")
    })

    def _likes(p: dict) -> int:
        return int(p.get("likes") or 0)

    def _top_likes(items: list[dict], limit: int = 5) -> list[dict]:
        ranked = sorted(items, key=_likes, reverse=True)
        out = []
        for p in ranked:
            if p.get("likes") is None and not p.get("url"):
                continue
            out.append({
                "url": p.get("url"),
                "likes": p.get("likes"),
                "username": p.get("username"),
                "is_influencer": bool(p.get("is_influencer")),
                "is_own": bool(p.get("is_own")),
                "kind": p.get("kind"),
            })
            if len(out) >= limit:
                break
        return out

    top5_page = _top_likes(own_posts)
    top5_influencers = _top_likes(influencer_posts)
    # legacy combined top5 (page first, then influencers) for older consumers
    if top5_page or top5_influencers:
        top5 = (top5_page + top5_influencers)[:5]
    else:
        top5 = _top_likes(posts)

    total_likes = sum(_likes(p) for p in posts if p.get("likes") is not None)
    influencer_likes = sum(_likes(p) for p in influencer_posts if p.get("likes") is not None)
    own_likes = sum(_likes(p) for p in own_posts if p.get("likes") is not None)

    return {
        "handle": handle,
        "profile_url": profile_url,
        "posts_first_page": len(posts),
        "own_posts": len(own_posts),
        "influencer_posts": len(influencer_posts),
        "total_influencers": len(influencer_handles),
        "influencer_handles": influencer_handles,
        "total_likes": total_likes,
        "own_likes": own_likes,
        "influencer_likes": influencer_likes,
        "top5": top5,
        "top5_page": top5_page,
        "top5_influencers": top5_influencers,
        "posts": posts,
    }


def analyze_company(
    company: str,
    *,
    domain: str = "",
    market: str = "us",
    profile_url: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    t_all = time.time()
    q = (query or company or domain or "").strip()
    if not q:
        raise ValueError("company/query required")
    loc = "US" if (market or "us").lower().startswith("us") else "BR"

    usage = {
        "search_cost_usd": 0.0,
        "fetch_cost_usd": 0.0,
        "fetch_urls": 0,
        "estimated_total_usd": 0.0,
        "source": "tinyfish_search+fetch",
        "note": "Search + Fetch free (daily Fetch allowance); likes from downloaded post pages",
    }

    if profile_url:
        search = {
            "ok": True,
            "profile_url": normalize_profile_url(profile_url),
            "handle": handle_from_profile_url(profile_url),
            "query": q,
            "elapsed_sec": 0,
            "cost_usd": 0.0,
        }
    else:
        search = tinyfish_search_instagram(q, location=loc)
    usage["search_cost_usd"] = 0.0
    usage["search_elapsed_sec"] = search.get("elapsed_sec")

    prof = search.get("profile_url") or ""
    handle = search.get("handle") or handle_from_profile_url(prof)
    if not prof or not handle:
        return {
            "ok": False,
            "company": company,
            "domain": domain,
            "query": q,
            "error": "Instagram profile not found via search",
            "usage": usage,
            "elapsed_sec": round(time.time() - t_all, 2),
            "total_influencers": 0,
            "total_likes": 0,
            "top5": [],
            "posts": [],
        }

    grid = extract_posts_from_profile(prof, handle)
    usage["fetch_urls"] += 1
    usage["profile_fetch_elapsed_sec"] = grid.get("elapsed_sec")

    posts = enrich_posts_with_likes(grid.get("posts") or [])
    usage["fetch_urls"] += len(grid.get("posts") or [])
    usage["estimated_total_usd"] = 0.0

    summary = summarize(posts, handle=handle, profile_url=prof)
    return {
        "ok": True,
        "company": company,
        "domain": domain,
        "query": search.get("query") or q,
        "search": {
            "profile_url": prof,
            "handle": handle,
            "title": search.get("title"),
            "candidates": search.get("candidates") or [],
        },
        "followers_label": grid.get("followers_label"),
        "elapsed_sec": round(time.time() - t_all, 2),
        "usage": usage,
        **summary,
    }
