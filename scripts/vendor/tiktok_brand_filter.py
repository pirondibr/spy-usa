# -*- coding: utf-8 -*-
"""Classify TikTok posts as confirmed / probable / unrelated for a brand.

No API keys. Subtitles come from the TikTok CDN URL already on the Apify item.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests

_PROMO_RE = re.compile(
    r"(?:#ad\b|#sponsored\b|#gifted\b|#partner\b|link in bio|discount code|"
    r"use code|promo code|#affiliat)",
    flags=re.I,
)
_RESELL_RE = re.compile(
    r"(?:cracked|nulled|free download|giveaway|pirat|warez|gratis\b)",
    flags=re.I,
)
_VTT_SKIP = re.compile(r"^(?:WEBVTT|NOTE\b|STYLE\b|\d+$)", flags=re.I)
_TS = re.compile(r"\d{2}:\d{2}")

# Common English / first-name tokens that collide with other TikTok meanings.
_COMMON = {
    "apple", "amazon", "arcade", "arcades", "bloom", "box", "cash", "cloud",
    "core", "crystal", "cursor", "daisy", "digital", "edge", "free", "game",
    "go", "hub", "jenni", "jennie", "lab", "labs", "live", "max", "media",
    "meta", "next", "nova", "open", "orange", "pay", "pixel", "play", "plus",
    "pro", "pulse", "rose", "sage", "shift", "shop", "smart", "social",
    "spark", "stack", "studio", "target", "wave",
}

_DEFAULT_POS = (
    "ai", "app", "software", "tool", "saas", "review", "product", "startup",
    "ads", "ugc", "code", "agent", "llm",
)

# Real official suffixes after the brand token. Digit-letter fakes (0fficial) stay out.
_OFFICIAL_TAILS = {
    "", "official", "oficial", "hq", "app", "ai", "io", "inc",
    "br", "usa", "us", "uk", "team", "tv",
}
_IMPERSONATOR_RE = re.compile(
    r"(?:0fficial|offici4l|off1cial|0ficial)",
    flags=re.I,
)

BRANDS: dict[str, dict[str, Any]] = {
    "higgsfield": {
        "name": "higgsfield",
        "query": "higgsfield ai",
        "token": r"higgsfield",
        "hashtag_prefix": "higgsfield",
        "mention": "higgsfield",
        "domain": "higgsfield.ai",
        "handle_official": "higgsfield",
        "ambiguous": False,
        "pos": [],
        "neg": [],
    },
    "arcads": {
        "name": "arcads",
        "query": "arcads",
        "token": r"arcads",
        "hashtag_prefix": "arcads",
        "mention": "arcads",
        "domain": "arcads.ai",
        "handle_official": "arcads",
        "ambiguous": False,
        "pos": [],
        "neg": ["arcade", "arcades", "fliperama", "arcadegame"],
    },
    "cursor": {
        "name": "cursor",
        "query": "cursor ai",
        "token": r"cursor",
        "hashtag_prefix": "cursor",
        "mention": "cursor",
        "domain": "cursor.com",
        "handle_official": "cursor_ai",
        "ambiguous": True,
        "pos": [
            "ai", "code", "coding", "coder", "agent", "ide", "vscode",
            "composer", "vibe", "llm", "gpt", "claude", "editor",
            "developer", "devtools", "anysphere",
        ],
        "neg": [
            "mouse", "pointer", "roblox", "css", "pointer-events",
            "caret", "blink", "i-beam",
        ],
    },
    "jenni": {
        "name": "jenni",
        "query": "jenni ai",
        "token": r"jenni(?:\s*ai)?",
        "hashtag_prefix": "jenni",
        "mention": "jenni",
        "domain": "jenni.ai",
        "handle_official": "jenni_ai",
        "ambiguous": True,
        "pos": [
            "ai", "essay", "writer", "writing", "paper", "academic",
            "homework", "cite", "citation", "research",
        ],
        "neg": [
            "blackpink", "jennie", "kpop", "k-pop", "blink", "lisa",
            "jisoo", "rosé", "roseanne",
        ],
    },
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def handle_is_impersonator(handle: str) -> bool:
    """Leetspeak 'official' (0/1/4) — typical fake brand accounts."""
    return bool(_IMPERSONATOR_RE.search((handle or "").lstrip("@")))


def handle_matches_brand(handle: str, brand: str, domain: str = "") -> bool:
    """True when the handle contains the brand or domain token (not a short prefix)."""
    got = _slug(handle)
    if not got or len(got) < 3:
        return False
    keys: list[str] = []
    raw_brand = (brand or "").strip()
    raw_dom = (domain or "").lower().lstrip("www.").split("/")[0]
    host = raw_dom.split(".")[0] if raw_dom else ""
    for raw in (raw_brand.split()[0] if raw_brand else "", host):
        tok = _slug(raw)
        if tok and len(tok) >= 3 and tok not in keys:
            keys.append(tok)
    for tok in keys:
        if got == tok or tok in got:
            return True
        if got in tok and len(got) >= max(5, int(len(tok) * 0.75)):
            return True
    return False


def _official_tail_ok(tail: str) -> bool:
    return _slug(tail) in _OFFICIAL_TAILS


def _word_re(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){token}(?![a-z0-9])", flags=re.I)


def resolve_brand(
    brand: str,
    *,
    domain: str = "",
    official_handle: str = "",
) -> dict[str, Any]:
    raw = (brand or "").strip()
    key = _slug(raw.split()[0] if raw else "") or _slug(domain.split(".")[0] if domain else "")
    aliases = {
        "jenniai": "jenni",
        "cursorai": "cursor",
        "higgsfieldai": "higgsfield",
        "arcadsai": "arcads",
    }
    known = BRANDS.get(key) or BRANDS.get(aliases.get(key, ""))
    if known:
        cfg = dict(known)
    else:
        token = re.escape((raw.split()[0] if raw else key) or key)
        host = (domain or "").lower().lstrip("www.")
        ambiguous = key in _COMMON or (len(key) <= 4 and not any(ch.isdigit() for ch in key))
        cfg = {
            "name": raw or key,
            "query": f"{raw or key} ai".strip(),
            "token": token,
            "hashtag_prefix": key,
            "mention": key,
            "domain": host,
            "handle_official": key,
            "ambiguous": ambiguous,
            "pos": list(_DEFAULT_POS) if ambiguous else [],
            "neg": [],
        }
    if official_handle:
        hint = official_handle.lstrip("@").lower()
        if handle_is_impersonator(hint):
            hint = ""
        elif hint and not handle_matches_brand(
            hint, str(cfg.get("name") or raw or key), str(cfg.get("domain") or domain or "")
        ):
            # Gemini/Google often return a bigger unrelated account. Keep only
            # brand-like handles; website-trusted exceptions stay exact-match
            # via caller passing a matching hint.
            hint = ""
        if hint:
            cfg["handle_official"] = hint
    if domain and not cfg.get("domain"):
        cfg["domain"] = domain.lower().lstrip("www.")
    return cfg


def search_query(brand: str, *, domain: str = "") -> str:
    return str(resolve_brand(brand, domain=domain).get("query") or f"{brand} ai").strip()


def _channel(post: dict[str, Any]) -> dict[str, Any]:
    ch = post.get("channel")
    return ch if isinstance(ch, dict) else {}


def _username(post: dict[str, Any]) -> str:
    ch = _channel(post)
    return str(ch.get("username") or post.get("user") or post.get("handle") or "").lstrip("@").lower()


def _hashtags(post: dict[str, Any]) -> list[str]:
    raw = post.get("hashtags") or []
    if isinstance(raw, str):
        raw = re.findall(r"#?([A-Za-z0-9_]+)", raw)
    out = []
    for h in raw:
        s = str(h or "").lstrip("#").lower()
        if s:
            out.append(s)
    return out


def _title(post: dict[str, Any]) -> str:
    return str(post.get("title") or post.get("text") or post.get("desc") or "")


def _blob(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p)


def _has_token(text: str, token: str) -> bool:
    if not text or not token:
        return False
    return bool(_word_re(token).search(text))


def _has_any(text: str, words: list[str]) -> bool:
    low = (text or "").lower()
    return any(_has_token(low, w) or w.lower() in low for w in words if w)


def _official(cfg: dict[str, Any], username: str) -> bool:
    got = _slug(username)
    if not got or handle_is_impersonator(username):
        return False
    want = _slug(str(cfg.get("handle_official") or ""))
    mention = _slug(str(cfg.get("mention") or cfg.get("name") or ""))
    if want and got == want:
        return True
    if cfg.get("ambiguous"):
        return False
    token = want or mention
    if token and got.startswith(token) and _official_tail_ok(got[len(token):]):
        return True
    if mention and mention != token and got.startswith(mention) and _official_tail_ok(got[len(mention):]):
        return True
    return False


def fetch_subtitle_text(post: dict[str, Any], *, timeout: float = 8.0) -> str:
    infos = post.get("subtitleInformation") or post.get("subtitle_information") or []
    if isinstance(infos, dict):
        infos = [infos]
    urls: list[str] = []
    for info in infos:
        if not isinstance(info, dict):
            continue
        href = str(info.get("url") or info.get("webvttUrl") or "").strip()
        if href.startswith("http"):
            urls.append(href)
    for href in urls[:2]:
        try:
            r = requests.get(href, timeout=timeout)
            if r.status_code >= 400 or not r.text:
                continue
            lines: list[str] = []
            for line in r.text.splitlines():
                s = line.strip()
                if not s or _VTT_SKIP.match(s) or "-->" in s or _TS.search(s) and len(s) < 32:
                    continue
                lines.append(s)
            text = re.sub(r"\s+", " ", " ".join(lines)).strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def classify(
    post: dict[str, Any],
    brand: str,
    sub_text: Optional[str] = None,
    *,
    domain: str = "",
    official_handle: str = "",
    min_views: Optional[int] = None,
) -> dict[str, Any]:
    cfg = resolve_brand(brand, domain=domain, official_handle=official_handle)
    token = str(cfg.get("token") or re.escape(str(cfg.get("name") or brand)))
    title = _title(post)
    tags = _hashtags(post)
    user = _username(post)
    speech = sub_text if sub_text is not None else str(post.get("subtitle_text") or "")
    host = str(cfg.get("domain") or "")
    mention = str(cfg.get("mention") or "")
    prefix = str(cfg.get("hashtag_prefix") or "")
    text_blob = _blob(title, speech)
    reasons: list[str] = []
    flags: list[str] = []

    title_plain = re.sub(r"#\S+", " ", title)
    in_title = bool(_word_re(token).search(title_plain))
    in_speech = bool(speech and _word_re(token).search(speech))
    in_mention = bool(mention and (f"@{mention}" in title.lower() or _official(cfg, user)))
    in_domain = bool(host and host.lower() in text_blob.lower())
    in_hashtag = any(t == prefix or t.startswith(prefix) for t in tags if prefix)
    impersonator = handle_is_impersonator(user)
    official = _official(cfg, user) and not impersonator
    if impersonator:
        flags.append("impersonator")
        official = False
    if official:
        reasons.append("official_handle")
        in_mention = True

    if in_title:
        reasons.append("brand_in_title")
    if in_speech:
        reasons.append("brand_in_speech")
    if in_mention and "official_handle" not in reasons:
        reasons.append("brand_mention")
    if in_domain:
        reasons.append("brand_domain")
    if in_hashtag:
        reasons.append("brand_hashtag")

    appeared = in_title or in_speech or in_mention or in_domain or in_hashtag
    pos_hit = _has_any(_blob(title, speech, " ".join(tags)), list(cfg.get("pos") or []))
    neg_hit = _has_any(_blob(title, speech, " ".join(tags)), list(cfg.get("neg") or []))
    if pos_hit:
        reasons.append("pos_context")
    if neg_hit:
        reasons.append("neg_context")

    if _PROMO_RE.search(_blob(title, " ".join(f"#{t}" for t in tags))):
        flags.append("promo/criador")
    if _RESELL_RE.search(title):
        flags.append("revenda/gratis?")
    if len(tags) >= 8 and in_hashtag and not (in_title or in_speech or in_mention):
        flags.append("hashtag_stuffing")
    title_wo_tags = re.sub(r"#\S+", "", title).strip()
    if not title_wo_tags and not speech:
        flags.append("sem_texto")
    views = post.get("views")
    try:
        views_n = int(views) if views is not None else None
    except (TypeError, ValueError):
        views_n = None
    if min_views and isinstance(views_n, int) and views_n < min_views:
        flags.append("poucas_views")

    ambiguous = bool(cfg.get("ambiguous"))
    label = "unrelated"
    score = 0
    if official:
        score += 50
    if in_title:
        score += 30
    if in_speech:
        score += 25
    if in_mention:
        score += 20
    if in_domain:
        score += 20
    if in_hashtag:
        score += 10
    if pos_hit:
        score += 15
    if neg_hit:
        score -= 40

    if impersonator:
        label = "unrelated"
        score = min(score, 0)
    elif not appeared:
        label = "unrelated"
        score = min(score, 0)
    elif neg_hit and (ambiguous or not official):
        label = "unrelated"
    elif official or in_domain:
        label = "confirmed"
    elif not ambiguous and (in_title or in_speech or in_mention):
        label = "confirmed"
    elif not ambiguous and in_hashtag:
        label = "probable"
    elif ambiguous and appeared and pos_hit and not neg_hit:
        label = "confirmed"
    elif ambiguous and appeared and not neg_hit:
        label = "probable"
    else:
        label = "unrelated"

    if "hashtag_stuffing" in flags and label == "confirmed" and not (in_title or in_speech or official):
        label = "probable"

    return {
        "id": str(post.get("id") or ""),
        "label": label,
        "score": score,
        "reasons": reasons,
        "flags": flags,
        "views": views_n,
        "likes": post.get("likes"),
        "comments": post.get("comments"),
        "shares": post.get("shares"),
        "title": title,
        "user": user,
        "verified": bool(_channel(post).get("verified")),
        "followers": _channel(post).get("followers"),
        "link": str(post.get("postPage") or post.get("url") or ""),
        "uploaded": str(post.get("uploadedAtFormatted") or ""),
        "hashtags": tags,
        "official": official,
        "ambiguous": ambiguous,
        "subtitle": bool(speech),
    }


def classify_all(
    posts: list[dict[str, Any]],
    brand: str,
    with_subtitles: bool = True,
    *,
    domain: str = "",
    official_handle: str = "",
    min_views: Optional[int] = None,
) -> list[dict[str, Any]]:
    uniq: list[dict[str, Any]] = []
    seen: set[str] = set()
    for post in posts or []:
        if not isinstance(post, dict):
            continue
        pid = str(post.get("id") or post.get("postPage") or "")
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        uniq.append(post)

    subs: dict[int, str] = {}
    if with_subtitles and uniq:
        with ThreadPoolExecutor(max_workers=min(8, len(uniq))) as pool:
            futs = {pool.submit(fetch_subtitle_text, p): i for i, p in enumerate(uniq)}
            for fut in as_completed(futs):
                try:
                    subs[futs[fut]] = fut.result() or ""
                except Exception:
                    subs[futs[fut]] = ""

    rows = []
    for i, post in enumerate(uniq):
        rows.append(
            classify(
                post,
                brand,
                subs.get(i, ""),
                domain=domain,
                official_handle=official_handle,
                min_views=min_views,
            )
        )
    return rows
