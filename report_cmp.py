# -*- coding: utf-8 -*-
"""Perfil da empresa + scoreboard de concorrentes (concorrentes-completo.html)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from report_analysis_compare import COLORS, MAX_COMPANIES

SCORE_LVL = {"high": 3, "medium": 2, "low": 1, "0": 0}

# mock key → report channel key
CHAN = {
    "google": "google_ads",
    "meta": "meta",
    "li_ads": "linkedin",
    "seo": "seo",
    "x": "twitter",
    "ig": "instagram",
    "li": "linkedin_profile",
    "yt": "youtube",
    "tt": "tiktok",
    "rd": "reddit",
    "yt_inf": "youtube_influencers",
    "ig_inf": "instagram_influencers",
}


def _has_channel(sec: Optional[dict[str, Any]]) -> bool:
    if not isinstance(sec, dict):
        return False
    return bool(
        sec.get("rows")
        or sec.get("total_fmt")
        or sec.get("total_ads_fmt")
        or sec.get("total_traffic_fmt")
    )


def _num(v: Any) -> Optional[float]:
    from report_html import _coerce_number

    return _coerce_number(v)


def _year_from_label(label: Any) -> Optional[int]:
    m = re.search(r"(20\d{2})", str(label or ""))
    return int(m.group(1)) if m else None


def _month_series(row: dict[str, Any]) -> tuple[list[float], list[str]]:
    months = list(row.get("visits_monthly") or [])[-3:]
    vals: list[float] = []
    labels: list[str] = []
    for m in months:
        if not isinstance(m, dict):
            continue
        n = _num(m.get("visits"))
        if n is None:
            n = _num(str(m.get("visits_fmt") or "").replace(",", ""))
        vals.append(float(n or 0))
        labels.append(str(m.get("label") or str(m.get("date") or "")[:7] or "—"))
    return vals, labels


def _brand_series(row: dict[str, Any]) -> tuple[list[float], list[str]]:
    latest = _num(row.get("traffic") or row.get("latest_volume")) or 0.0
    vals = [
        float(_num(row.get("volume_3y")) or 0),
        float(_num(row.get("volume_2y")) or 0),
        float(_num(row.get("volume_1y")) or 0),
        float(latest),
    ]
    year = _year_from_label(row.get("latest_label") or row.get("snapshot_label"))
    if year:
        labels = [str(year - 3), str(year - 2), str(year - 1), str(year)]
    else:
        labels = ["3 anos", "2 anos", "1 ano", "Atual"]
    return vals, labels


def _growth_from_series(vals: list[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    first, last = vals[0], vals[-1]
    if first <= 0:
        return None
    return round((last / first - 1) * 100, 1)


def build_cmp_payload(
    report: dict[str, Any],
    companies: list[dict[str, Any]],
    *,
    market: str = "US",
    colors: Optional[list[str]] = None,
) -> dict[str, Any]:
    from report_html import (  # noqa: PLC0415
        _channel_metric_value,
        _channel_score,
        _dfs_growth_pct,
        _row_for_company,
        _summary_companies,
    )

    raw = list(companies or _summary_companies(report))[:MAX_COMPANIES]
    palette = colors or [COLORS[i % len(COLORS)] for i in range(len(raw))]

    visit_labels: list[str] = []
    brand_labels: list[str] = []
    snap = ""
    brand_snap = ""

    rows_out: list[dict[str, Any]] = []
    for i, company in enumerate(raw):
        color = palette[i % len(palette)]
        scores: dict[str, Any] = {}
        data: dict[str, Any] = {}
        warns: dict[str, str] = {}
        for mk, key in CHAN.items():
            sec = report.get(key)
            if not _has_channel(sec if isinstance(sec, dict) else None):
                scores[mk] = None
                data[mk] = None
                continue
            assert isinstance(sec, dict)
            row = _row_for_company(sec, company)
            if row is None:
                scores[mk] = None
                data[mk] = None
                continue
            metric = _channel_metric_value(key, sec, row)
            scores[mk] = SCORE_LVL.get(_channel_score(key, metric), 0)
            data[mk] = metric
            note = str(row.get("note") or "").strip()
            if note:
                warns[mk] = note

        sw_sec = report.get("similarweb") if isinstance(report.get("similarweb"), dict) else {}
        sw_row = _row_for_company(sw_sec, company) if sw_sec else None
        sw_row = sw_row or {}
        v_series, v_labs = _month_series(sw_row)
        if v_labs and not visit_labels:
            visit_labels = v_labs
        visits = _num(sw_row.get("traffic"))
        if visits is None and v_series:
            visits = v_series[-1]
        vg = _growth_from_series(v_series)
        if vg is None:
            g = _num(sw_row.get("growth_pct") or sw_row.get("growth"))
            vg = g
        snap = str(sw_row.get("snapshot_label") or sw_sec.get("latest_label") or snap)

        dfs_sec = report.get("brand_dataforseo") if isinstance(report.get("brand_dataforseo"), dict) else {}
        dfs_row = _row_for_company(dfs_sec, company) if dfs_sec else None
        dfs_row = dfs_row or {}
        b_series, b_labs = _brand_series(dfs_row)
        if b_labs and not brand_labels:
            brand_labels = b_labs
        brand = _num(dfs_row.get("traffic") or dfs_row.get("latest_volume"))
        if brand is None and b_series:
            brand = b_series[-1]
        bg = dfs_row.get("growth_1y_pct")
        if not isinstance(bg, (int, float)):
            bg = _dfs_growth_pct(
                dfs_row.get("traffic") or dfs_row.get("latest_volume"),
                dfs_row.get("volume_1y"),
            )
        brand_snap = str(dfs_row.get("latest_label") or dfs_sec.get("latest_label") or brand_snap)

        host = str(company.get("domain") or "").strip()
        rows_out.append(
            {
                "name": str(company.get("name") or host or "—"),
                "dom": host,
                "color": color,
                "me": bool(company.get("is_client")),
                "visits": visits if visits is not None else 0,
                "vg": float(vg) if isinstance(vg, (int, float)) else 0,
                "brand": brand if brand is not None else 0,
                "bg": float(bg) if isinstance(bg, (int, float)) else 0,
                "s": scores,
                "d": data,
                "w": warns,
                "series": {"v": v_series, "b": b_series},
            }
        )

    if not visit_labels:
        visit_labels = ["M-2", "M-1", "Atual"][: max((len(r["series"]["v"]) for r in rows_out), default=0)]
    if not brand_labels:
        brand_labels = ["3 anos", "2 anos", "1 ano", "Atual"]

    first_m = visit_labels[0] if visit_labels else ""
    last_m = visit_labels[-1] if visit_labels else ""
    foot_visits = "SimilarWeb"
    if snap:
        foot_visits += f", {snap}"
    if first_m and last_m and first_m != last_m:
        foot_visits += f", variação {first_m} → {last_m}"
    foot_brand = "DataForSEO, variação em 1 ano"
    if brand_snap:
        foot_brand = f"DataForSEO, {brand_snap}, variação em 1 ano"

    return {
        "rows": rows_out,
        "visit_labels": visit_labels,
        "brand_labels": brand_labels,
        "foot_visits": foot_visits,
        "foot_brand": foot_brand,
        "market": market,
    }


def build_cmp_html(
    payload: dict[str, Any],
    *,
    profile_only: bool = False,
    root_id: str = "cmp",
) -> str:
    from report_html import _esc

    rows = payload.get("rows") or []
    if not rows:
        return ""
    raw = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    only = " data-profile-only" if profile_only else ""
    picker_note = (
        ""
        if profile_only or len(rows) < 2
        else '<span class="sec-note">Escolha a empresa aqui ou clicando no nome dela na tabela</span>'
    )
    picker = "" if profile_only or len(rows) < 2 else '<div class="picker" role="group" aria-label="Empresa do card"></div>'
    table = ""
    if not profile_only:
        table = f"""
