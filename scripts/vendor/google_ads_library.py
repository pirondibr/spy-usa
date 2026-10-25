# -*- coding: utf-8 -*-
"""Google Ads Transparency — domain search, region=anywhere.

Same page the UI opens:
https://adstransparency.google.com/?region=anywhere&domain=<host>

US-only geo (2840) undercounts (Higgsfield: 72 vs 700).
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote, urlparse

import requests

SEARCH_CREATIVES_URL = (
    "https://adstransparency.google.com/anji/_/rpc/SearchService/SearchCreatives"
)
LIBRARY_BASE = "https://adstransparency.google.com/"
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
REQUEST_TIMEOUT = 60


def clean_domain(url_or_domain: str) -> str:
    raw = (url_or_domain or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).netloc or urlparse(raw).path
    host = host.lower().replace("www.", "").split("/")[0].split(":")[0]
    return host


def library_url(url_or_domain: str) -> str:
    domain = clean_domain(url_or_domain)
    if not domain:
        return ""
    return f"{LIBRARY_BASE}?region=anywhere&domain={quote(domain)}"


def _search_payload(domain: str) -> dict[str, Any]:
    return {
        "2": 40,
        "3": {"12": {"1": domain, "2": True}},
        "7": {"1": 1, "2": 0},
    }


def lookup_google_ads(url_or_domain: str) -> dict[str, Any]:
    """One SearchCreatives call for the domain, all regions."""
    domain = clean_domain(url_or_domain)
    url = library_url(domain)
    empty = {
        "google_ads": None,
        "google_ads_url": url,
        "domain": domain,
        "region": "anywhere",
        "spb_credits": 0,
    }
    if not domain:
        return empty
    key = (
        os.environ.get("SCRAPINGBEE_API_KEY", "").strip()
        or os.environ.get("SPY_SCRAPINGBEE_API_KEY", "").strip()
    )
    if not key:
        return empty
    params = {
        "url": SEARCH_CREATIVES_URL,
        "api_key": key,
        "authuser": "0",
    }
    try:
        r = requests.post(
            SCRAPINGBEE_URL,
            params=params,
            data={"f.req": json.dumps(_search_payload(domain), separators=(",", ":"))},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        js = r.json()
    except Exception as exc:
        print(f"[GOOGLE] {domain} rpc failed: {exc}", flush=True)
        return empty
    credits = 0
    for h in ("Spb-cost", "Spb-credits", "Spb-needed-credits"):
        raw = r.headers.get(h)
        if raw:
            try:
                credits = int(float(raw))
                break
            except ValueError:
                pass
    ads = js.get("5")
    try:
        ads_count = int(ads) if ads is not None else None
    except (TypeError, ValueError):
        ads_count = None
    print(
        f"[GOOGLE] {domain} anywhere -> {ads_count} ads  credits={credits}",
        flush=True,
    )
    return {
        "google_ads": ads_count,
        "google_ads_url": url,
        "domain": domain,
        "region": "anywhere",
        "spb_credits": credits,
    }
