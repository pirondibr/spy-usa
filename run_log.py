# -*- coding: utf-8 -*-
"""Capture pipeline log lines, per-channel timings, and estimated API costs."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional

# Approximate unit costs (USD). Override via env if needed.
_SB_CREDIT_USD = float(os.environ.get("SPY_COST_SB_CREDIT", "0.0002") or 0.0002)
_DFS_TASK_USD = float(os.environ.get("SPY_COST_DFS_TASK", "0.05") or 0.05)
_APIFY_DOMAIN_USD = float(os.environ.get("SPY_COST_APIFY_DOMAIN", "0.03") or 0.03)
_APIFY_NOTE_RE = re.compile(r"×\s*(\d+)\s*domains", re.I)
_LEGACY_APIFY_DOMAIN_USD = 0.015
_TF_FETCH_USD = float(os.environ.get("SPY_COST_TF_FETCH", "0.0") or 0.0)
_TF_SEARCH_USD = float(os.environ.get("SPY_COST_TF_SEARCH", "0.0") or 0.0)
_OPENROUTER_CALL_USD = float(os.environ.get("SPY_COST_OPENROUTER_CALL", "0.01") or 0.01)

STEP_LABELS = {
    "briefing_concorrentes": "Briefing (+ competitors)",
    "competitors_discover": "Find competitors",
    "brand_growth": "Brand growth DataForSEO",
    "similarweb_alto": "SimilarWeb (Alto)",
    "seo": "SEO Orgânico",
    "brand": "Marca Semrush",
    "brand_dfs": "DataForSEO",
    "similarweb": "SimilarWeb",
    "google_ads": "Google Ads",
    "meta": "Meta Ads",
    "linkedin": "LinkedIn Ads",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "youtube_influencers": "YouTube Influencers",
    "instagram_influencers": "Instagram Influencers",
    "tiktok_influencers": "TikTok Influencers",
    "reddit": "Reddit",
    "twitter": "Twitter / X",
    "linkedin_profile": "LinkedIn Profile",
}

# step_id -> report section key (when different)
STEP_TO_SECTION = {
    "brand_dfs": "brand_dataforseo",
}

CHANNEL_APIS = {
    "briefing_concorrentes": ["OpenRouter", "ScrapingBee"],
    "competitors_discover": ["OpenRouter", "DataForSEO", "Semrush"],
    "brand_growth": ["DataForSEO"],
    "similarweb_alto": ["Apify"],
    "seo": ["Semrush"],
    "brand": ["Semrush"],
    "brand_dfs": ["DataForSEO"],
    "similarweb": ["Apify"],
    "google_ads": ["ScrapingBee"],
    "meta": ["ScrapingBee"],
    "linkedin": ["ScrapingBee"],
    "instagram": ["ScrapingBee", "TinyFish"],
    "youtube": ["ScrapingBee"],
    "tiktok": ["ScrapingBee"],
    "youtube_influencers": ["ScrapingBee"],
    "instagram_influencers": ["TinyFish"],
    "tiktok_influencers": ["TinyFish", "ScrapingBee", "DataForSEO"],
    "reddit": ["TinyFish", "ScrapingBee"],
    "twitter": ["TinyFish", "ScrapingBee"],
    "linkedin_profile": ["TinyFish", "ScrapingBee", "DataForSEO", "OpenRouter"],
}

_CREDIT_RE = re.compile(
    r"(?:credits?|creditos?|sb_credits|scrapingbee(?:\s+credits?)?)\s*[:=]\s*(\d+(?:\.\d+)?)",
    re.I,
)
_TIME_SUB_RE = re.compile(r"\[TIME-SUB\]\s+(.+?):\s*([\d.]+)s", re.I)


def _fmt_sec(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    if sec < 60:
        return f"{sec:.1f}s"
    m, s = divmod(int(round(sec)), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _fmt_usd(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v < 0.01 and v > 0:
        return f"${v:.4f}"
    return f"${v:.2f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v <= 0:
        return "0%"
    if v < 1:
        return f"{v:.1f}%"
    return f"{int(round(v))}%"


def _channel_is_skipped(ch: dict[str, Any]) -> bool:
    blob = " ".join(str(ch.get(k) or "") for k in ("detail", "cost_note", "status")).lower()
    return "skip" in blob or "pulado" in blob


def _apify_domain_count(ch: dict[str, Any]) -> Optional[int]:
    m = _APIFY_NOTE_RE.search(str(ch.get("cost_note") or ""))
    if m:
        return max(1, int(m.group(1)))
    usd = ch.get("cost_usd")
    if isinstance(usd, (int, float)) and float(usd) > 0 and _LEGACY_APIFY_DOMAIN_USD > 0:
        n = int(round(float(usd) / _LEGACY_APIFY_DOMAIN_USD))
        if n > 0:
            return n
    return None


def _is_apify_step(ch: dict[str, Any]) -> bool:
    sid = str(ch.get("id") or "")
    if sid in ("similarweb", "similarweb_alto"):
        return True
    apis = ch.get("apis") or []
    if isinstance(apis, str):
        apis = [apis]
    return "Apify" in apis or "Apify" in str(ch.get("apis_fmt") or "")


def refresh_apify_step_costs(channels: list[dict[str, Any]]) -> None:
    """Reprice SimilarWeb rows at the live Apify rate ($0.03/domain by default)."""
    for ch in channels:
        if not isinstance(ch, dict) or _channel_is_skipped(ch) or not _is_apify_step(ch):
            continue
        n = _apify_domain_count(ch)
        if not n:
            continue
        usd = round(n * _APIFY_DOMAIN_USD, 4)
        ch["cost_usd"] = usd
        ch["cost_fmt"] = _fmt_usd(usd)
        ch["cost_note"] = f"Apify ×{n} domains × ${_APIFY_DOMAIN_USD:g}"


def apply_cost_shares(
    channels: list[dict[str, Any]],
    totals: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Fill cost_pct / cost_pct_fmt on each step from cost_usd vs run total."""
    totals = totals if isinstance(totals, dict) else {}
    refresh_apify_step_costs(channels)
    total = 0.0
    for ch in channels:
        if not isinstance(ch, dict) or _channel_is_skipped(ch):
            continue
        v = ch.get("cost_usd")
        if isinstance(v, (int, float)) and float(v) > 0:
            total += float(v)
    if total > 0:
        totals["cost_usd"] = round(total, 4)
        totals["cost_fmt"] = _fmt_usd(total)

    for ch in channels:
        if not isinstance(ch, dict):
            continue
        if _channel_is_skipped(ch):
            ch["cost_pct"] = None
            ch["cost_pct_fmt"] = "—"
            continue
        v = ch.get("cost_usd")
        if not isinstance(v, (int, float)) or total <= 0:
            ch["cost_pct"] = None
            ch["cost_pct_fmt"] = "—"
            continue
        pct = 100.0 * float(v) / float(total)
        ch["cost_pct"] = round(pct, 1)
        ch["cost_pct_fmt"] = _fmt_pct(pct)

    if total > 0:
        totals["cost_pct"] = 100.0
        totals["cost_pct_fmt"] = "100%"
    else:
        totals.setdefault("cost_pct", None)
        totals.setdefault("cost_pct_fmt", "—")
    return totals


