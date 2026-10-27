# -*- coding: utf-8 -*-
"""Brand Search via DataForSEO Labs keyword_overview.

Descobre o nome da marca a partir do dominio + title do site e consulta
volume mensal nos EUA, comparando o mes mais recente com 1/2/3/5 anos.
Labs e a fonte principal; search_volume/live so entra se o Labs nao trouxer serie.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
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
DATAFORSEO_LABS_URL = (
    "https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_overview/live"
)
DATAFORSEO_VOLUME_URL = (
    "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
)
DFS_LABS_TASK_USD = 0.012
DFS_LABS_KEYWORD_USD = 0.00012
DFS_VOLUME_TASK_USD = 0.09
LAST_USAGE: dict[str, Any] = {}

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


SEMRUSH_BRAND_TOP_N = 5


def _domain_host(url_or_domain: str) -> str:
    raw = (url_or_domain or "").strip()
    if "://" not in raw and raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or urlparse(raw).path or raw).lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split("/")[0].strip(".")


def _phrase_words(phrase: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(phrase))


_BRAND_QUERY_EXTRAS = {
    "app", "ai", "io", "hq", "official", "oficial", "inc", "ads",
    "co", "com", "net", "org", "dev",
}

# Long-tail article titles that mention the brand plus rivals (Semrush, Pathmatics…)
# must not become the influencer / brand-search query.
_BRAND_QUERY_NOISE = {
    "competitor", "competitors", "tools", "tool", "strategy", "monitoring",
    "issues", "performance", "marketing", "roi", "organic", "traffic",
    "review", "reviews", "comparison", "versus", "vs", "alternative",
    "alternatives", "how", "what", "why", "best", "guide",
}


def semrush_phrase_is_branded(phrase: str, domain: str, company: str = "") -> bool:
    """True when a Semrush keyword is a short brand query, not a category word.

    'dropship io' / 'foreplay app' match. Bare 'dropship' does not when that
    token is a generic dictionary word. 'dropshipping' does not match dropship.io.
    Article titles like 'panoramata pathmatics semrush competitor …' do not match.
    """
    host = _domain_host(domain)
    brand = (host.split(".")[0] if host else brand_from_domain(domain)) or ""
    tld = host.split(".")[-1] if host and "." in host else ""
    brand_fold = re.sub(r"[^a-z0-9]+", "", _fold(brand))
    words = _phrase_words(phrase)
    folded = "".join(words)
    if len(brand_fold) < 3 or not folded:
        return False
    word_hit = brand_fold in words
    if tld and brand_fold in words and tld in words:
        word_hit = True
    compact_hit = folded == brand_fold or (tld and folded == brand_fold + tld)
    if not word_hit and not compact_hit:
        return False
    if len(words) > 4:
        return False
    extras_ok = set(_BRAND_QUERY_EXTRAS)
    if tld:
        extras_ok.add(tld)
    extra_words = [w for w in words if w != brand_fold and w != tld]
    if extra_words and not all(w in extras_ok for w in extra_words):
        return False
    if any(w in _BRAND_QUERY_NOISE for w in words):
        return False
    try:
        from brand_false_positive import GENERIC_BRAND_WORDS
    except Exception:
        GENERIC_BRAND_WORDS = set()
    only_brand = words == [brand_fold] or folded == brand_fold
    if only_brand and brand_fold in GENERIC_BRAND_WORDS:
        return False
    return True


def brand_query_is_usable(kw: str, domain: str = "", company: str = "") -> bool:
    """Influencer / cache reuse: keep only short brand queries for this company."""
    phrase = (kw or "").strip()
    if not phrase:
        return False
    host = domain or company
    if host and semrush_phrase_is_branded(phrase, host, company):
        return True
    words = _phrase_words(phrase)
    if not words or len(words) > 3:
        return False
    if any(w in _BRAND_QUERY_NOISE for w in words):
        return False
    compact = "".join(words)
    needles = []
    for raw in (company, brand_from_domain(domain) if domain else ""):
        n = re.sub(r"[^a-z0-9]+", "", _fold(raw or ""))
        if len(n) >= 3:
            needles.append(n)
    if not needles:
        return len(words) <= 3
    return any(n in compact or compact in n for n in needles)


def pick_semrush_brand_keyword(
    domain: str,
    *,
    company: str = "",
    db: str = "",
    limit: int = SEMRUSH_BRAND_TOP_N,
) -> Optional[dict[str, Any]]:
    """Highest-volume branded keyword in Semrush's top-N organic list, or None."""
    host = _domain_host(domain)
    if not host:
        return None
    if not db:
        try:
            from market import SEMRUSH_DB

            db = SEMRUSH_DB or "us"
        except Exception:
            db = "us"
    try:
        from semrush_keywords import fetch_top_keywords

        items = fetch_top_keywords(host, db=db, limit=int(limit) or SEMRUSH_BRAND_TOP_N)
    except Exception as e:
        print(f"[BRAND/KW] semrush top fail {host}: {e}", flush=True)
        return None
    branded: list[dict[str, Any]] = []
    for item in items or []:
        phrase = str(item.get("phrase") or "").strip()
        if not phrase or not semrush_phrase_is_branded(phrase, host, company):
            continue
        try:
            vol = int(item.get("volume") or 0)
        except (TypeError, ValueError):
            vol = 0
        branded.append({**item, "phrase": phrase, "volume": vol})
    preview = [str(i.get("phrase") or "") for i in (items or [])]
    if not branded:
        print(f"[BRAND/KW] semrush top{limit} not branded {host}: {preview}", flush=True)
        return None

    def _rank(phrase: str) -> int:
        words = _phrase_words(phrase)
        brand = host.split(".")[0]
        tld = host.split(".")[-1] if "." in host else ""
        compact = " ".join(words)
        if tld and compact == f"{brand} {tld}":
            return 4
        if tld and brand in words and tld in words:
            return 3
        if len(words) >= 2:
            return 2
        return 1

    branded.sort(key=lambda x: (int(x.get("volume") or 0), _rank(str(x.get("phrase") or ""))), reverse=True)
    best = branded[0]
    phrase = str(best.get("phrase") or "").strip().lower()
    brand = host.split(".")[0]
    tld = host.split(".")[-1] if "." in host else ""
    if tld and phrase == f"{brand}.{tld}":
        phrase = f"{brand} {tld}"
        best["phrase"] = phrase
    print(
        f"[BRAND/KW] semrush {host} -> {phrase!r} vol={best.get('volume')} "
        f"top{limit}={preview}",
        flush=True,
    )
    return {**best, "top_phrases": preview}


