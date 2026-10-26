# -*- coding: utf-8 -*-
"""Capture pipeline log lines, per-channel timings, and estimated API costs."""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Approximate unit costs (USD). Override via env if needed.
_SB_CREDIT_USD = float(os.environ.get("SPY_COST_SB_CREDIT", "0.0002") or 0.0002)
_DFS_LABS_TASK_USD = float(os.environ.get("SPY_COST_DFS_LABS_TASK", "0.012") or 0.012)
_DFS_LABS_KEYWORD_USD = float(os.environ.get("SPY_COST_DFS_LABS_KEYWORD", "0.00012") or 0.00012)
_DFS_VOLUME_TASK_USD = float(os.environ.get("SPY_COST_DFS_TASK", "0.09") or 0.09)
_DFS_TASK_USD = _DFS_LABS_TASK_USD
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
    "twitter_influencers": "X Influencers",
    "reddit": "Reddit",
    "twitter": "Twitter / X",
    "linkedin_profile": "LinkedIn Profile",
}

# step_id -> report section key (when different)
STEP_TO_SECTION = {
    "brand_dfs": "brand_dataforseo",
}

CHANNEL_APIS = {
    "briefing_concorrentes": ["OpenRouter Gemini", "ScrapingBee"],
    "competitors_discover": ["OpenRouter Gemini", "DataForSEO", "Semrush"],
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
    "tiktok_influencers": ["Apify"],
    "twitter_influencers": ["Apify"],
    "reddit": ["TinyFish", "ScrapingBee"],
    "twitter": ["TinyFish", "ScrapingBee"],
    "linkedin_profile": ["TinyFish", "ScrapingBee", "DataForSEO", "OpenRouter Gemini"],
}

_API_FROM_NOTE = (
    (re.compile(r"scrapingbee|\bsb\b|sb_credits", re.I), "ScrapingBee"),
    (re.compile(r"dataforseo|\blabs\b|keyword_overview|search_volume", re.I), "DataForSEO"),
    (re.compile(r"\bapify\b", re.I), "Apify"),
    (re.compile(r"tinyfish|\btf\b", re.I), "TinyFish"),
    (re.compile(r"openrouter|gemini", re.I), "OpenRouter Gemini"),
    (re.compile(r"semrush", re.I), "Semrush"),
)


def _normalize_api_name(name: str) -> str:
    n = (name or "").strip()
    low = n.lower()
    if low in {"openrouter", "gemini", "openrouter gemini"}:
        return "OpenRouter Gemini"
    if low in {"sb", "scraping bee"}:
        return "ScrapingBee"
    if low in {"dfs", "dataforseo labs"}:
        return "DataForSEO"
    if low in {"tf"}:
        return "TinyFish"
    return n


def apis_for_cost(note: str, fallback: Optional[list[str]] = None) -> list[str]:
    """APIs that produced the dollar amount in cost_note, else the channel defaults."""
    found: list[str] = []
    blob = note or ""
    for rx, label in _API_FROM_NOTE:
        if rx.search(blob) and label not in found:
            found.append(label)
    if found:
        return found
    out: list[str] = []
    for raw in fallback or []:
        lab = _normalize_api_name(str(raw))
        if lab and lab not in out:
            out.append(lab)
    return out


def _fmt_apis(apis: list[str]) -> str:
    return ", ".join(apis) if apis else "—"

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


def _runs_per_usd(total: Optional[float]) -> Optional[float]:
    if not isinstance(total, (int, float)) or float(total) <= 0:
        return None
    return round(1.0 / float(total), 2)


def _fmt_runs_per_usd(n: Optional[float]) -> str:
    if n is None or n <= 0:
        return "—"
    if n >= 10:
        return str(int(round(n)))
    if abs(n - round(n)) < 0.05:
        return str(int(round(n)))
    return f"{n:.1f}"


def cost_rates_note() -> str:
    return (
        f"Estimates: ScrapingBee ${_SB_CREDIT_USD:g}/credit · "
        f"DataForSEO Labs ${_DFS_LABS_TASK_USD:g}/task + ${_DFS_LABS_KEYWORD_USD:g}/kw · "
        f"Apify ~${_APIFY_DOMAIN_USD:g}/domain · "
        f"TinyFish search/fetch ${_TF_SEARCH_USD:g}/${_TF_FETCH_USD:g} · "
        f"OpenRouter ~${_OPENROUTER_CALL_USD:g}/call. "
        "Semrush = subscription (not unit-priced)."
    )


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
    if sid in ("tiktok_influencers", "twitter_influencers", "youtube_influencers"):
        return False
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


