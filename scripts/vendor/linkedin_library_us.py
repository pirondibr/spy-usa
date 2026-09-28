# -*- coding: utf-8 -*-
"""LinkedIn Ad Library (US) via ScrapingBee.

Fluxo Spy USA:
  1. Busca pelo nome da empresa (keyword / accountOwner)
  2. Abre o 1o anuncio com detail_id
  3. Le o pagante (Pago por / Paid for by)
  4. Pesquisa ?payer=<pagante>&countries=US e retorna o total de ads
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

try:
    from market import SCRAPINGBEE_COUNTRY, META_COUNTRY, ACCEPT_LANGUAGE
except ImportError:
    SCRAPINGBEE_COUNTRY = "us"
    META_COUNTRY = "US"
    ACCEPT_LANGUAGE = "en-US,en;q=0.9"

SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "").strip()
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
AD_LIBRARY_BASE = "https://www.linkedin.com/ad-library/search"
LI_COUNTRY = (os.environ.get("SPY_LINKEDIN_COUNTRY") or META_COUNTRY or "US").strip().upper()


def keyword_url(keyword: str) -> str:
    return f"{AD_LIBRARY_BASE}?keyword={quote_plus(keyword.strip())}&countries={LI_COUNTRY}"


def account_owner_url(name: str) -> str:
    return f"{AD_LIBRARY_BASE}?accountOwner={quote_plus(name.strip())}&countries={LI_COUNTRY}"


def payer_url(name: str) -> str:
    return f"{AD_LIBRARY_BASE}?payer={quote_plus(name.strip())}&countries={LI_COUNTRY}"


def parse_payer_name(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"^(pago por|paid for by)\s+", "", t, flags=re.IGNORECASE).strip()
    return t


def parse_result_count(text: str) -> Optional[int]:
    if not text:
        return None
    t = (text or "").replace("\xa0", " ").replace("&nbsp;", " ")
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if re.search(r"(nenhum resultado|no results|aucun r[eé]sultat)", t, flags=re.IGNORECASE):
        return 0
    m = re.search(
        r"([\d.,\s]+)\s+(?:an[uú]ncios?|ads?|publicit[eé]s?)\s+(?:correspond|match)",
        t,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    raw = re.sub(r"[^\d]", "", m.group(1))
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _fetch_html(url: str, *, wait_ms: int = 5000) -> tuple[str, int]:
    if not SCRAPINGBEE_API_KEY:
        raise RuntimeError("SCRAPINGBEE_API_KEY ausente")
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": url,
        "render_js": "true",
        "premium_proxy": "true",
        "country_code": SCRAPINGBEE_COUNTRY,
        "wait": str(wait_ms),
        "block_resources": "false",
    }
    # Prefer US English LinkedIn UI when possible
    headers = {"Spb-Accept-Language": ACCEPT_LANGUAGE}
    r = requests.get(SCRAPINGBEE_URL, params=params, headers=headers, timeout=120)
    credits = int(r.headers.get("Spb-cost") or 0)
    if r.status_code == 401:
        raise RuntimeError("ScrapingBee sem creditos (401) no LinkedIn")
    if r.status_code != 200:
        raise RuntimeError(f"ScrapingBee LinkedIn HTTP {r.status_code}")
    return r.text or "", credits


def extract_ads_from_html(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    ads: list[dict[str, str]] = []
    seen: set[str] = set()

    cards = soup.select(".base-ad-preview-card")
    if not cards:
        # Fallback: any detail links on the page
        for a in soup.select('a[href*="/ad-library/detail/"]'):
            href = a.get("href") or ""
            m = re.search(r"/ad-library/detail/(\d+)", href)
            if not m:
                continue
            detail_id = m.group(1)
            if detail_id in seen:
                continue
            seen.add(detail_id)
            company = (a.get_text(" ", strip=True) or "").strip()
            ads.append({
                "company": company,
                "text": "",
                "detail_id": detail_id,
                "detail_url": f"https://www.linkedin.com/ad-library/detail/{detail_id}",
            })
        return ads

    for card in cards:
        name_el = card.select_one(".font-bold")
        company = (name_el.get_text(" ", strip=True) if name_el else "").strip()
        if not company:
            aria = (card.get("aria-label") or "").strip()
            company = aria.split(",")[0].strip() if aria else ""
        text_el = card.select_one(".commentary__content")
        text = (text_el.get_text(" ", strip=True) if text_el else "").strip()
        link = card.select_one('a[href*="/ad-library/detail/"]')
        href = (link.get("href") if link else "") or ""
        m = re.search(r"/ad-library/detail/(\d+)", href)
        detail_id = m.group(1) if m else ""
        key = detail_id or f"{company}|{text[:60]}"
        if not detail_id or key in seen:
            continue
        seen.add(key)
        ads.append({
            "company": company,
            "text": text,
            "detail_id": detail_id,
            "detail_url": f"https://www.linkedin.com/ad-library/detail/{detail_id}",
        })
    return ads


def extract_payer_from_detail_html(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    payer_el = soup.select_one(".about-ad__paying-entity")
    payer_raw = (payer_el.get_text(" ", strip=True) if payer_el else "").strip()
    advertiser_el = soup.select_one(
        '[data-tracking-control-name="ad_library_about_ad_advertiser"]'
    )
    advertiser = (advertiser_el.get_text(" ", strip=True) if advertiser_el else "").strip()
    if not advertiser:
        # Fallback common patterns
        for sel in ("h1", ".ad-detail-advertiser", ".base-ad-preview-card .font-bold"):
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                advertiser = el.get_text(" ", strip=True)
                break
    text_el = soup.select_one(".commentary__content")
    text = (text_el.get_text(" ", strip=True) if text_el else "").strip()
    # Regex fallback for paid-for line
    if not payer_raw:
        m = re.search(
            r"(?:Pago por|Paid for by)\s*[:\-]?\s*([^\n<]{2,120})",
            html or "",
            flags=re.IGNORECASE,
        )
        if m:
            payer_raw = m.group(0).strip()
    return {
        "payer": parse_payer_name(payer_raw),
        "payer_raw": payer_raw,
        "advertiser": advertiser,
        "text": text,
    }


def extract_h1_count(html: str) -> Optional[int]:
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    if h1:
        n = parse_result_count(h1.get_text(" ", strip=True))
        if n is not None:
            return n
    return parse_result_count(html or "")


def _names_match(a: str, b: str) -> bool:
    fa = re.sub(r"[^a-z0-9]+", "", (a or "").lower())
    fb = re.sub(r"[^a-z0-9]+", "", (b or "").lower())
    if not fa or not fb:
        return False
    return fa == fb or fa in fb or fb in fa


def lookup_company_via_payer_flow(company_name: str) -> dict[str, Any]:
    """Nome empresa → achar ad → pagante → total ads (countries=US)."""
    q = (company_name or "").strip()
    credits = 0
    if not q:
        return {
            "linkedin_ads": None,
            "linkedin_payer": "",
            "linkedin_search_url": "",
            "linkedin_detail_url": "",
            "spb_credits": 0,
        }

    search_urls = [keyword_url(q), account_owner_url(q)]
    ads: list[dict[str, str]] = []
    used_search = ""
    last_err: Exception | None = None

    for url in search_urls:
        try:
            print(f"[LI/US] search {url}", flush=True)
            html, used = _fetch_html(url, wait_ms=6000)
            credits += used
            found = extract_ads_from_html(html)
            # Prefer cards that look like the queried company
            matched = [a for a in found if _names_match(a.get("company") or "", q)]
            ads = matched or found
            used_search = url
            if ads:
                break
        except Exception as e:
            last_err = e
            print(f"[LI/US] search fail: {e}", flush=True)
            time.sleep(1.0)

    if not ads:
        print(f"[LI/US] nenhum ad para '{q}' ({last_err})", flush=True)
        return {
            "linkedin_ads": 0 if last_err is None else None,
            "linkedin_payer": q,
            "linkedin_search_url": used_search or keyword_url(q),
            "linkedin_detail_url": "",
            "spb_credits": credits,
        }

    # Pick first ad with detail_id (prefer name match)
    ad = next((a for a in ads if a.get("detail_id")), ads[0])
    detail_id = ad.get("detail_id") or ""
    detail_url = ad.get("detail_url") or (
        f"https://www.linkedin.com/ad-library/detail/{detail_id}" if detail_id else ""
    )

    payer = ""
    advertiser = ad.get("company") or q
    if detail_id:
        try:
            print(f"[LI/US] detail {detail_id}", flush=True)
            dhtml, used = _fetch_html(detail_url, wait_ms=5000)
            credits += used
            detail = extract_payer_from_detail_html(dhtml)
            payer = (detail.get("payer") or "").strip()
            if detail.get("advertiser"):
                advertiser = detail["advertiser"]
            print(
                f"[LI/US] advertiser='{advertiser}' payer='{payer}'",
                flush=True,
            )
        except Exception as e:
            print(f"[LI/US] detail fail: {e}", flush=True)

    if not payer:
        payer = advertiser or q

    # Total via payer search
    p_url = payer_url(payer)
    total: Optional[int] = None
    try:
        print(f"[LI/US] payer search {p_url}", flush=True)
        phtml, used = _fetch_html(p_url, wait_ms=6000)
        credits += used
        total = extract_h1_count(phtml)
        if total is None:
            # Fallback: count visible cards
            total = len(extract_ads_from_html(phtml)) or None
        print(f"[LI/US] payer '{payer}': total={total}", flush=True)
    except Exception as e:
        print(f"[LI/US] payer fail: {e}", flush=True)

    return {
        "linkedin_ads": total,
        "linkedin_payer": payer,
        "linkedin_advertiser": advertiser,
        "linkedin_search_url": p_url,
        "linkedin_detail_url": detail_url,
        "linkedin_keyword_url": used_search or keyword_url(q),
        "spb_credits": credits,
    }