def resolve_brand_keyword(
    url: str,
    *,
    title: str = "",
    description: str = "",
    company_hint: str = "",
) -> dict[str, str]:
    """Brand keyword: Semrush top-5 branded term, else domain + title via LLM."""
    domain_brand = brand_from_domain(url)
    title_brand = brand_from_title(title, domain_brand)
    hint = (company_hint or "").strip()
    if hint:
        hint_clean = re.split(r"[|\-:]", hint)[0].strip()
        if 2 <= len(hint_clean) <= 40 and len(hint_clean.split()) <= 3:
            if domain_brand and domain_brand in _fold(hint_clean):
                fallback = domain_brand
            else:
                fallback = hint_clean.lower() if " " not in hint_clean else hint_clean
        else:
            fallback = domain_brand or title_brand or hint_clean
    else:
        fallback = domain_brand or title_brand
    fallback = re.sub(r"[!@%^()={};~'<>?\\|―*]+", "", fallback or "").strip()
    fallback = re.sub(r"\s+", " ", fallback)
    keyword = fallback
    reason = "heuristic"
    method = "heuristic"
    sm = pick_semrush_brand_keyword(url or domain_brand, company=hint)
    if sm and str(sm.get("phrase") or "").strip():
        keyword = re.sub(r"\s+", " ", str(sm.get("phrase") or "").strip()).lower()
        reason = (
            f"semrush top{SEMRUSH_BRAND_TOP_N} vol={sm.get('volume')}"
        )[:160]
        method = "semrush_top"
        print(
            f"[BRAND/DFS] keyword={keyword!r} method={method} "
            f"title={(title or '')[:40]!r} reason={reason}",
            flush=True,
        )
        meta = {
            "keyword": keyword,
            "domain_brand": domain_brand,
            "title_brand": title_brand,
            "company_hint": hint,
            "title": title or "",
            "description": (description or "")[:400],
            "url": url,
            "keyword_method": method,
            "keyword_reason": reason,
            "semrush_volume": sm.get("volume"),
            "semrush_top": sm.get("top_phrases") or [],
        }
        slug = (os.environ.get("SPY_SLUG") or "").strip()
        if slug and keyword:
            save_brand_search_keyword(slug, meta)
        return meta
    try:
        from llm_trace import chat, extract_json

        prompt = (
            "Choose the Google brand-search keyword for this company.\n\n"
            f"Domain token: {domain_brand or '—'}\n"
            f"Website: {url or '—'}\n"
            f"Homepage title: {(title or '—').strip()}\n"
            f"Homepage description: {(description or '—').strip()[:400]}\n"
            f"Company hint: {hint or '—'}\n\n"
            "Return JSON only:\n"
            '{"keyword":"turbo ai","reason":"title is Turbo AI"}\n\n'
            "Rules:\n"
            "- 1 to 3 words people type when they search THIS brand.\n"
            "- If the title or description uses a two-word product name (Turbo AI, Higgsfield AI), keep both words.\n"
            "- Do not use a generic dictionary word alone when the site brand is Name + AI/App/etc.\n"
            "- No TLD (.ai, .com, .io). No tagline. Lowercase.\n"
        )
        raw = chat(
            task="brand_keyword",
            prompt=prompt,
            max_tokens=200,
            temperature=0.1,
            extra={"url": url, "domain": domain_brand},
        )
        data = extract_json(raw)
        picked = re.sub(r"[!@%^()={};~'<>?\\|―*]+", "", str(data.get("keyword") or "")).strip()
        picked = re.sub(r"\s+", " ", picked)
        if picked and 1 <= len(picked.split()) <= 4:
            keyword = picked.lower()
            reason = str(data.get("reason") or "llm")[:160]
            method = "llm_title_desc"
    except Exception as e:
        reason = f"llm_fallback:{e}"[:160]
        method = "heuristic"
        print(f"[BRAND/DFS] llm keyword fail {url}: {e}", flush=True)
    print(
        f"[BRAND/DFS] keyword={keyword!r} method={method} "
        f"title={(title or '')[:40]!r} reason={reason}",
        flush=True,
    )
    meta = {
        "keyword": keyword,
        "domain_brand": domain_brand,
        "title_brand": title_brand,
        "company_hint": hint,
        "title": title or "",
        "description": (description or "")[:400],
        "url": url,
        "keyword_method": method,
        "keyword_reason": reason,
    }
    slug = (os.environ.get("SPY_SLUG") or "").strip()
    if slug and keyword:
        save_brand_search_keyword(slug, meta)
    return meta


