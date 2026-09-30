# -*- coding: utf-8 -*-
"""Etapa SimilarWeb Traffic (RapidAPI) do Spy USA.

Uso:
    python "5h - similarweb.py" semrush
    python "5h - similarweb.py" semrush --out outputs/metricas/semrush/similarweb.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FINAL_DIR = Path(__file__).resolve().parent
VENDOR = FINAL_DIR / "vendor"
ROOT = FINAL_DIR.parent
sys.path.insert(0, str(FINAL_DIR))
sys.path.insert(0, str(VENDOR))


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()

from workspace_paths import setup_workspace, OUT_METRICAS, OUT_CONCORRENTES  # noqa: E402

setup_workspace()

from find_concorrentes import find_client_xlsx, read_briefing_from_xlsx  # noqa: E402
from seo_pipeline import brand_token_from_domain, normalize_domain  # noqa: E402
from similarweb_traffic import traffic_reports_batch  # noqa: E402


def _slugify(client: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", client or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", s.lower()) or "cliente"


def _load_entities(slug: str, briefing: dict) -> list[dict]:
    entities: list[dict] = []
    client_url = briefing.get("url") or ""
    client_dom = normalize_domain(client_url)
    client_name = (
        briefing.get("cliente")
        or briefing.get("client")
        or brand_token_from_domain(client_url)
        or slug
    )
    entities.append({
        "name": client_name,
        "company": client_name,
        "domain": client_dom,
        "url": client_url or (f"https://{client_dom}/" if client_dom else ""),
        "is_client": True,
        "similaridade": "Cliente",
    })

    folder = OUT_CONCORRENTES / slug
    if not folder.exists():
        return entities

    files = sorted(
        folder.glob(f"concorrentes-all-{slug}-nacional*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        files = sorted(
            folder.glob(f"concorrentes-all-{slug}*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    if not files:
        return entities

    try:
        import openpyxl

        wb = openpyxl.load_workbook(files[0], read_only=True, data_only=True)
        if "Concorrentes Unificado" not in wb.sheetnames:
            wb.close()
            return entities
        ws = wb["Concorrentes Unificado"]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return entities
        headers = [str(h or "").strip() for h in rows[0]]
        idx = {h: i for i, h in enumerate(headers)}

        def cell(row, name):
            i = idx.get(name)
            return row[i] if i is not None and i < len(row) else ""

        for row in rows[1:]:
            if not any(row):
                continue
            dom = normalize_domain(cell(row, "Dominio") or "")
            if not dom or dom == client_dom:
                continue
            sim = str(cell(row, "Similaridade") or "").strip()
            if sim.lower().replace("é", "e") not in ("alto", "medio"):
                continue
            title_c = str(cell(row, "Titulo") or "").strip()
            url = str(cell(row, "URL") or "") or f"https://{dom}/"
            name = title_c.split("|")[0].strip() if title_c else brand_token_from_domain(dom)
            entities.append({
                "name": name or dom,
                "company": name or dom,
                "domain": dom,
                "url": url,
                "is_client": False,
                "similaridade": sim or "—",
            })
            if len(entities) >= 8:  # client + up to 7 competitors (API quota)
                break
    except Exception as e:
        print(f"[SIMILARWEB] competitors load fail: {e}", flush=True)
    return entities


def main() -> None:
    if len(sys.argv) < 2:
        print('Uso: python "5h - similarweb.py" <cliente>')
        sys.exit(1)
    client = sys.argv[1].strip()
    slug = _slugify(client)
    out_path = OUT_METRICAS / slug / f"similarweb-{slug}.json"
    for i, a in enumerate(sys.argv):
        if a == "--out" and i + 1 < len(sys.argv):
            out_path = Path(sys.argv[i + 1])

    briefing_xlsx = find_client_xlsx(client)
    briefing = read_briefing_from_xlsx(briefing_xlsx)
    entities = _load_entities(slug, briefing)
    print(f"[SIMILARWEB] entidades={len(entities)} slug={slug}", flush=True)
    for e in entities:
        print(f"  - {e.get('domain')} ({e.get('similaridade')})", flush=True)

    rows = traffic_reports_batch(entities)
    client_row = next((r for r in rows if r.get("is_client")), rows[0] if rows else {})
    payload = {
        "slug": slug,
        "source": "similarweb_rapidapi",
        "market": "global",
        "endpoint": "traffic",
        "rows": rows,
        "client_domain": client_row.get("domain"),
        "latest_label": client_row.get("snapshot_label"),
        "latest_visits": client_row.get("latest_visits"),
    }
    # Strip bulky raw from disk? Keep for debugging but trim nested raw to save space
    for r in payload["rows"]:
        r.pop("raw", None)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OUT] {out_path}", flush=True)
    for r in rows[:8]:
        err = f" ERR={r.get('error')}" if r.get("error") else ""
        print(
            f"  {r.get('domain')}: visits={r.get('traffic_fmt')} "
            f"bounce={r.get('bounce_fmt')} ppv={r.get('pages_fmt')} "
            f"tos={r.get('time_fmt')}{err}",
            flush=True,
        )


if __name__ == "__main__":
    main()
