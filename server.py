# -*- coding: utf-8 -*-
"""Spy USA — marketing analysis (US market). Form + HTML tables, no chatbot."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Optional

from flask import Flask, Response, jsonify, request, send_from_directory

from parse_input import ParsedInput, parse_user_message
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

APP_VERSION = "0.1.0"
REQUIRED_LIVE_KEYS = (
    "OPENROUTER_API_KEY",
    "SCRAPINGBEE_API_KEY",
    "DATAFORSEO_USER",
    "DATAFORSEO_PASS",
    "SEMRUSH_API_KEY",
)


def _live_keys_ready() -> dict[str, bool]:
    return {k: bool(os.environ.get(k, "").strip()) for k in REQUIRED_LIVE_KEYS}


@dataclass
class Job:
    job_id: str
    parsed: ParsedInput
    force: bool = False
    site_only: bool = False
    include_google_ads: bool = True
    include_linkedin: bool = True
    queue: Queue = field(default_factory=Queue)
    status: str = "pending"
    current_step: str = ""
    steps: dict = field(default_factory=dict)
    error: Optional[str] = None
    report: Optional[dict] = None
    html_url: str = ""


jobs: dict[str, Job] = {}


def emit(job: Job, event_type: str, **payload: Any) -> None:
    job.queue.put({"type": event_type, "job_id": job.job_id, "ts": time.time(), **payload})


def set_step(job: Job, step_id: str, state: str, detail: str = "") -> None:
    job.current_step = step_id
    job.steps[step_id] = {"state": state, "detail": detail, "at": time.time()}
    emit(job, "step", step_id=step_id, state=state, detail=detail, steps=job.steps)


def _worker(job: Job) -> None:
    try:
        job.status = "running"
        emit(job, "started", company=job.parsed.company, slug=job.parsed.slug, market="US")

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
        )
        job.report = report
        job.html_url = f"/runs/{job.job_id}/report.html"
        job.status = "done"
        emit(job, "finished", html_url=job.html_url, status="done")
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        emit(job, "error", message=str(e))
    finally:
        emit(job, "eof")


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
        "market": "US",
        "live_ready": all(keys.values()),
        "keys": keys,
        "steps": [{"id": s["id"], "label": s["label"]} for s in STEP_DEFS],
    })


@app.post("/api/analyze")
def analyze():
    body = request.get_json(silent=True) or {}
    raw = (body.get("url") or body.get("company") or body.get("q") or "").strip()
    if not raw:
        return jsonify({"error": "Informe um domínio ou URL (ex: semrush.com)"}), 400
    force = bool(body.get("force") or body.get("refresh"))
    site_only = bool(body.get("site_only") or body.get("solo") or body.get("only_site"))
    # Google Ads Library: default on; send false / 0 to skip
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
    parsed = parse_user_message(raw)
    if not parsed.url and not parsed.slug:
        return jsonify({"error": "Não foi possível interpretar a empresa/URL"}), 400

    missing = [k for k, ok in _live_keys_ready().items() if not ok]
    if missing:
        return jsonify({"error": "API keys ausentes: " + ", ".join(missing), "missing": missing}), 503

    job_id = uuid.uuid4().hex[:12]
    job = Job(
        job_id=job_id,
        parsed=parsed,
        force=force,
        site_only=site_only,
        include_google_ads=include_google_ads,
        include_linkedin=include_linkedin,
    )
    jobs[job_id] = job
    threading.Thread(target=_worker, args=(job,), daemon=True).start()
    return jsonify({
        "job_id": job_id,
        "company": parsed.company,
        "slug": parsed.slug,
        "url": parsed.url,
        "site_only": site_only,
        "include_google_ads": include_google_ads,
        "include_linkedin": include_linkedin,
        "stream": f"/api/jobs/{job_id}/stream",
        "status_url": f"/api/jobs/{job_id}",
    })


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        # Try disk
        report_path = RUNS_DIR / job_id / "report.html"
        if report_path.exists():
            return jsonify({"job_id": job_id, "status": "done", "html_url": f"/runs/{job_id}/report.html"})
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "job_id": job_id,
        "status": job.status,
        "current_step": job.current_step,
        "steps": job.steps,
        "error": job.error,
        "html_url": job.html_url or (f"/runs/{job_id}/report.html" if job.status == "done" else ""),
        "company": job.parsed.company,
        "slug": job.parsed.slug,
        "url": job.parsed.url,
    })


@app.get("/api/jobs/<job_id>/stream")
def job_stream(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    def gen():
        while True:
            try:
                msg = job.queue.get(timeout=25)
            except Empty:
                yield f"data: {json.dumps({'type': 'ping', 'ts': time.time()})}\n\n"
                continue
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg.get("type") in ("eof", "error", "finished"):
                if msg.get("type") == "error":
                    break
                if msg.get("type") in ("eof", "finished"):
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
