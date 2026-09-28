# -*- coding: utf-8 -*-
"""LinkedIn Ad Library — fluxo simples (1 pagina).

URL: https://www.linkedin.com/ad-library/search?accountOwner=<empresa>
(sem filtro de pais)

1) Baixa a pagina via ScrapingBee premium proxy (render_js=false)
2) Ctrl+F: confere se o nome da empresa aparece
3) Le o total do H1: "1,728 ads match your search criteria"

ScrapingBee com render_js=true e bloqueado/timeout no LinkedIn; sem JS passa.
O HTML ja vem server-side renderizado com os cards e o H1.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus

import requests

AD_LIBRARY_BASE = "https://www.linkedin.com/ad-library/search"
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
SCRAPINGBEE_COUNTRY = (os.environ.get("SPY_SCRAPINGBEE_COUNTRY") or "us").strip().lower()
REQUEST_TIMEOUT = int(os.environ.get("SPY_LINKEDIN_TIMEOUT") or 45)


def account_owner_url(name: str) -> str:
    """Form 'Company or advertiser' — sem countries=."""
    return f"{AD_LIBRARY_BASE}?accountOwner={quote_plus(name.strip())}"


def payer_url(name: str) -> str:
    return f"{AD_LIBRARY_BASE}?payer={quote_plus(name.strip())}"


def keyword_url(keyword: str) -> str:
    return account_owner_url(keyword)


def parse_result_count(text: str) -> Optional[int]:
    """Le 'N ads match your search criteria' (ou equivalente PT/FR)."""
    if not text:
        return None
    t = (text or "").replace("\xa0", " ").replace("&nbsp;", " ")
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if re.search(r"(nenhum resultado|no results|no ads match|aucun r[eé]sultat)", t, flags=re.IGNORECASE):
        return 0
    m = re.search(
        r"([\d.,]+)\s+(?:an[uú]ncios?|ads?|publicit[eé]s?)\s+(?:match|correspond)",
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


def _extract_h1(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def _name_appears(html: str, company: str) -> bool:
    """Ctrl+F basico no texto da pagina."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).lower()
    q = re.sub(r"\s+", " ", (company or "").strip()).lower()
    if not q or not text:
        return False
    if q in text:
        return True
    compact_t = re.sub(r"[^a-z0-9]+", "", text)
    compact_q = re.sub(r"[^a-z0-9]+", "", q)
    return bool(compact_q) and compact_q in compact_t


def _looks_blocked(html: str) -> bool:
    low = (html or "").lower()
    return any(
        x in low
        for x in (
            "you have been blocked",
            "attention required",
            "just a moment",
            "cf-browser-verification",
        )
    )


def fetch_ad_library_html(url: str) -> tuple[str, int]:
    """ScrapingBee premium (sem JS). Fallback: stealth proxy."""
    key = (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("SCRAPINGBEE_API_KEY ausente")

    attempts = [
        ("premium", {"premium_proxy": "true", "country_code": SCRAPINGBEE_COUNTRY}),
        ("stealth", {"stealth_proxy": "true"}),
    ]
    last_err: Exception | None = None
    for label, extra in attempts:
        params = {
            "api_key": key,
            "url": url,
            "render_js": "false",
            "block_resources": "false",
            **extra,
        }
        try:
            r = requests.get(SCRAPINGBEE_URL, params=params, timeout=REQUEST_TIMEOUT)
            credits = int(r.headers.get("Spb-cost") or 0)
            if r.status_code != 200:
                last_err = RuntimeError(f"ScrapingBee {label} HTTP {r.status_code}")
                print(f"[LI] {label} falhou: {last_err}", flush=True)
                time.sleep(1.0)
                continue
            html = r.text or ""
            if _looks_blocked(html):
                last_err = RuntimeError(f"ScrapingBee {label} bloqueado (Cloudflare)")
                print(f"[LI] {label} bloqueado", flush=True)
                time.sleep(1.0)
                continue
            print(f"[LI] {label} ok ({len(html)} bytes, {credits} creditos)", flush=True)
            return html, credits
        except Exception as e:
            last_err = e
            print(f"[LI] {label} erro: {e}", flush=True)
    raise RuntimeError(str(last_err) if last_err else "ScrapingBee falhou")


def lookup_company_via_payer_flow(company_name: str) -> dict[str, Any]:
    """accountOwner -> Ctrl+F nome -> total de anuncios (1 pagina)."""
    q = (company_name or "").strip()
    url = account_owner_url(q) if q else ""
    base = {
        "linkedin_ads": None,
        "linkedin_payer": "",
        "linkedin_advertiser": "",
        "linkedin_search_url": url,
        "linkedin_detail_url": "",
        "linkedin_keyword_url": url,
        "spb_credits": 0,
        "backend": "scrapingbee",
        "name_found": False,
    }
    if not q:
        return base

    print(f"[LI] accountOwner '{q}' -> {url}", flush=True)
    try:
        html, credits = fetch_ad_library_html(url)
    except Exception as e:
        print(f"[LI] falha: {e}", flush=True)
        base["error"] = str(e)
        return base

    base["spb_credits"] = credits
    h1 = _extract_h1(html)
    found = _name_appears(html, q)
    total = parse_result_count(h1) or parse_result_count(html)

    if not found:
        print(f"[LI] nome '{q}' nao aparece na pagina | h1='{h1}'", flush=True)
        base["linkedin_ads"] = 0
        return base

    print(f"[LI] '{q}' encontrado | h1='{h1}' | total={total}", flush=True)
    base["linkedin_ads"] = total
    base["linkedin_advertiser"] = q
    base["name_found"] = True
    return base
