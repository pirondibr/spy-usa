# -*- coding: utf-8 -*-
"""YouTube Influencers — ScrapingBee search cards (popular, relevance fallback)."""

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

from brand_llm_filter import apply_llm_labels, repartition
from tiktok_brand_filter import classify_all, resolve_brand, search_query

ACTOR_ID = "1p1aa7gcSydPkAE0d"
APIFY_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
_COST_PER_VIDEO = 0.50 / 1000
_MAX_DEFAULT = 20
_YT_SORT_VIEWS = "CAM%3D"  # YouTube "View count"
_YT_SORT_RELEVANCE = ""  # default YouTube ranking

SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"


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
    return max(20, min(50, n))


def _cache_dir() -> Path:
    root = (
        os.environ.get("RADAR_DATA_DIR")
        or os.environ.get("SPY_DATA_DIR")
        or ""
    ).strip()
    base = Path(root) if root else Path(__file__).resolve().parents[2] / "data"
    return base / "cache" / "youtube-sb"


def _cache_key(query: str, gl: str, max_items: int, sort: str = "v") -> str:
    raw = "|".join([query.lower(), gl, str(max_items), sort, date.today().isoformat()])
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
        "sort": "v",
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
        "subtitle_text": str(item.get("description") or item.get("text") or "")[:800],
        "channel": {
            "username": handle,
            "name": ch.get("name") or "",
            "url": ch_url,
            "id": ch.get("id") or "",
        },
    }


def quoted_brand_query(brand: str, domain: str = "") -> str:
    """Exact-phrase YouTube/Google query: \"trendtrack\"."""
    raw = (brand or "").strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 3:
        return raw
    token = re.sub(r"\s+ai$", "", raw, flags=re.I).strip()
    if not token:
        token = (domain or "").split(".")[0].strip()
    token = (token.split()[0] if token else "").strip().strip('"')
    return f'"{token}"' if token else ""


def _google_video_to_post(video: dict[str, Any]) -> Optional[dict[str, Any]]:
    vid = str(video.get("video_id") or video_id_from_url(str(video.get("url") or "")))
    url = str(video.get("url") or "")
    if vid and not url:
        url = f"https://www.youtube.com/watch?v={vid}"
    if not vid:
        vid = video_id_from_url(url)
    if not vid:
        return None
    title = str(video.get("title") or "")
    snippet = str(video.get("snippet") or "")
    handle = _handle_from_channel_url(str(video.get("channel_url") or ""))
    name = str(video.get("channel_name") or "")
    return {
        "id": vid,
        "title": title,
        "hashtags": [t.lstrip("#") for t in re.findall(r"#([A-Za-z0-9_]+)", title)],
        "views": video.get("views"),
        "postPage": url if "/shorts/" in url.lower() else f"https://www.youtube.com/watch?v={vid}",
        "uploadedAtFormatted": str(video.get("upload_age") or ""),
        "description": snippet[:400],
        "subtitle_text": snippet[:800],
        "channel": {
            "username": handle or name.lstrip("@"),
            "name": name,
            "url": video.get("channel_url") or "",
        },
    }


def _views_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    leftover: list[dict[str, Any]] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        pid = str(post.get("id") or video_id_from_url(str(post.get("postPage") or "")))
        if not pid:
            leftover.append(post)
            continue
        post["id"] = pid
        prev = by_id.get(pid)
        if not prev:
            by_id[pid] = post
            continue
        if _views_int(post.get("views")) > _views_int(prev.get("views")):
            if not post.get("subtitle_text"):
                post["subtitle_text"] = prev.get("subtitle_text") or ""
            if not (post.get("channel") or {}).get("url"):
                post["channel"] = prev.get("channel") or post.get("channel")
            by_id[pid] = post
        else:
            if not prev.get("subtitle_text") and post.get("subtitle_text"):
                prev["subtitle_text"] = post.get("subtitle_text")
    return list(by_id.values()) + leftover