def _metricas_dir() -> Path:
    try:
        from workspace_paths import OUT_METRICAS

        return Path(OUT_METRICAS)
    except Exception:
        return Path(__file__).resolve().parents[1] / "outputs" / "metricas"


def brand_keyword_path(slug: str) -> Path:
    return _metricas_dir() / slug / f"brand-keyword-{slug}.json"


def keyword_belongs_to_company(kw: str, slug: str, url: str = "", company: str = "") -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", _fold(kw))
    if len(compact) < 3:
        return False
    needles = []
    for raw in (slug, brand_from_domain(url) if url else "", company):
        n = re.sub(r"[^a-z0-9]+", "", _fold(raw or ""))
        if len(n) >= 3:
            needles.append(n)
    if not needles:
        return True
    return any(n in compact or compact in n for n in needles)


def load_brand_search_keyword(slug: str = "") -> str:
    slug = (slug or os.environ.get("SPY_SLUG") or "").strip()
    env = (os.environ.get("SPY_BRAND_KEYWORD") or "").strip()
    env_slug = (os.environ.get("SPY_SLUG") or "").strip()
    # Process env leaks across queued jobs on the same worker — only trust
    # it when it belongs to this slug. Prefer the slug sidecar either way.
    if env and slug and env_slug == slug:
        sidecar = ""
        try:
            path = brand_keyword_path(slug)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                sidecar = str((data or {}).get("keyword") or "").strip()
        except Exception:
            sidecar = ""
        if sidecar:
            return sidecar
        return env
    if not slug:
        return ""
    paths = (
        brand_keyword_path(slug),
        _metricas_dir() / slug / f"brand-dataforseo-{slug}.json",
    )
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        kw = str(data.get("keyword") or data.get("client_keyword") or "").strip()
        if not kw:
            for row in data.get("rows") or []:
                if isinstance(row, dict) and row.get("is_client") and row.get("brand_keyword"):
                    kw = str(row.get("brand_keyword") or "").strip()
                    break
        if kw:
            return kw
    return ""


