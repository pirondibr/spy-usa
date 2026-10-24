# -*- coding: utf-8 -*-
"""Find-competitors v2 — picker layout from concorrentes-encontrar.html."""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse

from report_html import (
    _briefing_nicho,
    _esc,
    _row_title,
    _sim_key,
    _vol_nums,
    build_competitor_table_rows,
    lang_switch_html,
)

PAL = ["#0F6B5C", "#4A6FA5", "#C2702E", "#7B5BB0", "#2E9C8A", "#B5476B", "#5B6470", "#8A6100"]
MAX_PICK = 3
_SRC_MAP = {
    "seo": "seo",
    "google": "seo",
    "serp": "seo",
    "organic": "seo",
    "llm": "llm",
    "ia": "llm",
    "ai": "llm",
    "semrush": "semrush",
    "sm": "semrush",
    "manual": "manual",
}


def _host(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    host = urlparse(raw if "://" in raw else f"https://{raw}").netloc
    host = host[4:] if host.startswith("www.") else host
    return host.lower()


def _fonte_keys(raw: Any) -> list[str]:
    parts = re.split(r"[,+/\s]+", str(raw or "").strip().lower())
    out: list[str] = []
    for p in parts:
        k = _SRC_MAP.get(p)
        if k and k not in out:
            out.append(k)
    return out


def _since_year(c: dict[str, Any]) -> Optional[int]:
    for key in ("started", "started_fmt"):
        m = re.search(r"(19|20)\d{2}", str(c.get(key) or ""))
        if m:
            return int(m.group(0))
    return None


def _visits(c: dict[str, Any]) -> Optional[float]:
    raw = c.get("similarweb_visits")
    if raw in (None, ""):
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _brand(c: dict[str, Any]) -> Optional[list[float]]:
    nums = _vol_nums((c.get("brand_aug_2026"), c.get("brand_aug_2025"), c.get("brand_aug_2024")))
    if nums is None:
        nums = _vol_nums((c.get("sm_marca_aug_2026"), c.get("sm_marca_aug_2025"), c.get("sm_marca_aug_2024")))
    if not nums:
        return None
    return [float(v or 0) for v in nums]


def _lvl(c: dict[str, Any]) -> Any:
    if c.get("manual") or "manual" in _fonte_keys(c.get("fonte")):
        return "u"
    return {"Alto": 3, "Medio": 2, "Baixo": 1}.get(_sim_key(c), 1)


def build_find_v2_payload(
    report: dict[str, Any],
    *,
    meta: dict[str, Any],
    briefing: dict[str, Any],
    client: str,
    site_host: str,
    run_id: str,
    market: str,
) -> dict[str, Any]:
    comps = build_competitor_table_rows(report, run_meta=meta)
    me_row = next((c for c in comps if c.get("is_client")), None)
    domain = ""
    if me_row:
        domain = str(me_row.get("domain") or "").strip().lower()
    if not domain:
        domain = site_host or _host(str(briefing.get("url") or meta.get("url") or ""))
    rows: list[dict[str, Any]] = []
    for i, c in enumerate(comps):
        if c.get("is_client"):
            continue
        dom = str(c.get("domain") or "").strip().lower()
        if not dom:
            continue
        lvl = _lvl(c)
        motivo = str(c.get("motivo") or "").strip()
        off = ""
        if lvl == 1 and motivo and motivo not in ("—", "-", "n/a"):
            off = motivo
        title = _row_title(c)
        rows.append({
            "n": str(c.get("name") or dom),
            "d": dom,
            "t": title,
            "lvl": lvl,
            "v": _visits(c),
            "b": _brand(c),
            "since": _since_year(c),
            "src": _fonte_keys(c.get("fonte")) or (["manual"] if c.get("manual") else []),
            "niche": str(c.get("nicho") or "").strip(),
            "off": off,
            "added": bool(c.get("manual")),
            "color": PAL[i % len(PAL)],
        })
    return {
        "meta": {
            "client": client,
            "domain": domain,
            "nicho": _briefing_nicho(briefing),
            "market_code": "BR" if str(market).upper() == "BR" else "US",
            "run_id": run_id,
            "visits": _visits(me_row) if me_row else None,
            "max": MAX_PICK,
        },
        "rows": rows,
    }


def build_find_v2(payload: dict[str, Any], *, ui_ver: str) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    meta = payload.get("meta") or {}
    client = _esc(meta.get("client") or "Spy USA")
    switch = """
    <div class="ui-switch" role="group" aria-label="Report layout">
      <span class="ui-switch-lab" data-i18n="nav.layout">Layout</span>
      <button type="button" data-ui-set="v1">v1</button>
      <button type="button" data-ui-set="v2" aria-pressed="true">v2</button>
    </div>"""
    return f"""
<div id="find-v2">
<script type="application/json" id="spy-find-v2-data">{data}</script>
<header class="top"><div class="wrap"><span class="logo">S</span><b>Spy USA</b>
  <div class="acts">
    {lang_switch_html()}
    {switch}
    <a href="/" data-i18n="nav.new">New analysis</a>
  </div>
</div></header>
<main class="wrap">
  <section class="head">
    <div class="eyebrow" id="find-eyebrow"></div>
    <h1 id="find-title">{client}</h1>
    <div class="steps" id="find-steps"></div>
    <div class="kpis" id="find-kpis"></div>
  </section>
  <div class="sh"><h2 data-i18n="find.list.h">Everyone we found</h2><p data-i18n="find.list.p">Click a group to see only that one, or All to see everything together</p></div>
  <form class="add" id="find-addf" autocomplete="off">
    <label for="find-addi" data-i18n="find.add.lab">Missing someone?</label>
    <input id="find-addi" type="text" inputmode="url" placeholder="competitor.com" data-i18n-placeholder="find.add.ph" aria-describedby="find-addm">
    <button type="submit" data-i18n="find.add.btn">+ Add website</button>
    <span id="find-addm" class="addm" role="status"></span>
  </form>
  <div class="lvt" id="find-lvt" role="group" aria-label="Filter by similarity"></div>
  <div class="ctl">
    <span class="seglab" data-i18n="find.show">Show</span>
    <div class="seg" id="find-fShow"></div>
    <span class="seglab" data-i18n="find.sort">Sort by</span>
    <div class="seg" id="find-fSort"></div>
  </div>
  <div class="bw"><table class="tb" id="find-list"></table></div>
  <p class="note" id="find-note" data-i18n="find.note"></p>
</main>
<div class="bar"><div class="wrap">
  <span class="lab" id="find-cnt"></span>
  <div class="chips" id="find-chips"></div>
  <button type="button" class="go" id="find-go" disabled>Analyze</button>
</div></div>
</div>
<script src="/static/report_find_v2.js?v={_esc(ui_ver)}"></script>
"""
