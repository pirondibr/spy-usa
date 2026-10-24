# -*- coding: utf-8 -*-
"""v6 analysis report — spy-usa-minimal-v2.html wired to live report data."""

from __future__ import annotations

import json
from typing import Any

from report_analysis_v5 import build_v5_payload


def build_analysis_v6(payload: dict[str, Any], *, ui_ver: str) -> str:
    from report_html import _esc, analysis_add_form_html

    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    meta = payload.get("meta") or {}
    client = _esc(meta.get("client") or "Spy USA")
    add_form = analysis_add_form_html(
        str(meta.get("run_id") or ""),
        [
            {"name": c.get("name"), "domain": c.get("dom")}
            for c in (payload.get("companies") or [])
            if isinstance(c, dict)
        ],
    )
    switch = """
    <div class="ui-switch" role="group" aria-label="Layout do relatório">
      <span class="ui-switch-lab">Layout</span>
      <button type="button" data-ui-set="v4">v4</button>
      <button type="button" data-ui-set="v5">v5</button>
      <button type="button" data-ui-set="v6" aria-pressed="true">v6</button>
    </div>"""
    return f"""
<div id="analysis-v6">
<script type="application/json" id="spy-v6-data">{data}</script>
<header class="top"><div class="wrap"><span class="logo">S</span><b>Spy USA</b>
  <div class="acts">
    {switch}
    <a href="/">Nova análise</a>
    <button type="button" onclick="window.print()">Exportar PDF</button>
  </div>
</div></header>
<main class="wrap">
  <section class="head">
    <div class="eyebrow" id="v6-eyebrow"></div>
    <h1 id="v6-title">{client}</h1>
    <div class="cos" id="v6-cos"></div>
    {add_form}
    <ul class="ins" id="v6-ins"></ul>
  </section>
  <section class="sec">
    <div class="sh"><h2>Placar</h2><p>Ordenado por visitas · clique numa empresa para ver o perfil</p></div>
    <div class="bw"><table class="board" id="v6-board"></table></div>
    <details class="flags" id="v6-flags"></details>
  </section>
  <div id="v6-fixed"></div>
  <section class="moresec" aria-labelledby="v6-more-h">
    <div class="sh" style="margin-top:44px"><h2 id="v6-more-h">Mais análises</h2><p>Clique para abrir · uma de cada vez</p></div>
    <nav class="tags" id="v6-tags" aria-label="Mais análises"></nav>
    <div id="v6-panels"></div>
  </section>
  <footer class="foot" id="v6-foot"></footer>
</main>
</div>
<script src="/static/report_v6.js?v={_esc(ui_ver)}"></script>
"""