def save_brand_search_keyword(slug: str, meta: dict[str, Any]) -> None:
    if not slug or not (meta or {}).get("keyword"):
        return
    path = brand_keyword_path(slug)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def ensure_brand_search_keyword(
    slug: str,
    *,
    url: str = "",
    title: str = "",
    description: str = "",
    company: str = "",
) -> dict[str, str]:
    """Reuse a Semrush brand keyword, else Semrush top-5, else title+domain LLM."""
    existing = load_brand_search_keyword(slug)
    existing_method = ""
    try:
        path = brand_keyword_path(slug)
        if path.exists():
            existing_method = str((json.loads(path.read_text(encoding="utf-8")) or {}).get("keyword_method") or "")
    except Exception:
        existing_method = ""
    if (
        existing
        and existing_method == "semrush_top"
        and keyword_belongs_to_company(existing, slug, url, company)
        and brand_query_is_usable(existing, url or slug, company)
    ):
        return {"keyword": existing, "keyword_method": "cached"}
    if existing:
        print(
            f"[BRAND/KW] ignore stale {existing!r} for slug={slug}",
            flush=True,
        )
    if not title and url:
        try:
            from seo_pipeline import scrape_site

            site = scrape_site(url)
            title = (site.get("title") or "").strip()
            description = (site.get("meta_description") or "").strip()
        except Exception as e:
            print(f"[BRAND/DFS] ensure scrape fail {url}: {e}", flush=True)
    meta = resolve_brand_keyword(
        url,
        title=title,
        description=description,
        company_hint=company,
    )
    if slug and meta.get("keyword"):
        save_brand_search_keyword(slug, meta)
        os.environ["SPY_BRAND_KEYWORD"] = meta["keyword"]
    return meta


def influencer_search_query(
    slug: str,
    *,
    name: str = "",
    domain: str = "",
    url: str = "",
    is_client: bool = False,
    override: str = "",
) -> str:
    """Client search term = brand-search LLM keyword. Peers keep the pack/heuristic."""
    if override and is_client:
        return override.strip()
    if is_client:
        site = url or (f"https://{domain}/" if domain else "")
        meta = ensure_brand_search_keyword(slug, url=site, company=name or slug)
        kw = str(meta.get("keyword") or "").strip()
        if kw and brand_query_is_usable(kw, site or domain, name or slug):
            return kw
    from tiktok_brand_filter import search_query

    return search_query(name or slug, domain=domain)


def _pct(new: Optional[int], old: Optional[int]) -> Optional[float]:
    """Growth %: ((new - old) / old) * 100. Missing or 0 baseline → n/d."""
    if new is None:
        return None
    try:
        new_i = int(new)
    except (TypeError, ValueError):
        return None
    if old is None or old == 0:
        return None
    try:
        old_i = int(old)
    except (TypeError, ValueError):
        return None
    if old_i == 0:
        return None
    return round(((new_i - old_i) / old_i) * 100, 2)


def _pick_month(
    monthly: list[dict],
    year: int,
    month: int,
) -> Optional[int]:
    for m in monthly:
        if int(m.get("year") or 0) == year and int(m.get("month") or 0) == month:
            vol = m.get("search_volume")
            if vol is None:
                vol = m.get("volume")
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
    today = datetime.today()
    while sm:
        last = sm[-1]
        if int(last["year"]) == today.year and int(last["month"]) == today.month:
            sm = sm[:-1]
            continue
        break
    if not sm:
        return {
            "latest": None,
            "comparisons": {},
            "monthly": [],
        }
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