def _section_usage(report: dict[str, Any], step_id: str) -> dict[str, Any]:
    key = STEP_TO_SECTION.get(step_id, step_id)
    section = report.get(key)
    if not isinstance(section, dict):
        return {}
    usage = section.get("usage_total") or section.get("usage") or {}
    return usage if isinstance(usage, dict) else {}


def _n_rows(report: dict[str, Any], step_id: str) -> int:
    key = STEP_TO_SECTION.get(step_id, step_id)
    section = report.get(key)
    if not isinstance(section, dict):
        return 0
    return len(section.get("rows") or [])


def _n_similarweb_alto(report: dict[str, Any]) -> int:
    n = 0
    for key in ("competitors", "competitors_raw"):
        rows = report.get(key) or []
        if not isinstance(rows, list):
            continue
        found = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("similarweb_visits") not in (None, ""):
                found += 1
        if found:
            n = found
            break
    return n


def _estimate_step_cost(
    step_id: str,
    report: dict[str, Any],
    log_credits: dict[str, float],
) -> tuple[Optional[float], str, list[str]]:
    """Returns (usd_or_none, usage_note, apis)."""
    apis = list(CHANNEL_APIS.get(step_id, []))
    usage = _section_usage(report, step_id)
    notes: list[str] = []
    usd = 0.0
    known = False

    # Explicit USD from vendor payloads
    for k in ("estimated_total_usd", "estimated_usd", "cost_usd", "total_cost_usd"):
        if isinstance(usage.get(k), (int, float)):
            usd += float(usage[k])
            known = True
            notes.append(f"{k}={usage[k]}")
    for k in ("search_cost_usd", "fetch_cost_usd"):
        if isinstance(usage.get(k), (int, float)) and float(usage[k]) > 0:
            usd += float(usage[k])
            known = True

    sb = usage.get("scrapingbee_credits")
    if sb is None:
        sb = log_credits.get(step_id)
    if isinstance(sb, (int, float)) and sb > 0:
        part = float(sb) * _SB_CREDIT_USD
        usd += part
        known = True
        notes.append(f"SB {int(sb)} credits × ${_SB_CREDIT_USD:g}")

    fetch_urls = usage.get("fetch_urls")
    if isinstance(fetch_urls, (int, float)) and fetch_urls > 0 and _TF_FETCH_USD > 0:
        usd += float(fetch_urls) * _TF_FETCH_USD
        known = True
        notes.append(f"TF fetch ×{int(fetch_urls)}")
    elif isinstance(fetch_urls, (int, float)) and fetch_urls > 0:
        notes.append(f"TF fetch urls={int(fetch_urls)} (free/allowance)")

    if step_id == "brand_dfs":
        n = max(1, _n_rows(report, step_id))
        # One live Search Volume task (batch) ≈ one DFS task
        usd += _DFS_TASK_USD
        known = True
        notes.append(f"DataForSEO search_volume (~{_DFS_TASK_USD:g}/task, {n} brands)")
        if "DataForSEO" not in apis:
            apis.append("DataForSEO")

    if step_id in ("similarweb", "similarweb_alto"):
        n = _n_rows(report, step_id)
        if step_id == "similarweb_alto" and n <= 0:
            n = _n_similarweb_alto(report)
        n = max(1, n)
        usd += n * _APIFY_DOMAIN_USD
        known = True
        notes.append(f"Apify ×{n} domains × ${_APIFY_DOMAIN_USD:g}")

    if step_id == "briefing_concorrentes":
        usd += _OPENROUTER_CALL_USD
        known = True
        notes.append(f"OpenRouter ~${_OPENROUTER_CALL_USD:g}")

    if step_id in ("seo", "brand"):
        notes.append("Semrush (subscription / not unit-priced here)")
        if not known:
            return None, "; ".join(notes) if notes else "Semrush", apis

    if step_id in ("google_ads", "meta", "linkedin") and not known:
        # fallback: parse global log credits for that tag
        c = log_credits.get(step_id)
        if c:
            usd = float(c) * _SB_CREDIT_USD
            known = True
            notes.append(f"SB {int(c)} credits (from log)")

    if not known:
        return None, "; ".join(notes) if notes else "n/d", apis
    return round(usd, 4), "; ".join(notes), apis


