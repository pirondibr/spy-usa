# -*- coding: utf-8 -*-
"""YouTube Influencers spy — ScrapingBee fetch of native YouTube search + parse.

TinyFish Fetch is blocked on youtube.com/results; ScrapingBee render_js works.
First page only:
- official vs unofficial view totals
- age buckets: 30d / 6m / 1y+
- top links official / unofficial
- product relevance from title+description (brand hit = yes)
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus, urlparse, parse_qs

import requests

SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL") or "google/gemini-2.5-flash"


def _scrapingbee_key() -> str:
    key = (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("SCRAPINGBEE_API_KEY ausente")
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


def _brand_in_text(text: str, tokens: list[str]) -> bool:
    """True if any brand token appears in title/description (incl. #hashtag / compact)."""
    blob = (text or "").lower()
    if not blob or not tokens:
        return False
    compact = re.sub(r"[^a-z0-9]+", "", blob)
    for tok in tokens:
        t = (tok or "").strip().lower()
        if not t or len(t) < 3:
            continue
        t_compact = re.sub(r"[^a-z0-9]+", "", t)
        if not t_compact:
            continue
        if t in blob or f"#{t_compact}" in blob.replace(" ", ""):
            return True
        if len(t_compact) >= 4 and t_compact in compact:
            return True
    return False


def _views_of(v: dict) -> Optional[int]:
    n = _as_int(v.get("views"))
    if n is not None:
        return n
    return _as_int(v.get("views_text"))


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


def _runs_text(obj: Any) -> str:
    if not obj:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        if "simpleText" in obj:
            return str(obj.get("simpleText") or "")
        runs = obj.get("runs") or []
        return "".join(str(r.get("text") or "") for r in runs if isinstance(r, dict))
    return ""


def _extract_yt_initial_data(html: str) -> Optional[dict]:
    idx = (html or "").find("ytInitialData")
    if idx < 0:
        return None
    start = html.find("{", idx)
    if start < 0:
        return None
    depth = 0
    end = None
    for i, ch in enumerate(html[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if not end:
        return None
    try:
        return json.loads(html[start:end])
    except Exception:
        return None


def _channel_from_renderer(vr: dict) -> tuple[str, str]:
    name = ""
    url = ""
    for key in ("ownerText", "longBylineText", "shortBylineText"):
        block = vr.get(key) or {}
        if not name:
            name = _runs_text(block)
        runs = block.get("runs") or []
        if not runs or not isinstance(runs[0], dict):
            continue
        nav = runs[0].get("navigationEndpoint") or {}
        browse = nav.get("browseEndpoint") or {}
        canon = browse.get("canonicalBaseUrl") or ""
        if canon:
            url = "https://www.youtube.com" + canon
            break
        web = ((nav.get("commandMetadata") or {}).get("webCommandMetadata") or {}).get("url") or ""
        if web:
            url = "https://www.youtube.com" + web if web.startswith("/") else web
            break
    return name, url


def _parse_videos_from_yt_data(data: dict) -> list[dict]:
    videos: list[dict] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "videoRenderer" in o:
                vr = o["videoRenderer"] or {}
                vid = str(vr.get("videoId") or "")
                title = _runs_text(vr.get("title"))
                views_text = _runs_text(vr.get("viewCountText")) or _runs_text(
                    vr.get("shortViewCountText")
                )
                age = _runs_text(vr.get("publishedTimeText"))
                snippet = _runs_text(vr.get("descriptionSnippet"))
                channel_name, channel_url = _channel_from_renderer(vr)
                watch = f"https://www.youtube.com/watch?v={vid}" if vid else ""
                videos.append({
                    "kind": "video",
                    "title": title,
                    "url": watch,
                    "video_id": vid,
                    "snippet": snippet,
                    "upload_age": age,
                    "views": _as_int(views_text),
                    "views_text": views_text,
                    "channel_name": channel_name,
                    "channel_url": channel_url,
                    "source": "youtube_native_scrapingbee",
                    "is_short": False,
                })
            if "reelItemRenderer" in o or "shortsLockupViewModel" in o:
                reel = o.get("reelItemRenderer") or o.get("shortsLockupViewModel") or {}
                vid = str(
                    reel.get("videoId")
                    or ((reel.get("onTap") or {}).get("innertubeCommand") or {})
                    .get("reelWatchEndpoint", {})
                    .get("videoId")
                    or ""
                )
                if not vid:
                    eid = ((reel.get("entityId") or "") if isinstance(reel, dict) else "") or ""
                    m = re.search(r"([A-Za-z0-9_-]{6,})", eid)
                    vid = m.group(1) if m else ""
                title = _runs_text(reel.get("headline") or reel.get("overlayMetadata", {}).get("primaryText"))
                views_text = _runs_text(
                    reel.get("viewCountText")
                    or ((reel.get("overlayMetadata") or {}).get("secondaryText"))
                )
                if vid:
                    videos.append({
                        "kind": "video",
                        "title": title,
                        "url": f"https://www.youtube.com/shorts/{vid}",
                        "video_id": vid,
                        "snippet": "",
                        "upload_age": "",
                        "views": _as_int(views_text),
                        "views_text": views_text,
                        "channel_name": "",
                        "channel_url": "",
                        "source": "youtube_native_scrapingbee",
                        "is_short": True,
                    })
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    seen: set[str] = set()
    out: list[dict] = []
    for v in videos:
        vid = v.get("video_id") or ""
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(v)
    return out


def _guess_official_channel(videos: list[dict], query: str) -> Optional[dict]:
    tokens = _brand_tokens(query)
    best = None
    best_score = -1
    for v in videos:
        name = str(v.get("channel_name") or "")
        url = str(v.get("channel_url") or "")
        handle = _handle_from_channel_url(url)
        blob = f"{name} {handle}".lower()
        compact = re.sub(r"[^a-z0-9]+", "", blob)
        score = 0
        for tok in tokens:
            t = re.sub(r"[^a-z0-9]+", "", tok)
            if t and t in compact:
                score += 10 + len(t)
        if score > best_score:
            best_score = score
            best = {"name": name, "url": url} if name or url else None
    return best if best_score >= 10 else None


def scrapingbee_youtube_search(query: str, *, country: str = "US") -> dict[str, Any]:
    """Fetch native YouTube search HTML via ScrapingBee (render_js) and parse cards."""
    t0 = time.time()
    cc = (country or "US").lower()[:2]
    search_url = (
        f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        f"&hl=en&gl={cc.upper()}"
    )
    try:
        r = requests.get(
            SCRAPINGBEE_URL,
            params={
                "api_key": _scrapingbee_key(),
                "url": search_url,
                "render_js": "true",
                "premium_proxy": "true",
                "country_code": cc,
                "wait": "2500",
            },
            timeout=120,
        )
    except requests.Timeout:
        return {
            "ok": False,
            "error": "ScrapingBee timeout (YouTube search)",
            "elapsed_sec": round(time.time() - t0, 2),
            "credits": 0,
            "videos": [],
            "official_channel": None,
            "search_url": search_url,
        }
    except requests.RequestException as e:
        return {
            "ok": False,
            "error": f"ScrapingBee request failed: {e}"[:300],
            "elapsed_sec": round(time.time() - t0, 2),
            "credits": 0,
            "videos": [],
            "official_channel": None,
            "search_url": search_url,
        }

    elapsed = round(time.time() - t0, 2)
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
            "error": f"ScrapingBee HTTP {r.status_code}: {r.text[:300]}",
            "elapsed_sec": elapsed,
            "credits": credits,
            "videos": [],
            "official_channel": None,
            "search_url": search_url,
        }

    data = _extract_yt_initial_data(r.text or "")
    if not data:
        return {
            "ok": False,
            "error": "ytInitialData not found in YouTube HTML (blocked or empty)",
            "elapsed_sec": elapsed,
            "credits": credits,
            "videos": [],
            "official_channel": None,
            "search_url": search_url,
        }

    videos = _parse_videos_from_yt_data(data)
    official = _guess_official_channel(videos, query)
    return {
        "ok": bool(videos),
        "error": None if videos else "No videos parsed from YouTube search page",
        "elapsed_sec": elapsed,
        "credits": credits,
        "videos": videos,
        "official_channel": official,
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


def classify_about_product(
    videos: list[dict],
    *,
    company: str,
    product_hint: str = "",
    domain: str = "",
) -> list[dict]:
    """Mark videos about the product/brand.

    Rule: brand/token in title or description (incl. hashtags) → yes.
    LLM only for ambiguous leftover rows; clear brand hits are never flipped to no.
    """
    if not videos:
        return videos
    tokens = _brand_tokens(company, domain or product_hint)

    def _apply_brand_override(v: dict) -> bool:
        blob = f"{v.get('title', '')} {v.get('snippet', '')}"
        if _brand_in_text(blob, tokens):
            v["about_product"] = True
            v["about_reason"] = "brand_in_title_or_description"
            return True
        return False

    # Pass 1: deterministic brand hit (covers HeyClicky / #heyclicky / Reviewing X)
    pending: list[int] = []
    for i, v in enumerate(videos):
        if _apply_brand_override(v):
            continue
        pending.append(i)
        v["about_product"] = False
        v["about_reason"] = "no_brand_token_yet"

    if not pending:
        return videos

    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        for i in pending:
            videos[i]["about_reason"] = "heuristic_no_brand"
        return videos

    lines = []
    for i in pending:
        v = videos[i]
        lines.append(
            f"[{i}] title={v.get('title')!r} description={v.get('snippet')!r}"
        )
    prompt = (
        f"Company/product brand: {company!r}. Domain/hint: {product_hint or domain!r}.\n"
        "For each YouTube search result, is the video about this product/brand "
        "(review, demo, tutorial, walkthrough, or clear product mention)?\n"
        "YES when the brand/product name appears in the title or description "
        "(including hashtags like #brand), or the video is clearly a review/demo of it.\n"
        "NO only when the result is unrelated / different product with a coincidental word.\n"
        "When unsure but the brand string appears, answer YES.\n"
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
        for i in pending:
            v = videos[i]
            # Re-check brand in case LLM path races — never downgrade brand hits
            if _apply_brand_override(v):
                continue
            it = by_i.get(i)
            if not it:
                v["about_product"] = False
                v["about_reason"] = "llm_missing→no"
                continue
            v["about_product"] = bool(it.get("about"))
            v["about_reason"] = str(it.get("reason") or "llm")[:120]
    except Exception as e:
        for i in pending:
            v = videos[i]
            if not _apply_brand_override(v):
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
        views = _views_of(v)
        item = {
            **v,
            "age_days": days,
            "age_bucket": age_bucket(days),
            "is_official": official,
            "views": views,
        }
        enriched.append(item)

    about = [v for v in enriched if v.get("about_product")]
    # Fallback: if classifier wiped everything but page has brand hits, use those
    if not about:
        tokens = _brand_tokens(company, domain)
        about = [
            v for v in enriched
            if _brand_in_text(f"{v.get('title', '')} {v.get('snippet', '')}", tokens)
        ]
        for v in about:
            v["about_product"] = True
            if not (v.get("about_reason") or "").startswith("brand_"):
                v["about_reason"] = "fallback_brand_in_title_or_description"
    pool = about  # only product-related for metrics
    official_views = sum((v.get("views") or 0) for v in pool if v.get("is_official"))
    unofficial_views = sum((v.get("views") or 0) for v in pool if not v.get("is_official"))
    buckets = {"30d": 0, "6m": 0, "1y_plus": 0, "unknown": 0}
    for v in pool:
        buckets[v.get("age_bucket") or "unknown"] = buckets.get(
            v.get("age_bucket") or "unknown", 0
        ) + (v.get("views") or 0)

    def _top_links(items: list[dict], limit: int = 5) -> list[dict]:
        ranked = sorted(items, key=lambda x: x.get("views") or 0, reverse=True)
        return [
            {
                "title": v.get("title"),
                "url": v.get("url"),
                "views": v.get("views"),
                "channel_name": v.get("channel_name"),
                "is_official": bool(v.get("is_official")),
                "age_bucket": v.get("age_bucket"),
                "upload_age": v.get("upload_age"),
            }
            for v in ranked[:limit]
        ]

    official_pool = [v for v in pool if v.get("is_official")]
    unofficial_pool = [v for v in pool if not v.get("is_official")]
    top5_official = _top_links(official_pool)
    top5_unofficial = _top_links(unofficial_pool)
    top5 = (top5_official + top5_unofficial)[:5]

    return {
        "videos_all": enriched,
        "videos_about_product": pool,
        "counts": {
            "search_page": len(enriched),
            "about_product": len(pool),
            "official": len(official_pool),
            "unofficial": len(unofficial_pool),
        },
        "views_official": official_views,
        "views_unofficial": unofficial_views,
        "views_by_age": buckets,
        "top5": top5,
        "top5_official": top5_official,
        "top5_unofficial": top5_unofficial,
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
        "scrapingbee_credits": 0,
        "openrouter": bool((os.environ.get("OPENROUTER_API_KEY") or "").strip()),
        "estimated_total_usd": 0.0,
        "source": "youtube_native_scrapingbee",
    }

    fetched = scrapingbee_youtube_search(q, country=loc)
    usage["scrapingbee_credits"] = int(fetched.get("credits") or 0)
    usage["fetch_elapsed_sec"] = fetched.get("elapsed_sec")

    videos = list(fetched.get("videos") or [])
    videos = classify_about_product(
        videos,
        company=company,
        product_hint=product_hint or domain,
        domain=domain,
    )
    summary = summarize_videos(
        videos,
        company=company,
        domain=domain,
        official_hint=fetched.get("official_channel"),
    )

    return {
        "ok": bool(fetched.get("ok") or videos),
        "company": company,
        "domain": domain,
        "query": q,
        "search_url": fetched.get("search_url")
        or f"https://www.youtube.com/results?search_query={quote_plus(q)}",
        "elapsed_sec": round(time.time() - t_all, 2),
        "usage": usage,
        "error": fetched.get("error"),
        **summary,
    }
