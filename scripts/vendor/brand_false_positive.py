# -*- coding: utf-8 -*-
"""Flag DataForSEO brand-volume false positives (generic keyword + inflated volume)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL") or "google/gemini-2.5-flash"

# Category / dictionary tokens that DataForSEO often measures as intent, not brand.
GENERIC_BRAND_WORDS = {
    "ad", "ads", "ai", "analytics", "app", "apps", "best", "blog",
    "bot", "brand", "brands", "care", "chat", "cloud", "commerce", "data",
    "digital", "dropship", "dropshipping", "e-commerce", "ecommerce", "finance",
    "food", "free", "game", "games", "growth", "guide", "health", "home",
    "hotel", "hub", "hunt", "hunter", "insight", "insights", "intelligence",
    "legal", "link", "mail", "market", "marketing", "marketplace", "media",
    "monitor", "music", "news", "niche", "online", "pay", "photo", "play",
    "ppc", "product", "products", "pulse", "radar", "rank", "retail", "review",
    "reviews", "search", "sem", "seo", "shop", "social", "spy", "spying",
    "store", "tool", "tools", "top", "tracker", "tracking", "travel", "trend",
    "trends", "video", "watch", "web",
}

LogFn = Callable[[str], None]


def _num(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "—":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _keyword(row: dict[str, Any]) -> str:
    raw = str(row.get("brand_keyword") or "").strip().lower()
    raw = re.sub(r"[^a-z0-9\-\s]+", "", raw)
    return re.sub(r"\s+", " ", raw).strip()


def high_volume_threshold(rows: list[dict[str, Any]]) -> Optional[float]:
    """High vs typical peers — ignore the fattest tail so Reddit does not hide Dropship."""
    vols = sorted(
        v
        for r in rows
        if not r.get("is_client")
        for v in (_num(r.get("brand_aug_2026")),)
        if v
    )
    if not vols:
        return None
    if len(vols) < 3:
        return 15_000.0
    cut = max(2, int(len(vols) * 0.8))
    core = vols[:cut]
    core_median = core[len(core) // 2]
    return max(core_median * 8.0, 15_000.0)


def is_high_volume(row: dict[str, Any], threshold: Optional[float]) -> bool:
    if row.get("is_client") or threshold is None:
        return False
    vol = _num(row.get("brand_aug_2026"))
    return vol is not None and vol >= threshold


def keyword_looks_generic(keyword: str) -> bool:
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    if kw in GENERIC_BRAND_WORDS:
        return True
    parts = [p for p in re.split(r"[\s\-]+", kw) if p]
    if len(parts) == 1:
        return parts[0] in GENERIC_BRAND_WORDS
    return all(p in GENERIC_BRAND_WORDS for p in parts)


def high_brand_candidates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Optional[float]]:
    threshold = high_volume_threshold(rows)
    picked = []
    for r in rows:
        if not is_high_volume(r, threshold):
            continue
        if not _keyword(r):
            continue
        picked.append(r)
    return picked, threshold


def heuristic_false_positive_domains(rows: list[dict[str, Any]]) -> set[str]:
    """High volume + generic keyword. Used as fallback / old-report overlay."""
    cands, _ = high_brand_candidates(rows)
    out: set[str] = set()
    for r in cands:
        if keyword_looks_generic(_keyword(r)):
            dom = str(r.get("domain") or "").strip().lower()
            if dom:
                out.add(dom)
    return out


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    text = re.sub(r"^[^{\[]*", "", text)
    text = re.sub(r"[^}\]]*$", "", text)
    return json.loads(text)


def _call_llm(prompt: str) -> str:
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    r = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.1,
        },
        timeout=15,
    )
    r.raise_for_status()
    return str(r.json()["choices"][0]["message"]["content"] or "")


def _llm_false_positives(
    candidates: list[dict[str, Any]],
    *,
    threshold: float,
    median: Optional[float],
) -> dict[str, bool]:
    lines = []
    for r in candidates:
        lines.append(
            "- domain={dom} | company={name} | keyword={kw} | aug2026={vol}".format(
                dom=r.get("domain") or "",
                name=r.get("name") or r.get("company") or "",
                kw=_keyword(r),
                vol=int(_num(r.get("brand_aug_2026")) or 0),
            )
        )
    prompt = f"""You review Google Ads brand-search volumes (DataForSEO).

A FALSE POSITIVE is when the queried keyword is a common/generic English word or category term
(so the volume measures category intent, not branded searches for this company).

Distinctive brand names are NOT false positives even with huge volume
(examples: reddit, semrush, zapier, hootsuite, similarweb, adobe).

Only these statistical outliers were sent (median≈{int(median or 0)}, high cutoff≈{int(threshold)}):
{chr(10).join(lines)}

Return JSON array only:
[{{"domain":"example.com","false_positive":true,"reason":"generic keyword"}}]
"""
    raw = _call_llm(prompt)
    data = _extract_json(raw)
    if isinstance(data, dict):
        data = data.get("results") or data.get("flags") or data.get("items") or []
    if not isinstance(data, list):
        return {}
    out: dict[str, bool] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        dom = str(item.get("domain") or "").strip().lower()
        if not dom:
            continue
        out[dom] = bool(item.get("false_positive"))
    return out


def flag_brand_false_positives(
    rows: list[dict[str, Any]],
    *,
    use_llm: bool = True,
    emit: Optional[LogFn] = None,
) -> int:
    """Mark rows in-place. Returns how many were flagged."""
    def _log(line: str) -> None:
        if emit:
            emit(line)

    for r in rows:
        r.setdefault("brand_false_positive", False)
        r.setdefault("brand_false_positive_reason", "")

    cands, threshold = high_brand_candidates(rows)
    if not cands or threshold is None:
        _log("[BRAND-FP] Nenhum volume alto o bastante para checar")
        return 0

    vols = sorted(v for v in (_num(r.get("brand_aug_2026")) for r in rows) if v)
    median = vols[len(vols) // 2] if vols else None
    names = ", ".join((c.get("domain") or "?") for c in cands[:12])
    _log(f"[BRAND-FP] High-volume check ({len(cands)}, cutoff {int(threshold)}): {names}")

    llm_map: dict[str, bool] = {}
    if use_llm:
        try:
            llm_map = _llm_false_positives(cands, threshold=threshold, median=median)
        except Exception as e:
            _log(f"[BRAND-FP] LLM falhou, usando heurística: {e}")

    flagged = 0
    for r in cands:
        dom = str(r.get("domain") or "").strip().lower()
        kw = _keyword(r)
        if llm_map:
            is_fp = bool(llm_map.get(dom))
            reason = "llm"
        else:
            is_fp = keyword_looks_generic(kw)
            reason = "heuristic: generic keyword + high volume"
        r["brand_false_positive"] = is_fp
        r["brand_false_positive_reason"] = reason if is_fp else ""
        if is_fp:
            flagged += 1
            _log(f"[BRAND-FP] * {dom} keyword='{kw}' ({reason})")

    return flagged
