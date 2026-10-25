# -*- coding: utf-8 -*-
"""LinkedIn Ad Library — keyword search + Ctrl+F (1 pagina).

URL: https://www.linkedin.com/ad-library/search?keyword=<empresa>
Fallback: accountOwner=<empresa>

1) Baixa a pagina via ScrapingBee premium proxy (render_js=false)
2) Ctrl+F: conta quantas vezes o nome da empresa aparece no HTML
3) Le o total do H1: "1,728 ads match your search criteria"
4) Mostra name-hits / ads total

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
    return f"{AD_LIBRARY_BASE}?keyword={quote_plus(keyword.strip())}"


def _ctrl_f_count(html: str, needles: list[str]) -> tuple[int, str]:
    """Case-insensitive substring count on visible-ish HTML (browser Ctrl+F)."""
    if not html or not needles:
        return 0, ""
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    best_n = 0
    best = ""
    for needle in needles:
        n = (needle or "").strip()
        if len(n) < 3:
            continue
        count = len(re.findall(re.escape(n), text, flags=re.IGNORECASE))
        if count > best_n:
            best_n = count
            best = n
    return best_n, best


def _needles_for(company: str) -> list[str]:
    q = re.sub(r"\s+", " ", (company or "").strip())
    q = re.split(r"[|\-–—:·•/]", q)[0].strip()
    out: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        t = re.sub(r"\s+", " ", (term or "").strip())
        key = t.lower()
        if len(t) < 3 or key in seen:
            return
        seen.add(key)
        out.append(t)

    _add(q)
    first = q.split(" ", 1)[0] if q else ""
    if first and len(first) >= 4:
        _add(first)
    return out


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
        r"([\d.,]+)\s+(?:an[uú]ncios?|ads?|publicit[eé]s?)\s+"
        r"(?:que\s+)?(?:match|correspond|coinciden)",
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


def _fmt_dual(ctrl_f: Optional[int], total: Optional[int]) -> str:
    if ctrl_f is None and total is None:
        return ""
    left = "—" if ctrl_f is None else str(int(ctrl_f))
    right = "—" if total is None else str(int(total))
    return f"{left}/{right}"


def lookup_company_via_payer_flow(company_name: str) -> dict[str, Any]:
    """Keyword search -> Ctrl+F company name -> H1 ads total. accountOwner fallback."""
    raw = (company_name or "").strip()
    q = re.split(r"[|\-–—:·•/]", raw)[0].strip() or raw
    needles = _needles_for(q)
    short = needles[-1] if len(needles) > 1 else ""
    keyword = keyword_url(q) if q else ""
    base = {
        "linkedin_ads": None,
        "linkedin_ads_total": None,
        "linkedin_ads_ctrl": None,
        "linkedin_ads_fmt": "",
        "linkedin_payer": "",
        "linkedin_advertiser": "",
        "linkedin_search_url": keyword,
        "linkedin_detail_url": "",
        "linkedin_keyword_url": keyword,
        "spb_credits": 0,
        "backend": "scrapingbee",
        "name_found": False,
        "method": "",
    }
    if not q:
        return base

    attempts: list[tuple[str, str]] = [("keyword", keyword)]
    if short and short.lower() != q.lower():
        attempts.append(("keyword_short", keyword_url(short)))
    attempts.append(("accountOwner", account_owner_url(q)))

    last_err = ""
    credits_all = 0
    for label, url in attempts:
        if not url:
            continue
        print(f"[LI] {label} '{q}' -> {url}", flush=True)
        try:
            html, credits = fetch_ad_library_html(url)
        except Exception as e:
            last_err = str(e)
            print(f"[LI] {label} falha: {e}", flush=True)
            continue
        credits_all += credits
        h1 = _extract_h1(html)
        total = parse_result_count(h1) or parse_result_count(html)
        ctrl, needle = _ctrl_f_count(html, needles)
        found = ctrl > 0 or _name_appears(html, q)
        print(
            f"[LI] {label} h1='{h1}' ctrl+f={ctrl} needle='{needle or q}' "
            f"total={total} found={found}",
            flush=True,
        )
        if not found and total in (None, 0):
            continue
        base["spb_credits"] = credits_all
        base["linkedin_search_url"] = url
        base["linkedin_keyword_url"] = keyword or url
        base["linkedin_ads_ctrl"] = ctrl
        base["linkedin_ads_total"] = total
        base["linkedin_ads_fmt"] = _fmt_dual(ctrl, total)
        base["linkedin_ads"] = total if total is not None else ctrl
        base["linkedin_advertiser"] = q
        base["name_found"] = found
        base["method"] = label
        return base

    base["spb_credits"] = credits_all
    if last_err:
        base["error"] = last_err
    print(f"[LI] nome '{q}' nao confirmado em keyword/accountOwner", flush=True)
    base["linkedin_ads"] = 0
    base["linkedin_ads_ctrl"] = 0
    base["linkedin_ads_fmt"] = _fmt_dual(0, 0)
    return base