def _dfs_auth() -> requests.auth.HTTPBasicAuth:
    if not DATAFORSEO_USER or not DATAFORSEO_PASS:
        raise RuntimeError("DATAFORSEO_USER / DATAFORSEO_PASS ausentes")
    return requests.auth.HTTPBasicAuth(DATAFORSEO_USER, DATAFORSEO_PASS)


def _cache_month() -> str:
    today = datetime.today()
    return f"{today.year:04d}-{today.month:02d}"


def _cache_path(location_code: int, language_code: str) -> Path:
    return (
        _metricas_dir()
        / "_cache"
        / f"dfs-labs-{int(location_code)}-{language_code}-{_cache_month()}.json"
    )


def _load_volume_cache(location_code: int, language_code: str) -> dict[str, dict]:
    path = _cache_path(location_code, language_code)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def _save_volume_cache(
    location_code: int,
    language_code: str,
    items: dict[str, dict],
) -> None:
    path = _cache_path(location_code, language_code)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "month": _cache_month(),
                    "location_code": int(location_code),
                    "language_code": language_code,
                    "items": items,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[BRAND/DFS] cache write fail: {e}", flush=True)


def _post_dfs(url: str, payload: list[dict], *, label: str) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for attempt in range(2):
        r = requests.post(url, auth=_dfs_auth(), json=payload, timeout=120)
        r.raise_for_status()
        js = r.json() if r.content else {}
        last = js if isinstance(js, dict) else {}
        task = (last.get("tasks") or [{}])[0] or {}
        ok = last.get("status_code") == 20000 and task.get("status_code") == 20000
        if ok:
            return last
        print(
            f"[BRAND/DFS] {label} status={last.get('status_code')} "
            f"task={task.get('status_code')} attempt={attempt}",
            flush=True,
        )
        if attempt == 0:
            time.sleep(2)
    return last


def _pack_volume_row(
    keyword: str,
    monthly: list[dict],
    *,
    info: dict[str, Any] | None = None,
    source: str,
    location_code: int,
    language_code: str,
) -> dict[str, Any]:
    analysis = analyze_monthly_brand(monthly)
    info = info or {}
    latest = analysis.get("latest") or {}
    print(
        f"[BRAND/DFS] '{keyword}' src={source} latest={latest.get('label')} "
        f"vol={latest.get('volume')} months={analysis.get('months_available')}",
        flush=True,
    )
    return {
        "keyword": keyword,
        "search_volume_avg": info.get("search_volume"),
        "cpc": info.get("cpc"),
        "competition": info.get("competition"),
        "last_updated_time": info.get("last_updated_time") or "",
        "location_code": location_code,
        "language_code": language_code,
        "source": source,
        **analysis,
    }


def _fetch_labs_overview(
    keywords: list[str],
    *,
    location_code: int,
    language_code: str,
) -> tuple[dict[str, dict], float]:
    payload = [{
        "keywords": keywords,
        "location_code": int(location_code),
        "language_code": language_code,
    }]
    print(
        f"[BRAND/DFS] labs keyword_overview {len(keywords)} kw "
        f"loc={location_code} lang={language_code}",
        flush=True,
    )
    js = _post_dfs(DATAFORSEO_LABS_URL, payload, label="labs")
    task = (js.get("tasks") or [{}])[0] or {}
    cost = float(task.get("cost") or js.get("cost") or 0) or (
        DFS_LABS_TASK_USD + DFS_LABS_KEYWORD_USD * len(keywords)
    )
    out: dict[str, dict] = {}
    if js.get("status_code") != 20000 or task.get("status_code") != 20000:
        return out, cost
    items: list[dict] = []
    for block in task.get("result") or []:
        items.extend((block or {}).get("items") or [])
    for item in items:
        kw = str(item.get("keyword") or "").strip()
        if not kw:
            continue
        info = item.get("keyword_info") or {}
        monthly = info.get("monthly_searches") or item.get("monthly_searches") or []
        if not monthly:
            print(f"[BRAND/DFS] labs '{kw}' sem monthly_searches", flush=True)
            continue
        out[kw.lower()] = _pack_volume_row(
            kw,
            monthly,
            info=info,
            source="dataforseo_labs",
            location_code=location_code,
            language_code=language_code,
        )
    return out, cost


