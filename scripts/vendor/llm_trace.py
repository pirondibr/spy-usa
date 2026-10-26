# -*- coding: utf-8 -*-
"""Log every OpenRouter call to SPY_LLM_LOG (JSONL) and expose a shared chat()."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL") or "google/gemini-2.5-flash"

TASK_LABELS = {
    "briefing": "Briefing",
    "brand_keyword": "Brand keyword",
    "brand_fp": "Brand FP",
    "sociais": "Sociais oficiais",
    "youtube_oficial": "YouTube oficial",
    "youtube_titulos": "YouTube títulos",
    "tiktok_titulos": "TikTok títulos",
    "x_titulos": "X títulos",
    "linkedin": "LinkedIn",
    "seo": "SEO",
    "concorrentes": "Concorrentes",
}


def task_label(task: str) -> str:
    return TASK_LABELS.get((task or "").strip(), (task or "LLM").strip() or "LLM")


def log_path() -> Optional[Path]:
    raw = (os.environ.get("SPY_LLM_LOG") or "").strip()
    if raw:
        return Path(raw)
    return None


def record(
    *,
    task: str,
    prompt: str,
    response: str = "",
    model: str = "",
    ok: bool = True,
    error: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> None:
    path = log_path()
    if not path:
        return
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task": (task or "other").strip() or "other",
        "label": task_label(task),
        "model": model or OPENROUTER_MODEL,
        "ok": bool(ok),
        "error": (error or "")[:300],
        "prompt": prompt or "",
        "response": response or "",
    }
    if extra:
        entry["extra"] = extra
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return


def load_calls(path: Optional[Path] = None) -> list[dict[str, Any]]:
    target = path or log_path()
    if not target or not target.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
    except Exception:
        return []
    return out


def group_calls(calls: list[dict[str, Any]]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    order = list(TASK_LABELS.keys())
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in calls or []:
        task = str(row.get("task") or "other")
        buckets.setdefault(task, []).append(row)
    grouped: list[tuple[str, str, list[dict[str, Any]]]] = []
    seen: set[str] = set()
    for task in order:
        if task in buckets:
            grouped.append((task, TASK_LABELS[task], buckets[task]))
            seen.add(task)
    for task, rows in buckets.items():
        if task not in seen:
            grouped.append((task, task_label(task), rows))
    return grouped


def chat(
    *,
    task: str,
    prompt: str,
    max_tokens: int = 800,
    temperature: float = 0.1,
    plugins: Optional[list] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """OpenRouter chat; always written to the run LLM log."""
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    model = (os.environ.get("OPENROUTER_MODEL") or OPENROUTER_MODEL).strip()
    if not key:
        record(task=task, prompt=prompt, ok=False, error="no_openrouter_key", model=model, extra=extra)
        raise RuntimeError("OPENROUTER_API_KEY ausente")
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if plugins:
        payload["plugins"] = plugins
    last_err: Optional[Exception] = None
    for attempt in range(5):
        try:
            r = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=90,
            )
            if r.status_code == 429 or r.status_code >= 500:
                try:
                    wait = float(r.headers.get("Retry-After") or "")
                except (TypeError, ValueError):
                    wait = (2 ** attempt) + 0.3
                wait = max(1.0, min(wait, 45.0))
                time.sleep(wait)
                last_err = RuntimeError(f"OpenRouter HTTP {r.status_code}")
                continue
            r.raise_for_status()
            content = (
                ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            )
            record(task=task, prompt=prompt, response=content, model=model, ok=True, extra=extra)
            return content
        except Exception as e:
            last_err = e
            if attempt >= 4:
                break
            time.sleep(min(20.0, (2 ** attempt) + 0.3))
    err = str(last_err or "OpenRouter call failed")
    record(task=task, prompt=prompt, ok=False, error=err, model=model, extra=extra)
    raise RuntimeError(err)


def extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    raw = re.sub(r"^[^{\[]*", "", raw)
    raw = re.sub(r"[^}\]]*$", "", raw)
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}
