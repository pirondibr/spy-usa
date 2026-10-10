# -*- coding: utf-8 -*-
"""LinkedIn company/profile — Google search; followers from snippet (page often bot-blocked)."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus

import requests

TINYFISH_SEARCH = "https://api.search.tinyfish.ai"

COMPANY_RE = re.compile(
    r"https?://(?:[a-z]+\.)?linkedin\.com/company/([^/?#]+)/?",
    flags=re.I,
)
PERSON_RE = re.compile(
    r"https?://(?:[a-z]+\.)?linkedin\.com/in/([^/?#]+)/?",
    flags=re.I,
)
FOLLOWERS_RE = re.compile(
    r"([\d][\d,.]*(?:\.\d+)?\s*[KkMmBb]?)\s+followers?\b",
    flags=re.I,
)


def _tf_key() -> str:
    key = (os.environ.get("TINYFISH_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("TINYFISH_API_KEY ausente")
    return key


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


def normalize_linkedin_url(url: str) -> tuple[str, str]:
    """Return (kind, clean_url) where kind is company|person|''."""
    u = (url or "").strip()
    m = COMPANY_RE.search(u)
    if m:
        slug = m.group(1).strip("/")
        return "company", f"https://www.linkedin.com/company/{slug}"
    m = PERSON_RE.search(u)
    if m:
        slug = m.group(1).strip("/")
        return "person", f"https://www.linkedin.com/in/{slug}"
    return "", ""


def tinyfish_search_linkedin(company: str, *, location: str = "US") -> dict[str, Any]:
    t0 = time.time()
    q = f"{company} linkedin"
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
        kind, url = normalize_linkedin_url(str(item.get("url") or ""))
        if not url:
            continue
        # skip posts
        if "/posts/" in (item.get("url") or "").lower() or "/pulse/" in (item.get("url") or "").lower():
            continue
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or item.get("description") or "")
        slug = url.rstrip("/").split("/")[-1]
        slug_c = re.sub(r"[^a-z0-9]+", "", slug.lower())
        score = 30 if kind == "company" else 10
        for tok in tokens:
            t = re.sub(r"[^a-z0-9]+", "", tok)
            if t and t == slug_c:
                score += 80
            elif t and t in slug_c:
                score += 40
            if t and t in re.sub(r"[^a-z0-9]+", "", title.lower()):
                score += 20
            if t and t in re.sub(r"[^a-z0-9]+", "", snippet.lower()):
                score += 10
        followers = None
        followers_text = ""
        m = FOLLOWERS_RE.search(f"{title} {snippet}")
        if m:
            followers_text = m.group(1).strip()
            followers = _parse_count(followers_text)
            score += 15
        candidates.append({
            "url": url,
            "kind": kind,
            "slug": slug,
            "title": title,
            "snippet": snippet,
            "followers": followers,
            "followers_text": followers_text,
            "score": score,
        })
    candidates.sort(key=lambda x: x["score"], reverse=True)
    seen, uniq = set(), []
    for c in candidates:
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        uniq.append(c)
    # Prefer company page with brand match
    best = next((c for c in uniq if c["kind"] == "company" and c["score"] >= 40), None)
    if not best:
        best = uniq[0] if uniq else None
    return {
        "ok": bool(best),
        "query": q,
        "profile": best,
        "candidates": uniq[:6],
        "elapsed_sec": round(time.time() - t0, 2),
    }


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
        "source": "tinyfish_search (followers from Google snippet)",
        "note": "LinkedIn pages often bot-block Fetch; snippet followers used when present",
    }

    search = tinyfish_search_linkedin(q, location=loc)
    prof = search.get("profile") or {}

    return {
        "ok": bool(prof.get("url")),
        "company": company,
        "domain": domain,
        "query": search.get("query") or q,
        "search_url": f"https://www.google.com/search?q={quote_plus(search.get('query') or q)}",
        "profile_url": prof.get("url") or "",
        "kind": prof.get("kind") or "",
        "slug": prof.get("slug") or "",
        "title": prof.get("title") or "",
        "snippet": prof.get("snippet") or "",
        "followers": prof.get("followers"),
        "followers_text": prof.get("followers_text") or (
            f"{prof['followers']:,}" if isinstance(prof.get("followers"), int) else ""
        ),
        "followers_source": "google_snippet" if prof.get("followers") is not None else None,
        "candidates": search.get("candidates") or [],
        "usage": usage,
        "elapsed_sec": round(time.time() - t_all, 2),
        "error": None if prof.get("url") else "LinkedIn profile not found",
    }
