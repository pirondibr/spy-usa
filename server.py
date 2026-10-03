# -*- coding: utf-8 -*-
"""Spy USA — marketing analysis (US market). Form + HTML tables, no chatbot."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Optional

from flask import Flask, Response, jsonify, request, send_from_directory

from parse_input import ParsedInput, parse_company_list
from pipeline import RUNS_DIR, STEP_DEFS, clear_slug_cache, run_pipeline

STATIC_DIR = Path(__file__).resolve().parent / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")


def _load_dotenv() -> None:
    for candidate in (
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / "radar-agent-demo" / ".env",
        Path.home() / "Desktop" / "Radar 09 2026" / ".env",
    ):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
        break


_load_dotenv()
os.environ.setdefault("SPY_MARKET", "us")

APP_VERSION = "0.3.0"
REQUIRED_LIVE_KEYS = (
    "OPENROUTER_API_KEY",
    "SCRAPINGBEE_API_KEY",
    "DATAFORSEO_USER",
    "DATAFORSEO_PASS",
    "SEMRUSH_API_KEY",
)


def _live_keys_ready() -> dict[str, bool]:
    return {k: bool(os.environ.get(k, "").strip()) for k in REQUIRED_LIVE_KEYS}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_run_meta(job: "Job", **extra: Any) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = RUNS_DIR / job.job_id
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": job.job_id,
        "slug": job.parsed.slug,
        "url": job.parsed.url,
        "company": job.parsed.company,
        "status": job.status,
        "market": (getattr(job, "market", None) or "us").upper(),
        "site_only": bool(job.site_only),
        "compare_all": bool(getattr(job, "compare_all", False)),
        "peer_urls": list(job.parsed.competitors or []),
        "include_google_ads": bool(job.include_google_ads),
        "include_linkedin": bool(job.include_linkedin),
        "force": bool(job.force),
        "created_at": job.created_at,
        "updated_at": _now_iso(),
        "html_url": job.html_url or (f"/runs/{job.job_id}/report.html" if job.status == "done" else ""),
        "error": job.error or "",
        "current_step": job.current_step or "",
    }
    meta.update(extra)
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_run_meta(run_id: str) -> Optional[dict[str, Any]]:
    path = RUNS_DIR / run_id / "meta.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    html = RUNS_DIR / run_id / "report.html"
    if html.exists():
        # Legacy run without meta.json
        company = run_id
        url = ""
        report_json = RUNS_DIR / run_id / "report.json"
        if report_json.exists():
            try:
                rep = json.loads(report_json.read_text(encoding="utf-8"))
                company = (
                    (rep.get("briefing") or {}).get("client")
                    or rep.get("client")
                    or company
                )
                url = (rep.get("briefing") or {}).get("url") or ""
            except Exception:
                pass
        mtime = datetime.fromtimestamp(html.stat().st_mtime, tz=timezone.utc)
        return {
            "id": run_id,
            "company": company,
            "url": url,
            "slug": "",
            "status": "done",
            "market": "US",
            "site_only": True,
            "created_at": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "html_url": f"/runs/{run_id}/report.html",
        }
    return None


def list_runs(limit: int = 40) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    if RUNS_DIR.exists():
        for d in RUNS_DIR.iterdir():
            if not d.is_dir():
                continue
            meta = _read_run_meta(d.name)
            if meta:
                by_id[d.name] = meta

    # Overlay in-memory jobs (running / just finished)
    for job in jobs.values():
        by_id[job.job_id] = {
            "id": job.job_id,
            "company": job.parsed.company,
            "url": job.parsed.url,
            "slug": job.parsed.slug,
            "status": job.status,
            "market": "US",
            "site_only": job.site_only,
            "include_google_ads": job.include_google_ads,
            "include_linkedin": job.include_linkedin,
            "force": job.force,
            "created_at": job.created_at,
            "html_url": job.html_url or (
                f"/runs/{job.job_id}/report.html" if job.status == "done" else ""
            ),
            "error": job.error or "",
            "current_step": job.current_step or "",
        }

    def _sort_key(m: dict[str, Any]) -> str:
        return str(m.get("created_at") or m.get("updated_at") or "")

    rows = sorted(by_id.values(), key=_sort_key, reverse=True)
    return rows[:limit]


@dataclass
class Job:
    job_id: str
    parsed: ParsedInput
    force: bool = False
    site_only: bool = False
    include_google_ads: bool = True
    include_linkedin: bool = True
    market: str = "us"
    compare_all: bool = False
    queue: Queue = field(default_factory=Queue)
    status: str = "pending"
    current_step: str = ""
    steps: dict = field(default_factory=dict)
    error: Optional[str] = None
    report: Optional[dict] = None
    html_url: str = ""
    created_at: str = field(default_factory=_now_iso)


jobs: dict[str, Job] = {}
_job_lock = threading.Lock()
_run_queue: Queue = Queue()
_runner_started = False


def emit(job: Job, event_type: str, **payload: Any) -> None:
    job.queue.put({"type": event_type, "job_id": job.job_id, "ts": time.time(), **payload})


def set_step(job: Job, step_id: str, state: str, detail: str = "") -> None:
    job.current_step = step_id
    job.steps[step_id] = {"state": state, "detail": detail, "at": time.time()}
    emit(job, "step", step_id=step_id, state=state, detail=detail, steps=job.steps)


def _ensure_runner() -> None:
    global _runner_started
    with _job_lock:
        if _runner_started:
            return
        _runner_started = True
        threading.Thread(target=_queue_runner, daemon=True).start()


def _queue_runner() -> None:
    """Processa jobs um a um (protege ScrapingBee / APIs)."""
    while True:
        job_id = _run_queue.get()
        job = jobs.get(job_id)
        if job:
            _worker(job)
        _run_queue.task_done()


def _worker(job: Job) -> None:
    try:
        job.status = "running"
        _write_run_meta(job)
        emit(
            job, "started",
            company=job.parsed.company,
            slug=job.parsed.slug,
            market=(job.market or "us").upper(),
            compare_all=bool(job.compare_all),
        )

        def _emit(event_type: str, **payload: Any) -> None:
            emit(job, event_type, **payload)

        def _set_step(step_id: str, state: str, detail: str = "") -> None:
            set_step(job, step_id, state, detail)

        report = run_pipeline(
            job.parsed,
            _emit,
            _set_step,
            run_id=job.job_id,
            force=job.force,
            site_only=job.site_only,
            include_google_ads=job.include_google_ads,
            include_linkedin=job.include_linkedin,
            market=job.market or "us",
            compare_all=bool(job.compare_all),
        )
        job.report = report
        job.html_url = f"/runs/{job.job_id}/report.html"
        job.status = "done"
        _write_run_meta(job)
        emit(job, "finished", html_url=job.html_url, status="done")
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        _write_run_meta(job)
        emit(job, "error", message=str(e))
    finally:
        emit(job, "eof")


def _enqueue_job(job: Job) -> None:
    jobs[job.job_id] = job
    _write_run_meta(job)
    _ensure_runner()
    _run_queue.put(job.job_id)


def _normalize_market(raw: Any) -> str:
    m = str(raw or "us").strip().lower()
    if m in ("br", "brazil", "brasil", "bra", "sites br", "sites_br", "sites-br"):
        return "br"
    return "us"


def _flags_from_body(body: dict) -> tuple[bool, bool, bool, bool, str, bool]:
    force = bool(body.get("force") or body.get("refresh"))
    # Default ON: modo sem pesquisar concorrentes
    if "site_only" in body or "solo" in body or "only_site" in body:
        site_only = bool(body.get("site_only") or body.get("solo") or body.get("only_site"))
    else:
        site_only = True
    if "include_google_ads" in body:
        include_google_ads = bool(body.get("include_google_ads"))
    elif "google_ads" in body:
        include_google_ads = bool(body.get("google_ads"))
    else:
        include_google_ads = True
    if "include_linkedin" in body:
        include_linkedin = bool(body.get("include_linkedin"))
    elif "linkedin" in body:
        include_linkedin = bool(body.get("linkedin"))
    else:
        include_linkedin = True
    market = _normalize_market(body.get("market") or body.get("spy_market") or os.environ.get("SPY_MARKET") or "us")
    compare_all = bool(
        body.get("compare_all")
        or body.get("all")
        or body.get("mode_all")
    )
    if compare_all:
        site_only = True
    return force, site_only, include_google_ads, include_linkedin, market, compare_all


def _job_payload(job: Job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "company": job.parsed.company,
        "slug": job.parsed.slug,
        "url": job.parsed.url,
        "site_only": job.site_only,
        "compare_all": bool(job.compare_all),
        "market": (job.market or "us").upper(),
        "include_google_ads": job.include_google_ads,
        "include_linkedin": job.include_linkedin,
        "force": job.force,
        "status": job.status,
        "stream": f"/api/jobs/{job.job_id}/stream",
        "status_url": f"/api/jobs/{job.job_id}",
        "html_url": job.html_url,
    }


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/hello")
def hello():
    keys = _live_keys_ready()
    return jsonify({
        "ok": True,
        "app": "spy-usa",
        "version": APP_VERSION,
        "market": _normalize_market(os.environ.get("SPY_MARKET") or "us").upper(),
        "markets": ["US", "BR"],
        "live_ready": all(keys.values()),
        "keys": keys,
        "steps": [{"id": s["id"], "label": s["label"]} for s in STEP_DEFS],
    })


@app.get("/api/runs")
def api_runs():
    limit = min(100, max(1, int(request.args.get("limit") or 40)))
    return jsonify({"runs": list_runs(limit=limit)})


@app.get("/api/runs/<run_id>")
def api_run_meta(run_id: str):
    meta = _read_run_meta(run_id)
    if not meta:
        job = jobs.get(run_id)
        if job:
            return jsonify(_job_payload(job))
        return jsonify({"error": "Run not found"}), 404
    return jsonify(meta)


def _start_jobs_from_raw(
    raw: str,
    *,
    force: bool,
    site_only: bool,
    include_google_ads: bool,
    include_linkedin: bool,
    market: str = "us",
    compare_all: bool = False,
) -> list[Job]:
    companies = parse_company_list(raw)
    if not companies:
        return []

    market = _normalize_market(market)
    if compare_all:
        site_only = True

    # All / discovery com N URLs → 1 job (primary + peers)
    if (compare_all or not site_only) and len(companies) > 1:
        primary = companies[0]
        primary.competitors = [
            (c.url or c.company or c.slug).rstrip("/")
            for c in companies[1:]
            if (c.url or c.company or c.slug)
        ]
        companies = [primary]

    created: list[Job] = []
    for parsed in companies:
        if not parsed.url and not parsed.slug:
            continue
        job = Job(
            job_id=uuid.uuid4().hex[:12],
            parsed=parsed,
            force=force,
            site_only=site_only,
            include_google_ads=include_google_ads,
            include_linkedin=include_linkedin,
            market=market,
            compare_all=compare_all,
        )
        _enqueue_job(job)
        created.append(job)
    return created


@app.post("/api/analyze")
def analyze():
    body = request.get_json(silent=True) or {}
    raw = (body.get("url") or body.get("company") or body.get("q") or body.get("urls") or "").strip()
    if isinstance(body.get("urls"), list):
        raw = "\n".join(str(x) for x in body.get("urls") if str(x).strip())
    if not raw:
        return jsonify({"error": "Informe um domínio ou URL (ex: semrush.com)"}), 400

    force, site_only, include_google_ads, include_linkedin, market, compare_all = _flags_from_body(body)

    missing = [k for k, ok in _live_keys_ready().items() if not ok]
    if missing:
        return jsonify({"error": "API keys ausentes: " + ", ".join(missing), "missing": missing}), 503

    created = _start_jobs_from_raw(
        raw,
        force=force,
        site_only=site_only,
        include_google_ads=include_google_ads,
        include_linkedin=include_linkedin,
        market=market,
        compare_all=compare_all,
    )
    if not created:
        return jsonify({"error": "Não foi possível interpretar a empresa/URL"}), 400

    payloads = [_job_payload(j) for j in created]
    primary = payloads[0]
    return jsonify({
        **primary,
        "batch": len(payloads) > 1,
        "jobs": payloads,
        "count": len(payloads),
        "market": market.upper(),
        "compare_all": compare_all,
        "site_only": site_only,
        "include_google_ads": include_google_ads,
        "include_linkedin": include_linkedin,
    })


@app.post("/api/rerun/<run_id>")
def rerun(run_id: str):
    """Refaz uma run anterior (force=true), reaproveitando URL/flags do meta."""
    meta = _read_run_meta(run_id)
    job_mem = jobs.get(run_id)
    if not meta and not job_mem:
        return jsonify({"error": "Run not found"}), 404

    url = ""
    site_only = True
    include_google_ads = True
    include_linkedin = True
    market = "us"
    compare_all = False
    peer_urls: list[str] = []
    if meta:
        url = (meta.get("url") or meta.get("company") or "").strip()
        site_only = bool(meta.get("site_only", True))
        include_google_ads = bool(meta.get("include_google_ads", True))
        include_linkedin = bool(meta.get("include_linkedin", True))
        market = _normalize_market(meta.get("market") or "us")
        compare_all = bool(meta.get("compare_all"))
        peer_urls = [str(x).strip() for x in (meta.get("peer_urls") or []) if str(x).strip()]
    if job_mem and not url:
        url = job_mem.parsed.url or job_mem.parsed.company
        site_only = job_mem.site_only
        include_google_ads = job_mem.include_google_ads
        include_linkedin = job_mem.include_linkedin
        market = _normalize_market(job_mem.market or "us")
        compare_all = bool(job_mem.compare_all)
        peer_urls = list(job_mem.parsed.competitors or [])

    if not url:
        return jsonify({"error": "Run sem URL para refazer"}), 400

    missing = [k for k, ok in _live_keys_ready().items() if not ok]
    if missing:
        return jsonify({"error": "API keys ausentes: " + ", ".join(missing), "missing": missing}), 503

    raw = url
    if peer_urls:
        raw = "\n".join([url] + peer_urls)

    created = _start_jobs_from_raw(
        raw,
        force=True,
        site_only=site_only,
        include_google_ads=include_google_ads,
        include_linkedin=include_linkedin,
        market=market,
        compare_all=compare_all,
    )
    if not created:
        return jsonify({"error": "Não foi possível interpretar a empresa/URL"}), 400

    payloads = [_job_payload(j) for j in created]
    primary = payloads[0]
    return jsonify({
        **primary,
        "batch": False,
        "jobs": payloads,
        "count": 1,
        "rerun_of": run_id,
    })


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        meta = _read_run_meta(job_id)
        if meta and meta.get("status") == "done":
            return jsonify({
                "job_id": job_id,
                "status": "done",
                "html_url": meta.get("html_url") or f"/runs/{job_id}/report.html",
                "company": meta.get("company"),
                "slug": meta.get("slug"),
                "url": meta.get("url"),
            })
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "job_id": job.job_id,
        "status": job.status,
        "current_step": job.current_step,
        "steps": job.steps,
        "error": job.error,
        "html_url": job.html_url or (f"/runs/{job.job_id}/report.html" if job.status == "done" else ""),
        "company": job.parsed.company,
        "slug": job.parsed.slug,
        "url": job.parsed.url,
        "site_only": job.site_only,
        "include_google_ads": job.include_google_ads,
        "include_linkedin": job.include_linkedin,
    })


@app.get("/api/jobs/<job_id>/stream")
def job_stream(job_id: str):
    job = jobs.get(job_id)
    if not job:
        meta = _read_run_meta(job_id)
        if meta and meta.get("status") == "done":
            def gen_done():
                yield f"data: {json.dumps({'type': 'finished', 'job_id': job_id, 'html_url': meta.get('html_url') or f'/runs/{job_id}/report.html', 'status': 'done'})}\n\n"
            return Response(gen_done(), mimetype="text/event-stream")
        return jsonify({"error": "Job not found"}), 404

    def gen():
        # Late subscriber: job already finished before EventSource connected
        if job.status == "done":
            yield f"data: {json.dumps({'type': 'finished', 'job_id': job.job_id, 'html_url': job.html_url or f'/runs/{job.job_id}/report.html', 'status': 'done'})}\n\n"
            return
        if job.status == "error":
            yield f"data: {json.dumps({'type': 'error', 'job_id': job.job_id, 'message': job.error or 'Error'})}\n\n"
            return
        while True:
            try:
                msg = job.queue.get(timeout=25)
            except Empty:
                # Status may have flipped while we waited
                if job.status == "done":
                    yield f"data: {json.dumps({'type': 'finished', 'job_id': job.job_id, 'html_url': job.html_url or f'/runs/{job.job_id}/report.html', 'status': 'done'})}\n\n"
                    return
                if job.status == "error":
                    yield f"data: {json.dumps({'type': 'error', 'job_id': job.job_id, 'message': job.error or 'Error'})}\n\n"
                    return
                yield f"data: {json.dumps({'type': 'ping', 'ts': time.time()})}\n\n"
                continue
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg.get("type") in ("eof", "error", "finished"):
                break

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/runs/<run_id>/report.html")
def run_report(run_id: str):
    path = RUNS_DIR / run_id / "report.html"
    if not path.exists():
        return "Report not found", 404
    return send_from_directory(path.parent, "report.html")


@app.post("/api/clear/<slug>")
def clear_cache(slug: str):
    try:
        result = clear_slug_cache(slug)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8770"))
    for d in (RUNS_DIR,):
        d.mkdir(parents=True, exist_ok=True)
    print(f"Spy USA -> http://127.0.0.1:{port}  market=US  v{APP_VERSION}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