def _fetch_volume_fallback(
    keywords: list[str],
    *,
    location_code: int,
    language_code: str,
    years_back: int = 6,
) -> tuple[dict[str, dict], float]:
    today = datetime.today()
    date_to = today.strftime("%Y-%m-%d")
    try:
        date_from = today.replace(year=today.year - years_back).strftime("%Y-%m-%d")
    except ValueError:
        date_from = today.replace(year=today.year - years_back, day=28).strftime("%Y-%m-%d")
    payload = [{
        "location_code": int(location_code),
        "language_code": language_code,
        "keywords": keywords,
        "date_from": date_from,
        "date_to": date_to,
        "search_partners": False,
    }]
    print(
        f"[BRAND/DFS] fallback search_volume {len(keywords)} kw "
        f"{date_from} -> {date_to}",
        flush=True,
    )
    js = _post_dfs(DATAFORSEO_VOLUME_URL, payload, label="search_volume")
    task = (js.get("tasks") or [{}])[0] or {}
    cost = float(task.get("cost") or js.get("cost") or 0) or DFS_VOLUME_TASK_USD
    out: dict[str, dict] = {}
    if js.get("status_code") != 20000 or task.get("status_code") != 20000:
        return out, cost
    for item in task.get("result") or []:
        kw = str(item.get("keyword") or "").strip()
        monthly = item.get("monthly_searches") or []
        if not kw or not monthly:
            continue
        out[kw.lower()] = _pack_volume_row(
            kw,
            monthly,
            info=item,
            source="dataforseo_google_ads",
            location_code=location_code,
            language_code=language_code,
        )
    return out, cost


def fetch_brand_volumes(
    keywords: list[str],
    *,
    location_code: int = LOCATION_CODE,
    language_code: str = LANGUAGE_CODE,
    years_back: int = 6,
) -> dict[str, dict]:
    """Labs keyword_overview first; old search_volume only if Labs has no series."""
    global LAST_USAGE
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
    usage = {
        "cost_usd": 0.0,
        "source": "dataforseo_labs",
        "keywords": len(kws),
        "cached": 0,
        "labs": 0,
        "fallback": 0,
        "note": "",
    }
    if not kws:
        LAST_USAGE = usage
        return {"_usage": usage}

    cache = _load_volume_cache(location_code, language_code)
    out: dict[str, dict] = {}
    missing: list[str] = []
    for kw in kws:
        hit = cache.get(kw.lower())
        monthly = (hit or {}).get("monthly") if isinstance(hit, dict) else None
        if hit and monthly:
            out[kw.lower()] = hit
            usage["cached"] += 1
        else:
            missing.append(kw)

    if missing:
        labs, labs_cost = _fetch_labs_overview(
            missing, location_code=location_code, language_code=language_code,
        )
        usage["cost_usd"] = round(usage["cost_usd"] + float(labs_cost or 0), 6)
        usage["labs"] = len(labs)
        still: list[str] = []
        for kw in missing:
            row = labs.get(kw.lower())
            if row and row.get("monthly"):
                out[kw.lower()] = row
                cache[kw.lower()] = row
            else:
                still.append(kw)
        if still:
            fb, fb_cost = _fetch_volume_fallback(
                still,
                location_code=location_code,
                language_code=language_code,
                years_back=years_back,
            )
            usage["cost_usd"] = round(usage["cost_usd"] + float(fb_cost or 0), 6)
            usage["fallback"] = len(fb)
            usage["source"] = "dataforseo_labs+google_ads"
            for kw in still:
                row = fb.get(kw.lower())
                if row and row.get("monthly"):
                    out[kw.lower()] = row
                    cache[kw.lower()] = row
        if labs or usage["fallback"]:
            _save_volume_cache(location_code, language_code, cache)

    if usage["cached"] and not usage["labs"] and not usage["fallback"]:
        usage["source"] = "cache"
        usage["cost_usd"] = 0.0
    if not usage["note"]:
        usage["note"] = (
            f"Labs ${DFS_LABS_TASK_USD:g}+${DFS_LABS_KEYWORD_USD:g}/kw · "
            f"{usage['keywords']} brands · cached={usage['cached']} "
            f"labs={usage['labs']} fallback={usage['fallback']}"
        )
    print(
        f"[BRAND/DFS] usage cost=${usage['cost_usd']} src={usage['source']} "
        f"cached={usage['cached']} labs={usage['labs']} fallback={usage['fallback']}",
        flush=True,
    )
    LAST_USAGE = dict(usage)
    out["_usage"] = usage
    return out


