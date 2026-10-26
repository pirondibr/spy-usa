# -*- coding: utf-8 -*-
"""LinkedIn company page — Google snippet first, OpenRouter :online (Exa) if no count."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus

import requests

from google_serp import google_serp, has_google_serp

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_CALL_USD = float(os.environ.get("SPY_COST_OPENROUTER_CALL", "0.01") or 0.01)
_OPENROUTER_WEB_USD = float(os.environ.get("SPY_COST_OPENROUTER_WEB", "0.007") or 0.007)

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
_SKIP_PATH = re.compile(r"/(?:posts|pulse|jobs|life|about|people|admin)(?:/|$)", flags=re.I)
_STOP = {
    "inc", "llc", "ltd", "ai", "the", "and", "company", "co", "corp",
    "official", "app", "group", "studio", "labs", "lab", "io",
}


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
    raw: list[str] = []
    for part in (company, domain.split(".")[0] if domain else ""):
        cleaned = re.sub(r"[^a-z0-9]+", " ", (part or "").lower()).strip()
        if not cleaned:
            continue
        raw.append(cleaned.replace(" ", ""))
        for word in cleaned.split():
            if word not in _STOP:
                raw.append(word)
    out, seen = [], set()
    for r in raw:
        if r and r not in seen and len(r) >= 3:
            seen.add(r)
            out.append(r)
    return out


def normalize_linkedin_url(url: str) -> tuple[str, str]:
    """Return (kind, clean_url) where kind is company|person|''."""
    u = (url or "").strip()
    if _SKIP_PATH.search(u.split("linkedin.com", 1)[-1] if "linkedin.com" in u.lower() else u):
        # still keep /company/{slug}/jobs → company root
        m = COMPANY_RE.search(u)
        if m:
            slug = m.group(1).strip("/")
            if slug.lower() not in {"jobs", "life", "about", "people", "posts", "admin"}:
                return "company", f"https://www.linkedin.com/company/{slug}"
        return "", ""
    m = COMPANY_RE.search(u)
    if m:
        slug = m.group(1).strip("/")
        return "company", f"https://www.linkedin.com/company/{slug}"
    m = PERSON_RE.search(u)
    if m:
        slug = m.group(1).strip("/")
        return "person", f"https://www.linkedin.com/in/{slug}"
    return "", ""


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _is_brand(slug: str, title: str, snippet: str, tokens: list[str]) -> bool:
    slug_c = _compact(slug)
    title_c = _compact(title)
    snip_c = _compact(snippet)
    for tok in tokens:
        t = _compact(tok)
        if not t:
            continue
        if t == slug_c or t in slug_c or (len(slug_c) >= 4 and slug_c in t):
            return True
        if t in title_c or t in snip_c:
            return True
    return False


def _has_snippet_followers(items: list[dict[str, Any]]) -> bool:
    for item in items or []:
        kind, url = normalize_linkedin_url(str(item.get("url") or ""))
        if kind != "company" or not url:
            continue
        blob = f"{item.get('title') or ''} {item.get('snippet') or item.get('description') or ''}"
        if FOLLOWERS_RE.search(blob):
            return True
    return False


def _candidate_from_item(item: dict[str, Any], tokens: list[str]) -> Optional[dict[str, Any]]:
    kind, url = normalize_linkedin_url(str(item.get("url") or ""))
    if not url:
        return None
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or item.get("description") or "")
    slug = url.rstrip("/").split("/")[-1]
    score = 30 if kind == "company" else 10
    slug_c = _compact(slug)
    title_c = _compact(title)
    snip_c = _compact(snippet)
    brand = False
    for tok in tokens:
        t = _compact(tok)
        if not t:
            continue
        if t == slug_c:
            score += 80
            brand = True
        elif t in slug_c or (len(slug_c) >= 4 and slug_c in t):
            score += 40
            brand = True
        if t in title_c:
            score += 20
            brand = True
        if t in snip_c:
            score += 10
            brand = True
    followers = None
    followers_text = ""
    m = FOLLOWERS_RE.search(f"{title} {snippet}")
    if m:
        followers_text = m.group(1).strip()
        followers = _parse_count(followers_text)
        score += 15
    return {
        "url": url,
        "kind": kind,
        "slug": slug,
        "title": title,
        "snippet": snippet,
        "followers": followers,
        "followers_text": followers_text,
        "score": score,
        "brand": brand or _is_brand(slug, title, snippet, tokens),
        "position": int(item.get("position") or 99),
    }


def _pick_profile(candidates: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    companies = [c for c in candidates if c.get("kind") == "company"]
    # First Google company link that is the brand.
    first_brand = next((c for c in companies if c.get("brand")), None)
    if first_brand:
        return first_brand
    scored = next((c for c in companies if int(c.get("score") or 0) >= 40), None)
    if scored:
        return scored
    return companies[0] if companies else (candidates[0] if candidates else None)


def search_linkedin_brand(
    company: str,
    *,
    domain: str = "",
    market: str = "us",
) -> dict[str, Any]:
    tokens = _brand_tokens(company, domain)
    brand = (company or (domain.split(".")[0] if domain else "")).strip()
    queries = [
        (f"{brand} site:linkedin.com/company", "linkedin.com"),
        (f"{brand} linkedin", "linkedin.com"),
    ]
    seen_q = set()
    all_candidates: list[dict[str, Any]] = []
    used_query = ""
    used_source = ""
    usage = {
        "search_cost_usd": 0.0,
        "source": "",
        "providers_tried": [],
        "note": "LinkedIn pages often bot-block Fetch; snippet followers used when present",
    }
    t0 = time.time()
    for q, domains in queries:
        if q.lower() in seen_q:
            continue
        seen_q.add(q.lower())
        serp = google_serp(
            q,
            market=market,
            include_domains=domains,
            accept=_has_snippet_followers,
        )
        usage["search_cost_usd"] = round(
            float(usage["search_cost_usd"]) + float(serp.get("cost_usd") or 0), 6
        )
        usage["providers_tried"] = list(
            dict.fromkeys(list(usage["providers_tried"]) + list(serp.get("providers_tried") or []))
        )
        if serp.get("credits"):
            usage["scrapingbee_credits"] = int(serp["credits"])
        batch = []
        for item in serp.get("items") or []:
            cand = _candidate_from_item(item, tokens)
            if cand:
                batch.append(cand)
        # keep first-page order; merge follower snippets from /jobs etc.
        uniq, seen = [], {}
        for c in batch:
            prev = seen.get(c["url"])
            if prev is None:
                seen[c["url"]] = c
                uniq.append(c)
            elif prev.get("followers") is None and c.get("followers") is not None:
                prev["followers"] = c["followers"]
                prev["followers_text"] = c.get("followers_text") or ""
                prev["score"] = max(int(prev.get("score") or 0), int(c.get("score") or 0))
        all_candidates.extend(c for c in uniq if c["url"] not in {x["url"] for x in all_candidates})
        picked = _pick_profile(uniq)
        if picked and (picked.get("brand") or picked.get("kind") == "company"):
            used_query = q
            used_source = str(serp.get("source") or "")
            usage["source"] = used_source
            return {
                "ok": True,
                "query": q,
                "profile": picked,
                "candidates": (uniq or all_candidates)[:6],
                "usage": usage,
                "elapsed_sec": round(time.time() - t0, 2),
            }
        if not used_query:
            used_query = q
            used_source = str(serp.get("source") or "")
            usage["source"] = used_source
    picked = _pick_profile(all_candidates)
    return {
        "ok": bool(picked),
        "query": used_query,
        "profile": picked,
        "candidates": all_candidates[:6],
        "usage": usage,
        "elapsed_sec": round(time.time() - t0, 2),
    }


def _extract_llm_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    raw = re.sub(r"^[^{\[]*", "", raw)
    raw = re.sub(r"[^}\]]*$", "", raw)
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _followers_from_text(text: str) -> Optional[int]:
    m = FOLLOWERS_RE.search(text or "")
    if not m:
        return None
    return _parse_count(m.group(1))


def openrouter_online_linkedin(
    company: str,
    *,
    domain: str = "",
    known_url: str = "",
) -> dict[str, Any]:
    """Gemini via OpenRouter web plugin (Exa, LinkedIn-only). Not native Google Search."""
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "error": "OPENROUTER_API_KEY missing"}
    model = (os.environ.get("OPENROUTER_MODEL") or "google/gemini-2.5-flash").strip()
    brand = (company or (domain.split(".")[0] if domain else "")).strip()
    if known_url:
        prompt = (
            f"The official LinkedIn company page for {brand} ({domain or brand}) is {known_url}.\n"
            "How many followers does THAT page have right now? Use the web results.\n"
            "Reply JSON only, no markdown:\n"
            f'{{"followers":123456,"followers_text":"123K","url":"{known_url}"}}\n'
            "Do not invent a round number if no count is in the results. "
            "Keep the same /company/ URL."
        )
    else:
        prompt = (
            f"Find the official LinkedIn company page for {brand} (website {domain or brand}) "
            "and how many followers it has. Use the web results.\n"
            "Reply JSON only, no markdown:\n"
            '{"followers":123456,"followers_text":"123K","url":"https://www.linkedin.com/company/..."}\n'
            "Only the company's own /company/ page, never a person, job, or post."
        )
    t0 = time.time()
    try:
        from llm_trace import chat

        text = chat(
            task="linkedin",
            prompt=prompt,
            max_tokens=400,
            temperature=0.1,
            plugins=[
                {
                    "id": "web",
                    "engine": "exa",
                    "max_results": 5,
                    "include_domains": ["linkedin.com"],
                }
            ],
            extra={"company": brand, "domain": domain},
        )
    except Exception as e:
        return {"ok": False, "error": str(e), "elapsed_sec": round(time.time() - t0, 2)}
    msg = {}
    data = _extract_llm_json(text)
    kind, url = normalize_linkedin_url(str(data.get("url") or known_url or ""))
    followers = data.get("followers")
    if isinstance(followers, str):
        followers = _parse_count(followers)
    if not isinstance(followers, (int, float)) or float(followers) <= 0:
        followers = _followers_from_text(text) or _parse_count(str(data.get("followers_text") or ""))
    if isinstance(followers, float):
        followers = int(followers)
    if isinstance(followers, int) and not (1 <= followers < 2_000_000_000):
        followers = None
    if known_url:
        _, keep = normalize_linkedin_url(known_url)
        if keep:
            url = keep
            kind = "company" if "/company/" in keep else kind
    citations = []
    for ann in msg.get("annotations") or []:
        cite = ann.get("url_citation") or {}
        href = str(cite.get("url") or "")
        if href:
            citations.append(href)
    return {
        "ok": bool(url or followers),
        "url": url,
        "kind": kind,
        "followers": followers,
        "followers_text": str(data.get("followers_text") or "").strip()
        or (f"{followers:,}" if isinstance(followers, int) else ""),
        "raw": text[:500],
        "citations": citations[:8],
        "model": model,
        "cost_usd": round(_OPENROUTER_CALL_USD + _OPENROUTER_WEB_USD, 4),
        "elapsed_sec": round(time.time() - t0, 2),
        "error": None if (url or followers) else "OpenRouter online returned no LinkedIn data",
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
    search: dict[str, Any] = {
        "profile": {},
        "query": q,
        "candidates": [],
        "usage": {"search_cost_usd": 0.0, "source": "", "providers_tried": []},
    }
    if has_google_serp():
        search = search_linkedin_brand(q, domain=domain, market=market)
    prof = dict(search.get("profile") or {})
    usage = dict(search.get("usage") or {})
    usage.setdefault(
        "note",
        "Google snippet first; OpenRouter :online (Exa, linkedin.com) if followers are missing",
    )
    followers_source = "google_snippet" if prof.get("followers") is not None else None
    known_url = str(prof.get("url") or "")
    if (prof.get("kind") or "") == "person":
        known_url = ""
    if prof.get("followers") is None:
        online = openrouter_online_linkedin(
            q, domain=domain, known_url=known_url
        )
        usage["openrouter_online"] = {
            "ok": bool(online.get("ok")),
            "error": online.get("error"),
            "elapsed_sec": online.get("elapsed_sec"),
            "citations": online.get("citations") or [],
            "model": online.get("model"),
        }
        usage["search_cost_usd"] = round(
            float(usage.get("search_cost_usd") or 0) + float(online.get("cost_usd") or 0), 6
        )
        if online.get("followers") is not None:
            prof["followers"] = online["followers"]
            prof["followers_text"] = online.get("followers_text") or ""
            followers_source = "openrouter_online"
            print(
                f"[LI] openrouter online followers={online.get('followers_text') or online.get('followers')} "
                f"url={online.get('url') or prof.get('url') or '—'}",
                flush=True,
            )
        online_url = str(online.get("url") or "")
        take_url = online_url and (
            not prof.get("url")
            or ((prof.get("kind") or "") == "person" and "/company/" in online_url)
        )
        if take_url:
            kind, url = normalize_linkedin_url(online_url)
            if url:
                prof["url"] = url
                prof["kind"] = kind or "company"
                prof["slug"] = url.rstrip("/").split("/")[-1]
        if online.get("error") and prof.get("followers") is None:
            usage["openrouter_error"] = online["error"]

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
        "followers_source": followers_source,
        "candidates": search.get("candidates") or [],
        "usage": usage,
        "elapsed_sec": round(time.time() - t_all, 2),
        "error": None if prof.get("url") else "LinkedIn profile not found",
    }
