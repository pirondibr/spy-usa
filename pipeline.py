# -*- coding: utf-8 -*-
"""Spy USA pipeline: briefing → (concorrentes?) → SEO → Brand → Google Ads → Meta → Social."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from parse_input import ParsedInput, normalize_url, slugify_client
from report_builder import build_early_briefing_competitors, build_report_from_xlsx
from report_html import render_report_html

APP_DIR = Path(__file__).resolve().parent
FINAL_DIR = APP_DIR / "scripts"
SCRIPT_ENTENDER = FINAL_DIR / "1- entender o cliente.py"
SCRIPT_CONCORRENTES = FINAL_DIR / "3 - concorrentes Geral.py"
SCRIPT_SEO = FINAL_DIR / "5b - seo organico.py"
SCRIPT_BRAND = FINAL_DIR / "5c - brand search.py"
SCRIPT_GOOGLE = FINAL_DIR / "5a - google ads.py"
SCRIPT_META = FINAL_DIR / "5d - meta ads.py"
SCRIPT_LINKEDIN = FINAL_DIR / "5e - linkedin ads.py"
SCRIPT_SOCIAL = FINAL_DIR / "5f - social ig yt.py"

_DATA_DIR = (os.environ.get("RADAR_DATA_DIR") or os.environ.get("SPY_DATA_DIR") or "").strip()
_OUT_ROOT = (Path(_DATA_DIR) / "outputs") if _DATA_DIR else (APP_DIR / "outputs")
METRICAS_DIR = _OUT_ROOT / "metricas"
BRIEFING_DIR = _OUT_ROOT / "entender"
CONCORRENTES_DIR = _OUT_ROOT / "concorrentes"
RUNS_DIR = _OUT_ROOT / "runs"

EmitFn = Callable[..., None]

STEP_DEFS = [
    {"id": "briefing_concorrentes", "label": "Briefing (+ competitors)", "index": 1, "eta_live": 180},
    {"id": "seo", "label": "SEO organic (US)", "index": 2, "eta_live": 30},
    {"id": "brand", "label": "Brand search (US)", "index": 3, "eta_live": 30},
    {"id": "google_ads", "label": "Google Ads Library (US)", "index": 4, "eta_live": 180},
    {"id": "meta", "label": "Meta Ads (US)", "index": 5, "eta_live": 180},
    {"id": "linkedin", "label": "LinkedIn Ads Library (US)", "index": 6, "eta_live": 240},
    {"id": "instagram", "label": "Instagram", "index": 7, "eta_live": 120},
    {"id": "youtube", "label": "YouTube", "index": 8, "eta_live": 20},
    {"id": "tiktok", "label": "TikTok", "index": 9, "eta_live": 40},
]
TOTAL_STEPS = len(STEP_DEFS)


def find_metricas_xlsx(slug: str) -> Optional[Path]:
    folder = METRICAS_DIR / slug
    if not folder.exists():
        return None
    files = sorted(
        folder.glob(f"metricas-concorrentes-{slug}*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        files = sorted(folder.glob("metricas-concorrentes-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def find_briefing_xlsx(slug: str) -> Optional[Path]:
    folder = BRIEFING_DIR / slug
    if not folder.exists():
        return None
    files = sorted(
        folder.glob(f"briefing-cliente-{slug}*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        files = sorted(folder.glob("briefing-cliente-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def find_concorrentes_xlsx(slug: str) -> Optional[Path]:
    folder = CONCORRENTES_DIR / slug
    if not folder.exists():
        return None
    nacional = sorted(
        folder.glob(f"concorrentes-all-{slug}-nacional*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if nacional:
        return nacional[0]
    files = sorted(
        folder.glob(f"concorrentes-all-{slug}*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        files = sorted(folder.glob("concorrentes-all-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def clear_slug_cache(slug: str) -> dict[str, Any]:
    import re
    import shutil

    safe = re.sub(r"[^a-z0-9_-]+", "", (slug or "").strip().lower())[:80]
    if not safe:
        raise ValueError("Invalid slug")
    deleted: list[str] = []
    for base in (METRICAS_DIR, BRIEFING_DIR, CONCORRENTES_DIR):
        folder = (base / safe).resolve()
        try:
            folder.relative_to(base.resolve())
        except ValueError as e:
            raise ValueError(f"Path outside outputs: {folder}") from e
        if folder.exists() and folder.is_dir():
            shutil.rmtree(folder)
            deleted.append(str(folder))
    return {"slug": safe, "deleted": deleted, "cleared": bool(deleted)}


def build_solo_national_xlsx(slug: str, client_url: str, client_name: str) -> Path:
    """Minimal concorrentes XLSX with only the client (Semrush US traffic, no competitor discovery)."""
    sys.path.insert(0, str(FINAL_DIR))
    sys.path.insert(0, str(FINAL_DIR / "vendor"))
    from workspace_paths import setup_workspace  # noqa: E402

    setup_workspace()
    from find_concorrentes import build_3period_traffic  # noqa: E402
    from find_concorrentes_all import _write_growth_sheet, _write_traffic_sheet  # noqa: E402
    from find_concorrentes import read_briefing_from_xlsx  # noqa: E402
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from datetime import datetime

    briefing_path = find_briefing_xlsx(slug)
    if not briefing_path:
        raise RuntimeError(f"Briefing not found for solo mode: {slug}")
    briefing = read_briefing_from_xlsx(briefing_path)
    url = briefing.get("url") or client_url
    profile = briefing.get("perfil") or "—"

    emit_log = f"[SOLO] Semrush traffic for {url} only (no competitors)"
    print(emit_log, flush=True)
    traffic = build_3period_traffic(url, [], profile)

    out_dir = CONCORRENTES_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"concorrentes-all-{slug}-nacional.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.append(["Spy USA — site only (no competitors)"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(["Cliente", client_name])
    ws.append(["URL", url])
    ws.append(["Slug", slug])
    ws.append(["Mode", "site_only"])
    ws.append(["Market", "US"])
    ws.append(["Data", datetime.now().strftime("%d/%m/%Y %H:%M")])

    ws_c = wb.create_sheet("Concorrentes Unificado")
    ws_c.append(["Dominio", "URL", "Titulo", "Similaridade", "Perfil", "Fonte", "Nicho (LLM)"])
    # empty competitors — metrics script allows SPY_SITE_ONLY

    _write_traffic_sheet(wb, traffic)
    _write_growth_sheet(wb, traffic)
    wb.save(out_path)
    print(f"[SOLO] Saved {out_path}", flush=True)
    return out_path


def _run_script(
    cmd: list[str],
    cwd: Path,
    on_log: Optional[Callable[[str], None]] = None,
    timeout_sec: Optional[int] = None,
    env: Optional[dict[str, str]] = None,
) -> None:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=run_env,
    )
    assert proc.stdout is not None
    tail: list[str] = []

    def _reader() -> None:
        for line in proc.stdout:
            line = line.rstrip("\n\r")
            if not line:
                continue
            tail.append(line)
            if len(tail) > 40:
                del tail[:-40]
            if on_log:
                on_log(line)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    reader.join(timeout=timeout_sec)
    if reader.is_alive():
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        hint = ("\n--- last lines ---\n" + "\n".join(tail[-15:])) if tail else ""
        raise TimeoutError(f"Command exceeded {timeout_sec}s: {' '.join(cmd)}{hint}")
    proc.wait()
    if proc.returncode != 0:
        hint = ("\n--- last lines ---\n" + "\n".join(tail[-20:])) if tail else ""
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}{hint}")


def _fmt_eta(seconds: int) -> str:
    if seconds >= 60:
        return f"~{max(1, round(seconds / 60))} min"
    return f"~{seconds}s"


def _emit_progress(
    emit: EmitFn,
    set_step: EmitFn,
    step_id: str,
    state: str,
    detail: str,
) -> None:
    meta = next((s for s in STEP_DEFS if s["id"] == step_id), None)
    index = int(meta["index"]) if meta else 0
    eta = int(meta.get("eta_live") or 60) if meta else 60
    set_step(step_id, state, detail)
    emit(
        "progress",
        step_id=step_id,
        state=state,
        detail=detail,
        index=index,
        total=TOTAL_STEPS,
        label=meta["label"] if meta else step_id,
        eta_seconds=eta,
        eta_label=_fmt_eta(eta),
        progress_label=f"Step {index}/{TOTAL_STEPS}",
    )


def _save_report(run_id: str, report: dict, parsed: ParsedInput) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    import json

    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    html = render_report_html(
        report,
        run_meta={
            "id": run_id,
            "slug": parsed.slug,
            "url": parsed.url,
            "company": parsed.company,
            "status": "done",
            "market": "US",
        },
    )
    html_path = run_dir / "report.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


def run_pipeline(
    parsed: ParsedInput,
    emit: EmitFn,
    set_step: EmitFn,
    run_id: str = "",
    force: bool = False,
    site_only: bool = False,
    include_google_ads: bool = True,
    include_linkedin: bool = True,
) -> dict:
    required = (
        "OPENROUTER_API_KEY",
        "SCRAPINGBEE_API_KEY",
        "DATAFORSEO_USER",
        "DATAFORSEO_PASS",
        "SEMRUSH_API_KEY",
    )
    missing = [k for k in required if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError("Missing API keys: " + ", ".join(missing))

    url = normalize_url(parsed.url) or parsed.url
    if not url:
        raise ValueError("Company URL is required.")
    slug = parsed.slug or slugify_client(url)
    client_name = parsed.company or slug
    script_env = {"SPY_SITE_ONLY": "1" if site_only else "0", "SPY_MARKET": "us"}

    def on_log(line: str) -> None:
        emit("log", line=line)

    if force:
        clear_slug_cache(slug)

    existing = find_metricas_xlsx(slug)
    if existing and existing.exists() and not force:
        emit("log", line=f"[CACHE] Using existing metrics: {existing.name}")
        report = build_report_from_xlsx(
            existing,
            client_name=client_name,
            preferred_competitors=parsed.competitors,
        )
        _emit_progress(emit, set_step, "briefing_concorrentes", "done", "Cached report")
        for sid in ("seo", "brand", "google_ads", "meta", "linkedin", "instagram", "youtube", "tiktok"):
            _emit_progress(emit, set_step, sid, "done", "Cached")
        if run_id:
            _save_report(run_id, report, parsed)
        emit("done", report=report, html_url=f"/runs/{run_id}/report.html" if run_id else "")
        return report

    emit(
        "pipeline_meta",
        mode="live",
        market="US",
        site_only=site_only,
        include_google_ads=include_google_ads,
        include_linkedin=include_linkedin,
        total_steps=TOTAL_STEPS,
        eta_label="~3–8 min" if site_only else "~10–15 min",
    )

    # 1) Briefing + optional competitors
    if site_only:
        _emit_progress(
            emit, set_step, "briefing_concorrentes", "running",
            f"Briefing + site only (no competitors): {url}",
        )
    else:
        _emit_progress(
            emit, set_step, "briefing_concorrentes", "running",
            f"Briefing + US competitors: {url}",
        )

    _run_script(
        [sys.executable, str(SCRIPT_ENTENDER), url],
        FINAL_DIR,
        on_log,
        timeout_sec=300,
        env=script_env,
    )
    briefing_xlsx = find_briefing_xlsx(slug)
    if not briefing_xlsx:
        raise RuntimeError(f"Briefing not generated for '{slug}'.")

    if site_only:
        build_solo_national_xlsx(slug, url, client_name)
        early = build_early_briefing_competitors(
            find_briefing_xlsx(slug),
            find_concorrentes_xlsx(slug),
            client_name=client_name,
            preferred_competitors=[],
            fallback_url=url,
        )
        early["competitors_note"] = "Site only — competitor discovery skipped."
        early["competitors_count"] = 0
        emit("partial", section="briefing_concorrentes", data=early, client=client_name)
        _emit_progress(emit, set_step, "briefing_concorrentes", "done", "Site only (0 competitors)")
    else:
        _run_script(
            [sys.executable, str(SCRIPT_CONCORRENTES), slug, "nacional"],
            FINAL_DIR,
            on_log,
            timeout_sec=600,
            env=script_env,
        )
        early = build_early_briefing_competitors(
            find_briefing_xlsx(slug),
            find_concorrentes_xlsx(slug),
            client_name=client_name,
            preferred_competitors=parsed.competitors,
            fallback_url=url,
        )
        emit("partial", section="briefing_concorrentes", data=early, client=client_name)
        _emit_progress(
            emit, set_step, "briefing_concorrentes", "done",
            f"{early.get('competitors_count', 0)} competitors",
        )

    # 2) SEO
    _emit_progress(emit, set_step, "seo", "running", "Building US SEO ranking...")
    _run_script(
        [sys.executable, str(SCRIPT_SEO), slug],
        FINAL_DIR,
        on_log,
        timeout_sec=180,
        env=script_env,
    )
    xlsx = find_metricas_xlsx(slug)
    if not xlsx:
        raise FileNotFoundError(f"Metrics XLSX not generated for '{slug}'")
    report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
    emit("partial", section="seo", data=report.get("seo") or {}, client=client_name)
    _emit_progress(emit, set_step, "seo", "done", "SEO ready")

    # 3) Brand
    _emit_progress(emit, set_step, "brand", "running", "Building brand ranking...")
    _run_script(
        [sys.executable, str(SCRIPT_BRAND), slug],
        FINAL_DIR,
        on_log,
        timeout_sec=180,
        env=script_env,
    )
    xlsx = find_metricas_xlsx(slug) or xlsx
    report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
    emit("partial", section="brand", data=report.get("brand") or {}, client=client_name)
    _emit_progress(emit, set_step, "brand", "done", "Brand ready")

    # 4) Google Ads Library (optional)
    if include_google_ads:
        _emit_progress(emit, set_step, "google_ads", "running", "Google Ads Transparency (US)...")
        try:
            _run_script(
                [sys.executable, str(SCRIPT_GOOGLE), slug],
                FINAL_DIR,
                on_log,
                timeout_sec=420,
                env=script_env,
            )
        except Exception as e:
            emit("log", line=f"[GOOGLE] Partial failure: {e}")
        xlsx = find_metricas_xlsx(slug) or xlsx
        report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
        emit("partial", section="google_ads", data=report.get("google_ads") or {}, client=client_name)
        _emit_progress(emit, set_step, "google_ads", "done", "Google Ads ready")
    else:
        _emit_progress(emit, set_step, "google_ads", "done", "Skipped")

    # 5) Meta
    _emit_progress(emit, set_step, "meta", "running", "Meta Ads Library (US)...")
    try:
        _run_script(
            [sys.executable, str(SCRIPT_META), slug],
            FINAL_DIR,
            on_log,
            timeout_sec=420,
            env=script_env,
        )
    except Exception as e:
        emit("log", line=f"[META] Partial failure: {e}")
    xlsx = find_metricas_xlsx(slug) or xlsx
    report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
    emit("partial", section="meta", data=report.get("meta") or {}, client=client_name)
    _emit_progress(emit, set_step, "meta", "done", "Meta ready")

    # 6) LinkedIn Ads Library (optional) — empresa → ad → pagante → total
    if include_linkedin:
        _emit_progress(
            emit, set_step, "linkedin", "running",
            "LinkedIn Ads Library (US): find ad → payer → total...",
        )
        try:
            _run_script(
                [sys.executable, str(SCRIPT_LINKEDIN), slug],
                FINAL_DIR,
                on_log,
                timeout_sec=600,
                env=script_env,
            )
        except Exception as e:
            emit("log", line=f"[LINKEDIN] Partial failure: {e}")
        xlsx = find_metricas_xlsx(slug) or xlsx
        report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
        emit("partial", section="linkedin", data=report.get("linkedin") or {}, client=client_name)
        _emit_progress(emit, set_step, "linkedin", "done", "LinkedIn ready")
    else:
        _emit_progress(emit, set_step, "linkedin", "done", "Skipped")

    # 7–9) Social
    _emit_progress(emit, set_step, "instagram", "running", "Instagram / YouTube / TikTok...")
    try:
        _run_script(
            [sys.executable, str(SCRIPT_SOCIAL), slug],
            FINAL_DIR,
            on_log,
            timeout_sec=600,
            env=script_env,
        )
    except Exception as e:
        emit("log", line=f"[SOCIAL] Partial failure: {e}")
    xlsx = find_metricas_xlsx(slug) or xlsx
    report = build_report_from_xlsx(xlsx, client_name=client_name, preferred_competitors=parsed.competitors)
    for sid in ("instagram", "youtube", "tiktok"):
        emit("partial", section=sid, data=report.get(sid) or {}, client=client_name)
        _emit_progress(emit, set_step, sid, "done", f"{sid} ready")

    html_url = ""
    if run_id:
        _save_report(run_id, report, parsed)
        html_url = f"/runs/{run_id}/report.html"

    emit("done", report=report, html_url=html_url)
    return report