def _semrush_series_to_monthly(series: list[dict]) -> list[dict]:
    monthly: list[dict] = []
    for it in series or []:
        date = str(it.get("date") or "")
        parts = date.split("-")
        if len(parts) < 2:
            continue
        try:
            year, month = int(parts[0]), int(parts[1])
        except (TypeError, ValueError):
            continue
        monthly.append({
            "year": year,
            "month": month,
            "search_volume": int(it.get("branded") or 0),
        })
    return monthly


def fetch_semrush_branded_fallback(domain: str) -> dict[str, Any]:
    """Domain Overview branded traffic. Prefer database=all, else US."""
    clean = (domain or "").strip()
    if not clean:
        return {}
    try:
        from seo_pipeline import fetch_semrush_monthly_trend
    except Exception as e:
        print(f"[BRAND/SM] import fail: {e}", flush=True)
        return {}
    series: list = []
    used_db = ""
    for db in ("all", "us"):
        print(f"[BRAND/SM] branded fallback {clean} db={db}", flush=True)
        try:
            series = fetch_semrush_monthly_trend(clean, db=db) or []
        except Exception as e:
            print(f"[BRAND/SM] {clean} db={db} erro: {e}", flush=True)
            series = []
        if series:
            used_db = db
            break
        print(f"[BRAND/SM] {clean} db={db} empty", flush=True)
    if not series:
        return {}
    analysis = analyze_monthly_brand(_semrush_series_to_monthly(series))
    latest = analysis.get("latest") or {}
    print(
        f"[BRAND/SM] {clean} db={used_db} latest={latest.get('label')} "
        f"branded={latest.get('volume')} months={analysis.get('months_available')}",
        flush=True,
    )
    return {**analysis, "semrush_db": used_db, "source": "semrush_branded"}


def _apply_semrush_branded_if_empty(row: dict[str, Any], domain: str) -> dict[str, Any]:
    vol = row.get("latest_volume")
    if vol not in (None, 0):
        return row
    fb = fetch_semrush_branded_fallback(domain)
    latest = fb.get("latest") or {}
    if latest.get("volume") is None and not fb.get("monthly"):
        return row
    comps = fb.get("comparisons") or {}
    aug = august_windows(fb.get("monthly") or [])
    sm_db = str(fb.get("semrush_db") or "us")
    row.update({
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
        "vol_2026_08": aug.get("vol_2026_08"),
        "vol_2025_08": aug.get("vol_2025_08"),
        "vol_2024_08": aug.get("vol_2024_08"),
        "growth_26_24_pct": aug.get("growth_26_24_pct"),
        "comparisons": comps,
        "months_available": fb.get("months_available"),
        "oldest_label": fb.get("oldest_label"),
        "source": "semrush_branded",
        "market": "ALL" if sm_db == "all" else "US",
        "semrush_db": sm_db,
    })
    return row


def brand_report_for_entity(
    *,
    url: str,
    title: str = "",
    description: str = "",
    company_hint: str = "",
    domain: str = "",
    name: str = "",
    is_client: bool = False,
) -> dict[str, Any]:
    meta = resolve_brand_keyword(
        url or domain,
        title=title,
        description=description,
        company_hint=company_hint or name,
    )
    keyword = meta["keyword"]
    volumes = fetch_brand_volumes([keyword]) if keyword else {}
    if isinstance(volumes, dict):
        volumes.pop("_usage", None)
    data = volumes.get((keyword or "").lower()) or {}
    latest = data.get("latest") or {}
    comps = data.get("comparisons") or {}
    row = {
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
        "source": data.get("source") or ("n/c" if not data else "dataforseo_labs"),
        "market": "US",
        "usage": dict(LAST_USAGE),
        "keyword_method": meta.get("keyword_method") or "",
        "keyword_reason": meta.get("keyword_reason") or "",
        "semrush_volume": meta.get("semrush_volume"),
    }
    if not data.get("monthly") and meta.get("keyword_method") == "semrush_top":
        sm_vol = meta.get("semrush_volume")
        if sm_vol not in (None, ""):
            try:
                row["latest_volume"] = int(sm_vol)
                row["latest_label"] = row.get("latest_label") or datetime.today().strftime("%Y-%m")
                row["source"] = "semrush_positions"
            except (TypeError, ValueError):
                pass
        return row
    return _apply_semrush_branded_if_empty(row, row.get("domain") or "")


