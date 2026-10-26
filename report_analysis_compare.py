# -*- coding: utf-8 -*-
"""v2 analysis report — comparative layout (aiapply-comparativo.html)."""

from __future__ import annotations

from typing import Any, Optional

COLORS = (
    "#0F6B5C",
    "#4A6FA5",
    "#C2702E",
    "#7B5BB0",
    "#B45309",
    "#0E7490",
    "#BE185D",
    "#365314",
)
MAX_COMPANIES = 8

SOURCE_META: dict[str, tuple[str, str, bool]] = {
    "direct": ("Direct", "#0E1116", False),
    "direto": ("Direct", "#0E1116", False),
    "search": ("Search", "#0F6B5C", False),
    "organic search": ("Search", "#0F6B5C", False),
    "busca": ("Search", "#0F6B5C", False),
    "social": ("Social", "#5E9E92", False),
    "referrals": ("Referrals", "#9AA3AE", False),
    "referral": ("Referrals", "#9AA3AE", False),
    "indicações": ("Referrals", "#9AA3AE", False),
    "mail": ("Email", "#C9D0D8", False),
    "email": ("Email", "#C9D0D8", False),
    "e-mail": ("Email", "#C9D0D8", False),
    "paid search": ("Paid search", "#C2702E", True),
    "busca paga": ("Paid search", "#C2702E", True),
    "paid social": ("Paid social", "#E39A5C", True),
    "social pago": ("Paid social", "#E39A5C", True),
    "display": ("Display", "#F2C59B", True),
    "display ads": ("Display", "#F2C59B", True),
    "paid referrals": ("Paid referrals", "#C2702E", True),
    "generative ai": ("Generative AI", "#7B5BB0", False),
    "ai": ("Generative AI", "#7B5BB0", False),
    "ia generativa": ("Generative AI", "#7B5BB0", False),
    "affiliates": ("Affiliates", "#E3E6EA", False),
    "afiliados": ("Affiliates", "#E3E6EA", False),
}

SCORE_LABEL = {
    "high": "Alto",
    "medium": "Médio",
    "low": "Baixo",
    "0": "Sem presença",
}
SCORE_DOT = {"high": "alto", "medium": "medio", "low": "baixo", "0": "zero"}


