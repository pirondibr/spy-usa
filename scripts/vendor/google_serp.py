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
    items = []
    for row in data.get("organic_results") or []:
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        items.append(_item(
            url,
            str(row.get("title") or ""),
            str(row.get("description") or row.get("snippet") or ""),
            int(row.get("position") or len(items) + 1),
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
    for task in js.get("tasks") or []:
        if task.get("status_code") not in (20000, None):
            err = task.get("status_message") or f"status {task.get('status_code')}"
        for res in task.get("result") or []:
            for it in res.get("items") or []:
                if (it.get("type") or "") != "organic":
                    continue
                url = str(it.get("url") or "").strip()
                if not url:
                    continue
                items.append(_item(
                    url,
                    str(it.get("title") or ""),
                    str(it.get("description") or ""),
                    int(it.get("rank_absolute") or it.get("rank_group") or len(items) + 1),
                    extra={
                        "breadcrumb": str(it.get("breadcrumb") or ""),
                        "is_video": bool(it.get("is_video")),
                    },
                ))
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
) -> dict[str, Any]:
    """Page-1 Google results. TinyFish first; rotate on miss or hourly limit."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "items": [], "error": "empty query", "source": ""}
    tried: list[str] = []
    last: dict[str, Any] = {"ok": False, "items": [], "error": "no provider", "source": ""}
    for name, fn in (
        ("tinyfish", lambda: _tinyfish(q, market=market, include_domains=include_domains)),
        ("scrapingbee", lambda: _scrapingbee(q, market=market)),
        ("dataforseo", lambda: _dataforseo(q, market=market)),
    ):
        last = fn()
        last["providers_tried"] = tried + [name]
        tried.append(name)
        if last.get("ok") and last.get("items"):
            last["query"] = q
            return last
    last["query"] = q
    last["providers_tried"] = tried
    return last
