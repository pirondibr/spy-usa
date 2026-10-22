# -*- coding: utf-8 -*-
"""Semrush organic top keywords (organic.Positions), same RPC as the Positions report."""

from __future__ import annotations

import os
import random
from string import ascii_lowercase, digits
from typing import Any
from urllib.parse import urlparse

import requests

RPC_URL = "https://www.semrush.com/dpa/rpc"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Origin": "https://www.semrush.com",
    "Referer": "https://www.semrush.com/analytics/organic/positions/",
}


def _clean_domain(value: str) -> str:
    raw = (value or "").strip()
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host.strip(".")


def _request_id() -> str:
    k = "".join(random.choices(ascii_lowercase + digits, k=33))
    return f"{k[:8]}-{k[8:12]}-{k[12:16]}-{k[16:]}"


def _item(call_id: int, method: str, report: str, args: dict,
          user_id: Any, api_key: str, request_id: str) -> dict:
    params: dict[str, Any] = {
        "request_id": request_id,
        "report": report,
        "args": args,
        "apiKey": api_key,
    }
    if user_id not in (None, ""):
        try:
            params["userId"] = int(user_id)
        except (TypeError, ValueError):
            params["userId"] = user_id
    return {"id": call_id, "jsonrpc": "2.0", "method": method, "params": params}


def _post(payload: Any, timeout: int) -> list:
    r = requests.post(RPC_URL, json=payload, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else [data]


def _call(item: dict, base_args: dict, user_id: Any, api_key: str,
          request_id: str, timeout: int) -> dict:
    data = _post(item, timeout)
    part = next((p for p in data if p.get("id") == item["id"]), data[0] if data else {})
    if part.get("error", {}).get("code") == -32600:
        companion = _item(
            7, "organic.MonthlyTrend", "organic.overview",
            {**base_args, "filter": {}}, user_id, api_key, request_id,
        )
        data = _post([companion, item], timeout)
        part = next((p for p in data if p.get("id") == item["id"]), {})
    return part


def _normalize(rows: list) -> list[dict[str, Any]]:
    out = []
    for x in rows or []:
        if not isinstance(x, dict):
            continue
        out.append({
            "phrase": x.get("phrase") or "",
            "position": x.get("position"),
            "volume": x.get("volume"),
            "traffic": x.get("traffic"),
            "traffic_pct": x.get("trafficPercent"),
            "url": x.get("url") or "",
            "serp_feature": bool(x.get("positionIsSERPFeature")),
        })
    return out


def fetch_top_keywords(
    domain: str,
    *,
    db: str = "us",
    limit: int = 10,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    """Top N organic keywords by traffic %, same order as Semrush Positions."""
    api_key = os.environ.get("SEMRUSH_API_KEY", "").strip()
    user_id = os.environ.get("SEMRUSH_USER_ID", "").strip()
    if not api_key:
        raise RuntimeError("SEMRUSH_API_KEY ausente")
    clean = _clean_domain(domain)
    if not clean:
        raise RuntimeError("Domain is required")
    rid = _request_id()
    base = {"database": db, "searchItem": clean, "searchType": "domain"}
    args = {
        **base,
        "dateType": "daily",
        "positionsType": "all",
        "filter": {},
        "display": {
            "order": {"field": "trafficPercent", "direction": "desc"},
            "page": 1,
            "pageSize": int(limit),
        },
    }
    part = _call(
        _item(9, "organic.Positions", "organic.positions", args, user_id, api_key, rid),
        base, user_id, api_key, rid, timeout,
    )
    if not part.get("error"):
        return _normalize(part.get("result") or [])[:limit]
    err1 = part["error"]
    if err1.get("code") == -32107:
        raise RuntimeError(f"Semrush report limit: {err1}")
    args2 = {
        **base,
        "dateType": "daily",
        "positionsType": "all",
        "display": {"order": {"field": "trafficPercent", "direction": "desc"}},
    }
    part = _call(
        _item(11, "organic.PositionsOverview", "organic.overview", args2,
              user_id, api_key, rid),
        base, user_id, api_key, rid, timeout,
    )
    if part.get("error"):
        raise RuntimeError(f"Semrush Positions={err1} / Overview={part['error']}")
    return _normalize(part.get("result") or [])[:limit]
