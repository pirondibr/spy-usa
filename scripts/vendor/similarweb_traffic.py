# -*- coding: utf-8 -*-
"""SimilarWeb traffic via RapidAPI (similarweb-insights)."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests

API_URL = "https://similarweb-insights.p.rapidapi.com/traffic"
API_HOST = "similarweb-insights.p.rapidapi.com"


def _api_key() -> str:
    return (
        os.environ.get("SIMILARWEB_RAPIDAPI_KEY")
        or os.environ.get("RAPIDAPI_KEY")
        or os.environ.get("X_RAPIDAPI_KEY")
        or ""
    ).strip()


def normalize_domain(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = urlparse(raw).hostname or ""
    except Exception:
        host = raw
    host = host.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _fmt_int(n: Any) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def _fmt_pct(share: Any, *, digits: int = 1) -> str:
    if not isinstance(share, (int, float)):
        return "—"
    # API returns fractions (0.47) or already percent-like (>1)
    val = float(share)
    if abs(val) <= 1.5:
        val *= 100.0
    return f"{val:.{digits}f}%"


def _fmt_time_on_site(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)):
        return "—"
    s = float(seconds)
    if s < 60:
        return f"{s:.1f}s"
    m = int(s // 60)
    rem = s - m * 60
    return f"{m}m {rem:.0f}s"


def _month_label(iso_date: str) -> str:
    raw = (iso_date or "").strip()
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%b %Y")
    except Exception:
        return raw[:10]


def fetch_traffic(domain: str, *, detailed: bool = True, timeout: int = 45) -> dict[str, Any]:
    """GET /traffic for one domain. Raises on HTTP/API errors."""
    key = _api_key()
    if not key:
        raise RuntimeError(
            "Missing SIMILARWEB_RAPIDAPI_KEY (or RAPIDAPI_KEY) for SimilarWeb RapidAPI"
        )
    dom = normalize_domain(domain)
    if not dom:
        raise ValueError("Empty domain")

    headers = {
        "x-rapidapi-key": key,
        "x-rapidapi-host": API_HOST,
    }
    params = {"domain": dom, "detailed": "true" if detailed else "false"}
    resp = requests.get(API_URL, headers=headers, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"SimilarWeb HTTP {resp.status_code}: {resp.text[:240]}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected SimilarWeb payload type: {type(data)}")
    return data


def normalize_payload(raw: dict[str, Any], *, domain: str = "") -> dict[str, Any]:
    """Flatten RapidAPI traffic response into report-friendly fields."""
    visits_map = raw.get("Visits") or {}
    if not isinstance(visits_map, dict):
        visits_map = {}

    monthly: list[dict[str, Any]] = []
    for date_key, visits in visits_map.items():
        monthly.append({
            "date": str(date_key),
            "label": _month_label(str(date_key)),
            "visits": visits if isinstance(visits, (int, float)) else None,
            "visits_fmt": _fmt_int(visits) if isinstance(visits, (int, float)) else "—",
        })
    monthly.sort(key=lambda r: r["date"])

    latest = monthly[-1] if monthly else None
    # Prefer SnapshotDate month if present in series
    snap = str(raw.get("SnapshotDate") or "")
    if snap and monthly:
        snap_day = snap[:10]
        match = next((m for m in monthly if str(m["date"])[:10] == snap_day), None)
        if match:
            latest = match

    eng = raw.get("Engagement") or {}
    if not isinstance(eng, dict):
        eng = {}
    bounce = eng.get("BounceRate")
    ppv = eng.get("PagesPerVisit")
    tos = eng.get("TimeOnSite")

    sources_raw = raw.get("Sources") or {}
    if not isinstance(sources_raw, dict):
        sources_raw = {}
    source_order = ("Direct", "Search", "Social", "Referrals", "Paid Referrals", "Mail")
    sources: list[dict[str, Any]] = []
    for name in source_order:
        if name not in sources_raw:
            continue
        val = sources_raw.get(name)
        sources.append({
            "name": name,
            "share": val if isinstance(val, (int, float)) else None,
            "share_fmt": _fmt_pct(val) if isinstance(val, (int, float)) else "—",
        })
    for name, val in sources_raw.items():
        if name in source_order:
            continue
        sources.append({
            "name": str(name),
            "share": val if isinstance(val, (int, float)) else None,
            "share_fmt": _fmt_pct(val) if isinstance(val, (int, float)) else "—",
        })

    countries_raw = raw.get("TopCountryShares") or {}
    if not isinstance(countries_raw, dict):
        countries_raw = {}
    countries: list[dict[str, Any]] = []
    for code, share in countries_raw.items():
        countries.append({
            "code": str(code).upper(),
            "share": share if isinstance(share, (int, float)) else None,
            "share_fmt": _fmt_pct(share) if isinstance(share, (int, float)) else "—",
        })
    countries.sort(key=lambda c: -(c["share"] or 0))

    latest_visits = latest.get("visits") if latest else None
    return {
        "domain": normalize_domain(domain) or domain,
        "snapshot_date": snap[:10] if snap else (latest.get("date", "")[:10] if latest else ""),
        "snapshot_label": _month_label(snap) if snap else (latest.get("label") if latest else "—"),
        "latest_visits": latest_visits,
        "traffic": latest_visits if isinstance(latest_visits, (int, float)) else 0,
        "traffic_fmt": _fmt_int(latest_visits) if isinstance(latest_visits, (int, float)) else "—",
        "bounce_rate": bounce,
        "bounce_fmt": _fmt_pct(bounce) if isinstance(bounce, (int, float)) else "—",
        "pages_per_visit": ppv,
        "pages_fmt": f"{float(ppv):.2f}" if isinstance(ppv, (int, float)) else "—",
        "time_on_site": tos,
        "time_fmt": _fmt_time_on_site(tos),
        "is_data_from_ga": bool(raw.get("IsDataFromGa")),
        "visits_monthly": monthly,
        "sources": sources,
        "countries": countries,
        "raw": raw,
    }


def traffic_reports_batch(
    entities: list[dict[str, Any]],
    *,
    pause_sec: float = 0.35,
) -> list[dict[str, Any]]:
    """Fetch + normalize SimilarWeb for each entity (client / competitors)."""
    rows: list[dict[str, Any]] = []
    for i, ent in enumerate(entities):
        dom = normalize_domain(ent.get("domain") or ent.get("url") or "")
        name = ent.get("name") or ent.get("company") or dom
        base = {
            "name": name,
            "domain": dom,
            "url": ent.get("url") or (f"https://{dom}/" if dom else ""),
            "is_client": bool(ent.get("is_client")),
            "similaridade": ent.get("similaridade") or ("Cliente" if ent.get("is_client") else "—"),
        }
        if not dom:
            rows.append({**base, "error": "missing domain", "traffic": 0, "traffic_fmt": "—"})
            continue
        try:
            raw = fetch_traffic(dom)
            norm = normalize_payload(raw, domain=dom)
            rows.append({**base, **norm, "error": None})
        except Exception as e:
            rows.append({
                **base,
                "error": str(e),
                "traffic": 0,
                "traffic_fmt": "—",
                "visits_monthly": [],
                "sources": [],
                "countries": [],
            })
        if i + 1 < len(entities) and pause_sec > 0:
            time.sleep(pause_sec)

    rows.sort(key=lambda r: (-(r.get("traffic") or 0), 0 if r.get("is_client") else 1))
    return rows
