# -*- coding: utf-8 -*-
"""TikTok influencers from Google SERP only — never fetch tiktok.com."""

from __future__ import annotations

import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus

from google_serp import google_serp, has_google_serp

_VIEW_RE = re.compile(
    r"([\d]+(?:[.,]\d+)?)\s*([KkMmBb])?\+?\s*views?",
    flags=re.I,
)
_HANDLE_RE = re.compile(r"tiktok\.com/@([^/?#]+)", flags=re.I)
_VIDEO_RE = re.compile(r"/video/(\d+)", flags=re.I)


def parse_views_text(*parts: Any) -> Optional[int]:
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
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(
        (m.group(2) or "").lower(), 1
    )
    return int(n * mult)


def handle_from_url(url: str) -> str:
    m = _HANDLE_RE.search(url or "")
    return (m.group(1) if m else "").strip().lower()


def is_tiktok_url(url: str) -> bool:
    low = (url or "").lower()
    return "tiktok.com/" in low or low.startswith("https://vm.tiktok.com")


def is_tiktok_post(url: str) -> bool:
    low = (url or "").lower()
    if not is_tiktok_url(low):
        return False
    return bool(_VIDEO_RE.search(low) or "/photo/" in low or "/t/" in low)


def official_hint_from_url(url: str) -> Optional[dict]:
    handle = handle_from_url(url)
    if not handle:
        return None
    return {"name": f"@{handle}", "url": f"https://www.tiktok.com/@{handle}"}


def _brand_tokens(company: str, domain: str = "") -> list[str]:
    raw = []
    for part in (company, domain.split(".")[0] if domain else ""):
        part = re.sub(r"[^a-z0-9]+", " ", (part or "").lower()).strip()
        if part:
            raw.append(part)
            raw.append(part.replace(" ", ""))
    out: list[str] = []
    seen = set()
    for r in raw:
        compact = re.sub(r"[^a-z0-9]+", "", r)
        if compact and len(compact) >= 4 and compact not in seen:
            seen.add(compact)
            out.append(compact)
    return out


def _brand_in_text(text: str, tokens: list[str]) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    return any(t in compact for t in tokens if len(t) >= 4)


def _item_view_blob(it: dict[str, Any]) -> str:
    return " ".join(
        str(it.get(k) or "")
        for k in (
            "breadcrumb",
            "snippet",
            "description",
            "extended_snippet",
            "pre_snippet",
            "highlighted",
            "title",
        )
    )


def _has_tiktok_views(items: list[dict[str, Any]]) -> bool:
    for it in items or []:
        if not is_tiktok_url(str(it.get("url") or "")):
            continue
        if parse_views_text(_item_view_blob(it)) is not None:
            return True
    return False


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
    q = (query or f"site:tiktok.com {name}").strip()
    loc = "US" if not (market or "us").lower().startswith("br") else "BR"
    if not has_google_serp():
        fetched = {"ok": False, "items": [], "error": "no Google SERP provider", "source": ""}
    else:
        fetched = google_serp(
            q,
            market=market,
            include_domains="tiktok.com",
            accept=_has_tiktok_views,
        )
    tokens = _brand_tokens(name, domain)
    hint_handle = handle_from_url(str((official_hint or {}).get("url") or ""))
    if not hint_handle:
        hint_handle = str((official_hint or {}).get("name") or "").lstrip("@").lower()
    if not hint_handle:
        for it in fetched.get("items") or []:
            url = str(it.get("url") or "")
            if is_tiktok_post(url):
                continue
            if not is_tiktok_url(url):
                continue
            title = str(it.get("title") or "")
            if tokens and _brand_in_text(title, tokens):
                hint_handle = handle_from_url(url)
                if hint_handle:
                    official_hint = official_hint or official_hint_from_url(url)
                    break

    posts: list[dict] = []
    skipped_no_views = 0
    skipped_not_post = 0
    skipped_brand = 0
    for it in fetched.get("items") or []:
        url = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        desc = str(it.get("description") or it.get("snippet") or "").strip()
        breadcrumb = str(it.get("breadcrumb") or "")
        extra = " ".join(
            str(it.get(k) or "")
            for k in ("extended_snippet", "pre_snippet", "highlighted", "snippet")
        )
        views = parse_views_text(breadcrumb, extra, desc, title)
        if not is_tiktok_url(url):
            skipped_not_post += 1
            continue
        if views is None:
            skipped_no_views += 1
            continue
        if not (is_tiktok_post(url) or it.get("is_video")):
            skipped_not_post += 1
            continue
        blob = f"{title} {desc}"
        if tokens and not _brand_in_text(blob, tokens):
            skipped_brand += 1
            continue
        handle = handle_from_url(url)
        official = bool(hint_handle and handle and handle == hint_handle)
        age = ""
        if "·" in breadcrumb:
            age = breadcrumb.split("·")[-1].strip()
        elif "ago" in breadcrumb.lower():
            age = breadcrumb
        posts.append({
            "title": title or f"@{handle}" or "TikTok",
            "url": url,
            "handle": handle,
            "views": views,
            "age": age,
            "snippet": desc,
            "is_official": official,
            "about_reason": "brand_in_title" if _brand_in_text(title, tokens) else "brand_in_description",
        })

    official_pool = [p for p in posts if p.get("is_official")]
    other_pool = [p for p in posts if not p.get("is_official")]
    official_views = sum(int(p.get("views") or 0) for p in official_pool)
    other_views = sum(int(p.get("views") or 0) for p in other_pool)

    def _top(items: list[dict], limit: int = 5) -> list[dict]:
        ranked = sorted(items, key=lambda x: int(x.get("views") or 0), reverse=True)
        return ranked[:limit]

    search_url = f"https://www.google.com/search?q={quote_plus(q)}&hl=en&gl={loc}"
    return {
        "ok": bool(fetched.get("ok") or posts),
        "company": name,
        "domain": domain,
        "query": q,
        "search_url": search_url,
        "official_channel": official_hint,
        "views_official": official_views,
        "views_unofficial": other_views,
        "about_count": len(posts),
        "page_count": len(fetched.get("items") or []),
        "top5": _top(posts),
        "top5_official": _top(official_pool),
        "top5_unofficial": _top(other_pool),
        "videos_about_product": posts,
        "counts": {
            "search_page": len(fetched.get("items") or []),
            "about_product": len(posts),
            "official": len(official_pool),
            "unofficial": len(other_pool),
            "skipped_no_views": skipped_no_views,
            "skipped_not_post": skipped_not_post,
            "skipped_brand": skipped_brand,
        },
        "usage": {
            "source": fetched.get("source") or "",
            "providers_tried": fetched.get("providers_tried") or [],
            "estimated_usd": float(fetched.get("cost_usd_total") or fetched.get("cost_usd") or 0),
            "scrapingbee_credits": fetched.get("credits_total") or fetched.get("credits") or 0,
            "dataforseo_tasks": 1 if "dataforseo" in (fetched.get("providers_tried") or []) else 0,
            "note": "Google first page. TinyFish first, then ScrapingBee, then DataForSEO. Views from SERP. TikTok URLs are not fetched.",
        },
        "elapsed_sec": round(time.time() - t0, 2),
        "error": fetched.get("error"),
    }
