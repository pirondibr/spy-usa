# -*- coding: utf-8 -*-
"""Infer company start month from Semrush organic MonthlyTrend."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

_YM = re.compile(r"^(\d{4})-(\d{2})$")
_MONTHS_EN = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_MONTHS_PT = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)


def format_started(ym: str, market: str = "us") -> str:
    m = _YM.match((ym or "").strip())
    if not m:
        return ""
    months = _MONTHS_PT if str(market or "").lower() == "br" else _MONTHS_EN
    return f"{months[int(m.group(2)) - 1]} {m.group(1)}"


def infer_started(series: list[dict[str, Any]] | None, *, market: str = "us") -> dict[str, Any]:
    """First month with traffic after the leading zeros.

    Semrush lists monthly organic traffic oldest → newest. Zeros at the start
    mean the domain was not ranking yet. The first month after that 0-run is
    the start. If the oldest month already has traffic, Semrush history is
    truncated and we still use that month.
    """
    pts: list[dict[str, Any]] = []
    for raw in series or []:
        if not isinstance(raw, dict):
            continue
        date = str(raw.get("date") or "").strip()
        if not _YM.match(date):
            continue
        try:
            total = int(raw.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        pts.append({"date": date, "total": total})
    pts.sort(key=lambda p: p["date"])
    empty = {
        "started": "",
        "started_fmt": "",
        "started_truncated": False,
        "started_source": "semrush",
    }
    if not pts:
        return empty

    first_zero = next((i for i, p in enumerate(pts) if p["total"] <= 0), None)
    first_traffic = next((i for i, p in enumerate(pts) if p["total"] > 0), None)
    if first_traffic is None:
        return empty

    started = pts[first_traffic]["date"]
    truncated = first_zero is None or first_zero > first_traffic
    return {
        "started": started,
        "started_fmt": format_started(started, market),
        "started_truncated": truncated,
        "started_source": "semrush",
    }


def _one(row: dict[str, Any], *, db: str, market: str) -> dict[str, Any]:
    from seo_pipeline import fetch_semrush_monthly_trend  # noqa: E402

    domain = str(row.get("domain") or "").strip()
    series = fetch_semrush_monthly_trend(domain, db=db) if domain else []
    inferred = infer_started(series, market=market)
    return {"domain": domain.lower(), **inferred}


def attach_started_batch(
    rows: list[dict[str, Any]],
    *,
    market: str = "",
    db: str = "",
    only_missing: bool = True,
    workers: int = 6,
    emit: Optional[Callable[[str], None]] = None,
) -> int:
    """Fill started / started_fmt on competitor rows. Returns how many were fetched."""
    mkt = (market or os.environ.get("SPY_MARKET") or "us").strip().lower()
    semrush_db = (db or ("br" if mkt == "br" else "us")).strip().lower()
    targets: list[dict[str, Any]] = []
    for row in rows:
        if only_missing and str(row.get("started") or "").strip():
            continue
        if str(row.get("domain") or "").strip():
            targets.append(row)
    if not targets:
        return 0

    def _log(line: str) -> None:
        if emit:
            emit(line)

    _log(f"[STARTED] Semrush MonthlyTrend ({semrush_db}) em {len(targets)} domínio(s)")
    found: dict[str, dict[str, Any]] = {}
    workers = max(1, min(int(workers or 1), 8, len(targets)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, row, db=semrush_db, market=mkt) for row in targets]
        for fut in as_completed(futs):
            try:
                item = fut.result()
            except Exception as e:
                _log(f"[STARTED] Falhou: {e}")
                continue
            found[(item.get("domain") or "").lower()] = item

    filled = 0
    for row in rows:
        key = str(row.get("domain") or "").strip().lower()
        item = found.get(key)
        if not item:
            continue
        row["started"] = item.get("started") or ""
        row["started_fmt"] = item.get("started_fmt") or ""
        row["started_truncated"] = bool(item.get("started_truncated"))
        row["started_source"] = "semrush"
        filled += 1
    _log(f"[STARTED] {filled}/{len(targets)} com mês de início")
    return filled
