# -*- coding: utf-8 -*-
"""Google SERP with TinyFish → ScrapingBee → DataForSEO rotation.

TinyFish Search is free within 30/min and 500/hour. Paid providers only run
when TinyFish is missing, empty, or rate-limited.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional

import requests

TINYFISH_SEARCH = "https://api.search.tinyfish.ai"
SCRAPINGBEE_GOOGLE = "https://app.scrapingbee.com/api/v1/google"
DATAFORSEO_SERP_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"

_SB_CREDIT_USD = float(os.environ.get("SPY_COST_SB_CREDIT", "0.0002") or 0.0002)
_DFS_LIVE_USD = float(os.environ.get("SPY_COST_DFS_SERP", "0.002") or 0.002)
_TF_COOLDOWN_SEC = 3600

_OPERATOR_RE = re.compile(
    r"\b(?:site|inurl|intitle|intext|filetype|link|define|id|info|inanchor|"
    r"allinurl|allintitle|allintext|allinanchor):",
    flags=re.I,
)

_tf_skip_until = 0.0
_tf_skip_reason = ""


def _tf_key() -> str:
    return (os.environ.get("TINYFISH_API_KEY") or "").strip()


def _sb_key() -> str:
    return (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip()


def _dfs_auth() -> tuple[str, str]:
    user = (
        os.environ.get("DATAFORSEO_USER")
        or os.environ.get("DATAFORSEO_LOGIN")
        or ""
    ).strip()
    pw = (
        os.environ.get("DATAFORSEO_PASS")
        or os.environ.get("DATAFORSEO_PASSWORD")
        or ""
    ).strip()
    return user, pw


def has_google_serp() -> bool:
    user, pw = _dfs_auth()
    return bool(_tf_key() or _sb_key() or (user and pw))


def _is_rate_limited(status: int, body: str) -> bool:
    if status == 429:
        return True
    low = (body or "").lower()
    return any(
        needle in low
        for needle in (
            "rate limit",
            "too many requests",
            "quota",
            "per hour",
            "per minute",
        )
    )


def _location_code(market: str) -> int:
    return 2076 if (market or "us").lower().startswith("br") else 2840


def _has_operator(query: str) -> bool:
    return bool(_OPERATOR_RE.search(query or ""))


def _dfs_safe_query(query: str) -> str:
    """Drop site: operators so DataForSEO does not apply the 5x surcharge."""
    q = (query or "").strip()
    m = re.match(r"site:(\S+)\s+(.*)$", q, flags=re.I)
    if not m:
        return q
    host = m.group(1).lower()
    rest = m.group(2).strip()
    if "linkedin.com" in host:
        return f"{rest} linkedin".strip()
    if "tiktok.com" in host:
        return f"{rest} tiktok".strip()
    if "twitter.com" in host or host.startswith("x.com"):
        return f"{rest} twitter".strip()
    return rest or q


def _item(url: str, title: str, snippet: str, position: int, extra: Optional[dict] = None) -> dict[str, Any]:
    row = {
        "url": url,
        "title": title,
        "snippet": snippet,
        "position": position,
    }
    if extra:
        row.update(extra)
    return row


def _tinyfish(query: str, *, market: str, include_domains: Optional[str]) -> dict[str, Any]:
    global _tf_skip_until, _tf_skip_reason
    key = _tf_key()
    if not key:
        return {"ok": False, "items": [], "error": "TINYFISH_API_KEY missing", "source": "tinyfish"}
    if time.time() < _tf_skip_until:
        return {
            "ok": False,
            "items": [],
            "error": _tf_skip_reason or "TinyFish hourly limit, rotating",
            "rate_limited": True,
            "source": "tinyfish",
        }
    loc = "US" if not (market or "us").lower().startswith("br") else "BR"
    params: dict[str, Any] = {
        "query": query,
        "location": loc,
        "language": "en" if loc == "US" else "pt",
        "page": 0,
    }
    if include_domains:
        params["include_domains"] = include_domains
    t0 = time.time()
    try:
        r = requests.get(
            TINYFISH_SEARCH,
            params=params,
            headers={"X-API-Key": key},
            timeout=45,
        )
        body = r.text[:400] if r.text else ""
        if _is_rate_limited(r.status_code, body):
            _tf_skip_until = time.time() + _TF_COOLDOWN_SEC
            _tf_skip_reason = f"TinyFish {r.status_code} rate limit"
            return {
                "ok": False,
                "items": [],
                "error": _tf_skip_reason,
                "rate_limited": True,
                "source": "tinyfish",
                "elapsed_sec": round(time.time() - t0, 2),
            }
        r.raise_for_status()
        data = r.json() if r.content else {}
    except Exception as e:
        return {
            "ok": False,
            "items": [],
            "error": str(e)[:200],
            "source": "tinyfish",
            "elapsed_sec": round(time.time() - t0, 2),
        }
    items = []
    for i, row in enumerate(data.get("results") or [], 1):
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        items.append(_item(
            url,
            str(row.get("title") or ""),
            str(row.get("snippet") or row.get("description") or ""),
            int(row.get("position") or i),
        ))
    return {
        "ok": bool(items),
        "items": items,
        "source": "tinyfish",
        "cost_usd": 0.0,
        "elapsed_sec": round(time.time() - t0, 2),
        "error": None if items else "TinyFish returned no results",
    }


def _scrapingbee(query: str, *, market: str) -> dict[str, Any]:
    key = _sb_key()
    if not key:
        return {"ok": False, "items": [], "error": "SCRAPINGBEE_API_KEY missing", "source": "scrapingbee"}
    loc = "us" if not (market or "us").lower().startswith("br") else "br"
    t0 = time.time()
    try:
        r = requests.get(
            SCRAPINGBEE_GOOGLE,
            params={
                "api_key": key,
                "search": query,
                "country_code": loc,
                "language": "en" if loc == "us" else "pt",
                "light_request": "true",
            },
            timeout=90,
        )
    except requests.RequestException as e:
        return {
            "ok": False,
            "items": [],
            "error": str(e)[:200],
            "source": "scrapingbee",
            "elapsed_sec": round(time.time() - t0, 2),
        }
    credits = 10
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
            "items": [],
            "error": f"HTTP {r.status_code}",
            "credits": credits,
            "source": "scrapingbee",
            "elapsed_sec": round(time.time() - t0, 2),
        }
    data = r.json() if r.content else {}
    rows = list(data.get("organic_results") or [])
    for key in ("video_results", "videos", "inline_videos"):
        extra = data.get(key)
        if isinstance(extra, list):
            rows.extend(extra)
        elif isinstance(extra, dict):
            rows.extend(extra.get("items") or extra.get("results") or [])
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("link") or "").strip()
        if not url:
            continue
        rich = row.get("rich_snippet") or row.get("rich_snippets") or {}
        breadcrumb = " · ".join(
            str(x) for x in (
                row.get("displayed_link"),
                row.get("displayed_url"),
                row.get("date"),
                rich if not isinstance(rich, (dict, list)) else "",
            )
            if x
        )
        if isinstance(rich, dict):
            breadcrumb = " · ".join(
                x for x in (breadcrumb, str(rich.get("top") or ""), str(rich.get("bottom") or "")) if x
            )
        items.append(_item(
            url,
            str(row.get("title") or ""),
            str(row.get("description") or row.get("snippet") or ""),
            int(row.get("position") or len(items) + 1),
            extra={
                "description": str(row.get("description") or row.get("snippet") or ""),
                "breadcrumb": breadcrumb,
                "is_video": "tiktok.com" in url.lower() or "video" in str(row.get("type") or "").lower(),
            },
        ))
    return {
        "ok": bool(items),
        "items": items,
        "source": "scrapingbee",
        "credits": credits,
        "cost_usd": round(credits * _SB_CREDIT_USD, 6),
        "elapsed_sec": round(time.time() - t0, 2),
        "error": None if items else "ScrapingBee returned no organic results",
    }


def _dataforseo(query: str, *, market: str) -> dict[str, Any]:
    user, pw = _dfs_auth()
    if not user or not pw:
        return {"ok": False, "items": [], "error": "DATAFORSEO credentials missing", "source": "dataforseo"}
    safe_q = _dfs_safe_query(query)
    t0 = time.time()
    try:
        r = requests.post(
            DATAFORSEO_SERP_URL,
            auth=(user, pw),
            json=[{
                "keyword": safe_q,
                "location_code": _location_code(market),
                "language_code": "en" if not (market or "").lower().startswith("br") else "pt",
                "device": "desktop",
                "depth": 10,
            }],
            timeout=120,
        )
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        return {
            "ok": False,
            "items": [],
            "error": str(e)[:200],
            "source": "dataforseo",
            "elapsed_sec": round(time.time() - t0, 2),
        }
    items: list[dict[str, Any]] = []
    err = None
    seen: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                _walk(child)
            return
        if not isinstance(node, dict):
            return
        url = str(node.get("url") or "").strip()
        kind = str(node.get("type") or "")
        if url and url not in seen:
            tiktok = "tiktok.com" in url.lower()
            video = "video" in kind.lower() or bool(node.get("is_video"))
            if kind in ("organic", "video", "organic_video", "video_element") or tiktok:
                seen.add(url)
                items.append(_item(
                    url,
                    str(node.get("title") or ""),
                    str(node.get("description") or node.get("snippet") or ""),
                    int(node.get("rank_absolute") or node.get("rank_group") or len(items) + 1),
                    extra={
                        "description": str(node.get("description") or node.get("snippet") or ""),
                        "breadcrumb": str(node.get("breadcrumb") or ""),
                        "extended_snippet": str(node.get("extended_snippet") or ""),
                        "pre_snippet": str(node.get("pre_snippet") or ""),
                        "highlighted": str(node.get("highlighted") or ""),
                        "is_video": video or tiktok,
                    },
                ))
        for key in ("items", "videos", "results"):
            _walk(node.get(key))

    for task in js.get("tasks") or []:
        if task.get("status_code") not in (20000, None):
            err = task.get("status_message") or f"status {task.get('status_code')}"
        for res in task.get("result") or []:
            _walk(res.get("items") or [])
    cost = _DFS_LIVE_USD
    if _has_operator(safe_q):
        cost *= 5
    return {
        "ok": bool(items),
        "items": items,
        "source": "dataforseo",
        "cost_usd": round(cost, 6),
        "query_used": safe_q,
        "elapsed_sec": round(time.time() - t0, 2),
        "error": err if not items else None,
    }


def google_serp(
    query: str,
    *,
    market: str = "us",
    include_domains: Optional[str] = None,
    accept: Optional[Any] = None,
) -> dict[str, Any]:
    """Page-1 Google results. TinyFish first; rotate on miss, hourly limit, or accept()."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "items": [], "error": "empty query", "source": ""}
    tried: list[str] = []
    last: dict[str, Any] = {"ok": False, "items": [], "error": "no provider", "source": ""}
    fallback: Optional[dict[str, Any]] = None
    cost_acc = 0.0
    credits_acc = 0
    for name, fn in (
        ("tinyfish", lambda: _tinyfish(q, market=market, include_domains=include_domains)),
        ("scrapingbee", lambda: _scrapingbee(q, market=market)),
        ("dataforseo", lambda: _dataforseo(q, market=market)),
    ):
        last = fn()
        tried.append(name)
        cost_acc += float(last.get("cost_usd") or 0)
        credits_acc += int(last.get("credits") or 0)
        last["providers_tried"] = list(tried)
        last["query"] = q
        last["cost_usd_total"] = round(cost_acc, 6)
        if credits_acc:
            last["credits_total"] = credits_acc
        items = last.get("items") or []
        if items and fallback is None:
            fallback = dict(last)
        usable = bool(accept(items)) if callable(accept) else bool(items)
        if last.get("ok") and usable:
            return last
    if fallback is not None:
        fallback["providers_tried"] = list(tried)
        fallback["query"] = q
        fallback["cost_usd_total"] = round(cost_acc, 6)
        if credits_acc:
            fallback["credits_total"] = credits_acc
        fallback["rotated"] = True
        return fallback
    last["query"] = q
    last["providers_tried"] = tried
    last["cost_usd_total"] = round(cost_acc, 6)
    return last
