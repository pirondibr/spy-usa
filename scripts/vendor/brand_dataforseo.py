# -*- coding: utf-8 -*-
"""Brand Search via DataForSEO (Google Ads search volume history).

Descobre o nome da marca a partir do dominio + title do site e consulta
volume mensal nos EUA, comparando o mes mais recente com 1/2/3/5 anos.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests

try:
    from market import LOCATION_CODE, LANGUAGE_CODE
except ImportError:
    LOCATION_CODE = 2840
    LANGUAGE_CODE = "en"

DATAFORSEO_USER = (
    os.environ.get("DATAFORSEO_USER", "").strip()
    or os.environ.get("DATAFORSEO_LOGIN", "").strip()
)
DATAFORSEO_PASS = (
    os.environ.get("DATAFORSEO_PASS", "").strip()
    or os.environ.get("DATAFORSEO_PASSWORD", "").strip()
)
DATAFORSEO_VOLUME_URL = (
    "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
)

SKIP_TITLE_WORDS = {
    "home", "official", "website", "site", "welcome", "login", "sign", "in",
    "the", "and", "or", "of", "for", "a", "an", "to", "inc", "llc", "ltd",
    "corp", "corporation", "company", "co",
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s).strip().lower()


def brand_from_domain(url_or_domain: str) -> str:
    raw = (url_or_domain or "").strip()
    if "://" not in raw and raw:
        raw = "https://" + raw
    host = urlparse(raw).netloc or urlparse(raw).path or raw
    host = host.lower().replace("www.", "").split("/")[0]
    for suf in (".com.br", ".co.uk", ".com", ".net", ".org", ".io", ".ai", ".us", ".app"):
        if host.endswith(suf):
            host = host[: -len(suf)]
            break
    token = host.split(".")[0]
    token = re.sub(r"[^a-z0-9]+", "", token)
    return token


def brand_from_title(title: str, domain_brand: str = "") -> str:
    t = (title or "").strip()
    if not t:
        return ""
    # Take left side of common separators
    for sep in ("|", "–", "—", "-", ":"):
        if sep in t:
            t = t.split(sep, 1)[0].strip()
            break
    # Drop trailing taglines in parentheses
    t = re.sub(r"\([^)]*\)", "", t).strip()
    words = [w for w in re.split(r"\s+", t) if w]
    cleaned = []
    for w in words[:4]:
        low = _fold(w)
        low = re.sub(r"[^a-z0-9]", "", low)
        if not low or low in SKIP_TITLE_WORDS:
            continue
        cleaned.append(w.strip(",.;:!?"))
    if not cleaned:
        return ""
    # Prefer short brand-like phrase (1-2 words)
    candidate = " ".join(cleaned[:2]).strip()
    # If title starts with domain brand, use domain brand
    db = _fold(domain_brand)
    if db and db in _fold(candidate):
        return domain_brand
    # Single token without spaces is better as lowercase brand keyword
    if " " not in candidate and len(candidate) <= 24:
        return candidate.lower()
    return candidate


def resolve_brand_keyword(
    url: str,
    *,
    title: str = "",
    company_hint: str = "",
) -> dict[str, str]:
    """Escolhe a keyword de marca a consultar no DataForSEO."""
    domain_brand = brand_from_domain(url)
    title_brand = brand_from_title(title, domain_brand)
    hint = (company_hint or "").strip()
    # Prefer explicit company hint if short brand-like
    if hint:
        hint_clean = re.split(r"[|\-:]", hint)[0].strip()
        if 2 <= len(hint_clean) <= 40 and len(hint_clean.split()) <= 3:
            # Prefer domain token if company hint is legal name like "Semrush Inc"
            if domain_brand and domain_brand in _fold(hint_clean):
                keyword = domain_brand
            else:
                keyword = hint_clean.lower() if " " not in hint_clean else hint_clean
        else:
            keyword = domain_brand or title_brand or hint_clean
    else:
        keyword = domain_brand or title_brand

    keyword = re.sub(r"[!@%^()={};~'<>?\\|―*]+", "", keyword or "").strip()
    keyword = re.sub(r"\s+", " ", keyword)
    return {
        "keyword": keyword,
        "domain_brand": domain_brand,
        "title_brand": title_brand,
        "company_hint": hint,
        "title": title or "",
        "url": url,
    }


def _pct(new: Optional[int], old: Optional[int]) -> Optional[float]:
    if new is None or old in (None, 0):
        return None
    return round(((new - old) / old) * 100, 2)


def _pick_month(
    monthly: list[dict],
    year: int,
    month: int,
) -> Optional[int]:
    for m in monthly:
        if int(m.get("year") or 0) == year and int(m.get("month") or 0) == month:
            vol = m.get("search_volume")
            return int(vol) if vol is not None else None
    return None


def analyze_monthly_brand(monthly: list[dict]) -> dict[str, Any]:
    """Mes mais recente + comparativos 1/2/3/5 anos."""
    if not monthly:
        return {
            "latest": None,
            "comparisons": {},
            "monthly": [],
        }
    sm = sorted(monthly, key=lambda m: (int(m["year"]), int(m["month"])))
    latest = sm[-1]
    ly, lm = int(latest["year"]), int(latest["month"])
    latest_vol = int(latest.get("search_volume") or 0)

    comparisons = {}
    for years in (1, 2, 3, 5):
        ty, tm = ly - years, lm
        vol = _pick_month(sm, ty, tm)
        comparisons[f"{years}y"] = {
            "years": years,
            "year": ty,
            "month": tm,
            "label": f"{ty:04d}-{tm:02d}",
            "volume": vol,
            "growth_pct": _pct(latest_vol, vol),
        }

    return {
        "latest": {
            "year": ly,
            "month": lm,
            "label": f"{ly:04d}-{lm:02d}",
            "volume": latest_vol,
        },
        "comparisons": comparisons,
        "monthly": [
            {
                "year": int(m["year"]),
                "month": int(m["month"]),
                "label": f"{int(m['year']):04d}-{int(m['month']):02d}",
                "volume": int(m.get("search_volume") or 0),
            }
            for m in sm
        ],
        "months_available": len(sm),
        "oldest_label": f"{int(sm[0]['year']):04d}-{int(sm[0]['month']):02d}",
    }


def fetch_brand_volumes(
    keywords: list[str],
    *,
    location_code: int = LOCATION_CODE,
    language_code: str = LANGUAGE_CODE,
    years_back: int = 6,
) -> dict[str, dict]:
    """POST Google Ads search_volume/live for brand keywords (US by default)."""
    kws = []
    seen = set()
    for k in keywords:
        kk = (k or "").strip()
        if not kk:
            continue
        key = kk.lower()
        if key in seen:
            continue
        seen.add(key)
        kws.append(kk)
    if not kws:
        return {}
    if not DATAFORSEO_USER or not DATAFORSEO_PASS:
        raise RuntimeError("DATAFORSEO_USER / DATAFORSEO_PASS ausentes")

    today = datetime.today()
    date_to = today.strftime("%Y-%m-%d")
    try:
        date_from = today.replace(year=today.year - years_back).strftime("%Y-%m-%d")
    except ValueError:
        date_from = today.replace(year=today.year - years_back, day=28).strftime("%Y-%m-%d")

    payload = [{
        "location_code": int(location_code),
        "language_code": language_code,
        "keywords": kws,
        "date_from": date_from,
        "date_to": date_to,
        "search_partners": False,
    }]
    auth = requests.auth.HTTPBasicAuth(DATAFORSEO_USER, DATAFORSEO_PASS)
    print(
        f"[BRAND/DFS] {len(kws)} keywords loc={location_code} lang={language_code} "
        f"{date_from} -> {date_to}",
        flush=True,
    )
    r = requests.post(DATAFORSEO_VOLUME_URL, auth=auth, json=payload, timeout=120)
    r.raise_for_status()
    js = r.json()
    if js.get("status_code") != 20000:
        raise RuntimeError(
            f"DataForSEO erro {js.get('status_code')}: {js.get('status_message')}"
        )

    out: dict[str, dict] = {}
    results = (js.get("tasks") or [{}])[0].get("result") or []
    for item in results:
        kw = (item.get("keyword") or "").strip()
        if not kw:
            continue
        monthly = item.get("monthly_searches") or []
        analysis = analyze_monthly_brand(monthly)
        out[kw.lower()] = {
            "keyword": kw,
            "search_volume_avg": item.get("search_volume"),
            "cpc": item.get("cpc"),
            "competition": item.get("competition"),
            "location_code": location_code,
            "language_code": language_code,
            **analysis,
        }
        latest = analysis.get("latest") or {}
        print(
            f"[BRAND/DFS] '{kw}' latest={latest.get('label')} "
            f"vol={latest.get('volume')} months={analysis.get('months_available')}",
            flush=True,
        )
    return out


def brand_report_for_entity(
    *,
    url: str,
    title: str = "",
    company_hint: str = "",
    domain: str = "",
    name: str = "",
    is_client: bool = False,
) -> dict[str, Any]:
    meta = resolve_brand_keyword(url or domain, title=title, company_hint=company_hint or name)
    keyword = meta["keyword"]
    volumes = fetch_brand_volumes([keyword]) if keyword else {}
    data = volumes.get((keyword or "").lower()) or {}
    latest = data.get("latest") or {}
    comps = data.get("comparisons") or {}
    return {
        "name": name or company_hint or meta["domain_brand"] or keyword,
        "domain": domain or brand_from_domain(url),
        "url": url,
        "is_client": is_client,
        "brand_keyword": keyword,
        "domain_brand": meta["domain_brand"],
        "title_brand": meta["title_brand"],
        "site_title": title,
        "latest_label": latest.get("label"),
        "latest_volume": latest.get("volume"),
        "volume_1y": (comps.get("1y") or {}).get("volume"),
        "volume_2y": (comps.get("2y") or {}).get("volume"),
        "volume_3y": (comps.get("3y") or {}).get("volume"),
        "volume_5y": (comps.get("5y") or {}).get("volume"),
        "growth_1y_pct": (comps.get("1y") or {}).get("growth_pct"),
        "growth_2y_pct": (comps.get("2y") or {}).get("growth_pct"),
        "growth_3y_pct": (comps.get("3y") or {}).get("growth_pct"),
        "growth_5y_pct": (comps.get("5y") or {}).get("growth_pct"),
        "comparisons": comps,
        "months_available": data.get("months_available"),
        "oldest_label": data.get("oldest_label"),
        "cpc": data.get("cpc"),
        "search_volume_avg": data.get("search_volume_avg"),
        "source": "dataforseo_google_ads",
        "market": "US",
    }


def brand_reports_batch(entities: list[dict]) -> list[dict]:
    """Resolve keywords, one DFS call, map back to entities."""
    metas = []
    keywords = []
    for e in entities:
        meta = resolve_brand_keyword(
            e.get("url") or e.get("domain") or "",
            title=e.get("title") or "",
            company_hint=e.get("company") or e.get("name") or e.get("title") or "",
        )
        metas.append(meta)
        if meta["keyword"]:
            keywords.append(meta["keyword"])
    volumes = fetch_brand_volumes(keywords)
    rows = []
    for e, meta in zip(entities, metas):
        kw = (meta["keyword"] or "").lower()
        data = volumes.get(kw) or {}
        latest = data.get("latest") or {}
        comps = data.get("comparisons") or {}
        rows.append({
            "name": e.get("name") or e.get("company") or meta["domain_brand"] or kw,
            "domain": e.get("domain") or meta["domain_brand"],
            "url": e.get("url") or "",
            "is_client": bool(e.get("is_client")),
            "similaridade": e.get("similaridade") or ("Cliente" if e.get("is_client") else "—"),
            "brand_keyword": meta["keyword"],
            "domain_brand": meta["domain_brand"],
            "title_brand": meta["title_brand"],
            "site_title": meta.get("title") or e.get("title") or "",
            "latest_label": latest.get("label"),
            "latest_volume": latest.get("volume"),
            "volume_1y": (comps.get("1y") or {}).get("volume"),
            "volume_2y": (comps.get("2y") or {}).get("volume"),
            "volume_3y": (comps.get("3y") or {}).get("volume"),
            "volume_5y": (comps.get("5y") or {}).get("volume"),
            "growth_1y_pct": (comps.get("1y") or {}).get("growth_pct"),
            "growth_2y_pct": (comps.get("2y") or {}).get("growth_pct"),
            "growth_3y_pct": (comps.get("3y") or {}).get("growth_pct"),
            "growth_5y_pct": (comps.get("5y") or {}).get("growth_pct"),
            "comparisons": comps,
            "months_available": data.get("months_available"),
            "oldest_label": data.get("oldest_label"),
            "cpc": data.get("cpc"),
            "search_volume_avg": data.get("search_volume_avg"),
            "source": "dataforseo_google_ads",
            "market": "US",
        })
    rows.sort(key=lambda r: (r.get("latest_volume") or 0), reverse=True)
    return rows
