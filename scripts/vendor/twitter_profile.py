# -*- coding: utf-8 -*-
"""Twitter/X profile — Google search + ScrapingBee profile fetch for followers."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus

import requests

TINYFISH_SEARCH = "https://api.search.tinyfish.ai"
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"

PROFILE_RE = re.compile(
    r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?:/|$|\?)",
    flags=re.I,
)
SKIP_HANDLES = {
    "home", "explore", "search", "settings", "i", "intent", "share", "hashtag",
    "login", "signup", "privacy", "tos", "about", "messages", "notifications",
    "compose", "status", "with_replies", "reposts", "highlights", "media",
}
FOLLOWERS_RE = re.compile(
    r"([\d][\d,.]*(?:\.\d+)?\s*[KkMmBb]?)\s*[Ff]ollowers",
    flags=re.I,
)
FOLLOWERS_HTML_RE = re.compile(
    r'(?:verified_)?followers[^<]{0,80}?>.*?([\d][\d,.]*(?:\.\d+)?[KkMmBb]?)\s*</[^>]+>\s*(?:<[^>]+>\s*)*[Ff]ollowers'
    r'|([\d][\d,.]*(?:\.\d+)?[KkMmBb]?)\s*(?:</span>\s*)+[Ff]ollowers',
    flags=re.I | re.S,
)


def _tf_key() -> str:
    key = (os.environ.get("TINYFISH_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("TINYFISH_API_KEY ausente")
    return key


def _sb_key() -> str:
    return (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip()


def _parse_count(raw: str) -> Optional[int]:
    if not raw:
        return None
    s = raw.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^([\d.]+)([KkMmBb])?$", s)
    if not m:
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else None
    num = float(m.group(1))
    suf = (m.group(2) or "").upper()
    if suf == "K":
        num *= 1_000
    elif suf == "M":
        num *= 1_000_000
    elif suf == "B":
        num *= 1_000_000_000
    return int(num)


def normalize_profile_url(url: str) -> str:
    m = PROFILE_RE.search(url or "")
    if not m:
        return ""
    handle = m.group(1)
    if handle.lower() in SKIP_HANDLES or handle.lower() == "status":
        return ""
    # reject status URLs
    if "/status/" in (url or "").lower():
        return ""
    return f"https://x.com/{handle}"


def handle_from_url(url: str) -> str:
    m = PROFILE_RE.search(url or "")
    h = (m.group(1) if m else "").strip()
    return h if h.lower() not in SKIP_HANDLES else ""


def _brand_tokens(company: str, domain: str = "") -> list[str]:
    raw = []
    for part in (company, domain.split(".")[0] if domain else ""):
        part = re.sub(r"[^a-z0-9]+", " ", (part or "").lower()).strip()
        if part:
            raw.append(part.replace(" ", ""))
            raw.append(part)
    out, seen = [], set()
    for r in raw:
        if r and r not in seen and len(r) >= 3:
            seen.add(r)
            out.append(r)
    return out


def tinyfish_search_twitter(company: str, *, location: str = "US") -> dict[str, Any]:
    t0 = time.time()
    q = f'{company} site:x.com OR site:twitter.com'
    r = requests.get(
        TINYFISH_SEARCH,
        params={
            "query": q,
            "location": location,
            "language": "en" if location.upper() == "US" else "pt",
            "page": 0,
        },
        headers={"X-API-Key": _tf_key()},
        timeout=45,
    )
    r.raise_for_status()
    data = r.json() if r.content else {}
    results = data.get("results") or []
    tokens = _brand_tokens(company)
    candidates = []
    for item in results:
        url = normalize_profile_url(str(item.get("url") or ""))
        if not url:
            # try to lift @handle from title/snippet
            blob = f"{item.get('title') or ''} {item.get('snippet') or ''}"
            m = re.search(r"@([A-Za-z0-9_]{1,15})", blob)
            if m and m.group(1).lower() not in SKIP_HANDLES:
                url = f"https://x.com/{m.group(1)}"
            else:
                continue
        handle = handle_from_url(url)
        if not handle:
            continue
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or item.get("description") or "")
        score = 0
        h_c = re.sub(r"[^a-z0-9]+", "", handle.lower())
        for tok in tokens:
            t = re.sub(r"[^a-z0-9]+", "", tok)
            if t and t == h_c:
                score += 80
            elif t and t in h_c:
                score += 40
            if t and t in re.sub(r"[^a-z0-9]+", "", title.lower()):
                score += 15
        followers_hint = None
        m = FOLLOWERS_RE.search(f"{title} {snippet}")
        if m:
            followers_hint = _parse_count(m.group(1))
            score += 10
        candidates.append({
            "url": url,
            "handle": handle,
            "title": title,
            "snippet": snippet,
            "followers_hint": followers_hint,
            "score": score,
        })
    candidates.sort(key=lambda x: x["score"], reverse=True)
    # dedupe by handle
    seen, uniq = set(), []
    for c in candidates:
        h = c["handle"].lower()
        if h in seen:
            continue
        seen.add(h)
        uniq.append(c)
    best = uniq[0] if uniq else None
    return {
        "ok": bool(best),
        "query": q,
        "profile": best,
        "candidates": uniq[:6],
        "elapsed_sec": round(time.time() - t0, 2),
    }


def scrapingbee_fetch_followers(profile_url: str, *, country: str = "us") -> dict[str, Any]:
    key = _sb_key()
    if not key or not profile_url:
        return {"ok": False, "followers": None, "followers_text": "", "credits": 0, "error": "missing key/url"}
    t0 = time.time()
    try:
        r = requests.get(
            SCRAPINGBEE_URL,
            params={
                "api_key": key,
                "url": profile_url,
                "render_js": "true",
                "premium_proxy": "true",
                "country_code": (country or "us").lower()[:2],
                "wait": "4000",
            },
            timeout=120,
        )
    except requests.RequestException as e:
        return {"ok": False, "followers": None, "followers_text": "", "credits": 0,
                "error": str(e)[:200], "elapsed_sec": round(time.time() - t0, 2)}
    credits = 0
    for h in ("Spb-cost", "Spb-credits-cost", "spb-cost"):
        if r.headers.get(h):
            try:
                credits = int(float(r.headers[h]))
            except Exception:
                pass
            break
    if not r.ok:
        return {"ok": False, "followers": None, "followers_text": "", "credits": credits,
                "error": f"HTTP {r.status_code}", "elapsed_sec": round(time.time() - t0, 2)}
    html = r.text or ""
    followers = None
    followers_text = ""
    # Strip tags then look for "15.2K Followers" (X markup varies a lot)
    plain = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    plain = re.sub(r"<style[\s\S]*?</style>", " ", plain, flags=re.I)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    m = re.search(
        r"([\d][\d,.]*(?:\.\d+)?\s*[KkMmBb]?)\s+Followers\b",
        plain,
        flags=re.I,
    )
    if not m:
        # fallback on raw HTML near verified_followers
        m = re.search(
            r"verified_followers[\s\S]{0,240}?([\d][\d,.]*(?:\.\d+)?[KkMmBb]?)\s*[\s\S]{0,40}?[Ff]ollowers",
            html,
            flags=re.I,
        )
    if m:
        followers_text = m.group(1).strip()
        followers = _parse_count(followers_text)
    title_m = re.search(r"<title>([^<]+)</title>", html, flags=re.I)
    return {
        "ok": followers is not None,
        "followers": followers,
        "followers_text": followers_text,
        "page_title": (title_m.group(1).strip() if title_m else ""),
        "credits": credits,
        "elapsed_sec": round(time.time() - t0, 2),
        "error": None if followers is not None else "followers not found in profile HTML",
    }


def _llm_pick_x(
    *,
    company: str,
    domain: str,
    cards: list[dict[str, Any]],
    website: str = "",
) -> dict[str, Any]:
    empty = {"ok": False, "url": "", "reason": "", "i": -1}
    if not cards:
        return empty
    lines = []
    for i, card in enumerate(cards):
        lines.append(
            f"[{i}] url={card.get('url')!r} handle={card.get('handle')!r} "
            f"title={card.get('title')!r} description={card.get('snippet')!r}"
        )
    prompt = (
        "You pick the official X / Twitter profile of ONE company, or none.\n\n"
        f"Company / brand: {company or domain}\n"
        f"Website: {website or domain}\n"
        f"Domain: {domain}\n\n"
        "Return JSON only, no markdown:\n"
        '{"official_i":0,"reason":"short"}\n\n'
        "Rules:\n"
        "- official_i is THIS company's own account.\n"
        "- Use -1 if none of the candidates is that company.\n"
        "- A meme coin, rapper, car, or lookalike handle is not this company.\n"
        "- Prefer a title/bio that mentions the website or product.\n"
        "- More followers is not a reason to pick a lookalike.\n\n"
        + "\n".join(lines)
    )
    try:
        from llm_trace import chat, extract_json

        raw = chat(
            task="x_oficial",
            prompt=prompt,
            max_tokens=300,
            temperature=0.1,
            extra={"company": company, "domain": domain},
        )
        data = extract_json(raw)
        try:
            idx = int(data.get("official_i", -1))
        except (TypeError, ValueError):
            idx = -1
        reason = str(data.get("reason") or "")[:160]
        if 0 <= idx < len(cards):
            return {
                "ok": True,
                "url": cards[idx].get("url") or "",
                "reason": reason or "llm",
                "i": idx,
            }
        return {"ok": True, "url": "", "reason": reason or "none", "i": -1}
    except Exception as e:
        print(f"[TW] llm pick failed: {e}", flush=True)
        return {"ok": False, "url": "", "reason": str(e)[:160], "i": -1}


def analyze_company(
    company: str,
    *,
    domain: str = "",
    market: str = "us",
    query: str | None = None,
) -> dict[str, Any]:
    t_all = time.time()
    q = (query or company or (domain.split(".")[0] if domain else "")).strip()
    if not q:
        raise ValueError("company/query required")
    loc = "US" if (market or "us").lower().startswith("us") else "BR"
    usage = {
        "search_cost_usd": 0.0,
        "scrapingbee_credits": 0,
        "source": "tinyfish_search + scrapingbee_profile",
    }

    search = tinyfish_search_twitter(q, location=loc)
    cards = list(search.get("candidates") or [])
    pick = _llm_pick_x(
        company=q,
        domain=domain,
        cards=cards,
        website=f"https://{domain}/" if domain else "",
    )
    prof = search.get("profile") or {}
    if pick.get("url"):
        prof = next(
            (
                c for c in cards
                if (c.get("url") or "").rstrip("/") == str(pick.get("url") or "").rstrip("/")
            ),
            {"url": pick["url"], "handle": handle_from_url(pick["url"]), "title": "", "snippet": ""},
        )
    elif pick.get("ok"):
        prof = {}
    followers = prof.get("followers_hint")
    followers_text = ""
    followers_source = "google_snippet" if followers is not None else None
    if pick.get("ok"):
        followers_source = (followers_source or "llm") if followers is not None else "llm"

    if prof.get("url"):
        fetched = scrapingbee_fetch_followers(prof["url"], country=loc.lower()[:2])
        usage["scrapingbee_credits"] = int(fetched.get("credits") or 0)
        if fetched.get("followers") is not None:
            followers = fetched["followers"]
            followers_text = fetched.get("followers_text") or ""
            followers_source = "scrapingbee_profile+llm" if pick.get("ok") else "scrapingbee_profile"
        elif followers is None:
            usage["profile_fetch_error"] = fetched.get("error")

    handle = (prof.get("handle") or handle_from_url(str(prof.get("url") or ""))).lstrip("@")
    usage["llm_pick"] = {"ok": pick.get("ok"), "reason": pick.get("reason"), "i": pick.get("i")}
    return {
        "ok": bool(prof.get("url")),
        "company": company,
        "domain": domain,
        "query": search.get("query") or q,
        "search_url": f"https://www.google.com/search?q={quote_plus(search.get('query') or q)}",
        "profile_url": prof.get("url") or "",
        "handle": handle,
        "title": prof.get("title") or "",
        "snippet": prof.get("snippet") or "",
        "followers": followers,
        "followers_text": followers_text or (f"{followers:,}" if isinstance(followers, int) else ""),
        "followers_source": followers_source,
        "candidates": search.get("candidates") or [],
        "usage": usage,
        "elapsed_sec": round(time.time() - t_all, 2),
        "error": None if prof.get("url") else "Twitter/X profile not found",
    }