<section class="sec" id="concorrentes">
  <div class="sec-h"><h2>Todos os concorrentes</h2><span class="sec-note">Onde cada empresa é forte ou fraca, canal a canal</span></div>
  <div class="bar">
    <div style="display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center">
      <div class="seg" role="group" aria-label="Nível de detalhe">
        <button type="button" data-view="full" aria-pressed="true">Por canal</button>
        <button type="button" data-view="compact" aria-pressed="false">Só categorias</button>
      </div>
      <div class="seg" role="group" aria-label="Mostrar">
        <button type="button" data-mode="lvl" aria-pressed="true">Notas</button>
        <button type="button" data-mode="data" aria-pressed="false">Dados</button>
      </div>
      <label class="chk"><input type="checkbox" class="cmp-weak">Destacar fraquezas</label>
    </div>
    <div class="legend">
      <span class="g-org"><span class="m on3" aria-hidden="true"><i></i><i></i><i></i></span>Alto</span>
      <span class="g-org"><span class="m on2" aria-hidden="true"><i></i><i></i><i></i></span>Médio</span>
      <span class="g-org"><span class="m on1" aria-hidden="true"><i></i><i></i><i></i></span>Baixo</span>
      <span><span class="m z" aria-hidden="true"><i></i><i></i><i></i></span>Sem presença</span>
      <span><span class="na">n/c</span>Não coletado</span>
      <span><span class="warn" style="margin:0">!</span>Verificar dado</span>
    </div>
  </div>
  <div class="card">
    <div class="tw"><table class="cmp-t"></table></div>
    <div class="foot">
      <span>Clique no nome de uma coluna para ordenar. A sua empresa fica sempre no topo.</span>
      <span>Visitas: {_esc(payload.get("foot_visits") or "SimilarWeb")}. Marca: {_esc(payload.get("foot_brand") or "DataForSEO")}.</span>
      <span>● ao lado do número = maior valor da coluna. No modo Dados, o peso do número segue a nota (negrito = Alto, cinza = Baixo, vermelho = zero).</span>
    </div>
  </div>
</section>"""

    perfil_id = "perfil" if root_id == "cmp" else f"perfil-{root_id}"
    return f"""
<div id="{_esc(root_id)}" class="cmp{' cmp-panel' if not profile_only else ''}" data-cmp{only}>
<script type="application/json" class="cmp-data">{raw}</script>
<section class="sec" id="{_esc(perfil_id)}">
  <div class="sec-h"><h2>Perfil da empresa</h2>{picker_note}</div>
  {picker}
  <div class="card pcard"></div>
</section>
{table}
</div>"""