def august_windows(monthly: list[dict] | None, *, month: int = 8) -> dict[str, Any]:
    """Volumes de agosto 2026 / 2025 / 2024 + crescimento 2026 vs 2024."""
    rows = monthly or []
    v26 = _pick_month(rows, 2026, month)
    v25 = _pick_month(rows, 2025, month)
    v24 = _pick_month(rows, 2024, month)
    return {
        "vol_2026_08": v26,
        "vol_2025_08": v25,
        "vol_2024_08": v24,
        "growth_26_24_pct": _pct(v26, v24),
    }


def brand_reports_batch(entities: list[dict]) -> list[dict]:
    """Resolve keywords, one DFS call, map back to entities."""
    metas = []
    keywords = []
    for e in entities:
        meta = resolve_brand_keyword(
            e.get("url") or e.get("domain") or "",
            title=e.get("title") or "",
            description=e.get("description") or e.get("meta_description") or "",
            company_hint=e.get("company") or e.get("name") or e.get("title") or "",
        )
        metas.append(meta)
        if meta["keyword"]:
            keywords.append(meta["keyword"])
    volumes = fetch_brand_volumes(keywords)
    if isinstance(volumes, dict):
        volumes.pop("_usage", None)
    rows = []
    for e, meta in zip(entities, metas):
        kw = (meta["keyword"] or "").lower()
        data = volumes.get(kw) or {}
        latest = data.get("latest") or {}
        comps = data.get("comparisons") or {}
        aug = august_windows(data.get("monthly") or [])
        row = {
            "name": e.get("name") or e.get("company") or meta["domain_brand"] or kw,
            "domain": e.get("domain") or meta["domain_brand"],
            "url": e.get("url") or "",
            "is_client": bool(e.get("is_client")),
            "similaridade": e.get("similaridade") or ("Cliente" if e.get("is_client") else "—"),
            "brand_keyword": meta["keyword"],
            "keyword_method": meta.get("keyword_method") or "",
            "keyword_reason": meta.get("keyword_reason") or "",
            "domain_brand": meta["domain_brand"],
            "title_brand": meta["title_brand"],
            "site_title": meta.get("title") or e.get("title") or "",
            "site_description": meta.get("description") or e.get("description") or "",
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
            "vol_2026_08": aug.get("vol_2026_08"),
            "vol_2025_08": aug.get("vol_2025_08"),
            "vol_2024_08": aug.get("vol_2024_08"),
            "growth_26_24_pct": aug.get("growth_26_24_pct"),
            "comparisons": comps,
            "months_available": data.get("months_available"),
            "oldest_label": data.get("oldest_label"),
            "cpc": data.get("cpc"),
            "search_volume_avg": data.get("search_volume_avg"),
            "source": data.get("source") or ("n/c" if not data else "dataforseo_labs"),
            "market": "US",
            "semrush_volume": meta.get("semrush_volume"),
        }
        if not data.get("monthly") and meta.get("keyword_method") == "semrush_top":
            sm_vol = meta.get("semrush_volume")
            if sm_vol not in (None, ""):
                try:
                    row["latest_volume"] = int(sm_vol)
                    row["latest_label"] = row.get("latest_label") or datetime.today().strftime("%Y-%m")
                    row["source"] = "semrush_positions"
                except (TypeError, ValueError):
                    pass
            rows.append(row)
            continue
        rows.append(_apply_semrush_branded_if_empty(
            row, e.get("domain") or meta.get("domain_brand") or "",
        ))
    rows.sort(key=lambda r: (r.get("latest_volume") or 0), reverse=True)
    brand_reports_batch.last_usage = dict(LAST_USAGE)
    return rows