def _credits_from_logs(lines: list[str]) -> dict[str, float]:
    """Best-effort map of step_id → ScrapingBee credits from log lines."""
    out: dict[str, float] = {}
    tag_map = [
        (re.compile(r"\[META", re.I), "meta"),
        (re.compile(r"\[LINKEDIN", re.I), "linkedin"),
        (re.compile(r"\[GOOGLE", re.I), "google_ads"),
        (re.compile(r"\[YT-INF|youtube.?influencers", re.I), "youtube_influencers"),
        (re.compile(r"\[IG-INF|instagram.?influencers", re.I), "instagram_influencers"),
        (re.compile(r"\[TT-INF|tiktok.?influencers", re.I), "tiktok_influencers"),
        (re.compile(r"\[REDDIT", re.I), "reddit"),
        (re.compile(r"\[TW\b|twitter", re.I), "twitter"),
        (re.compile(r"\[LI\b|linkedin.?profile", re.I), "linkedin_profile"),
        (re.compile(r"\[SOCIAL", re.I), "instagram"),
    ]
    current: Optional[str] = None
    for line in lines:
        for rx, sid in tag_map:
            if rx.search(line):
                current = sid
                break
        m = _CREDIT_RE.search(line)
        if m and current:
            out[current] = out.get(current, 0.0) + float(m.group(1))
        # Totals like "[META/SB] Total credits ScrapingBee: 13"
        if re.search(r"Total credits|Total creditos", line, re.I) and m:
            if current:
                out[current] = float(m.group(1))
    return out


