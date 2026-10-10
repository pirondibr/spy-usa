# -*- coding: utf-8 -*-
"""YouTube Influencers spy — TinyFish Search (free) + Agent (metered) + OpenRouter.

First page of YouTube search only:
- official vs unofficial view totals
- age buckets: 30d / 6m / 1y+
- top 5 links
- product relevance from title+description (doubt = no)
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus, urlparse, parse_qs

import requests

TINYFISH_SEARCH = "https://api.search.tinyfish.ai"
TINYFISH_AGENT_RUN = "https://agent.tinyfish.ai/v1/automation/run"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL") or "google/gemini-2.5-flash"
AGENT_STEP_USD = 0.016
BROWSER_MIN_USD = 0.002


def _api_key() -> str:
    key = (os.environ.get("TINYFISH_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("TINYFISH_API_KEY ausente")
    return key


def video_id_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        if "youtu.be" in (p.netloc or ""):
            return (p.path or "").strip("/").split("/")[0]
        if "/shorts/" in (p.path or ""):
            return (p.path or "").split("/shorts/")[-1].split("/")[0]
        qs = parse_qs(p.query or "")
        if qs.get("v"):
            return qs["v"][0]
        m = re.search(r"[?&]v=([\w-]{6,})", url)
        return m.group(1) if m else ""
    except Exception:
        return ""


def normalize_watch_url(url: str) -> str:
    vid = video_id_from_url(url)
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    return (url or "").strip()


def parse_age_to_days(text: str) -> Optional[int]:
    """Parse '2 months ago', '6d ago', '1 year ago' → approx days."""
    t = (text or "").strip().lower().replace("uploaded", "").strip()
    if not t:
        return None
    if "stream" in t or "live" in t:
        return 0
    m = re.search(
        r"(\d+)\s*(second|minute|hour|day|week|month|year|sec|min|hr|d|w|mo|yr|y)s?\b",
        t,
    )
    if not m:
        if "yesterday" in t:
            return 1
        if "today" in t or "hour" in t or "minute" in t:
            return 0
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit in ("second", "sec", "minute", "min", "hour", "hr"):
        return 0
    if unit in ("day", "d"):
        return n
    if unit in ("week", "w"):
        return n * 7
    if unit in ("month", "mo"):
        return n * 30
    if unit in ("year", "yr", "y"):
        return n * 365
    return None


def age_bucket(days: Optional[int]) -> str:
    if days is None:
        return "unknown"
    if days <= 30:
        return "30d"
    if days <= 183:
        return "6m"
    return "1y_plus"


def _brand_tokens(company: str, domain: str = "") -> list[str]:
    raw = []
    for part in (company, domain.split(".")[0] if domain else ""):
        part = re.sub(r"[^a-z0-9]+", " ", (part or "").lower()).strip()
        if part:
            raw.append(part)
            raw.append(part.replace(" ", ""))
    # common variants
    out: list[str] = []
    seen = set()
    for r in raw:
        if r and r not in seen and len(r) >= 3:
            seen.add(r)
            out.append(r)
        if r and not r.endswith("y"):
            alt = r + "y"
            if alt not in seen:
                seen.add(alt)
                out.append(alt)
    return out


def _handle_from_channel_url(url: str) -> str:
    m = re.search(r"youtube\.com/@([^/?&#]+)", (url or ""), flags=re.I)
    return (m.group(1) if m else "").lower()


def is_official_channel(
    channel_name: str,
    channel_url: str,
    company: str,
    domain: str = "",
    official_hint: Optional[dict] = None,
) -> bool:
    tokens = _brand_tokens(company, domain)
    if official_hint:
        on = str(official_hint.get("name") or "").strip().lower()
        oh = str(official_hint.get("url") or "").strip().lower()
        hint_handle = _handle_from_channel_url(oh)
        if on:
            tokens.append(on)
            tokens.append(re.sub(r"[^a-z0-9]+", "", on))
        if hint_handle:
            tokens.append(hint_handle)
        cn = (channel_name or "").strip().lower()
        ch = (channel_url or "").strip().lower()
        ch_handle = _handle_from_channel_url(ch)
        if on and cn and (cn == on or on in cn or cn in on):
            return True
        if hint_handle and ch_handle and hint_handle == ch_handle:
            return True
        if oh and ch and (ch.rstrip("/") == oh.rstrip("/") or hint_handle and hint_handle in ch):
            return True
    blob = f"{channel_name} {channel_url}".lower()
    compact = re.sub(r"[^a-z0-9]+", "", blob)
    for tok in tokens:
        t = (tok or "").replace(" ", "")
        if t and len(t) >= 4 and t in compact:
            return True
    return False


def tinyfish_search_youtube(query: str, *, location: str = "US") -> dict[str, Any]:
    """Free Search API scoped to youtube.com — first page."""
    t0 = time.time()
    params = {
        "query": query,
        "include_domains": "youtube.com",
        "location": location,
        "language": "en" if location.upper() == "US" else "pt",
        "page": 0,
    }
    r = requests.get(
        TINYFISH_SEARCH,
        params=params,
        headers={"X-API-Key": _api_key()},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json() if r.content else {}
    results = data.get("results") or data.get("organic") or []
    videos: list[dict] = []
    for item in results:
        url = normalize_watch_url(str(item.get("url") or ""))
        if "/watch" not in url and "/shorts/" not in str(item.get("url") or ""):
            # keep channel results separately
            u = str(item.get("url") or "")
            if "/@" in u or "/channel/" in u or "/c/" in u:
                videos.append({
                    "kind": "channel",
                    "title": item.get("title") or "",
                    "url": u,
                    "snippet": item.get("snippet") or item.get("description") or "",
                    "upload_age": item.get("date") or "",
                    "source": "search",
                })
            continue
        if "/shorts/" in str(item.get("url") or ""):
            url = str(item.get("url") or "")
        videos.append({
            "kind": "video",
            "title": item.get("title") or "",
            "url": url,
            "video_id": video_id_from_url(url),
            "snippet": item.get("snippet") or item.get("description") or "",
            "upload_age": item.get("date") or "",
            "views": None,
            "channel_name": "",
            "channel_url": "",
            "source": "search",
            "is_short": "/shorts/" in url,
        })
    return {
        "ok": True,
        "query": query,
        "items": videos,
        "elapsed_sec": round(time.time() - t0, 2),
        "cost_usd": 0.0,
        "meter": "search_free",
    }


def tinyfish_agent_youtube_search(query: str, *, country: str = "US") -> dict[str, Any]:
    """Metered Agent — scrape first page of YouTube search for views/channels."""
    t0 = time.time()
    search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    goal = (
        "You are on the YouTube SEARCH RESULTS first page only. Do NOT open page 2. "
        "Do NOT click into videos. Extract EVERY visible video and short on the first page "
        "(typically 8–20 items). For each return title, url, channel_name, channel_url, "
        "views as a number, views_text, upload_age (e.g. '3 months ago'), is_short. "
        "Also identify the official brand channel if present (name + url). "
        f"Brand/search query: {query!r}."
    )
    payload = {
        "url": search_url,
        "goal": goal,
        "browser_profile": "lite",
        "proxy_config": {"enabled": True, "country_code": (country or "US").upper()[:2]},
        "output_schema": {
            "type": "object",
            "properties": {
                "official_channel": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
                "videos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "channel_name": {"type": "string"},
                            "channel_url": {"type": "string"},
                            "views": {"type": "number"},
                            "views_text": {"type": "string"},
                            "upload_age": {"type": "string"},
                            "is_short": {"type": "boolean"},
                        },
                    },
                },
            },
            "required": ["videos"],
        },
    }
    r = requests.post(
        TINYFISH_AGENT_RUN,
        headers={
            "X-API-Key": _api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=180,
    )
    elapsed = round(time.time() - t0, 2)
    if not r.ok:
        return {
            "ok": False,
            "error": f"TinyFish Agent HTTP {r.status_code}: {r.text[:300]}",
            "elapsed_sec": elapsed,
            "num_of_steps": 0,
            "cost_usd": 0.0,
            "videos": [],
            "official_channel": None,
        }
    data = r.json() if r.content else {}
    steps = int(data.get("num_of_steps") or 0)
    # browser ≈ elapsed minutes
    browser_cost = (elapsed / 60.0) * BROWSER_MIN_USD
    step_cost = steps * AGENT_STEP_USD
    result = data.get("result") or {}
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {"raw": result}
    videos_raw = result.get("videos") if isinstance(result, dict) else []
    videos: list[dict] = []
    for v in videos_raw or []:
        url = normalize_watch_url(str(v.get("url") or ""))
        if not url and not v.get("url"):
            continue
        raw_url = str(v.get("url") or url)
        videos.append({
            "kind": "video",
            "title": v.get("title") or "",
            "url": url or raw_url,
            "video_id": video_id_from_url(url or raw_url),
            "snippet": "",
            "upload_age": v.get("upload_age") or "",
            "views": _as_int(v.get("views")),
            "views_text": v.get("views_text") or "",
            "channel_name": v.get("channel_name") or "",
            "channel_url": v.get("channel_url") or "",
            "source": "agent",
            "is_short": bool(v.get("is_short")) or "/shorts/" in raw_url,
        })
    status = str(data.get("status") or "")
    return {
        "ok": status.upper() == "COMPLETED",
        "status": status,
        "run_id": data.get("run_id"),
        "error": (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else data.get("error"),
        "elapsed_sec": elapsed,
        "num_of_steps": steps,
        "cost_usd": round(step_cost + browser_cost, 4),
        "cost_breakdown": {
            "steps": steps,
            "step_usd": round(step_cost, 4),
            "browser_min_usd": round(browser_cost, 4),
        },
        "videos": videos,
        "official_channel": (result.get("official_channel") if isinstance(result, dict) else None),
        "search_url": search_url,
    }


def _as_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().lower().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([kmb])?$", s)
    if not m:
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else None
    num = float(m.group(1))
    suf = m.group(2)
    if suf == "k":
        num *= 1_000
    elif suf == "m":
        num *= 1_000_000
    elif suf == "b":
        num *= 1_000_000_000
    return int(num)


def merge_search_and_agent(
    search_items: list[dict],
    agent_videos: list[dict],
) -> list[dict]:
    by_id: dict[str, dict] = {}
    for v in agent_videos:
        vid = v.get("video_id") or video_id_from_url(v.get("url") or "")
        if not vid:
            continue
        by_id[vid] = dict(v)
        by_id[vid]["video_id"] = vid
    for s in search_items:
        if s.get("kind") == "channel":
            continue
        vid = s.get("video_id") or video_id_from_url(s.get("url") or "")
        if not vid:
            continue
        if vid in by_id:
            cur = by_id[vid]
            if not cur.get("snippet") and s.get("snippet"):
                cur["snippet"] = s["snippet"]
            if not cur.get("upload_age") and s.get("upload_age"):
                cur["upload_age"] = s["upload_age"]
            if not cur.get("title") and s.get("title"):
                cur["title"] = s["title"]
        else:
            by_id[vid] = dict(s)
            by_id[vid]["video_id"] = vid
    return list(by_id.values())


def classify_about_product(
    videos: list[dict],
    *,
    company: str,
    product_hint: str = "",
) -> list[dict]:
    """OpenRouter: about product? Doubt → no. Batch in one call."""
    if not videos:
        return videos
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        # Without LLM: heuristic — title/snippet must contain brand token
        tokens = _brand_tokens(company)
        for v in videos:
            blob = f"{v.get('title','')} {v.get('snippet','')}".lower()
            hit = any(t in blob for t in tokens if len(t) >= 4)
            v["about_product"] = bool(hit)
            v["about_reason"] = "heuristic_brand_token" if hit else "heuristic_no_brand"
        return videos

    lines = []
    for i, v in enumerate(videos):
        lines.append(
            f"[{i}] title={v.get('title')!r} description={v.get('snippet')!r}"
        )
    prompt = (
        f"Company/product: {company!r}. Extra context: {product_hint!r}.\n"
        "For each YouTube result, decide if the video is ABOUT this product/company "
        "(review, demo, tutorial, mention as the subject). "
        "If unsure or only a coincidental title match, answer no.\n"
        "Return ONLY JSON: {\"items\":[{\"i\":0,\"about\":true/false,\"reason\":\"short\"},...]}\n\n"
        + "\n".join(lines)
    )
    try:
        r = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "temperature": 0.1,
                "max_tokens": 1200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        r.raise_for_status()
        content = (
            r.json().get("choices", [{}])[0].get("message", {}).get("content") or ""
        )
        m = re.search(r"\{[\s\S]*\}", content)
        parsed = json.loads(m.group(0)) if m else {}
        by_i = {
            int(it["i"]): it
            for it in (parsed.get("items") or [])
            if isinstance(it, dict) and "i" in it
        }
        for i, v in enumerate(videos):
            it = by_i.get(i)
            if not it:
                v["about_product"] = False
                v["about_reason"] = "llm_missing→no"
                continue
            about = bool(it.get("about"))
            # doubt already instructed as no; still coerce null-ish
            v["about_product"] = about
            v["about_reason"] = str(it.get("reason") or "")[:120]
    except Exception as e:
        for v in videos:
            v["about_product"] = False
            v["about_reason"] = f"llm_error→no:{e}"[:120]
    return videos


def summarize_videos(
    videos: list[dict],
    *,
    company: str,
    domain: str = "",
    official_hint: Optional[dict] = None,
) -> dict[str, Any]:
    enriched = []
    for v in videos:
        days = parse_age_to_days(str(v.get("upload_age") or ""))
        official = is_official_channel(
            str(v.get("channel_name") or ""),
            str(v.get("channel_url") or ""),
            company,
            domain,
            official_hint,
        )
        item = {
            **v,
            "age_days": days,
            "age_bucket": age_bucket(days),
            "is_official": official,
            "views": _as_int(v.get("views")),
        }
        enriched.append(item)

    about = [v for v in enriched if v.get("about_product")]
    pool = about if about else []  # only product-related for metrics
    # If LLM marked everything no, still expose all but metrics on about-only
    official_views = sum((v.get("views") or 0) for v in pool if v.get("is_official"))
    unofficial_views = sum((v.get("views") or 0) for v in pool if not v.get("is_official"))
    buckets = {"30d": 0, "6m": 0, "1y_plus": 0, "unknown": 0}
    for v in pool:
        buckets[v.get("age_bucket") or "unknown"] = buckets.get(
            v.get("age_bucket") or "unknown", 0
        ) + (v.get("views") or 0)

    ranked = sorted(pool, key=lambda x: x.get("views") or 0, reverse=True)
    top5 = [
        {
            "title": v.get("title"),
            "url": v.get("url"),
            "views": v.get("views"),
            "channel_name": v.get("channel_name"),
            "is_official": v.get("is_official"),
            "age_bucket": v.get("age_bucket"),
            "upload_age": v.get("upload_age"),
        }
        for v in ranked[:5]
    ]

    return {
        "videos_all": enriched,
        "videos_about_product": pool,
        "counts": {
            "search_page": len(enriched),
            "about_product": len(pool),
            "official": sum(1 for v in pool if v.get("is_official")),
            "unofficial": sum(1 for v in pool if not v.get("is_official")),
        },
        "views_official": official_views,
        "views_unofficial": unofficial_views,
        "views_by_age": buckets,
        "top5": top5,
        "official_channel": official_hint,
    }


def analyze_company(
    company: str,
    *,
    domain: str = "",
    product_hint: str = "",
    market: str = "us",
    query: str | None = None,
) -> dict[str, Any]:
    """Full YouTube Influencers pass for one company (first search page)."""
    t_all = time.time()
    q = (query or company or domain or "").strip()
    if not q:
        raise ValueError("company/query required")
    loc = "US" if (market or "us").lower().startswith("us") else "BR"
    usage = {
        "search_cost_usd": 0.0,
        "agent_cost_usd": 0.0,
        "agent_steps": 0,
        "openrouter": True if os.environ.get("OPENROUTER_API_KEY") else False,
        "estimated_total_usd": 0.0,
    }

    search = tinyfish_search_youtube(q, location=loc)
    usage["search_cost_usd"] = float(search.get("cost_usd") or 0)

    agent = tinyfish_agent_youtube_search(q, country=loc)
    usage["agent_cost_usd"] = float(agent.get("cost_usd") or 0)
    usage["agent_steps"] = int(agent.get("num_of_steps") or 0)
    usage["estimated_total_usd"] = round(
        usage["search_cost_usd"] + usage["agent_cost_usd"], 4
    )
    usage["agent_run_id"] = agent.get("run_id")
    usage["agent_elapsed_sec"] = agent.get("elapsed_sec")
    usage["search_elapsed_sec"] = search.get("elapsed_sec")

    merged = merge_search_and_agent(search.get("items") or [], agent.get("videos") or [])
    merged = classify_about_product(
        merged, company=company, product_hint=product_hint or domain
    )
    summary = summarize_videos(
        merged,
        company=company,
        domain=domain,
        official_hint=agent.get("official_channel"),
    )

    return {
        "ok": bool(agent.get("ok") or merged),
        "company": company,
        "domain": domain,
        "query": q,
        "search_url": agent.get("search_url")
        or f"https://www.youtube.com/results?search_query={quote_plus(q)}",
        "elapsed_sec": round(time.time() - t_all, 2),
        "usage": usage,
        "agent_error": agent.get("error"),
        **summary,
    }