def build_analysis_compare(
    report: dict[str, Any],
    meta: dict[str, Any],
    *,
    briefing: dict[str, Any],
    client: str,
    site_url: str,
    site_host: str,
    run_id: str,
    market: str,
    companies: Optional[list[dict[str, Any]]] = None,
) -> str:
    from report_html import (  # noqa: PLC0415
        _channel_metric_value,
        _channel_score,
        _compact_num,
        _confirmed_badge,
        _dfs_growth_pct,
        _esc,
        _fmt_vol,
        _resolve_run_log,
        analysis_add_form_html,
        exec_tabs_html,
        _row_for_company,
        _summary_channel_url,
        _summary_companies,
    )

    raw_cos = companies or _summary_companies(report)
    if not raw_cos:
        raw_cos = [{"name": client, "domain": site_host, "is_client": True, "_key": ""}]
    raw_cos = raw_cos[:MAX_COMPANIES]
    palette = [(c, COLORS[i % len(COLORS)]) for i, c in enumerate(raw_cos)]

    def section(key: str) -> dict[str, Any]:
        sec = report.get(key)
        return sec if isinstance(sec, dict) else {}

    def has_channel(key: str) -> bool:
        sec = section(key)
        return bool(
            sec.get("rows")
            or sec.get("total_fmt")
            or sec.get("total_ads_fmt")
            or sec.get("total_traffic_fmt")
        )

    def coerce(v: Any) -> Optional[float]:
        if v in (None, ""):
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace("\u00a0", "").replace(" ", "").replace("%", "").replace(",", "")
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    def cn(company: dict, color: str, *, you: bool = True) -> str:
        name = str(company.get("name") or company.get("domain") or "—")
        you_html = '<span class="you">você</span>' if you and company.get("is_client") else ""
        return (
            f'<span class="cn"><span class="cdot" style="background:{_esc(color)}"></span>'
            f"{_esc(name)}{you_html}</span>"
        )

    def sd(score: str, skipped: bool = False) -> str:
        if skipped:
            return '<span class="sd skip" title="Nota: Não coletado" aria-label="Nota: Não coletado"></span>'
        cls = SCORE_DOT.get(score, "baixo")
        lab = "Não coletado" if skipped else SCORE_LABEL.get(score, "Baixo")
        return f'<span class="sd {cls}" title="Nota: {lab}" aria-label="Nota: {lab}"></span>'

    def company_url(company: dict) -> str:
        dom = str(company.get("domain") or "").strip()
        if company.get("is_client") and site_url:
            return site_url
        if not dom:
            return ""
        return dom if "://" in dom else f"https://{dom}"

    def fmt_metric(key: str, sec: dict, row: Optional[dict]) -> str:
        row = row or {}
        if key in ("google_ads", "meta", "linkedin"):
            return str(row.get("ads_fmt") or row.get("value_fmt") or sec.get("total_ads_fmt") or "0")
        if key == "brand_dataforseo":
            return str(row.get("traffic_fmt") or row.get("latest_volume") or "0")
        if key in ("brand", "seo", "similarweb"):
            return str(row.get("traffic_fmt") or "0")
        if key == "reddit":
            return str(row.get("total_comments_fmt") or row.get("traffic_fmt") or "0")
        if key == "instagram_influencers":
            return str(row.get("total_likes_fmt") or row.get("traffic_fmt") or "0")
        if key == "youtube_influencers":
            return str(row.get("traffic_fmt") or sec.get("total_traffic_fmt") or "0")
        if key in ("twitter", "linkedin_profile"):
            return str(row.get("followers_fmt") or row.get("traffic_fmt") or row.get("value_fmt") or "0")
        return str(row.get("value_fmt") or row.get("followers_fmt") or row.get("traffic_fmt") or "0")

    def gcell(g: Optional[float]) -> str:
        if not isinstance(g, (int, float)):
            return '<span class="pct">—</span>'
        cls = "up" if g > 0 else ("down" if g < 0 else "")
        txt = f"{g:+.0f}%" if abs(g) >= 100 else f"{g:+.1f}%"
        return f'<span class="pct {cls}">{txt}</span>'

    def growth_of(row: dict, years: str) -> Optional[float]:
        g = row.get(f"growth_{years}_pct")
        if isinstance(g, (int, float)):
            return float(g)
        return _dfs_growth_pct(row.get("traffic") or row.get("latest_volume"), row.get(f"volume_{years}"))

    def flag(text: str, block: bool = False) -> str:
        if not text:
            return ""
        cls = "flag block" if block else "flag"
        return f'<span class="{cls}">{_esc(text)}</span>'

    def tabs(tid: str, panels: list[str], *, selected: int = 0) -> str:
        buttons = []
        bodies = []
        pick = selected if 0 <= selected < len(panels) else 0
        for i, ((company, color), body) in enumerate(zip(palette, panels)):
            sel = "true" if i == pick else "false"
            hid = "" if i == pick else " hidden"
            buttons.append(
                f'<button type="button" class="tb" role="tab" aria-selected="{sel}" data-tabs="{tid}" data-i="{i}">'
                f'<span class="cdot" style="background:{_esc(color)}"></span>{_esc(company.get("name") or "")}</button>'
            )
            bodies.append(f'<div class="tp" data-tabs="{tid}" data-i="{i}"{hid}>{body}</div>')
        return (
            f'<div class="tabwrap"><div class="tabs2" role="tablist">{"".join(buttons)}</div>'
            f"{''.join(bodies)}</div>"
        )

    def ctile(key: str, href: str, name: str, tmeta: str) -> str:
        skipped = not has_channel(key)
        sec = section(key)
        rows_info: list[tuple[dict, str, Optional[dict], Optional[float], str, bool]] = []
        for company, color in palette:
            row = _row_for_company(sec, company) if sec else None
            if skipped or row is None:
                rows_info.append((company, color, row, None, "0", True))
                continue
            metric = _channel_metric_value(key, sec, row)
            score = _channel_score(key, metric)
            rows_info.append((company, color, row, metric, score, False))
        nums = [inf[3] or 0 for inf in rows_info if not inf[5]]
        max_m = max(nums) if nums else 0
        crs = []
        notes = []
        for company, color, row, metric, score, row_skip in rows_info:
            if row_skip:
                val = "não coletado"
                w = 0.0
                extra = " na"
            elif metric is None:
                val = "—"
                w = 0.0
                extra = " na"
            elif metric <= 0:
                val = fmt_metric(key, sec, row)
                w = 0.0
                extra = " z"
            else:
                val = fmt_metric(key, sec, row)
                w = (metric / max_m * 100) if max_m else 0
                extra = " lead" if metric == max_m else ""
            crs.append(
                f'<div class="cr{extra}">{cn(company, color)}'
                f'<span class="bt"><i style="width:{w:.1f}%;background:{_esc(color)}"></i></span>'
                f'<span class="cv num">{_esc(val)}{(_confirmed_badge(row) if key == "meta" else "")}</span>{sd(score, row_skip)}</div>'
            )
            note = (row or {}).get("note") or (row or {}).get("flag")
            if note:
                notes.append(str(note))
        if skipped:
            notes.append("Etapa pulada nesta rodada")
        flag_html = flag("Verificar · " + notes[0]) if notes else ""
        return (
            f'<a class="tile ctile" href="{_esc(href)}">'
            f'<span class="nm"><span class="chn">{_esc(name)}</span>'
            f'<span class="tmeta" title="{_esc(tmeta)}">{_esc(tmeta)}</span></span>'
            f'<div class="crs">{"".join(crs)}</div>{flag_html}</a>'
        )

    pop = [
        ctile("similarweb", "#trafego", "Visitas", "SimilarWeb · visitas/mês"),
        ctile("brand_dataforseo", "#marca", "Buscas de marca", "DataForSEO · buscas/mês"),
        ctile("brand", "#marca", "Tráfego de marca", "Semrush · visitas/mês"),
    ]
    paid = [
        ctile("google_ads", "#paga", "Google Ads", "anúncios"),
        ctile("meta", "#paga", "Meta Ads", "anúncios"),
        ctile("linkedin", "#paga", "LinkedIn Ads", "anúncios"),
    ]
    org = [
        ctile("seo", "#seo", "SEO orgânico", "Semrush · visitas/mês"),
        ctile("instagram", "#perfis", "Instagram", "seguidores"),
        ctile("tiktok", "#perfis", "TikTok", "seguidores"),
        ctile("twitter", "#perfis", "X / Twitter", "seguidores"),
        ctile("reddit", "#reddit", "Reddit", "comentários"),
        ctile("youtube", "#perfis", "YouTube", "inscritos"),
        ctile("linkedin_profile", "#perfis", "LinkedIn", "seguidores"),
    ]
    inf = [
        ctile("youtube_influencers", "#youtube", "YouTube", "1ª página · views"),
        ctile("instagram_influencers", "#instagram", "Instagram", "1ª página · curtidas"),
    ]

    def col(title: str, css: str, tiles: list[str]) -> str:
        return (
            f'<div class="sum-col {css}"><h3>{_esc(title)}<span class="cnt">{len(tiles)} canais</span></h3>'
            f"{''.join(tiles)}</div>"
        )

    summary_html = f"""
    <section class="sec" id="resumo">
      <div class="sec-head"><h2>Resumo dos canais</h2><span class="sec-note">Barras comparam as empresas dentro de cada canal · clique para ver o detalhe</span></div>
      <div class="card">
        <div class="sum">
          {col("Popularidade", "g-pop", pop)}
          {col("Mídia paga", "g-paid", paid)}
          {col("Orgânico", "g-org", org)}
          {col("Influenciadores", "g-inf", inf)}
        </div>
        <div class="sum-legend"><span class="lg-t">Nota do pipeline</span>
          <span class="lgi">{sd("high")}Alto</span>
          <span class="lgi">{sd("medium")}Médio</span>
          <span class="lgi">{sd("low")}Baixo</span>
          <span class="lgi">{sd("0")}Sem presença</span>
          <span class="lgi">{sd("0", True)}Não coletado</span>
          <span class="lg-n">Valor em negrito = maior do canal</span>
        </div>
      </div>
    </section>"""

    # --- similarweb compare ---
    sw = section("similarweb")
    sw_card = ""
    if has_channel("similarweb"):
        ov_rows = []
        month_keys: list[str] = []
        seen_m: set[str] = set()
        label_by: dict[str, str] = {}
        for company, _c in palette:
            row = _row_for_company(sw, company) or {}
            for m in row.get("visits_monthly") or []:
                d = str(m.get("date") or m.get("label") or "")
                if d and d not in seen_m:
                    seen_m.add(d)
                    month_keys.append(d)
                    label_by[d] = str(m.get("label") or d[:7])
        month_keys = month_keys[-3:] if len(month_keys) > 3 else month_keys
        month_vals: dict[str, dict[str, float]] = {d: {} for d in month_keys}
        month_fmt: dict[str, dict[str, str]] = {d: {} for d in month_keys}
        for company, color in palette:
            row = _row_for_company(sw, company) or {}
            ga = "Sim" if row.get("is_data_from_ga") else "Não"
            ov_rows.append(
                f"<tr><td>{cn(company, color)}</td>"
                f'<td class="r">{_esc(row.get("traffic_fmt") or "—")}</td>'
                f'<td class="r">{_esc(row.get("bounce_fmt") or "—")}</td>'
                f'<td class="r">{_esc(row.get("pages_fmt") or "—")}</td>'
                f'<td class="r">{_esc(row.get("time_fmt") or "—")}</td>'
                f'<td class="r muted" style="font-weight:400">{_esc(ga)}</td></tr>'
            )
            for m in row.get("visits_monthly") or []:
                d = str(m.get("date") or m.get("label") or "")
                if d not in month_vals:
                    continue
                n = coerce(m.get("visits")) or 0
                month_vals[d][company.get("_key") or ""] = n
                month_fmt[d][company.get("_key") or ""] = str(m.get("visits_fmt") or _compact_num(n))

        sw_panels = []
        for company, color in palette:
            key = company.get("_key") or ""
            row = _row_for_company(sw, company) or {}
            vals = [month_vals.get(d, {}).get(key, 0) or 0 for d in month_keys]
            mx = max(vals) if vals else 0
            gcols_one = []
            for d, n in zip(month_keys, vals):
                h = max(4, round(n / mx * 100)) if n and mx else 4
                lab = month_fmt.get(d, {}).get(key) or "—"
                gcols_one.append(
                    f'<div class="gcol"><div class="gbars">'
                    f'<span class="gb" title="{_esc(company.get("name") or "")} · {_esc(lab)}">'
                    f'<b class="num">{_esc(lab)}</b><i style="height:{h}%;background:{_esc(color)}"></i></span>'
                    f'</div><span class="gl">{_esc(label_by.get(d, d))}</span></div>'
                )
            delta_one = ""
            if len(month_keys) >= 2 and vals and vals[0]:
                p = (vals[-1] / vals[0] - 1) * 100
                cls = "up" if p > 0 else "down"
                delta_one = (
                    f'<p class="deltas">{_esc(label_by.get(month_keys[0], ""))} → '
                    f'{_esc(label_by.get(month_keys[-1], ""))}: '
                    f'<b class="num {cls}">{p:+.1f}%</b></p>'
                )
            countries = list(row.get("countries") or [])[:5]
            cnums = []
            for ctry in countries:
                n = coerce(ctry.get("share"))
                if n is None:
                    n = coerce(str(ctry.get("share_fmt") or "").replace("%", ""))
                cnums.append(n or 0)
            cmx = max(cnums) if cnums else 1
            clis = []
            for ctry, n in zip(countries, cnums):
                w = 0 if cmx <= 0 else round(n / cmx * 100)
                label = ctry.get("name") or ctry.get("code") or "—"
                fmt = ctry.get("share_fmt") or (f"{n:.1f}%" if n else "—")
                clis.append(
                    f'<li><span class="l">{_esc(label)}</span>'
                    f'<span class="t"><i style="width:{w}%;background:{_esc(color)}"></i></span>'
                    f'<span class="v num">{_esc(fmt)}</span></li>'
                )
            sw_panels.append(
                f'<div class="pad-g"><div class="g2" style="gap:32px">'
                f'<div><div class="sub-h" style="padding:0 0 12px">Visitas mensais</div>'
                f'<div class="gchart">{"".join(gcols_one) if gcols_one else "<p class=sec-note>Sem série mensal.</p>"}</div>'
                f"{delta_one}</div>"
                f'<div><div class="sub-h" style="padding:0 0 12px">Principais países</div>'
                f'<ul class="hb">{"".join(clis) or "<li class=na><span class=l>—</span></li>"}</ul></div>'
                f"</div></div>"
            )

        source_order: list[str] = []
        source_seen: set[str] = set()
        for company, _c in palette:
            row = _row_for_company(sw, company) or {}
            for s in row.get("sources") or []:
                raw = str(s.get("name") or "").strip()
                if raw and raw.lower() not in source_seen:
                    source_seen.add(raw.lower())
                    source_order.append(raw)

        def src_meta(name: str) -> tuple[str, str, bool]:
            return SOURCE_META.get(name.lower(), (name, "#9AA3AE", False))

        stacks = []
        paid_shares = []
        for company, color in palette:
            row = _row_for_company(sw, company) or {}
            by_name = {}
            for s in row.get("sources") or []:
                n = coerce(s.get("share"))
                if n is None:
                    n = coerce(str(s.get("share_fmt") or "").replace("%", ""))
                if n is not None and n <= 1.5:
                    n = n * 100
                by_name[str(s.get("name") or "")] = (n or 0, s.get("share_fmt") or "")
            segs = []
            paid_n = 0.0
            for raw in source_order:
                lab, col, is_paid = src_meta(raw)
                n, fmt = by_name.get(raw, (0, ""))
                if n <= 0:
                    continue
                if is_paid:
                    paid_n += n
                segs.append(
                    f'<span style="width:{n:.2f}%;background:{col}" title="{_esc(lab)} {fmt or f"{n:.1f}%"}"></span>'
                )
            stacks.append(
                f'<div class="srow">{cn(company, color)}<div class="stack2">{"".join(segs)}</div>'
                f'<span class="paidsum num">pago {paid_n:.1f}%</span></div>'
            )
            paid_shares.append(paid_n)

        legend = []
        for raw in source_order:
            lab, col, _p = src_meta(raw)
            legend.append(f'<li><span class="dot" style="background:{col}"></span>{_esc(lab)}</li>')

        detail_rows = []
        for raw in source_order:
            lab, col, is_paid = src_meta(raw)
            cells = []
            for company, _c in palette:
                row = _row_for_company(sw, company) or {}
                by_name = {str(s.get("name")): s.get("share_fmt") or "—" for s in (row.get("sources") or [])}
                cells.append(f'<td class="r">{_esc(by_name.get(raw, "—"))}</td>')
            tr_cls = ' class="paidrow"' if is_paid else ""
            detail_rows.append(
                f"<tr{tr_cls}><td><span class=\"dot\" style=\"background:{col}\"></span>{_esc(lab)}</td>{''.join(cells)}</tr>"
            )
        head_cos = "".join(f'<th class="r">{_esc(c.get("name") or "")}</th>' for c, _ in palette)
        snap = ""
        for company, _c in palette:
            row = _row_for_company(sw, company) or {}
            snap = row.get("snapshot_label") or snap

        sw_card = f"""
    <div class="card" id="trafego">
      <div class="card-head"><h3>Tráfego do site</h3><span class="src">SimilarWeb{(' · snapshot ' + _esc(snap)) if snap else ''}</span></div>
      <div class="tw" style="margin-top:12px"><table>
        <thead><tr><th>Empresa</th><th class="r">Visitas / mês</th><th class="r">Rejeição</th><th class="r">Páginas / visita</th><th class="r">Tempo no site</th><th class="r">Google Analytics</th></tr></thead>
        <tbody>{''.join(ov_rows)}</tbody>
      </table></div>
      {tabs("sw", sw_panels)}
      <div class="pad-g" style="border-top:1px solid var(--line)">
        <div class="sub-h" style="padding:0 0 12px">Origem das visitas</div>
        {''.join(stacks)}
        <ul class="legend3">{''.join(legend)}</ul>
        <details class="more"><summary>Ver tabela completa</summary>
          <div class="tw"><table class="tight"><thead><tr><th>Origem</th>{head_cos}</tr></thead>
          <tbody>{''.join(detail_rows)}</tbody></table></div>
        </details>
      </div>
    </div>"""
    else:
        paid_shares = [0.0 for _ in palette]

    # --- brand ---
    dfs = section("brand_dataforseo")
    brand = section("brand")

    def _brand_g(row: dict) -> str:
        raw = row.get("growth_fmt") or ""
        if raw in ("", "n/a", "—"):
            return '<span class="pct">—</span>'
        cls = "up" if str(raw).startswith("+") else ("down" if str(raw).startswith("-") else "")
        return f'<span class="pct {cls}">{_esc(raw)}</span>'

    # fix brand growth cell — rebuild rows cleanly
    brand_rows = []
    for company, color in palette:
        drow = _row_for_company(dfs, company) or {}
        brow = _row_for_company(brand, company) or {}
        kw = drow.get("brand_keyword") or brow.get("brand_keyword") or ""
        latest = drow.get("traffic_fmt") or _fmt_vol(drow.get("latest_volume") or drow.get("traffic"))
        kw_html = f'<div class="kw">"{_esc(kw)}"</div>' if kw else ""
        brand_rows.append(
            f"<tr><td>{cn(company, color)}{kw_html}</td>"
            f'<td class="r big">{_esc(latest or "—")}</td>'
            f'<td class="r muted" style="font-weight:500">{_esc(_fmt_vol(drow.get("volume_1y")))}</td>'
            f'<td class="r muted" style="font-weight:500">{_esc(_fmt_vol(drow.get("volume_2y")))}</td>'
            f'<td class="r muted" style="font-weight:500">{_esc(_fmt_vol(drow.get("volume_3y")))}</td>'
            f'<td class="r">{gcell(growth_of(drow, "1y"))}</td>'
            f'<td class="r">{gcell(growth_of(drow, "2y"))}</td>'
            f'<td class="r sep">{_esc(brow.get("traffic_fmt") or "—")}</td>'
            f"<td class=\"r\">{_brand_g(brow)}</td></tr>"
        )

    market_label = "EUA" if str(market).upper() == "US" else "Brasil"
    marca_card = f"""
      <div class="card" id="marca">
        <div class="card-head"><h3>Busca pela marca</h3><span class="src">{_esc(market_label)} · DataForSEO · Semrush</span></div>
        <div class="tw" style="margin-top:12px"><table>
          <thead><tr><th rowspan="2">Empresa</th><th colspan="6" class="grp">Volume de busca · DataForSEO</th><th colspan="2" class="grp sep">Tráfego de marca · Semrush</th></tr>
          <tr><th class="r">Atual</th><th class="r">1 ano</th><th class="r">2 anos</th><th class="r">3 anos</th><th class="r">Δ 1 ano</th><th class="r">Δ 2 anos</th><th class="r sep">Visitas</th><th class="r">Δ</th></tr></thead>
          <tbody>{''.join(brand_rows)}</tbody>
        </table></div>
        <div class="foot">Quando o volume histórico é 0, a variação usa base 100. DataForSEO mede volume de busca; Semrush estima tráfego — por isso os números diferem.</div>
      </div>"""

    def bar_list(key: str, *, extra: str = "", spend: bool = False, cost: int = 0) -> str:
        sec = section(key)
        skipped = not has_channel(key)
        infos = []
        for company, color in palette:
            row = _row_for_company(sec, company) if sec else None
            metric = None if (skipped or row is None) else _channel_metric_value(key, sec, row)
            infos.append((company, color, row, metric, skipped or row is None))
        nums = [m or 0 for *_, m, sk in infos if not sk]
        mx = max(nums) if nums else 0
        lis = []
        for company, color, row, metric, sk in infos:
            url = _summary_channel_url(key, sec, row or {}, market=market) if row else ""
            if sk:
                lk = (
                    f'<a class="lk" href="{_esc(url)}" target="_blank" rel="noopener">↗</a>'
                    if url else ""
                )
                lis.append(
                    f'<li>{cn(company, color)}<span class="sd skip"></span>'
                    f'<span class="muted">não coletado</span>{lk}</li>'
                )
                continue
            w = (metric / mx * 100) if mx and metric else 0
            val = fmt_metric(key, sec, row)
            x = ""
            if spend:
                x = str((row or {}).get("investimento_fmt") or "")
                if not x and cost and metric:
                    pref = "R$" if str(market).upper() == "BR" else "US$"
                    x = f"{pref} {int(metric * cost):,}".replace(",", ".")
            link = f'<a class="lk" href="{_esc(url)}" target="_blank" rel="noopener">↗</a>' if url else ""
            g = ""
            if extra == "seo":
                gf = (row or {}).get("growth_fmt") or ""
                if gf and gf not in ("n/a", "—"):
                    cls = "up" if str(gf).startswith("+") else ("down" if str(gf).startswith("-") else "")
                    g = f'<span class="x num"><span class="{cls}">{_esc(gf)}</span></span>'
                else:
                    g = '<span class="x num"></span>'
            elif spend:
                g = f'<span class="x num">{_esc(x)}</span>' if x else '<span class="x num"></span>'
            else:
                g = '<span class="x num"></span>'
            lis.append(
                f'<li>{cn(company, color)}<span class="t"><i style="width:{w:.1f}%;background:{_esc(color)}"></i></span>'
                f'<span class="v num">{_esc(val)}{(_confirmed_badge(row) if key == "meta" else "")}</span>{g}{link}</li>'
            )
        cls = "cb paid" if spend else ("cb skiplist" if skipped else "cb")
        return f'<ul class="{cls}">{"".join(lis)}</ul>'

    seo_card = f"""
      <div class="card" id="seo">
        <div class="card-head"><h3>SEO orgânico</h3><span class="src">Semrush · {_esc(market_label)}</span></div>
        <div class="card-pad"><div class="unit-l">visitas orgânicas / mês</div>{bar_list("seo", extra="seo")}</div>
      </div>"""

    paid_bar_items = []
    mx_paid = max(paid_shares) if paid_shares else 0
    for (company, color), share in zip(palette, paid_shares):
        w = (share / mx_paid * 100) if mx_paid else 0
        paid_bar_items.append(
            f'<li>{cn(company, color)}<span class="t"><i style="width:{w:.1f}%;background:{_esc(color)}"></i></span>'
            f'<span class="v num">{share:.1f}%</span><span class="x num"></span></li>'
        )
    paid_sw_card = f"""
      <div class="card">
        <div class="card-head"><h3>Busca paga no tráfego</h3><span class="src">SimilarWeb</span></div>
        <div class="card-pad"><div class="unit-l">% das visitas vindas de anúncios (busca + social + display)</div>
        <ul class="cb">{''.join(paid_bar_items)}</ul></div>
        <div class="foot">Busca paga, social pago e display somados.</div>
      </div>"""

    busca_html = f"""
    <section class="sec" id="busca">
      <div class="sec-head"><h2>Busca &amp; tráfego</h2></div>
      {sw_card}
      {marca_card}
      <div class="g2">{seo_card}{paid_sw_card}</div>
    </section>"""

    def paid_card(key: str, title: str, cost: int) -> str:
        skipped = not has_channel(key)
        pref = "R$" if str(market).upper() == "BR" else "US$"
        src = "etapa pulada nesta rodada" if skipped else (f"≈ {pref} {cost} por anúncio" if cost else "")
        body = bar_list(key, spend=not skipped, cost=cost)
        extra = "" if skipped else '<div class="unit-l"><span>anúncios ativos</span><span>gasto est.</span></div>'
        return (
            f'<div class="card"><div class="card-head"><h3>{_esc(title)}</h3><span class="src">{_esc(src)}</span></div>'
            f'<div class="card-pad">{extra}{body}</div></div>'
        )

    paid_html = f"""
    <section class="sec" id="paga">
      <div class="sec-head"><h2>Mídia paga</h2><span class="sec-note">Bibliotecas públicas de anúncios · {_esc(market_label)}</span></div>
      <div class="g3">
        {paid_card("google_ads", "Google Ads", 200 if str(market).upper() != "BR" else 600)}
        {paid_card("meta", "Meta Ads", 80 if str(market).upper() != "BR" else 250)}
        {paid_card("linkedin", "LinkedIn Ads", 0)}
      </div>
      <p class="note">Gasto é estimativa do pipeline, não valor declarado.</p>
    </section>"""

    # --- profiles ---
    profile_keys = [
        ("instagram", "Instagram", "seguidores"),
        ("tiktok", "TikTok", "seguidores"),
        ("twitter", "X / Twitter", "seguidores"),
        ("youtube", "YouTube", "inscritos"),
        ("linkedin_profile", "LinkedIn", "seguidores"),
    ]
    prof_head = "".join(f'<th class="r">{cn(c, col)}</th>' for c, col in palette)
    prof_rows = []
    for key, label, unit in profile_keys:
        sec = section(key)
        skipped = not has_channel(key)
        cells = []
        metrics = []
        for company, color in palette:
            row = _row_for_company(sec, company) if sec else None
            if skipped or row is None:
                metrics.append((company, color, row, None, True))
            else:
                metrics.append((company, color, row, _channel_metric_value(key, sec, row), False))
        scored = [m or -1 for *_, m, sk in metrics if not sk]
        best_n = max(scored) if scored else -1
        note = ""
        for company, color, row, metric, sk in metrics:
            score = "0" if sk else _channel_score(key, metric)
            extra = " na" if sk else (" z" if (metric is not None and metric <= 0) else (" lead" if metric == best_n and metric and metric > 0 else ""))
            val = "não coletado" if sk else fmt_metric(key, sec, row)
            url = str((row or {}).get("url") or "")
            handle = str((row or {}).get("handle") or "").lstrip("@")
            if url:
                lab = f"@{handle} ↗" if handle else "Perfil ↗"
                ph = f'<div class="ph"><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(lab)}</a></div>'
            else:
                ph = '<div class="ph"><span class="muted">não encontrado</span></div>'
            cells.append(
                f'<td class="r pc{extra}"><div class="pv num">{sd(score, sk)}{_esc(val)}</div>{ph}</td>'
            )
            if (row or {}).get("note"):
                note = str(row.get("note"))
        flag_html = f'<div class="flag">Verificar · {_esc(note)}</div>' if note else ""
        prof_rows.append(
            f"<tr><td><b>{_esc(label)}</b><div class=\"kw\">{_esc(unit)}</div>{flag_html}</td>{''.join(cells)}</tr>"
        )

    profiles_html = f"""
    <div class="card" id="perfis">
      <div class="card-head"><h3>Perfis oficiais</h3><span class="src">seguidores / inscritos · em negrito o maior</span></div>
      <div class="tw" style="margin-top:12px"><table class="prof">
        <thead><tr><th>Rede</th>{prof_head}</tr></thead>
        <tbody>{''.join(prof_rows)}</tbody>
      </table></div>
    </div>"""

    def item_li(title: str, href: str, meta_s: str, val: str, official: bool = False) -> str:
        own = '<span class="own">Oficial</span>' if official else ""
        title_html = (
            f'<a class="it" href="{_esc(href)}" target="_blank" rel="noopener">{own}{_esc(title)} ↗</a>'
            if href else f'<span class="it">{own}{_esc(title)}</span>'
        )
        return f'<li>{title_html}<span class="im">{_esc(meta_s)}</span><span class="iv">{_esc(val)}</span></li>'

    yt = section("youtube_influencers")
    yt_card = ""
    if has_channel("youtube_influencers"):
        yt_rows = []
        yt_panels = []
        yt_has: list[bool] = []
        for company, color in palette:
            row = _row_for_company(yt, company) or {}
            top_off = list(row.get("top5_official") or [])
            top_unoff = list(row.get("top5_unofficial") or [])
            if not top_off and not top_unoff:
                for t in row.get("top5") or []:
                    (top_off if t.get("is_official") else top_unoff).append(t)
            found = [t for t in (top_off + top_unoff) if t.get("url")]
            search = str(row.get("search_url") or row.get("url") or "").strip()
            link_bits = []
            for t in found[:3]:
                full = str(t.get("title") or "vídeo")
                short = full if len(full) <= 42 else full[:39].rstrip() + "…"
                link_bits.append(
                    f'<a class="yl" href="{_esc(t.get("url"))}" target="_blank" rel="noopener" title="{_esc(full)}">{_esc(short)}</a>'
                )
            if search:
                link_bits.append(
                    f'<a class="yl" href="{_esc(search)}" target="_blank" rel="noopener">Busca ↗</a>'
                )
            links_html = "<div class=\"yls\">" + "".join(link_bits) + "</div>" if link_bits else "—"
            yt_rows.append(
                f"<tr><td>{cn(company, color)}</td>"
                f'<td class="r big">{_esc(row.get("traffic_fmt") or "—")}</td>'
                f'<td class="r">{_esc(row.get("views_official_fmt") or "0")}</td>'
                f'<td class="r">{_esc(row.get("views_unofficial_fmt") or "0")}</td>'
                f'<td class="r muted" style="font-weight:500">{_esc(str(row.get("about_count") or "—"))}</td>'
                f'<td class="r muted" style="font-weight:500">{_esc(row.get("views_30d_fmt") or "0")}</td>'
                f'<td class="r muted" style="font-weight:500">{_esc(row.get("views_6m_fmt") or "0")}</td>'
                f'<td class="r muted" style="font-weight:500">{_esc(row.get("views_1y_plus_fmt") or "0")}</td>'
                f"<td>{links_html}</td></tr>"
            )
            off_lis = [
                item_li(
                    str(t.get("title") or "vídeo"),
                    str(t.get("url") or ""),
                    " · ".join(x for x in [str(t.get("channel_name") or ""), str(t.get("upload_age") or "")] if x),
                    str(_compact_num(t.get("views")) if t.get("views") is not None else t.get("views_fmt") or "—"),
                    official=True,
                )
                for t in top_off[:5]
            ]
            un_lis = [
                item_li(
                    str(t.get("title") or "vídeo"),
                    str(t.get("url") or ""),
                    " · ".join(x for x in [str(t.get("channel_name") or ""), str(t.get("upload_age") or "")] if x),
                    str(_compact_num(t.get("views")) if t.get("views") is not None else t.get("views_fmt") or "—"),
                )
                for t in top_unoff[:5]
            ]
            yt_has.append(bool(off_lis or un_lis))
            note = row.get("note") or ""
            search_html = (
                f'<p class="infs"><a href="{_esc(search)}" target="_blank" rel="noopener">Ver busca no YouTube ↗</a></p>'
                if search else ""
            )
            yt_panels.append(
                f'{flag(str(note), True) if note else ""}{search_html}'
                f'<div class="g2" style="gap:0">'
                f'<div><p class="sub-h">Canal oficial</p>'
                f'{("<ul class=items>" + "".join(off_lis) + "</ul>") if off_lis else "<p class=empty>Nada encontrado.</p>"}</div>'
                f'<div class="bl"><p class="sub-h">Outros canais</p>'
                f'{("<ul class=items>" + "".join(un_lis) + "</ul>") if un_lis else "<p class=empty>Nada encontrado.</p>"}</div>'
                f"</div>"
            )
        yt_pick = next((i for i, ok in enumerate(yt_has) if ok), 0)
        yt_card = f"""
    <div class="card" id="youtube">
      <div class="card-head"><h3>YouTube — vídeos sobre a marca</h3><span class="src">1ª página da busca pelo nome</span></div>
      <div class="tw" style="margin-top:12px"><table>
        <thead><tr><th>Empresa</th><th class="r">Views</th><th class="r">Canal oficial</th><th class="r">Outros canais</th><th class="r">Vídeos</th><th class="r">Últimos 30d</th><th class="r">Até 6m</th><th class="r">1 ano+</th><th>Links</th></tr></thead>
        <tbody>{''.join(yt_rows)}</tbody>
      </table></div>
      {tabs("yt", yt_panels, selected=yt_pick)}
    </div>"""

    ig = section("instagram_influencers")
    ig_prof = section("instagram")
    ig_card = ""
    if has_channel("instagram_influencers"):
        ig_rows = []
        ig_panels = []
        for company, color in palette:
            row = _row_for_company(ig, company) or {}
            prow = _row_for_company(ig_prof, company) or {}
            ig_rows.append(
                f"<tr><td>{cn(company, color)}</td>"
                f'<td class="r">{_esc(prow.get("followers_fmt") or prow.get("value_fmt") or "—")}</td>'
                f'<td class="r big">{_esc(row.get("total_likes_fmt") or "—")}</td>'
                f'<td class="r">{_esc(str(row.get("own_posts") or 0))}</td>'
                f'<td class="r">{_esc(str(row.get("total_influencers") or 0))}</td>'
                f'<td class="r">{_esc(str(row.get("influencer_posts") or 0))}</td></tr>'
            )
            own = list(row.get("top5_page") or [])
            infs = list(row.get("top5_influencers") or [])
            if not own and not infs:
                for t in row.get("top5") or []:
                    (infs if t.get("is_influencer") else own).append(t)
            handles = ", ".join(f"@{h}" for h in (row.get("influencer_handles") or [])[:8])
            own_lis = [
                item_li(
                    str(t.get("caption") or (f"@{t.get('username')}" if t.get("username") else "post")),
                    str(t.get("url") or ""),
                    "próprio",
                    str(_compact_num(t.get("likes")) if t.get("likes") is not None else t.get("likes_fmt") or "—"),
                )
                for t in own[:5]
            ]
            inf_lis = [
                item_li(
                    str(t.get("caption") or (f"@{t.get('username')}" if t.get("username") else "post")),
                    str(t.get("url") or ""),
                    "influenciador",
                    str(_compact_num(t.get("likes")) if t.get("likes") is not None else t.get("likes_fmt") or "—"),
                )
                for t in infs[:5]
            ]
            ig_panels.append(
                f'{f"<p class=infs><b>Influenciadores:</b> {_esc(handles)}</p>" if handles else ""}'
                f'<div class="g2" style="gap:0">'
                f'<div><p class="sub-h">Posts próprios mais curtidos</p>'
                f'{("<ul class=items>" + "".join(own_lis) + "</ul>") if own_lis else "<p class=empty>—</p>"}</div>'
                f'<div class="bl"><p class="sub-h">Posts de influenciadores</p>'
                f'{("<ul class=items>" + "".join(inf_lis) + "</ul>") if inf_lis else "<p class=empty>—</p>"}</div>'
                f"</div>"
            )
        ig_card = f"""
    <div class="card" id="instagram">
      <div class="card-head"><h3>Instagram — 1ª página</h3><span class="src">posts próprios e de influenciadores</span></div>
      <div class="tw" style="margin-top:12px"><table>
        <thead><tr><th>Empresa</th><th class="r">Seguidores</th><th class="r">Curtidas</th><th class="r">Posts próprios</th><th class="r">Influenciadores</th><th class="r">Posts de influenciadores</th></tr></thead>
        <tbody>{''.join(ig_rows)}</tbody>
      </table></div>
      {tabs("ig", ig_panels)}
    </div>"""

    rd = section("reddit")
    rd_card = ""
    if has_channel("reddit"):
        rd_rows = []
        rd_panels = []
        for company, color in palette:
            row = _row_for_company(rd, company) or {}
            rd_rows.append(
                f"<tr><td>{cn(company, color)}</td>"
                f'<td class="r">{_esc(str(row.get("posts_first_page") or 0))}</td>'
                f'<td class="r big">{_esc(row.get("total_comments_fmt") or row.get("traffic_fmt") or "0")}</td>'
                f'<td class="r muted" style="font-weight:500">{_esc(row.get("total_results_fmt") or "—")}</td></tr>'
            )
            lis = []
            for t in list(row.get("top_posts") or [])[:5]:
                sub = f"r/{t.get('subreddit')}" if t.get("subreddit") else ""
                com = t.get("comments")
                com_s = f"{_compact_num(com)} com." if com is not None else ""
                lis.append(
                    f'<li><a class="it" href="{_esc(t.get("url") or "")}" target="_blank" rel="noopener">{_esc(t.get("title") or "post")}</a>'
                    f'<span class="im">{_esc(sub)}</span><span class="iv num">{_esc(com_s)}</span></li>'
                )
            note = row.get("note") or ""
            rd_panels.append(
                f'{flag(str(note), True) if note else ""}'
                f'{("<ul class=items>" + "".join(lis) + "</ul>") if lis else "<p class=empty>—</p>"}'
            )
        rd_card = f"""
    <div class="card" id="reddit">
      <div class="card-head"><h3>Reddit — 1ª página</h3><span class="src">Google: site:reddit.com + nome da marca</span></div>
      <div class="tw" style="margin-top:12px"><table>
        <thead><tr><th>Empresa</th><th class="r">Posts</th><th class="r">Comentários</th><th class="r">Resultados no Google</th></tr></thead>
        <tbody>{''.join(rd_rows)}</tbody>
      </table></div>
      {tabs("rd", rd_panels)}
      <div class="foot">"Resultados no Google" é a contagem genérica da busca e não mede presença real.</div>
    </div>"""

    social_html = f"""
    <section class="sec" id="social">
      <div class="sec-head"><h2>Social &amp; comunidade</h2></div>
      {profiles_html}
      {yt_card}
      {ig_card}
      {rd_card}
    </section>"""

    payload = _resolve_run_log(report, meta) or {}
    channels = payload.get("channels") or []
    lines = payload.get("lines") or []
    totals = payload.get("totals") or {}
    log_text = "\n".join(str(x) for x in lines)
    n_cos = len(palette)
    exec_html = ""
    if channels or lines:
        exec_html = f"""
    <details class="exec" id="execucao">
      <summary><span><span class="t">Execução</span> <span class="s num">&nbsp;{_esc(totals.get("sec_fmt") or "")}{(' · custo est. ' + _esc(totals.get("cost_fmt"))) if totals.get("cost_fmt") else ''}{(' · ' + str(n_cos) + ' empresas') if n_cos else ''}{(' · ' + str(len(channels)) + ' etapas') if channels else ''}</span></span><span class="o">Detalhes</span></summary>
      <div class="exec-body">
        {exec_tabs_html(
            channels=list(channels),
            totals=totals,
            log_text=log_text,
            rates=str(payload.get("rates_note") or "").strip(),
            api_pulls=payload.get("api_pulls") if isinstance(payload.get("api_pulls"), dict) else None,
            llm_calls=list(payload.get("llm_calls") or []),
        )}
      </div>
    </details>"""

    nicho = briefing.get("nicho") or ""
    escopo = briefing.get("escopo") or ""
    n_peers = max(0, n_cos - 1)
    vs = "1 concorrente" if n_peers == 1 else f"{n_peers} concorrentes"
    kicker_bits = ["Relatório de canais", "Comparativo"]
    if nicho:
        kicker_bits.append(str(nicho))
    kicker_bits.append(market_label)
    chips = []
    for company, color in palette:
        url = company_url(company)
        host = str(company.get("domain") or "")
        you = "<em>você</em>" if company.get("is_client") else ""
        inner = (
            f'<span class="cdot" style="background:{_esc(color)}"></span>'
            f'<b>{_esc(company.get("name") or host or "—")}</b>'
            f'{f"<span>{_esc(host)}</span>" if host else ""}{you}'
        )
        if url:
            chips.append(
                f'<a class="cochip" href="{_esc(url)}" target="_blank" rel="noopener" data-domain="{_esc(host)}">{inner}</a>'
            )
        else:
            chips.append(f'<span class="cochip" data-domain="{_esc(host)}">{inner}</span>')
    snap = ""
    for company, _c in palette:
        row = _row_for_company(section("similarweb"), company) or {}
        snap = row.get("snapshot_label") or snap

    from report_cmp import build_cmp_html, build_cmp_payload

    cmp_html = build_cmp_html(
        build_cmp_payload(
            report,
            [c for c, _ in palette],
            market=market,
            colors=[c for _, c in palette],
        ),
        profile_only=False,
        root_id="cmp",
    )

    return f"""
<div id="analysis-v2" class="is-compare">
  <nav class="anav" aria-label="Seções">
    <div class="anav-in">
      <a href="#lista">Tabela</a>
      {('<a href="#perfil">Perfil</a>' if cmp_html else "")}
      {('<a href="#concorrentes">Concorrentes</a>' if cmp_html else "")}
      {('<a href="#ganhando">Quem ganha</a>' if cmp_html else "")}
      <a href="#resumo">Resumo</a>
      <a href="#busca">Busca &amp; tráfego</a>
      <a href="#paga">Mídia paga</a>
      <a href="#social">Social</a>
      {('<a href="#execucao">Execução</a>' if exec_html else "")}
    </div>
  </nav>
  <main class="av2">
    <section class="mast">
      <div>
        <div class="kicker">{_esc(" · ".join(kicker_bits))}</div>
        <div class="title"><h1>{_esc(client)} <span class="vs">vs</span> {_esc(vs)}</h1></div>
        <div class="cochips">{''.join(chips)}</div>
      </div>
      <dl class="meta">
        {f'<div><dt>Nicho</dt><dd>{_esc(nicho)}</dd></div>' if nicho else ""}
        {f'<div><dt>Escopo</dt><dd>{_esc(escopo)} · {_esc(market_label)}</dd></div>' if escopo else f'<div><dt>Mercado</dt><dd>{_esc(market_label)}</dd></div>'}
        {f'<div><dt>Dados até</dt><dd>{_esc(snap)}</dd></div>' if snap else ""}
        {f'<div><dt>Run</dt><dd class="num">{_esc(run_id)}</dd></div>' if run_id else ""}
      </dl>
    </section>
    {analysis_add_form_html(run_id, [c for c, _ in palette])}
    <section class="sec" id="lista"></section>
    {cmp_html}
    {summary_html}
    {busca_html}
    {paid_html}
    {social_html}
    {exec_html}
    <footer class="av2-foot">WinnerTracker{(' · run ' + _esc(run_id)) if run_id else ""}</footer>
  </main>
</div>"""
