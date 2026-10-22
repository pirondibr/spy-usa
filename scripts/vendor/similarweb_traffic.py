# -*- coding: utf-8 -*-
"""SimilarWeb traffic via Apify Actor (NRzGu7xR83tudau6J)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

ACTOR_ID = "NRzGu7xR83tudau6J"


def _api_token() -> str:
    return (
        os.environ.get("APIFY_TOKEN")
        or os.environ.get("APIFY_API_TOKEN")
        or os.environ.get("APIFY_API_KEY")
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
        return f"{int(float(n)):,}"
    except Exception:
        return str(n)


def _fmt_pct(share: Any, *, digits: int = 1) -> str:
    if not isinstance(share, (int, float)):
        try:
            share = float(share)
        except Exception:
            return "—"
    val = float(share)
    if abs(val) <= 1.5:
        val *= 100.0
    return f"{val:.{digits}f}%"


def _fmt_time_on_site(seconds: Any) -> str:
    try:
        s = float(seconds)
    except Exception:
        return "—"
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
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")[:10])
        return dt.strftime("%b %Y")
    except Exception:
        return raw[:10]


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def normalize_payload(item: dict[str, Any], *, domain: str = "") -> dict[str, Any]:
    """Flatten Apify SimilarWeb item into report-friendly fields."""
    analytics = item.get("analytics") if isinstance(item.get("analytics"), dict) else {}
    raw = analytics.get("rawResponse") if isinstance(analytics.get("rawResponse"), dict) else {}
    if not raw and isinstance(item.get("rawResponse"), dict):
        raw = item["rawResponse"]

    visits_map = (
        analytics.get("estimatedMonthlyVisits")
        or raw.get("EstimatedMonthlyVisits")
        or {}
    )
    if not isinstance(visits_map, dict):
        visits_map = {}

    monthly: list[dict[str, Any]] = []
    for date_key, visits in visits_map.items():
        n = _num(visits)
        monthly.append({
            "date": str(date_key),
            "label": _month_label(str(date_key)),
            "visits": int(n) if n is not None else None,
            "visits_fmt": _fmt_int(n) if n is not None else "—",
        })
    monthly.sort(key=lambda r: r["date"])
    latest = monthly[-1] if monthly else None

    eng = raw.get("Engagments") or raw.get("Engagements") or analytics.get("engagement") or {}
    if not isinstance(eng, dict):
        eng = {}
    bounce = _num(eng.get("BounceRate") or analytics.get("bounceRate"))
    ppv = _num(eng.get("PagePerVisit") or eng.get("PagesPerVisit") or analytics.get("pagesPerVisit"))
    tos = _num(eng.get("TimeOnSite") or analytics.get("timeOnSite"))
    eng_visits = _num(eng.get("Visits"))

    sources_raw = analytics.get("trafficSources") or raw.get("TrafficSources") or {}
    if not isinstance(sources_raw, dict):
        sources_raw = {}
    # Map Apify keys → report labels (compatible with old RapidAPI names)
    source_map = [
        ("Direct", "Direct"),
        ("SearchOrganic", "Search"),
        ("SearchPaid", "Paid Search"),
        ("SocialOrganic", "Social"),
        ("SocialPaid", "Social Paid"),
        ("Referrals", "Referrals"),
        ("Mail", "Mail"),
        ("DisplayAds", "Display Ads"),
        ("GenAi", "Gen AI"),
        ("Affiliate", "Affiliate"),
    ]
    sources: list[dict[str, Any]] = []
    seen_src: set[str] = set()
    for key, label in source_map:
        if key not in sources_raw:
            continue
        val = _num(sources_raw.get(key))
        sources.append({
            "name": label,
            "share": val,
            "share_fmt": _fmt_pct(val) if val is not None else "—",
        })
        seen_src.add(key)
    for key, val in sources_raw.items():
        if key in seen_src:
            continue
        n = _num(val)
        sources.append({
            "name": str(key),
            "share": n,
            "share_fmt": _fmt_pct(n) if n is not None else "—",
        })

    countries: list[dict[str, Any]] = []
    top_countries = raw.get("TopCountryShares") or []
    if isinstance(top_countries, list):
        for c in top_countries:
            if not isinstance(c, dict):
                continue
            code = str(c.get("CountryCode") or c.get("Code") or "").upper()
            share = _num(c.get("Value") or c.get("share"))
            if not code:
                continue
            countries.append({
                "code": code,
                "share": share,
                "share_fmt": _fmt_pct(share) if share is not None else "—",
            })
    countries.sort(key=lambda c: -(c["share"] or 0))

    latest_visits = latest.get("visits") if latest else None
    if latest_visits is None and eng_visits is not None:
        latest_visits = int(eng_visits)

    snap = ""
    if latest:
        snap = str(latest.get("date") or "")[:10]
    elif eng.get("Year") and eng.get("Month"):
        try:
            snap = f"{int(eng['Year']):04d}-{int(eng['Month']):02d}-01"
        except Exception:
            snap = ""

    dom = normalize_domain(
        domain
        or analytics.get("siteName")
        or item.get("target")
        or raw.get("SiteName")
        or ""
    )

    global_rank = None
    gr = raw.get("GlobalRank") or {}
    if isinstance(gr, dict):
        global_rank = gr.get("Rank")
    elif isinstance(gr, (int, float)):
        global_rank = gr

    return {
        "domain": dom,
        "snapshot_date": snap,
        "snapshot_label": _month_label(snap) if snap else (latest.get("label") if latest else "—"),
        "latest_visits": latest_visits,
        "traffic": int(latest_visits) if isinstance(latest_visits, (int, float)) else 0,
        "traffic_fmt": _fmt_int(latest_visits) if isinstance(latest_visits, (int, float)) else "—",
        "bounce_rate": bounce,
        "bounce_fmt": _fmt_pct(bounce) if bounce is not None else "—",
        "pages_per_visit": ppv,
        "pages_fmt": f"{float(ppv):.2f}" if ppv is not None else "—",
        "time_on_site": tos,
        "time_fmt": _fmt_time_on_site(tos),
        "is_data_from_ga": bool(raw.get("IsDataFromGa")),
        "global_rank": global_rank,
        "category": analytics.get("category") or (raw.get("Category") or ""),
        "visits_monthly": monthly,
        "sources": sources,
        "countries": countries,
        "raw": item,
    }


def _dataset_id(run: Any) -> str:
    if isinstance(run, dict):
        return str(run.get("defaultDatasetId") or run.get("default_dataset_id") or "")
    return str(
        getattr(run, "default_dataset_id", None)
        or getattr(run, "defaultDatasetId", None)
        or ""
    )


def fetch_traffic_batch(domains: list[str], *, waiting: int = 2000) -> dict[str, dict[str, Any]]:
    """Run Apify Actor once for many domains. Returns domain → normalized payload."""
    token = _api_token()
    if not token:
        raise RuntimeError("Missing APIFY_TOKEN (Apify API token) for SimilarWeb")

    clean: list[str] = []
    seen: set[str] = set()
    for d in domains:
        dom = normalize_domain(d)
        if not dom or dom in seen:
            continue
        seen.add(dom)
        clean.append(dom)
    if not clean:
        return {}

    try:
        from apify_client import ApifyClient
    except ImportError as e:
        raise RuntimeError("apify-client not installed — pip install apify-client") from e

    client = ApifyClient(token)
    run_input = {
        "startUrls": clean,
        "waiting": waiting,
        "proxy": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        },
    }
    actor = client.actor(ACTOR_ID)
    try:
        run = actor.call(
            run_input=run_input,
            run_timeout=timedelta(seconds=120),
            wait_duration=timedelta(seconds=150),
        )
    except TypeError:
        try:
            run = actor.call(
                run_input=run_input,
                timeout_secs=120,
                wait_for_finish=150,
            )
        except TypeError:
            run = actor.call(run_input=run_input, timeout_secs=120)
    if run is None:
        raise RuntimeError("Apify SimilarWeb timed out (150s) without a run result")
    status = ""
    if isinstance(run, dict):
        status = str(run.get("status") or "")
    else:
        status = str(getattr(run, "status", "") or "")
    if status.upper() not in ("", "SUCCEEDED", "READY"):
        raise RuntimeError(f"Apify SimilarWeb status={status} (timeout 150s)")
    ds_id = _dataset_id(run)
    if not ds_id:
        raise RuntimeError("Apify run finished without defaultDatasetId")

    by_domain: dict[str, dict[str, Any]] = {}
    for item in client.dataset(ds_id).iterate_items():
        if not isinstance(item, dict):
            continue
        # Skip error-only rows
        if item.get("error") and not (item.get("analytics") or item.get("rawResponse")):
            continue
        target = normalize_domain(
            item.get("target")
            or (item.get("analytics") or {}).get("siteName")
            or ""
        )
        if not target:
            continue
        try:
            by_domain[target] = normalize_payload(item, domain=target)
        except Exception:
            continue
    return by_domain


def fetch_traffic(domain: str, *, detailed: bool = True, timeout: int = 45) -> dict[str, Any]:
    """Fetch one domain (wrapper for compatibility). Returns raw Apify item-shaped dict."""
    batch = fetch_traffic_batch([domain])
    dom = normalize_domain(domain)
    if dom not in batch:
        raise RuntimeError(f"No SimilarWeb data from Apify for {dom}")
    # Return stored raw for callers that expect a dict; prefer full item
    return batch[dom].get("raw") or batch[dom]


def traffic_reports_batch(
    entities: list[dict[str, Any]],
    *,
    pause_sec: float = 0.0,
) -> list[dict[str, Any]]:
    """Fetch + normalize SimilarWeb for each entity (one Apify Actor run)."""
    domains = [
        normalize_domain(ent.get("domain") or ent.get("url") or "")
        for ent in entities
    ]
    try:
        by_domain = fetch_traffic_batch([d for d in domains if d])
        batch_error = None
    except Exception as e:
        by_domain = {}
        batch_error = str(e)

    rows: list[dict[str, Any]] = []
    for ent in entities:
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
        norm = by_domain.get(dom)
        if not norm:
            rows.append({
                **base,
                "error": batch_error or "No data from Apify",
                "traffic": 0,
                "traffic_fmt": "—",
                "visits_monthly": [],
                "sources": [],
                "countries": [],
            })
            continue
        row = {**base, **norm, "error": None}
        row.pop("raw", None)
        rows.append(row)

    rows.sort(key=lambda r: (-(r.get("traffic") or 0), 0 if r.get("is_client") else 1))
    return rows