def _is_dfs_volume_step(ch: dict[str, Any]) -> bool:
    sid = str(ch.get("id") or "")
    if sid in ("brand_dfs", "brand_growth"):
        return True
    blob = " ".join(str(ch.get(k) or "") for k in ("label", "cost_note", "apis_fmt")).lower()
    return "dataforseo" in blob and (
        "keyword_overview" in blob or "search_volume" in blob or "labs" in blob
    )


_EST_USD_NOTE_RE = re.compile(r"estimated(?:_total)?_usd\s*=\s*([0-9.]+)", re.I)


def refresh_duplicate_usage_costs(channels: list[dict[str, Any]]) -> None:
    """Undo old logs that added estimated_usd + search_cost_usd (same number)."""
    for ch in channels:
        if not isinstance(ch, dict) or _channel_is_skipped(ch):
            continue
        sid = str(ch.get("id") or "")
        if sid not in ("twitter_influencers", "tiktok_influencers", "youtube_influencers"):
            continue
        note = str(ch.get("cost_note") or "")
        m = _EST_USD_NOTE_RE.search(note)
        if not m:
            continue
        est = float(m.group(1))
        stored = ch.get("cost_usd")
        if est <= 0 or not isinstance(stored, (int, float)):
            continue
        if abs(float(stored) - 2.0 * est) < 0.0008:
            ch["cost_usd"] = round(est, 4)
            ch["cost_fmt"] = _fmt_usd(est)
            ch["cost_note"] = f"Apify billed ${est:g}"


def _dfs_labs_cost(n_keywords: int, *, cached: bool = False) -> float:
    if cached or n_keywords <= 0:
        return 0.0
    return round(_DFS_LABS_TASK_USD + _DFS_LABS_KEYWORD_USD * max(1, n_keywords), 6)


def refresh_dfs_step_costs(channels: list[dict[str, Any]]) -> None:
    """Reprice Brand DataForSEO rows at Labs keyword_overview rates."""
    for ch in channels:
        if not isinstance(ch, dict) or _channel_is_skipped(ch) or not _is_dfs_volume_step(ch):
            continue
        note = str(ch.get("cost_note") or "")
        if "fallback" in note.lower() and "search_volume" in note.lower():
            usd = round(_DFS_VOLUME_TASK_USD, 4)
            ch["cost_usd"] = usd
            ch["cost_fmt"] = _fmt_usd(usd)
            continue
        n = 1
        m = re.search(r"(\d+)\s*brands?", note, re.I)
        if m:
            n = max(1, int(m.group(1)))
        cached = "cached=" in note and re.search(r"cached=(\d+)", note)
        labs_n = re.search(r"labs=(\d+)", note)
        if cached and int(cached.group(1)) >= n and not (labs_n and int(labs_n.group(1))):
            usd = 0.0
        else:
            usd = _dfs_labs_cost(n)
        ch["cost_usd"] = usd
        ch["cost_fmt"] = _fmt_usd(usd)
        ch["cost_note"] = (
            f"DataForSEO Labs keyword_overview "
            f"${_DFS_LABS_TASK_USD:g}+${_DFS_LABS_KEYWORD_USD:g}/kw, {n} brands"
        )