def _row_to_video(row: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    ch = post.get("channel") if isinstance(post.get("channel"), dict) else {}
    handle = str(row.get("user") or ch.get("username") or "").lstrip("@")
    publish = str(row.get("uploaded") or post.get("uploadedAtFormatted") or "")
    vid = str(row.get("id") or post.get("id") or "")
    title = str(row.get("title") or post.get("title") or "").strip()
    href = str(row.get("link") or post.get("postPage") or "")
    if not title:
        title = href or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
    return {
        "id": vid,
        "title": title,
        "url": href or (f"https://www.youtube.com/watch?v={vid}" if vid else ""),
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
        "description": str(
            post.get("subtitle_text") or post.get("description") or ""
        )[:400],
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
        return obj.strip()
    if isinstance(obj, dict):
        for key in ("simpleText", "content", "accessibilityText", "text", "label"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                nested = _runs_text(val)
                if nested:
                    return nested
        runs = obj.get("runs") or []
        if runs:
            return "".join(str(r.get("text") or "") for r in runs if isinstance(r, dict)).strip()
    return ""


def _extract_yt_initial_data(html: str) -> Optional[dict]:
    blob = html or ""
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", blob, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    idx = blob.find("ytInitialData")
    if idx < 0:
        return None
    start = blob.find("{", idx)
    if start < 0:
        return None
    depth = 0
    end = None
    for i, ch in enumerate(blob[start:], start):
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
        return json.loads(blob[start:end])
    except Exception:
        return None


def _card_snippet(vr: dict) -> str:
    """Search-card description lives in detailedMetadataSnippets, not descriptionSnippet."""
    chunks: list[str] = []
    for block in vr.get("detailedMetadataSnippets") or []:
        if not isinstance(block, dict):
            continue
        text = _runs_text(block.get("snippetText"))
        if text:
            chunks.append(text.replace("\n", " "))
    if chunks:
        return " ".join(chunks)
    return _runs_text(vr.get("descriptionSnippet"))


def _youtube_search_url(
    query: str,
    *,
    sort: str = "views",
    for_scrapingbee: bool = False,
) -> str:
    """YouTube search. View-count uses sp=CAM%3D; relevance omits sp (YouTube default)."""
    url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    if (sort or "views").lower() != "views":
        return url
    sp = _YT_SORT_VIEWS
    if for_scrapingbee:
        # Double-encode % so requests+ScrapingBee leave YouTube with CAM%3D.
        sp = sp.replace("%", "%25")
    return f"{url}&sp={sp}"


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


def _card_rank(card: dict) -> tuple[int, int]:
    title = 1 if str(card.get("title") or "").strip() else 0
    extra = (
        (1 if card.get("snippet") else 0)
        + (1 if card.get("channel_name") else 0)
        + (1 if card.get("views") else 0)
    )
    return title, extra


def _from_classic_renderer(vr: dict, *, is_short: bool = False) -> Optional[dict]:
    if not isinstance(vr, dict):
        return None
    vid = str(vr.get("videoId") or "")
    if not vid:
        return None
    title = _runs_text(vr.get("title")) or _runs_text(vr.get("headline"))
    views_text = _runs_text(vr.get("viewCountText")) or _runs_text(vr.get("shortViewCountText"))
    age = _runs_text(vr.get("publishedTimeText"))
    snippet = _card_snippet(vr)
    channel_name, channel_url = _channel_from_renderer(vr)
    path = f"/shorts/{vid}" if is_short else f"/watch?v={vid}"
    return {
        "kind": "video",
        "title": title,
        "url": f"https://www.youtube.com{path}",
        "video_id": vid,
        "snippet": snippet,
        "upload_age": age,
        "views": _as_int(views_text),
        "views_text": views_text,
        "channel_name": channel_name,
        "channel_url": channel_url,
        "source": "youtube_native_scrapingbee",
        "is_short": is_short,
    }


def _from_lockup(lockup: dict) -> Optional[dict]:
    if not isinstance(lockup, dict):
        return None
    vid = str(lockup.get("contentId") or "")
    if not vid or len(vid) < 6:
        tap = ((lockup.get("rendererContext") or {}).get("commandContext") or {}).get("onTap") or {}
        innertube = (tap.get("innertubeCommand") or {}) if isinstance(tap, dict) else {}
        vid = str(
            (innertube.get("watchEndpoint") or {}).get("videoId")
            or (innertube.get("reelWatchEndpoint") or {}).get("videoId")
            or ""
        )
    if not vid:
        return None
    meta = (lockup.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    title = _runs_text(meta.get("title")) or _runs_text(lockup.get("accessibilityText"))
    rows = ((meta.get("metadata") or {}).get("contentMetadataViewModel") or {}).get("metadataRows") or []
    bits = [_runs_text(row) for row in rows if isinstance(row, dict)]
    views_text = next((b for b in bits if "view" in b.lower()), "")
    age = next((b for b in bits if "ago" in b.lower() or "há" in b.lower()), "")
    channel_name = next((b for b in bits if b and b != views_text and b != age), "")
    image = str((lockup.get("contentImage") or {}).get("thumbnailViewModel") or "")
    is_short = "shorts" in image.lower()
    path = f"/shorts/{vid}" if is_short else f"/watch?v={vid}"
    return {
        "kind": "video",
        "title": title,
        "url": f"https://www.youtube.com{path}",
        "video_id": vid,
        "snippet": "",
        "upload_age": age,
        "views": _as_int(views_text),
        "views_text": views_text,
        "channel_name": channel_name,
        "channel_url": "",
        "source": "youtube_native_scrapingbee",
        "is_short": is_short,
    }


def _parse_videos_from_yt_data(data: dict) -> list[dict]:
    videos: list[dict] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "videoRenderer" in o:
                card = _from_classic_renderer(o.get("videoRenderer") or {})
                if card:
                    videos.append(card)
            if "compactVideoRenderer" in o:
                card = _from_classic_renderer(o.get("compactVideoRenderer") or {})
                if card:
                    videos.append(card)
            if "lockupViewModel" in o:
                card = _from_lockup(o.get("lockupViewModel") or {})
                if card:
                    videos.append(card)
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
                title = (
                    _runs_text(reel.get("headline"))
                    or _runs_text((reel.get("overlayMetadata") or {}).get("primaryText"))
                    or _runs_text(reel.get("accessibilityText"))
                )
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
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for v in videos:
        vid = str(v.get("video_id") or "")
        if not vid:
            continue
        prev = by_id.get(vid)
        if prev is None:
            by_id[vid] = v
            order.append(vid)
            continue
        if _card_rank(v) > _card_rank(prev):
            if not v.get("snippet"):
                v["snippet"] = prev.get("snippet") or ""
            if not v.get("channel_name"):
                v["channel_name"] = prev.get("channel_name") or ""
                v["channel_url"] = prev.get("channel_url") or v.get("channel_url") or ""
            by_id[vid] = v
        else:
            if not prev.get("snippet") and v.get("snippet"):
                prev["snippet"] = v.get("snippet")
            if not prev.get("title") and v.get("title"):
                prev["title"] = v.get("title")
            if not prev.get("channel_name") and v.get("channel_name"):
                prev["channel_name"] = v.get("channel_name")
                prev["channel_url"] = v.get("channel_url") or prev.get("channel_url") or ""
    out = [by_id[vid] for vid in order]
    return [v for v in out if str(v.get("title") or "").strip()]


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


def scrapingbee_youtube_search(
    query: str,
    *,
    country: str = "US",
    sort: str = "views",
) -> dict[str, Any]:
    """One no-JS ScrapingBee credit: ytInitialData cards including description snippets."""
    t0 = time.time()
    search_url = _youtube_search_url(query, sort=sort)
    fetch_url = _youtube_search_url(query, sort=sort, for_scrapingbee=True)
    try:
        r = requests.get(
            SCRAPINGBEE_URL,
            params={
                "api_key": _scrapingbee_key(),
                "url": fetch_url,
                "render_js": "false",
            },
            timeout=150,
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


def classify_about_product(
    videos: list[dict],
    *,
    company: str,
    product_hint: str = "",
    domain: str = "",
    niche: str = "",
) -> tuple[list[dict], Optional[dict]]:
    """LLM-confirm titles for THIS brand in THIS niche. No brand-in-title recovery."""
    apply_llm_labels(
        videos,
        brand=company,
        domain=domain,
        niche=niche or product_hint,
        product=product_hint or domain,
        channel="youtube",
    )
    official = next(
        (v for v in videos if v.get("is_official") and v.get("about_product")),
        None,
    )
    return videos, official


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


def _classify_youtube_posts(
    posts: list[dict[str, Any]],
    *,
    name: str,
    domain: str,
    hint_handle: str,
    official_hint: Optional[dict],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
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
    return confirmed, probable, unrelated, official_pool, other_pool, videos


def _search_video_to_post(video: dict[str, Any]) -> Optional[dict[str, Any]]:
    vid = str(video.get("video_id") or video_id_from_url(str(video.get("url") or "")))
    if not vid:
        return None
    title = str(video.get("title") or "")
    desc = str(video.get("description") or video.get("snippet") or "")
    handle = _handle_from_channel_url(str(video.get("channel_url") or ""))
    name = str(video.get("channel_name") or "")
    href = str(video.get("url") or "")
    if not href:
        href = f"https://www.youtube.com/watch?v={vid}"
    return {
        "id": vid,
        "title": title,
        "hashtags": [t.lstrip("#") for t in re.findall(r"#([A-Za-z0-9_]+)", title + " " + desc)],
        "views": video.get("views"),
        "postPage": href,
        "uploadedAtFormatted": str(video.get("upload_age") or ""),
        "description": desc[:800],
        "subtitle_text": desc[:2000],
        "channel": {
            "username": handle or name.lstrip("@"),
            "name": name,
            "url": video.get("channel_url") or "",
        },
    }


def _collect_search_posts(
    query: str,
    *,
    loc: str,
    loc_sb: str,
    max_items: int,
    sort: str,
) -> dict[str, Any]:
    """One ScrapingBee no-JS search page for the given YouTube sort."""
    cache_key = _cache_key(query, loc, max_items, f"sb-njs-{sort}")
    search_url = _youtube_search_url(query, sort=sort)
    cached_posts = _cache_get(cache_key)
    if cached_posts is not None:
        posts = [p for p in cached_posts if isinstance(p, dict)]
        return {
            "posts": posts,
            "credits": 0,
            "search_url": search_url,
            "search_n": len(posts),
            "snippet_n": sum(1 for p in posts if p.get("subtitle_text") or p.get("description")),
            "cached": True,
            "error": None,
            "sort": sort,
        }
    fetched = scrapingbee_youtube_search(query, country=loc_sb, sort=sort)
    videos = list(fetched.get("videos") or [])
    picked = videos[:max_items]
    posts = [p for p in (_search_video_to_post(v) for v in picked) if p]
    if posts:
        _cache_put(cache_key, posts)
    return {
        "posts": posts,
        "credits": int(fetched.get("credits") or 0),
        "search_url": str(fetched.get("search_url") or search_url),
        "search_n": len(videos),
        "snippet_n": sum(1 for v in picked if v.get("snippet") or v.get("description")),
        "cached": False,
        "error": None if videos else (fetched.get("error") or "search empty"),
        "sort": sort,
    }


def analyze_company(
    company: str,
    *,
    domain: str = "",
    product_hint: str = "",
    market: str = "us",
    query: str | None = None,
    official_hint: Optional[dict] = None,
    niche: str = "",
    product: str = "",
) -> dict[str, Any]:
    """YouTube influencers: ScrapingBee search cards only (popular, relevance if 0)."""
    t_all = time.time()
    name = (company or (domain.split(".")[0] if domain else "")).strip()
    q = (query or search_query(name, domain=domain) or name or domain or "").strip()
    if not q:
        raise ValueError("company/query required")
    loc = "us" if (market or "us").lower().startswith("us") else "br"
    loc_sb = "US" if loc == "us" else "BR"
    hint_handle = _handle_from_channel_url(str((official_hint or {}).get("url") or ""))
    if not hint_handle:
        hint_handle = str((official_hint or {}).get("name") or "").lstrip("@").lower()
    cfg = resolve_brand(name, domain=domain, official_handle=hint_handle)
    max_items = _max_items()

    pack = _collect_search_posts(q, loc=loc, loc_sb=loc_sb, max_items=max_items, sort="views")
    used_sort = "views"
    fallback_used = False
    credits = int(pack.get("credits") or 0)
    cached = bool(pack.get("cached"))
    posts = list(pack.get("posts") or [])
    search_n = int(pack.get("search_n") or len(posts))
    snippet_n = int(pack.get("snippet_n") or 0)
    search_url = str(pack.get("search_url") or _youtube_search_url(q, sort="views"))
    error = pack.get("error")

    if not posts:
        print(
            f"[YT-INF] popular search empty ({error or 'no videos'}); trying relevance",
            flush=True,
        )
        rel = _collect_search_posts(q, loc=loc, loc_sb=loc_sb, max_items=max_items, sort="relevance")
        credits += int(rel.get("credits") or 0)
        cached = cached and bool(rel.get("cached"))
        if rel.get("posts"):
            pack = rel
            posts = list(rel.get("posts") or [])
            search_n = int(rel.get("search_n") or len(posts))
            snippet_n = int(rel.get("snippet_n") or 0)
            search_url = str(rel.get("search_url") or search_url)
            error = None
            used_sort = "relevance"
            fallback_used = True
        else:
            print(
                f"[YT-INF] relevance search empty ({rel.get('error') or 'no videos'}); "
                f"trying Google SERP",
                flush=True,
            )
            google = google_youtube_search(q, market=market)
            credits += int(google.get("credits") or 0)
            videos = list(google.get("videos") or [])
            if google.get("search_url"):
                search_url = str(google.get("search_url"))
            search_n = len(videos)
            picked = videos[:max_items]
            snippet_n = sum(1 for v in picked if v.get("snippet") or v.get("description"))
            posts = [p for p in (_search_video_to_post(v) for v in picked) if p]
            error = None if videos else (
                f"{error or 'popular empty'} | {rel.get('error') or 'relevance empty'} | "
                f"{google.get('error') or 'google empty'}"
            )
            used_sort = "google" if videos else used_sort

    if not snippet_n:
        snippet_n = sum(1 for p in posts if p.get("subtitle_text") or p.get("description"))

    confirmed, probable, unrelated, official_pool, other_pool, fetched = _classify_youtube_posts(
        posts,
        name=name,
        domain=domain,
        hint_handle=hint_handle,
        official_hint=official_hint,
    )

    if not confirmed and used_sort == "views":
        print(
            f"[YT-INF] popular kept 0 brand videos "
            f"(search={search_n} unrelated={len(unrelated)}); trying relevance",
            flush=True,
        )
        rel = _collect_search_posts(q, loc=loc, loc_sb=loc_sb, max_items=max_items, sort="relevance")
        credits += int(rel.get("credits") or 0)
        cached = cached and bool(rel.get("cached"))
        rel_posts = list(rel.get("posts") or [])
        if rel_posts:
            c2, p2, u2, off2, oth2, fetched2 = _classify_youtube_posts(
                rel_posts,
                name=name,
                domain=domain,
                hint_handle=hint_handle,
                official_hint=official_hint,
            )
            if c2 or p2:
                posts = rel_posts
                search_n = int(rel.get("search_n") or len(rel_posts))
                snippet_n = int(rel.get("snippet_n") or 0) or sum(
                    1 for p in rel_posts if p.get("subtitle_text") or p.get("description")
                )
                search_url = str(rel.get("search_url") or search_url)
                confirmed, probable, unrelated = c2, p2, u2
                official_pool, other_pool, fetched = off2, oth2, fetched2
                used_sort = "relevance"
                fallback_used = True
                error = None
                print(
                    f"[YT-INF] relevance fallback kept confirmed={len(confirmed)} "
                    f"probable={len(probable)}",
                    flush=True,
                )
            else:
                print(
                    f"[YT-INF] relevance also 0 brand videos "
                    f"(search={len(rel_posts)} unrelated={len(u2)}); keeping popular set",
                    flush=True,
                )

    apply_llm_labels(
        fetched,
        brand=q or name,
        domain=domain,
        niche=niche or product_hint,
        product=product or product_hint or domain,
        channel="youtube",
    )
    confirmed, probable, unrelated, official_pool, other_pool = repartition(fetched)

    def _top(items: list[dict], limit: int = 5) -> list[dict]:
        return sorted(items, key=lambda x: int(x.get("views") or 0), reverse=True)[:limit]

    buckets = {"30d": 0, "6m": 0, "1y_plus": 0, "unknown": 0}
    for v in confirmed:
        key = v.get("age_bucket") or "unknown"
        buckets[key] = buckets.get(key, 0) + int(v.get("views") or 0)

    print(
        f"[YT-INF] q={q!r} sort={used_sort} fallback={fallback_used} "
        f"sb-search={search_n or len(posts)} snippet={snippet_n} "
        f"confirmed={len(confirmed)} probable={len(probable)} "
        f"unrelated={len(unrelated)} credits={credits} cached={cached}",
        flush=True,
    )
    return {
        "ok": bool(confirmed or probable or posts),
        "company": name,
        "domain": domain,
        "query": q,
        "search_url": search_url,
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
        "llm_title_filter": True,
        "about_count": len(confirmed),
        "page_count": len(posts),
        "top5": _top(confirmed or probable),
        "top5_official": _top(official_pool),
        "top5_unofficial": _top(other_pool),
        "videos_about_product": confirmed,
        "videos_probable": probable,
        "videos_unrelated": unrelated,
        "videos_fetched": fetched,
        "counts": {
            "search_page": search_n or len(posts),
            "about_product": len(confirmed),
            "confirmed": len(confirmed),
            "probable": len(probable),
            "unrelated": len(unrelated),
            "official": len(official_pool),
            "unofficial": len(other_pool),
            "with_snippet": snippet_n,
        },
        "usage": {
            "source": "scrapingbee_youtube_njs",
            "cached": cached,
            "estimated_usd": 0.0,
            "posts": len(posts),
            "max_items": max_items,
            "sort": used_sort,
            "sort_fallback": fallback_used,
            "gl": loc,
            "scrapingbee_credits": credits,
            "note": (
                "ScrapingBee no-JS YouTube search. Popular first (sp=CAM%3D); "
                "relevance if the page is empty or brand filter keeps 0. "
                "Regex prefilter, then OpenRouter LLM (brand / niche / product)."
            ),
        },
        "elapsed_sec": round(time.time() - t_all, 2),
        "error": error if not posts else None,
    }
