# -*- coding: utf-8 -*-
"""LLM pass: is this title about brand X in niche Y selling product Z?"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL") or "google/gemini-2.5-flash"

_CHANNEL_NOUN = {
    "youtube": "YouTube video",
    "tiktok": "TikTok post",
    "x": "X / Twitter post",
    "twitter": "X / Twitter post",
}


def load_briefing_xyz(slug: str) -> dict[str, str]:
    """Nicho + produto from briefing-cliente-{slug}.xlsx (Briefing / Traducao)."""
    out = {"nicho": "", "produto": ""}
    if not slug:
        return out
    try:
        from workspace_paths import PIPELINE_OUTPUT_DIR
    except Exception:
        return out
    folder = PIPELINE_OUTPUT_DIR / slug
    path = folder / f"briefing-cliente-{slug}.xlsx"
    if not path.exists() and folder.exists():
        hits = sorted(folder.glob("briefing-cliente-*.xlsx"))
        path = hits[0] if hits else path
    if not path.exists():
        return out
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        fields: dict[str, str] = {}
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            for row in ws.iter_rows(values_only=True):
                if not row or len(row) < 2:
                    continue
                label = str(row[0] or "").strip().lower()
                val = str(row[1] or "").strip()
                if label and val and val not in ("—", "-", "n/a"):
                    fields.setdefault(label, val)
        wb.close()
    except Exception:
        return out

    def pick(*needles: str) -> str:
        for needle in needles:
            for lab, val in fields.items():
                if lab == needle or lab.startswith(needle):
                    return val
        return ""

    nicho = pick(
        "nicho especifico",
        "nicho principal",
        "nicho medio",
        "nicho amplo",
        "nicho",
    )
    produto = pick(
        "produto principal",
        "produto especifico",
        "produto medio",
        "produto amplo",
        "modelo de produto",
        "produto",
    )
    return {"nicho": nicho, "produto": produto}


def _call_openrouter_json(prompt: str, *, max_tokens: int = 8000, task: str = "youtube_titulos") -> dict:
    from llm_trace import chat, extract_json

    raw = chat(task=task, prompt=prompt, max_tokens=max_tokens, temperature=0.1)
    return extract_json(raw)


def _item_line(i: int, v: dict[str, Any]) -> str:
    title = v.get("title") or ""
    channel = v.get("channel_name") or v.get("handle") or ""
    text = (
        v.get("snippet")
        or v.get("description")
        or v.get("subtitle_text")
        or ""
    )
    return (
        f"[{i}] title={title!r} author={channel!r} text={str(text)[:400]!r}"
    )


def apply_llm_labels(
    videos: list[dict[str, Any]],
    *,
    brand: str,
    domain: str = "",
    niche: str = "",
    product: str = "",
    channel: str = "youtube",
) -> dict[str, Any]:
    """Rewrite confirmed/unrelated from LLM. Regex labels stay if the LLM is down."""
    meta = {
        "ok": False,
        "model": OPENROUTER_MODEL,
        "about": 0,
        "n": len(videos or []),
        "error": "",
    }
    if not videos:
        return meta
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        for v in videos:
            v.setdefault("about_reason", "no_openrouter_key")
        meta["error"] = "no_openrouter_key"
        print(f"[BRAND-LLM] {brand}: skipped (no OPENROUTER_API_KEY)", flush=True)
        return meta

    kind = _CHANNEL_NOUN.get((channel or "youtube").lower(), "post")
    site = (domain or "").strip()
    niche_line = (niche or "unknown niche").strip()
    product_line = (product or site or brand).strip()
    lines = [_item_line(i, v) for i, v in enumerate(videos[:40])]
    prompt = (
        f"You classify {kind} search results for ONE product.\n"
        f"Brand name: {brand!r}\n"
        f"Official website: {site!r}\n"
        f"Niche / market: {niche_line!r}\n"
        f"What they sell: {product_line!r}\n\n"
        "Set about=true only if the item is about THIS brand in THIS niche "
        "(review, tutorial, ad, demo, comparison, news, or a creator using this product).\n"
        "A domain or exact product phrase (e.g. turbo.ai, Turbo AI, #turboai) is about=true.\n"
        "Set about=false when the text only shares a common word with the brand "
        "(song, movie, car part, toy, sports, slang, another company, unrelated meaning).\n"
        "Examples: 'Turbo Lover' / 'MODO TURBO' / Beyblade Turbo are not turbo.ai; "
        "'Leonardo da Vinci' is not leonardo.ai; a fashion runway is not Runway ML.\n"
        "Return ONLY JSON: "
        '{"items":[{"i":0,"about":true,"reason":"short"}]}\n\n'
        + "\n".join(lines)
    )
    try:
        task = {
            "youtube": "youtube_titulos",
            "tiktok": "tiktok_titulos",
            "x": "x_titulos",
            "twitter": "x_titulos",
        }.get((channel or "youtube").lower(), "youtube_titulos")
        parsed = _call_openrouter_json(prompt, task=task)
        by_i: dict[int, dict[str, Any]] = {}
        for it in parsed.get("items") or []:
            if not isinstance(it, dict):
                continue
            try:
                idx = int(it.get("i"))
            except (TypeError, ValueError):
                continue
            by_i[idx] = it
        about_n = 0
        for i, v in enumerate(videos[:40]):
            it = by_i.get(i)
            if it is None:
                v["about_product"] = False
                v["about_reason"] = "llm_no_verdict"
                v["label"] = "unrelated"
                continue
            about = bool(it.get("about"))
            v["about_product"] = about
            v["about_reason"] = str(it.get("reason") or ("about" if about else "not_this_product"))[:160]
            if about:
                about_n += 1
                if v.get("label") != "confirmed":
                    v["label"] = "confirmed"
            else:
                v["label"] = "unrelated"
        for v in videos[40:]:
            v["about_reason"] = "beyond_llm_batch"
        meta["ok"] = True
        meta["about"] = about_n
        print(
            f"[BRAND-LLM] {channel} {brand}: about={about_n}/{min(len(videos), 40)} "
            f"nicho={niche_line!r} produto={product_line!r}",
            flush=True,
        )
    except Exception as e:
        meta["error"] = str(e)[:200]
        print(f"[BRAND-LLM] {channel} {brand} failed: {e}", flush=True)
        for v in videos:
            v.setdefault("about_reason", f"llm_error:{e}"[:160])
    return meta


def repartition(videos: list[dict[str, Any]]) -> tuple[list, list, list, list, list]:
    confirmed = [v for v in videos if v.get("label") == "confirmed"]
    probable = [v for v in videos if v.get("label") == "probable"]
    unrelated = [v for v in videos if v.get("label") == "unrelated"]
    official_pool = [v for v in confirmed if v.get("is_official")]
    other_pool = [v for v in confirmed if not v.get("is_official")]
    return confirmed, probable, unrelated, official_pool, other_pool