class RunRecorder:
    """Collects log lines + step wall times for one pipeline run."""

    def __init__(self) -> None:
        self.started_at = time.time()
        self.lines: list[str] = []
        self._step_t0: dict[str, float] = {}
        self.steps: dict[str, dict[str, Any]] = {}

    def add_line(self, line: str) -> None:
        text = (line or "").rstrip("\n\r")
        if text:
            self.lines.append(text)

    def mark_step(
        self,
        step_id: str,
        state: str,
        detail: str = "",
        label: str = "",
    ) -> None:
        if not step_id:
            return
        row = self.steps.setdefault(
            step_id,
            {
                "id": step_id,
                "label": label or STEP_LABELS.get(step_id, step_id),
                "sec": 0.0,
                "status": state,
                "detail": detail or "",
            },
        )
        if label:
            row["label"] = label
        if detail:
            row["detail"] = detail
        row["status"] = state
        if state == "running":
            self._step_t0[step_id] = time.time()
        elif state == "done":
            t0 = self._step_t0.pop(step_id, None)
            if t0 is not None:
                row["sec"] = float(row.get("sec") or 0) + (time.time() - t0)

    def finalize(self, report: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        report = report or {}
        # Close any still-running steps
        now = time.time()
        for sid, t0 in list(self._step_t0.items()):
            row = self.steps.setdefault(
                sid,
                {
                    "id": sid,
                    "label": STEP_LABELS.get(sid, sid),
                    "sec": 0.0,
                    "status": "running",
                    "detail": "",
                },
            )
            row["sec"] = float(row.get("sec") or 0) + (now - t0)
            row["status"] = "done"
        self._step_t0.clear()

        log_credits = _credits_from_logs(self.lines)
        order = list(STEP_LABELS.keys())
        channels: list[dict[str, Any]] = []
        total_cost = 0.0
        cost_known = False

        for sid in order:
            row = self.steps.get(sid)
            if not row and sid not in log_credits and not _section_usage(report, sid):
                # skip channels never touched
                continue
            if not row:
                row = {
                    "id": sid,
                    "label": STEP_LABELS.get(sid, sid),
                    "sec": 0.0,
                    "status": "n/d",
                    "detail": "",
                }
            status = str(row.get("status") or "")
            detail = str(row.get("detail") or "")
            if status == "done" and detail.lower().startswith("skip"):
                cost_usd, note, apis = None, "skipped", CHANNEL_APIS.get(sid, [])
            else:
                cost_usd, note, apis = _estimate_step_cost(sid, report, log_credits)
            if isinstance(cost_usd, (int, float)):
                total_cost += float(cost_usd)
                cost_known = True
            channels.append({
                "id": sid,
                "label": row.get("label") or STEP_LABELS.get(sid, sid),
                "sec": round(float(row.get("sec") or 0), 2),
                "sec_fmt": _fmt_sec(float(row.get("sec") or 0)),
                "status": status,
                "detail": detail,
                "apis": apis,
                "apis_fmt": ", ".join(apis) if apis else "—",
                "cost_usd": cost_usd,
                "cost_fmt": _fmt_usd(cost_usd),
                "cost_note": note,
            })

        # TIME-SUB extras from metricas script (informational)
        time_subs = [
            {"label": m.group(1).strip(), "sec": float(m.group(2))}
            for line in self.lines
            for m in [_TIME_SUB_RE.search(line)]
            if m
        ]

        total_sec = now - self.started_at
        totals = {
            "sec": round(total_sec, 2),
            "sec_fmt": _fmt_sec(total_sec),
            "cost_usd": round(total_cost, 4) if cost_known else None,
            "cost_fmt": _fmt_usd(total_cost if cost_known else None),
        }
        apply_cost_shares(channels, totals)
        return {
            "lines": self.lines[-2000:],  # cap stored log
            "line_count": len(self.lines),
            "channels": channels,
            "time_subs": time_subs,
            "totals": totals,
            "rates_note": (
                f"Estimativas: ScrapingBee ${_SB_CREDIT_USD:g}/credit · "
                f"DataForSEO ~${_DFS_TASK_USD:g}/task · "
                f"Apify ~${_APIFY_DOMAIN_USD:g}/domain · "
                f"TinyFish search/fetch ${_TF_SEARCH_USD:g}/${_TF_FETCH_USD:g} · "
                f"OpenRouter ~${_OPENROUTER_CALL_USD:g}/call. "
                "Semrush = assinatura (não unitizado)."
            ),
        }


def attach_run_log(report: dict[str, Any], recorder: RunRecorder) -> dict[str, Any]:
    report["run_log"] = recorder.finalize(report)
    return report


def write_run_log_files(run_dir, payload: dict[str, Any]) -> None:
    """Persist run.log + run_stats.json next to report.json."""
    from pathlib import Path
    import json

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = payload.get("lines") or []
    (run_dir / "run.log").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    stats = {k: v for k, v in payload.items() if k != "lines"}
    (run_dir / "run_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
