# -*- coding: utf-8 -*-
"""YouTube Influencers — Apify first-page search (no video open).

Primary: apidojo/youtube-scraper keyword search (min 10 videos, ~$0.50/1k).
Fallback: ScrapingBee native YouTube / Google SERP if Apify fails.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus, urlparse, parse_qs

import requests

from tiktok_brand_filter import classify_all, resolve_brand

ACTOR_ID = "1p1aa7gcSydPkAE0d"
APIFY_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
_COST_PER_VIDEO = 0.50 / 1000
_MAX_DEFAULT = 10

SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL") or "google/gemini-2.5-flash"


def _api_token() -> str:
    return (
        os.environ.get("APIFY_TOKEN")
        or os.environ.get("APIFY_API_TOKEN")
        or os.environ.get("APIFY_API_KEY")
        or ""
    ).strip()


def has_youtube_apify() -> bool:
    return bool(_api_token())


def _max_items() -> int:
    raw = (os.environ.get("SPY_YOUTUBE_MAX_ITEMS") or str(_MAX_DEFAULT)).strip()
    try:
        n = int(raw)
    except ValueError:
        n = _MAX_DEFAULT
    return max(10, min(50, n))


def _cache_dir() -> Path:
    root = (
        os.environ.get("RADAR_DATA_DIR")
        or os.environ.get("SPY_DATA_DIR")
        or ""
    ).strip()
    base = Path(root) if root else Path(__file__).resolve().parents[2] / "data"
    return base / "cache" / "youtube-apify"


def _cache_key(query: str, gl: str, max_items: int) -> str:
    raw = "|".join([query.lower(), gl, str(max_items), date.today().isoformat()])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _cache_get(key: str) -> Optional[list[dict[str, Any]]]:
    path = _cache_dir() / date.today().isoformat() / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else None


def _cache_put(key: str, items: list[dict[str, Any]]) -> None:
    folder = _cache_dir() / date.today().isoformat()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{key}.json").write_text(
            json.dumps({"items": items}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        return


def _iso_to_days(text: str) -> Optional[int]:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", (text or "").strip())
    if not m:
        return parse_age_to_days(text)
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return max(0, (date.today() - d).days)
    except ValueError:
        return parse_age_to_days(text)


def _run_apify(
    query: str,
    *,
    max_items: int,
    gl: str,
    hl: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    token = _api_token()
    if not token:
        raise RuntimeError("Missing APIFY_TOKEN for YouTube Apify")
    body = {
        "keywords": [query],
        "gl": gl,
        "hl": hl,
        "uploadDate": "all",
        "duration": "all",
        "features": "all",
        "sort": "r",
        "maxItems": max_items,
    }
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
            items = payload if isinstance(payload, list) else []
            items = [p for p in items if isinstance(p, dict)]
            return items, {
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


def _item_to_post(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    typ = str(item.get("type") or "video").lower()
    if typ not in ("video", "short", "shorts", ""):
        return None
    ch = item.get("channel") if isinstance(item.get("channel"), dict) else {}
    title = str(item.get("title") or "")
    tags = [t.lstrip("#") for t in re.findall(r"#([A-Za-z0-9_]+)", title)]
    url = str(item.get("url") or "")
    if not url and item.get("id"):
        url = f"https://www.youtube.com/watch?v={item.get('id')}"
    ch_url = str(ch.get("url") or "")
    handle = _handle_from_channel_url(ch_url)
    publish = (
        item.get("publishDate")
        or item.get("publishedAt")
        or item.get("uploadDate")
        or item.get("date")
        or ""
    )
    views = item.get("viewCount")
    if views is None:
        views = item.get("views")
    return {
        "id": str(item.get("id") or item.get("videoId") or ""),
        "title": title,
        "hashtags": tags,
        "views": views,
        "likes": item.get("likes") or item.get("likeCount"),
        "postPage": url,
        "uploadedAtFormatted": str(publish),
        "description": str(item.get("description") or "")[:400],
        "channel": {
            "username": handle,
            "name": ch.get("name") or "",
            "url": ch_url,
            "id": ch.get("id") or "",
        },
    }


def _row_to_video(row: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    ch = post.get("channel") if isinstance(post.get("channel"), dict) else {}
    handle = str(row.get("user") or ch.get("username") or "").lstrip("@")
    publish = str(row.get("uploaded") or post.get("uploadedAtFormatted") or "")
    return {
        "id": row.get("id") or post.get("id") or "",
        "title": row.get("title") or post.get("title") or "YouTube",
        "url": row.get("link") or post.get("postPage") or "",
        "handle": handle,
        "channel_name": ch.get("name") or (f"@{handle}" if handle else ""),
        "channel_url": ch.get("url") or (f"https://www.youtube.com/@{handle}" if handle else ""),
        "views": row.get("views") if row.get("views") is not None else post.get("views"),
        "likes": row.get("likes") if row.get("likes") is not None else post.get("likes"),
        "upload_age": publish,
        "age_days": _iso_to_days(publish),
        "is_official": bool(row.get("official")),
        "label": row.get("label"),
        "score": row.get("score"),
        "reasons": row.get("reasons") or [],
        "flags": row.get("flags") or [],
        "about_product": row.get("label") == "confirmed",
        "about_reason": ",".join(row.get("reasons") or []) or row.get("label"),
    }


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


def official_hint_from_url(url: str) -> Optional[dict]:
    raw = (url or "").strip()
    if not raw or "/watch" in raw or "/shorts/" in raw:
        return None
    handle = _handle_from_channel_url(raw)
    if handle:
        return {"name": f"@{handle}", "url": f"https://www.youtube.com/@{handle}"}
    if "youtube.com/" in raw.lower():
        return {"name": "", "url": raw.split("?")[0]}
    return None


def is_official_channel(
    channel_name: str,
    channel_url: str,
    company: str,
    domain: str = "",
    official_hint: Optional[dict] = None,
) -> bool:
    """Hint from the site/LLM, or the channel name/handle itself carrying the brand."""
    on = str((official_hint or {}).get("name") or "").strip().lower().lstrip("@")
    oh = str((official_hint or {}).get("url") or "").strip().lower()
    hint_handle = _handle_from_channel_url(oh) or on
    cn = (channel_name or "").strip().lower().lstrip("@")
    ch = (channel_url or "").strip().lower()
    ch_handle = _handle_from_channel_url(ch)
    if hint_handle and ch_handle and hint_handle == ch_handle:
        return True
    if oh and ch and ch.rstrip("/") == oh.rstrip("/"):
        return True
    if on and cn and cn == on:
        return True
    tokens = [
        t for t in _brand_tokens(company, domain)
        if len(re.sub(r"[^a-z0-9]+", "", t)) >= 5
    ]
    if tokens and _brand_in_text(f"{cn} {ch} {ch_handle}", tokens):
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


_VIEW_RE = re.compile(
    r"([\d]+(?:[.,]\d+)?)\s*([KkMmBb])?\+?\s*views?",
    flags=re.I,
)
_AGE_RE = re.compile(
    r"(\d+\s*(?:second|minute|hour|day|week|month|year|sec|min|hr|d|w|mo|yr|y)s?\s+ago|yesterday|today)",
    flags=re.I,
)


def _parse_views_blob(*parts: Any) -> Optional[int]:
    blob = " · ".join(str(p) for p in parts if p)
    if not blob:
        return None
    m = _VIEW_RE.search(blob)
    if not m:
        return None
    raw = (m.group(1) or "").replace(",", ".")
    try:
        n = float(raw)
    except ValueError:
        return None
    if n <= 0:
        return None
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get((m.group(2) or "").lower(), 1)
    return int(n * mult)


def _has_youtube_views(items: list[dict[str, Any]]) -> bool:
    for it in items or []:
        url = str(it.get("url") or "").lower()
        if "youtube.com" not in url and "youtu.be" not in url:
            continue
        if "/watch" not in url and "/shorts/" not in url and "youtu.be/" not in url:
            continue
        raw = it.get("views")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return True
        blob = " ".join(
            str(it.get(k) or "")
            for k in (
                "breadcrumb",
                "snippet",
                "description",
                "extended_snippet",
                "pre_snippet",
                "title",
            )
        )
        if _parse_views_blob(blob):
            return True
    return False


def google_youtube_search(query: str, *, market: str = "us") -> dict[str, Any]:
    """Page-1 Google for YouTube videos when native YouTube scrape fails."""
    t0 = time.time()
    search_url = f"https://www.google.com/search?q={quote_plus(query + ' site:youtube.com')}&hl=en"
    try:
        from google_serp import google_serp
        fetched = google_serp(
            query,
            market=market,
            include_domains="youtube.com",
            accept=_has_youtube_views,
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"Google SERP fallback failed: {e}"[:300],
            "elapsed_sec": round(time.time() - t0, 2),
            "credits": 0,
            "videos": [],
            "official_channel": None,
            "search_url": search_url,
            "source": "google_serp",
        }
    videos: list[dict] = []
    seen: set[str] = set()
    for it in fetched.get("items") or []:
        url = normalize_watch_url(str(it.get("url") or ""))
        vid = video_id_from_url(url)
        if not vid or vid in seen:
            continue
        low = url.lower()
        if "youtube.com" not in low and "youtu.be" not in low:
            continue
        if "/watch" not in low and "/shorts/" not in low and "youtu.be/" not in low:
            continue
        seen.add(vid)
        title = str(it.get("title") or "").strip()
        channel = ""
        if title.lower().endswith(" - youtube"):
            parts = [p.strip() for p in title.rsplit(" - ", 2) if p.strip()]
            if len(parts) >= 2 and parts[-1].lower() == "youtube":
                title = parts[0]
                if len(parts) == 3:
                    channel = parts[1]
        blob = " ".join(
            str(it.get(k) or "")
            for k in ("breadcrumb", "snippet", "description", "extended_snippet", "pre_snippet")
        )
        views = it.get("views") if isinstance(it.get("views"), (int, float)) else None
        if not views:
            views = _parse_views_blob(blob, title)
        age_m = _AGE_RE.search(blob)
        videos.append({
            "kind": "video",
            "title": title,
            "url": url if "/shorts/" in low else f"https://www.youtube.com/watch?v={vid}",
            "video_id": vid,
            "snippet": str(it.get("snippet") or it.get("description") or ""),
            "upload_age": age_m.group(0) if age_m else "",
            "views": int(views) if views else None,
            "views_text": str(views) if views else "",
            "channel_name": channel,
            "channel_url": "",
            "source": fetched.get("source") or "google_serp",
            "is_short": "/shorts/" in low,
        })
    return {
        "ok": bool(videos),
        "error": None if videos else (fetched.get("error") or "Google SERP returned no YouTube videos"),
        "elapsed_sec": round(time.time() - t0, 2),
        "credits": int(fetched.get("credits_total") or fetched.get("credits") or 0),
        "videos": videos,
        "official_channel": None,
        "search_url": search_url,
        "source": fetched.get("source") or "google_serp",
    }


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
            timeout=80,
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
    return {
        "ok": bool(videos),
        "error": None if videos else "No videos parsed from YouTube search page",
        "elapsed_sec": elapsed,
        "credits": credits,
        "videos": videos,
        "official_channel": None,
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


def _call_openrouter_json(prompt: str, *, max_tokens: int = 8000) -> dict:
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY ausente")
    last_err: Optional[Exception] = None
    for attempt in range(5):
        r = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "temperature": 0.1,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        if r.status_code == 429 or r.status_code >= 500:
            try:
                wait = float(r.headers.get("Retry-After") or "")
            except (TypeError, ValueError):
                wait = (2 ** attempt) + 0.3
            wait = max(1.0, min(wait, 45.0))
            print(f"[YT-LLM] {r.status_code} — retry {attempt + 1}/5 in {wait:.1f}s", flush=True)
            time.sleep(wait)
            last_err = RuntimeError(f"OpenRouter HTTP {r.status_code}")
            continue
        r.raise_for_status()
        content = (
            r.json().get("choices", [{}])[0].get("message", {}).get("content") or ""
        )
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            raise RuntimeError("OpenRouter returned no JSON")
        return json.loads(m.group(0))
    if last_err:
        raise last_err
    raise RuntimeError("OpenRouter call failed")


def classify_about_product(
    videos: list[dict],
    *,
    company: str,
    product_hint: str = "",
    domain: str = "",
) -> tuple[list[dict], Optional[dict]]:
    """LLM-confirm titles. Brand in title/description counts as about the product."""
    official_from_llm: Optional[dict] = None
    if not videos:
        return videos, None
    for v in videos:
        v["about_product"] = False
        v["about_reason"] = "pending_llm"

    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        for v in videos:
            v["about_reason"] = "no_openrouter_key"
        return videos, None

    lines = []
    for i, v in enumerate(videos[:40]):
        lines.append(
            f"[{i}] title={v.get('title')!r} channel={v.get('channel_name')!r} "
            f"channel_url={v.get('channel_url')!r} description={v.get('snippet')!r}"
        )
    site = (domain or product_hint or "").strip()
    prompt = (
        f"Brand/company: {company!r}. Official website: {site!r}.\n"
        "These are YouTube search results for that brand.\n"
        "Set about=true when the TITLE or DESCRIPTION mentions this brand/product name "
        "(or a clear variant like 'Higgsfield AI'), or the video is a review, tutorial, "
        "ad, demo, comparison, or news of this product.\n"
        "If the brand name is in the title, about=true. Do not reject those as 'unclear'.\n"
        "Set about=false ONLY when the video is clearly a different well-known thing that "
        "just shares a word (a person, song, movie, or another company). "
        "Examples: 'Leonardo da Vinci' is not leonardo.ai; a fashion 'runway' video is not Runway ML.\n"
        "Also set official_i to the index of a video from the company's own YouTube channel, or -1.\n"
        "Return ONLY JSON: "
        '{"items":[{"i":0,"about":true,"reason":"short"}],"official_i":-1}\n\n'
        + "\n".join(lines)
    )
    try:
        parsed = _call_openrouter_json(prompt)
        by_i = {
            int(it["i"]): it
            for it in (parsed.get("items") or [])
            if isinstance(it, dict) and "i" in it
        }
        for i, v in enumerate(videos):
            it = by_i.get(i)
            if not it:
                v["about_product"] = False
                v["about_reason"] = "llm_missing"
                continue
            v["about_product"] = bool(it.get("about"))
            v["about_reason"] = str(it.get("reason") or "llm")[:160]
        try:
            official_i = int(parsed.get("official_i", -1))
        except (TypeError, ValueError):
            official_i = -1
        if 0 <= official_i < len(videos):
            pick = videos[official_i]
            official_from_llm = {
                "name": str(pick.get("channel_name") or ""),
                "url": str(pick.get("channel_url") or ""),
            }
            if not official_from_llm["url"] and not official_from_llm["name"]:
                official_from_llm = None
        print(
            f"[YT-LLM] {company}: about={sum(1 for v in videos if v.get('about_product'))}/"
            f"{len(videos)} official={official_from_llm}",
            flush=True,
        )
    except Exception as e:
        print(f"[YT-LLM] {company} failed: {e}", flush=True)
        for v in videos:
            v["about_product"] = False
            v["about_reason"] = f"llm_error:{e}"[:160]
    tokens = [
        t for t in _brand_tokens(company, domain)
        if len(re.sub(r"[^a-z0-9]+", "", t)) >= 5
    ] or _brand_tokens(company, domain)
    recovered = 0
    for v in videos:
        blob = f"{v.get('title') or ''} {v.get('snippet') or ''} {v.get('channel_name') or ''}"
        if not _brand_in_text(blob, tokens):
            continue
        if not v.get("about_product"):
            recovered += 1
        v["about_product"] = True
        v["about_reason"] = "brand_in_title"
    if recovered:
        print(f"[YT-LLM] {company}: recovered {recovered} via brand-in-title", flush=True)
    return videos, official_from_llm


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
    pool = about  # only LLM-confirmed videos appear in the report
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
    official_hint: Optional[dict] = None,
) -> dict[str, Any]:
    """Full YouTube Influencers pass for one company (first search page)."""
    t_all = time.time()
    name = (company or (domain.split(".")[0] if domain else "")).strip()
    q = (query or name or domain or "").strip()
    if not q:
        raise ValueError("company/query required")
    loc = "us" if (market or "us").lower().startswith("us") else "br"
    hl = "en" if loc == "us" else "pt"
    hint_handle = _handle_from_channel_url(str((official_hint or {}).get("url") or ""))
    if not hint_handle:
        hint_handle = str((official_hint or {}).get("name") or "").lstrip("@").lower()
    cfg = resolve_brand(name, domain=domain, official_handle=hint_handle)
    max_items = _max_items()

    cached = False
    cache_key = _cache_key(q, loc, max_items)
    raw = _cache_get(cache_key)
    fetch_meta: dict[str, Any] = {"ok": True, "error": None, "elapsed_sec": 0}
    if raw is None:
        if has_youtube_apify():
            raw, fetch_meta = _run_apify(q, max_items=max_items, gl=loc, hl=hl)
            if fetch_meta.get("ok") and raw:
                _cache_put(cache_key, raw)
        else:
            raw = []
            fetch_meta = {"ok": False, "error": "APIFY_TOKEN missing"}
    else:
        cached = True

    posts = [p for p in (_item_to_post(it) for it in (raw or [])) if p]
    if posts:
        classified = classify_all(
            posts,
            name,
            with_subtitles=False,
            domain=domain,
            official_handle=hint_handle,
        )
        by_id = {str(p.get("id") or ""): p for p in posts if p.get("id")}
        videos = [
            _row_to_video(row, by_id.get(str(row.get("id") or ""), {}))
            for row in classified
        ]
        for v in videos:
            v["is_official"] = bool(v.get("is_official")) or is_official_channel(
                str(v.get("channel_name") or ""),
                str(v.get("channel_url") or ""),
                name,
                domain,
                official_hint,
            )
            days = v.get("age_days")
            if days is None:
                days = _iso_to_days(str(v.get("upload_age") or ""))
                v["age_days"] = days
            v["age_bucket"] = age_bucket(days)
            v["views"] = _views_of(v) or 0

        confirmed = [v for v in videos if v.get("label") == "confirmed"]
        probable = [v for v in videos if v.get("label") == "probable"]
        unrelated = [v for v in videos if v.get("label") == "unrelated"]
        official_pool = [v for v in confirmed if v.get("is_official")]
        other_pool = [v for v in confirmed if not v.get("is_official")]

        def _top(items: list[dict], limit: int = 5) -> list[dict]:
            return sorted(items, key=lambda x: int(x.get("views") or 0), reverse=True)[:limit]

        buckets = {"30d": 0, "6m": 0, "1y_plus": 0, "unknown": 0}
        for v in confirmed:
            key = v.get("age_bucket") or "unknown"
            buckets[key] = buckets.get(key, 0) + int(v.get("views") or 0)

        billed = max(len(raw), 10) if raw and not cached else 0
        cost = round(billed * _COST_PER_VIDEO, 6) if not cached else 0.0
        print(
            f"[YT-INF] apify q={q!r} items={len(raw)} confirmed={len(confirmed)} "
            f"probable={len(probable)} unrelated={len(unrelated)} "
            f"~${cost:.4f} cached={cached}",
            flush=True,
        )
        return {
            "ok": bool(confirmed or probable or (fetch_meta.get("ok") and raw)),
            "company": name,
            "domain": domain,
            "query": q,
            "search_url": f"https://www.youtube.com/results?search_query={quote_plus(q)}",
            "official_channel": official_hint or (
                official_hint_from_url(f"https://www.youtube.com/@{hint_handle}")
                if hint_handle else None
            ),
            "brand": {
                "name": cfg.get("name"),
                "ambiguous": bool(cfg.get("ambiguous")),
                "query": q,
            },
            "views_official": sum(int(v.get("views") or 0) for v in official_pool),
            "views_unofficial": sum(int(v.get("views") or 0) for v in other_pool),
            "views_by_age": buckets,
            "about_count": len(confirmed),
            "page_count": len(raw or []),
            "top5": _top(confirmed or probable),
            "top5_official": _top(official_pool),
            "top5_unofficial": _top(other_pool),
            "videos_about_product": confirmed,
            "counts": {
                "search_page": len(raw or []),
                "about_product": len(confirmed),
                "confirmed": len(confirmed),
                "probable": len(probable),
                "unrelated": len(unrelated),
                "official": len(official_pool),
                "unofficial": len(other_pool),
            },
            "usage": {
                "source": "apify_youtube",
                "actor": ACTOR_ID,
                "cached": cached,
                "estimated_usd": cost,
                "estimated_total_usd": cost,
                "search_cost_usd": cost,
                "posts": len(raw or []),
                "max_items": max_items,
                "gl": loc,
                "elapsed_fetch_sec": fetch_meta.get("elapsed_sec"),
                "scrapingbee_credits": 0,
                "note": (
                    "Apify apidojo/youtube-scraper keyword search. "
                    "First page, no video open. Brand filter confirmed/probable/unrelated."
                ),
            },
            "elapsed_sec": round(time.time() - t_all, 2),
            "error": None if (raw or cached) else (fetch_meta.get("error") or "YouTube Apify returned no videos"),
        }

    print(
        f"[YT-INF] Apify empty ({fetch_meta.get('error') or 'no videos'}); "
        f"falling back to ScrapingBee / Google SERP",
        flush=True,
    )
    loc_sb = "US" if loc == "us" else "BR"
    usage = {
        "scrapingbee_credits": 0,
        "openrouter": bool((os.environ.get("OPENROUTER_API_KEY") or "").strip()),
        "estimated_total_usd": 0.0,
        "source": "youtube_native_scrapingbee",
        "apify_error": fetch_meta.get("error"),
    }

    fetched = scrapingbee_youtube_search(q, country=loc_sb)
    usage["scrapingbee_credits"] = int(fetched.get("credits") or 0)
    usage["fetch_elapsed_sec"] = fetched.get("elapsed_sec")
    usage["source"] = "youtube_native_scrapingbee"
    if not fetched.get("videos"):
        print(
            f"[YT-INF] native YouTube empty ({fetched.get('error') or 'no videos'}); "
            f"falling back to Google SERP",
            flush=True,
        )
        google = google_youtube_search(q, market=market)
        usage["scrapingbee_credits"] += int(google.get("credits") or 0)
        usage["source"] = google.get("source") or "google_serp"
        usage["fetch_elapsed_sec"] = round(
            float(fetched.get("elapsed_sec") or 0) + float(google.get("elapsed_sec") or 0), 2
        )
        if google.get("videos"):
            fetched = google
        else:
            fetched["error"] = (
                f"{fetched.get('error') or 'native empty'} | "
                f"{google.get('error') or 'google empty'}"
            )

    videos = list(fetched.get("videos") or [])
    videos, llm_official = classify_about_product(
        videos,
        company=company,
        product_hint=product_hint or domain,
        domain=domain,
    )
    hint = official_hint or llm_official or _guess_official_channel(videos, company)
    summary = summarize_videos(
        videos,
        company=company,
        domain=domain,
        official_hint=hint,
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