def apply_cost_shares(
    channels: list[dict[str, Any]],
    totals: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Fill cost_pct / cost_pct_fmt on each step from cost_usd vs run total."""
    totals = totals if isinstance(totals, dict) else {}
    refresh_apify_step_costs(channels)
    refresh_dfs_step_costs(channels)
    refresh_duplicate_usage_costs(channels)
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        apis = ch.get("apis")
        if not isinstance(apis, list) or not apis:
            apis = apis_for_cost(
                str(ch.get("cost_note") or ""),
                CHANNEL_APIS.get(str(ch.get("id") or ""), []),
            )
        else:
            apis = [_normalize_api_name(str(a)) for a in apis if str(a).strip()]
            from_note = apis_for_cost(str(ch.get("cost_note") or ""), None)
            if from_note:
                apis = from_note
        ch["apis"] = apis
        ch["apis_fmt"] = _fmt_apis(apis)
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

    runs = _runs_per_usd(total if total > 0 else None)
    totals["runs_per_usd"] = runs
    totals["runs_per_usd_fmt"] = _fmt_runs_per_usd(runs)
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
    if not isinstance(usage, dict):
        usage = {}
    usage = dict(usage)
    if not usage.get("scrapingbee_credits"):
        credits = 0
        for row in section.get("rows") or []:
            if not isinstance(row, dict):
                continue
            u = row.get("usage") if isinstance(row.get("usage"), dict) else {}
            credits += int(u.get("scrapingbee_credits") or u.get("credits") or 0)
        if credits > 0:
            usage["scrapingbee_credits"] = credits
    if usage.get("elapsed_sec") in (None, 0, 0.0) and section.get("elapsed_sec"):
        usage["elapsed_sec"] = section.get("elapsed_sec")
    return usage


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

    # One vendor total only. X/TikTok/YouTube store the same figure on
    # estimated_usd and search_cost_usd — summing both doubled Apify.
    picked_total = None
    picked_key = ""
    for k in ("estimated_total_usd", "estimated_usd", "cost_usd", "total_cost_usd"):
        if isinstance(usage.get(k), (int, float)):
            picked_total = float(usage[k])
            picked_key = k
            break
    if picked_total is not None and picked_total > 0:
        usd += picked_total
        known = True
        notes.append(f"{picked_key}={picked_total}")
    else:
        for k in ("search_cost_usd", "fetch_cost_usd"):
            if isinstance(usage.get(k), (int, float)) and float(usage[k]) > 0:
                usd += float(usage[k])
                known = True
                notes.append(f"{k}={usage[k]}")

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

    if step_id in ("brand_dfs", "brand_growth"):
        usage_cost = usage.get("cost_usd")
        if known:
            notes.append(
                usage.get("note")
                or f"DataForSEO Labs billed ${usd:g}"
            )
        elif isinstance(usage_cost, (int, float)) and float(usage_cost) >= 0:
            usd += float(usage_cost)
            known = True
            notes.append(
                usage.get("note")
                or f"DataForSEO Labs billed ${float(usage_cost):g}"
            )
        else:
            n = _n_rows(report, step_id)
            if step_id == "brand_growth" and n <= 0:
                bg = report.get("brand_growth_usage") if isinstance(report.get("brand_growth_usage"), dict) else {}
                if isinstance(bg.get("cost_usd"), (int, float)):
                    usd += float(bg["cost_usd"])
                    known = True
                    notes.append(bg.get("note") or f"DataForSEO Labs billed ${float(bg['cost_usd']):g}")
                    n = 0
                else:
                    n = len(report.get("competitors") or []) or 1
            if not known:
                n = max(1, n)
                part = _dfs_labs_cost(n)
                usd += part
                known = True
                notes.append(
                    f"DataForSEO Labs keyword_overview "
                    f"${_DFS_LABS_TASK_USD:g}+${_DFS_LABS_KEYWORD_USD:g}/kw, {n} brands"
                )
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

    if step_id == "instagram_influencers":
        notes.append("TinyFish Search+Fetch (free / daily allowance)")
        if not known:
            return 0.0, "; ".join(notes), apis

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
        (re.compile(r"\[X-INF|twitter.?influencers|x.?influencers", re.I), "twitter_influencers"),
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

    def absorb_child_log(self, child_log: Optional[dict[str, Any]]) -> None:
        """Copy per-channel wall times from a nested site_only run into All mode."""
        if not isinstance(child_log, dict):
            return
        for ch in child_log.get("channels") or []:
            if not isinstance(ch, dict):
                continue
            sid = str(ch.get("id") or "").strip()
            if not sid:
                continue
            row = self.steps.setdefault(
                sid,
                {
                    "id": sid,
                    "label": ch.get("label") or STEP_LABELS.get(sid, sid),
                    "sec": 0.0,
                    "status": "done",
                    "detail": "",
                },
            )
            try:
                extra = float(ch.get("sec") or 0)
            except (TypeError, ValueError):
                extra = 0.0
            if extra > 0:
                row["sec"] = float(row.get("sec") or 0) + extra
            if ch.get("label"):
                row["label"] = ch["label"]
            if ch.get("status"):
                row["status"] = ch["status"]
            detail = str(ch.get("detail") or "").strip()
            if detail and not str(row.get("detail") or "").lower().startswith("merged"):
                row["detail"] = detail

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
            usage = _section_usage(report, sid)
            try:
                sec = float(row.get("sec") or 0)
            except (TypeError, ValueError):
                sec = 0.0
            if sec <= 0:
                for key in ("elapsed_sec", "elapsed"):
                    raw = usage.get(key)
                    if isinstance(raw, (int, float)) and float(raw) > 0:
                        sec = float(raw)
                        break
            status = str(row.get("status") or "")
            detail = str(row.get("detail") or "")
            if status == "done" and detail.lower().startswith("skip"):
                cost_usd, note, apis = None, "skipped", list(CHANNEL_APIS.get(sid, []))
            else:
                cost_usd, note, apis = _estimate_step_cost(sid, report, log_credits)
            apis = apis_for_cost(note, apis or CHANNEL_APIS.get(sid, []))
            if isinstance(cost_usd, (int, float)):
                total_cost += float(cost_usd)
                cost_known = True
            channels.append({
                "id": sid,
                "label": row.get("label") or STEP_LABELS.get(sid, sid),
                "sec": round(sec, 2),
                "sec_fmt": _fmt_sec(sec),
                "status": status,
                "detail": detail,
                "apis": apis,
                "apis_fmt": _fmt_apis(apis),
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
            "rates_note": cost_rates_note(),
        }


def _as_view_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        digits = re.sub(r"[^\d]", "", str(value or ""))
        return int(digits) if digits else 0


def _slim_pulled_video(
    item: dict[str, Any],
    *,
    platform: str,
    company: str,
) -> dict[str, Any]:
    desc = str(
        item.get("description")
        or item.get("snippet")
        or item.get("subtitle_text")
        or item.get("text")
        or ""
    ).replace("\n", " ")
    return {
        "platform": platform,
        "company": company,
        "title": str(item.get("title") or "")[:240],
        "description": desc[:400],
        "views": _as_view_int(item.get("views")),
        "age": str(item.get("upload_age") or item.get("age") or ""),
        "channel": str(item.get("channel_name") or item.get("handle") or ""),
        "url": str(item.get("url") or item.get("postPage") or ""),
        "label": str(item.get("label") or ""),
    }


def _row_pulled_videos(row: dict[str, Any]) -> list[dict[str, Any]]:
    fetched = row.get("videos_fetched")
    if isinstance(fetched, list) and fetched:
        return [x for x in fetched if isinstance(x, dict)]
    out: list[dict[str, Any]] = []
    keys = (
        ("videos_confirmed", "videos_probable", "videos_unrelated")
        if (row.get("videos_confirmed") or row.get("videos_unrelated"))
        else ("videos_about_product", "videos_probable", "videos_unrelated")
    )
    for key in keys:
        for item in row.get(key) or []:
            if isinstance(item, dict):
                out.append(item)
    return out


def collect_api_pulls(report: Optional[dict[str, Any]] = None) -> dict[str, list[dict[str, Any]]]:
    """YouTube + TikTok items returned by the API before the brand cut."""
    report = report or {}
    youtube: list[dict[str, Any]] = []
    tiktok: list[dict[str, Any]] = []
    for row in (report.get("youtube_influencers") or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        company = str(row.get("name") or row.get("domain") or "")
        for item in _row_pulled_videos(row):
            youtube.append(_slim_pulled_video(item, platform="youtube", company=company))
    for row in (report.get("tiktok_influencers") or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        company = str(row.get("name") or row.get("domain") or "")
        for item in _row_pulled_videos(row):
            tiktok.append(_slim_pulled_video(item, platform="tiktok", company=company))
    return {"youtube": youtube, "tiktok": tiktok}


def attach_run_log(report: dict[str, Any], recorder: RunRecorder) -> dict[str, Any]:
    payload = recorder.finalize(report)
    payload["api_pulls"] = collect_api_pulls(report)
    try:
        vendor = Path(__file__).resolve().parent / "scripts" / "vendor"
        if str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        from llm_trace import load_calls

        payload["llm_calls"] = load_calls()
    except Exception:
        payload["llm_calls"] = []
    report["run_log"] = payload
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
