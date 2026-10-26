# -*- coding: utf-8 -*-
"""v2 analysis report (channel dashboard) matching trendtrack-canais.html."""

from __future__ import annotations

from typing import Any, Optional


def build_analysis_v2(
    report: dict[str, Any],
    meta: dict[str, Any],
    *,
    briefing: dict[str, Any],
    client: str,
    site_url: str,
    site_host: str,
    run_id: str,
    market: str,
    with_competitors: bool = False,
) -> str:
    from report_html import (  # noqa: PLC0415
        _channel_metric_value,
        _channel_score,
        _client_row,
        _compact_num,
        _dfs_growth_pct,
        _esc,
        _resolve_run_log,
        analysis_add_form_html,
        exec_tabs_html,
        _summary_channel_url,
        _summary_companies,
    )

    companies = _summary_companies(report)
    if with_competitors or len(companies) > 1:
        from report_analysis_compare import build_analysis_compare

        return build_analysis_compare(
            report,
            meta,
            briefing=briefing,
            client=client,
            site_url=site_url,
            site_host=site_host,
            run_id=run_id,
            market=market,
            companies=companies,
        )

    def client_row(key: str) -> Optional[dict[str, Any]]:
        sec = report.get(key)
        return _client_row(sec) if isinstance(sec, dict) else None

    def section(key: str) -> Optional[dict[str, Any]]:
        sec = report.get(key)
        return sec if isinstance(sec, dict) else None

    def has_channel(key: str) -> bool:
        sec = section(key)
        if not sec:
            return False
        return bool(
            sec.get("rows")
            or sec.get("total_fmt")
            or sec.get("total_ads_fmt")
            or sec.get("total_traffic_fmt")
        )

    def badge(score: str, skipped: bool = False) -> str:
        if skipped:
            return '<span class="sc skip">Pulado</span>'
        mapping = {
            "high": ("alto", "Alto"),
            "medium": ("medio", "Médio"),
            "low": ("baixo", "Baixo"),
            "0": ("zero", "Sem presença"),
        }
        cls, lab = mapping.get(score, ("baixo", "Baixo"))
        return f'<span class="sc {cls}">{lab}</span>'

    def tile(
        *,
        href: str,
        name: str,
        src: str,
        value: str,
        unit: str,
        score: str,
        skipped: bool,
    ) -> str:
        extra = " is-skip" if skipped else (" is-zero" if score == "0" else "")
        src_html = f'<span class="srcn">{_esc(src)}</span>' if src else ""
        unit_html = f"<small>{_esc(unit)}</small>" if unit else ""
        return (
            f'<a class="tile{extra}" href="{_esc(href)}">'
            f'<span class="nm"><span class="chn">{_esc(name)}</span>{src_html}</span>'
            f'<span class="vl num">{value}{unit_html}</span>'
            f"{badge(score, skipped)}</a>"
        )

    def channel_tile(
        key: str,
        *,
        href: str,
        name: str,
        src: str,
        kind: str,
        unit: str,
        value_override: str = "",
        unit_override: str = "",
    ) -> str:
        skipped = not has_channel(key)
        sec = section(key) or {}
        row = client_row(key)
        metric = _channel_metric_value(key, sec, row) if not skipped else None
        score = "0" if skipped else _channel_score(key, metric)
        if value_override:
            val = value_override
        elif skipped:
            val = "—"
        else:
            val = _fmt_value(key, kind, sec, row)
        unit_txt = "não coletado" if skipped else (unit_override or unit)
        return tile(
            href=href, name=name, src=src, value=_esc(val),
            unit=unit_txt, score=score, skipped=skipped,
        )

    def _fmt_value(key: str, kind: str, sec: dict, row: Optional[dict]) -> str:
        row = row or {}
        if kind == "ads":
            return str(row.get("ads_fmt") or row.get("value_fmt") or sec.get("total_ads_fmt") or "0")
        if key == "brand_dataforseo":
            return str(row.get("traffic_fmt") or row.get("latest_volume") or sec.get("total_traffic_fmt") or "0")
        if key in ("brand", "seo", "similarweb"):
            return str(row.get("traffic_fmt") or sec.get("total_traffic_fmt") or "0")
        if key == "reddit":
            return str(row.get("total_comments_fmt") or row.get("traffic_fmt") or "0")
        if key == "instagram_influencers":
            return str(row.get("total_likes_fmt") or row.get("traffic_fmt") or "0")
        if key == "youtube_influencers":
            return str(
                row.get("traffic_fmt")
                or sec.get("total_traffic_fmt")
                or _compact_num((_coerce(row.get("views_official")) or 0) + (_coerce(row.get("views_unofficial")) or 0))
                or "0"
            )
        if key in ("twitter", "linkedin_profile"):
            return str(row.get("followers_fmt") or row.get("traffic_fmt") or "0")
        return str(row.get("value_fmt") or row.get("followers_fmt") or row.get("traffic_fmt") or "0")

    def _coerce(v: Any) -> Optional[float]:
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def growth_small(key: str) -> str:
        row = client_row(key) or {}
        sec = section(key) or {}
        if key == "brand_dataforseo":
            g = row.get("growth_1y_pct")
            if not isinstance(g, (int, float)):
                g = _dfs_growth_pct(row.get("traffic") or row.get("latest_volume"), row.get("volume_1y"))
            if isinstance(g, (int, float)):
                return f"{g:+.0f}%" if abs(g) >= 100 else f"{g:+.1f}% 1a"
            return ""
        g = row.get("growth_fmt") or sec.get("growth_fmt") or ""
        return "" if g in ("", "n/a", "—") else str(g)

    # --- summary ---
    pop_tiles = [
        channel_tile("similarweb", href="#trafego", name="Visitas", src="SimilarWeb", kind="similarweb", unit="/mês"),
        channel_tile(
            "brand_dataforseo", href="#marca", name="Buscas de marca", src="DataForSEO",
            kind="brand_dfs", unit=growth_small("brand_dataforseo"),
        ),
        channel_tile(
            "brand", href="#marca", name="Tráfego de marca", src="Semrush",
            kind="brand", unit=growth_small("brand") or "visitas",
        ),
    ]
    paid_tiles = [
        channel_tile("google_ads", href="#paga", name="Google Ads", src="", kind="ads", unit="anúncios"),
        channel_tile("meta", href="#paga", name="Meta Ads", src="", kind="ads", unit="anúncios"),
        channel_tile("linkedin", href="#paga", name="LinkedIn Ads", src="", kind="ads", unit="anúncios"),
    ]
    org_tiles = [
        channel_tile("seo", href="#seo", name="SEO orgânico", src="Semrush", kind="seo", unit="visitas/mês"),
        channel_tile("twitter", href="#perfis", name="X / Twitter", src="", kind="count", unit="seguidores"),
        channel_tile("instagram", href="#perfis", name="Instagram", src="", kind="count", unit="seguidores"),
        channel_tile("linkedin_profile", href="#perfis", name="LinkedIn", src="", kind="count", unit="seguidores"),
        channel_tile("youtube", href="#perfis", name="YouTube", src="", kind="count", unit="inscritos"),
        channel_tile("tiktok", href="#perfis", name="TikTok", src="", kind="count", unit="seguidores"),
        channel_tile("reddit", href="#reddit", name="Reddit", src="", kind="seo", unit="comentários"),
    ]
    inf_tiles = [
        channel_tile("youtube_influencers", href="#youtube", name="YouTube", src="1ª página", kind="seo", unit="views"),
        channel_tile("instagram_influencers", href="#instagram", name="Instagram", src="1ª página", kind="seo", unit="curtidas"),
    ]

    def col(title: str, css: str, tiles: list[str]) -> str:
        return (
            f'<div class="sum-col {css}"><h3>{_esc(title)}<span class="cnt">{len(tiles)} canais</span></h3>'
            f"{''.join(tiles)}</div>"
        )

    summary_html = f"""
    <section class="sec" id="resumo">
      <div class="sec-head"><h2>Resumo dos canais</h2><span class="sec-note">Clique em um canal para ver o detalhe</span></div>
      <div class="card">
        <div class="sum">
          {col("Popularidade", "g-pop", pop_tiles)}
          {col("Mídia paga", "g-paid", paid_tiles)}
          {col("Orgânico", "g-org", org_tiles)}
          {col("Influenciadores", "g-inf", inf_tiles)}
        </div>
        <div class="sum-legend">
          <span class="lg-t">Nota do pipeline</span>
          {badge("high")}{badge("medium")}{badge("low")}{badge("0")}{badge("0", True)}
          <span class="lg-n">Pulado = etapa não executada nesta rodada</span>
        </div>
      </div>
    </section>"""

    # --- similarweb ---
    sw = section("similarweb") or {}
    sw_row = client_row("similarweb") or {}
    sw_card = ""
    if has_channel("similarweb"):
        months = list(sw_row.get("visits_monthly") or [])[-3:]
        max_v = 1.0
        parsed_months = []
        for m in months:
            n = _coerce(m.get("visits")) or _coerce(str(m.get("visits_fmt") or "").replace(",", "")) or 0
            parsed_months.append((m, n))
            max_v = max(max_v, n)
        bars = []
        for i, (m, n) in enumerate(parsed_months):
            h = max(4, round(n / max_v * 100)) if max_v else 4
            last = " last" if i == len(parsed_months) - 1 else ""
            label = m.get("label") or str(m.get("date") or "")[:7]
            val = m.get("visits_fmt") or _compact_num(n)
            bars.append(
                f'<div class="col{last}"><b class="num">{_esc(val)}</b>'
                f'<i style="height:{h}%"></i><span>{_esc(label)}</span></div>'
            )
        month_note = ""
        if len(parsed_months) >= 2:
            deltas = []
            for i in range(1, len(parsed_months)):
                prev, cur = parsed_months[i - 1][1], parsed_months[i][1]
                if prev:
                    p = (cur / prev - 1) * 100
                    cls = "up" if p > 0 else "down"
                    deltas.append(f'<b class="{cls} num">{p:+.1f}%</b> {_esc(parsed_months[i][0].get("label") or "")}')
            if parsed_months[0][1]:
                p = (parsed_months[-1][1] / parsed_months[0][1] - 1) * 100
                cls = "up" if p > 0 else "down"
                deltas.append(f'<b class="{cls} num">{p:+.1f}%</b> no período')
            if deltas:
                month_note = f'<p style="margin:12px 0 0;font-size:13px;color:var(--muted)">{" · ".join(deltas)}</p>'

        sources = list(sw_row.get("sources") or [])
        src_nums = []
        for s in sources:
            n = _coerce(s.get("share"))
            if n is None:
                raw = str(s.get("share_fmt") or "").replace("%", "").replace(",", ".")
                n = _coerce(raw)
            src_nums.append(n or 0)
        max_src = max(src_nums) if src_nums else 1
        src_lis = []
        for s, n in zip(sources, src_nums):
            w = 0 if max_src <= 0 else round(n / max_src * 100)
            na = ' class="na"' if n <= 0 else ""
            fmt = s.get("share_fmt") or (f"{n:.1f}%" if n else "—")
            src_lis.append(
                f'<li{na}><span class="l">{_esc(s.get("name") or "—")}</span>'
                f'<span class="t"><i style="width:{w}%"></i></span>'
                f'<span class="v num">{_esc(fmt)}</span></li>'
            )

        countries = list(sw_row.get("countries") or [])
        c_nums = []
        for c in countries:
            n = _coerce(c.get("share"))
            if n is None:
                raw = str(c.get("share_fmt") or "").replace("%", "").replace(",", ".")
                n = _coerce(raw)
            c_nums.append(n or 0)
        max_c = max(c_nums) if c_nums else 1
        c_lis = []
        for c, n in zip(countries, c_nums):
            w = 0 if max_c <= 0 else round(n / max_c * 100)
            label = c.get("name") or c.get("code") or "—"
            fmt = c.get("share_fmt") or (f"{n:.1f}%" if n else "—")
            c_lis.append(
                f'<li><span class="l">{_esc(label)}</span>'
                f'<span class="t"><i style="width:{w}%"></i></span>'
                f'<span class="v num">{_esc(fmt)}</span></li>'
            )

        snap = sw_row.get("snapshot_label") or sw.get("latest_label") or ""
        ga = "Sim" if sw_row.get("is_data_from_ga") else "Não"
        sw_url = sw_row.get("url") or site_url
        sw_card = f"""
    <div class="card" id="trafego">
      <div class="card-head"><h3>Tráfego do site</h3><span class="src">SimilarWeb{(' · snapshot ' + _esc(snap)) if snap else ''}{(' · <a href="' + _esc(sw_url) + '" target="_blank" rel="noopener">' + _esc(site_host or sw_url) + ' ↗</a>') if sw_url else ''}</span></div>
      <div class="kstrip" style="margin-top:14px;border-top:1px solid var(--line)">
        <div class="k"><div class="k-l">Visitas / mês</div><div class="k-v num">{_esc(sw_row.get("traffic_fmt") or sw.get("total_traffic_fmt") or "—")}</div></div>
        <div class="k"><div class="k-l">Taxa de rejeição</div><div class="k-v num">{_esc(sw_row.get("bounce_fmt") or "—")}</div></div>
        <div class="k"><div class="k-l">Páginas / visita</div><div class="k-v num">{_esc(sw_row.get("pages_fmt") or "—")}</div></div>
        <div class="k"><div class="k-l">Tempo no site</div><div class="k-v num">{_esc(sw_row.get("time_fmt") or "—")}</div></div>
        <div class="k"><div class="k-l">Google Analytics</div><div class="k-v">{_esc(ga)} <small>detectado</small></div></div>
      </div>
      <div class="g3" style="padding:20px 22px;gap:28px">
        <div>
          <div class="sub-h" style="padding:0 0 12px">Visitas mensais</div>
          <div class="cols">{''.join(bars) if bars else '<p class="sec-note">Sem série mensal.</p>'}</div>
          {month_note}
        </div>
        <div>
          <div class="sub-h" style="padding:0 0 12px">Origem das visitas</div>
          <ul class="hb">{''.join(src_lis) if src_lis else '<li class="na"><span class="l">—</span><span class="t"><i style="width:0"></i></span><span class="v">—</span></li>'}</ul>
        </div>
        <div>
          <div class="sub-h" style="padding:0 0 12px">Principais países</div>
          <ul class="hb">{''.join(c_lis) if c_lis else '<li class="na"><span class="l">—</span><span class="t"><i style="width:0"></i></span><span class="v">—</span></li>'}</ul>
        </div>
      </div>
    </div>"""

    # --- brand + seo ---
    dfs = section("brand_dataforseo") or {}
    dfs_row = client_row("brand_dataforseo") or {}
    brand = section("brand") or {}
    brand_row = client_row("brand") or {}
    seo = section("seo") or {}
    seo_row = client_row("seo") or {}

    def gcell(g: Optional[float]) -> str:
        if not isinstance(g, (int, float)):
            return '<span class="pct">—</span>'
        cls = "up" if g > 0 else ("down" if g < 0 else "")
        txt = f"{g:+.0f}%" if abs(g) >= 100 else f"{g:+.1f}%"
        return f'<span class="pct {cls}">{txt}</span>'

    brand_rows = []
    if has_channel("brand_dataforseo"):
        latest = dfs_row.get("traffic") or dfs_row.get("latest_volume")
        periods = [
            ("Atual", dfs_row.get("latest_label") or "atual", latest, None),
            ("1 ano atrás", None, dfs_row.get("volume_1y"), "1y"),
            ("2 anos atrás", None, dfs_row.get("volume_2y"), "2y"),
            ("3 anos atrás", None, dfs_row.get("volume_3y"), "3y"),
            ("5 anos atrás", None, dfs_row.get("volume_5y"), "5y"),
        ]
        for label, latest_lab, vol, years in periods:
            title = f"{latest_lab}" if latest_lab and label == "Atual" else label
            if years:
                g = dfs_row.get(f"growth_{years}_pct")
                if not isinstance(g, (int, float)):
                    g = _dfs_growth_pct(latest, vol)
            else:
                g = None
            vol_txt = "—" if vol is None else (dfs_row.get("traffic_fmt") if years is None else f"{int(vol):,}" if str(vol).replace("-", "").isdigit() else str(vol))
            if years is None:
                vol_txt = str(dfs_row.get("traffic_fmt") or vol_txt)
            if vol is None and years:
                vol_txt = '<span style="font-weight:400">sem dado</span>'
            brand_rows.append(
                f"<tr><td>{_esc(title)}</td><td class=\"r\">{vol_txt if '<' in str(vol_txt) else _esc(vol_txt)}</td>"
                f"<td class=\"r\">{gcell(g) if years else '<span class=\"muted\">—</span>'}</td></tr>"
            )

    dfs_g = dfs_row.get("growth_1y_pct")
    if not isinstance(dfs_g, (int, float)):
        dfs_g = _dfs_growth_pct(dfs_row.get("traffic") or dfs_row.get("latest_volume"), dfs_row.get("volume_1y"))
    dfs_g_html = ""
    if isinstance(dfs_g, (int, float)):
        cls = "up" if dfs_g > 0 else "down"
        txt = f"{dfs_g:+.0f}%" if abs(dfs_g) >= 100 else f"{dfs_g:+.1f}%"
        dfs_g_html = f'<small class="{cls}">{txt} em 1 ano</small>'
    brand_g = brand_row.get("growth_fmt") or brand.get("growth_fmt") or ""
    brand_g_html = ""
    if brand_g and brand_g not in ("n/a", "—"):
        cls = "up" if str(brand_g).startswith("+") else ("down" if str(brand_g).startswith("-") else "")
        brand_g_html = f'<small class="{cls}">{_esc(brand_g)}</small>'

    kw = dfs_row.get("brand_keyword") or dfs.get("client_keyword") or ""
    dfs_url = _summary_channel_url("brand_dataforseo", dfs, dfs_row, market=market)
    brand_url = _summary_channel_url("brand", brand, brand_row, market=market)
    seo_url = _summary_channel_url("seo", seo, seo_row, market=market)
    seo_g = seo_row.get("growth_fmt") or seo.get("growth_fmt") or "—"
    seo_g_cls = "up" if str(seo_g).startswith("+") else ("down" if str(seo_g).startswith("-") else "")

    marca_card = f"""
      <div class="card" id="marca">
        <div class="card-head"><h3>Busca pela marca</h3><span class="src">{('palavra-chave "' + _esc(kw) + '" · ') if kw else ''}{_esc(market)}</span></div>
        <div class="kstrip" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-top:14px;border-top:1px solid var(--line)">
          <div class="k"><div class="k-l">DataForSEO</div><div class="k-v num">{_esc(dfs_row.get("traffic_fmt") or dfs.get("total_traffic_fmt") or "—")} {dfs_g_html}</div></div>
          <div class="k"><div class="k-l">Semrush · tráfego de marca</div><div class="k-v num">{_esc(brand_row.get("traffic_fmt") or brand.get("total_traffic_fmt") or "—")} {brand_g_html}</div></div>
        </div>
        <div class="tw"><table>
          <thead><tr><th>Período (DataForSEO)</th><th class="r">Volume</th><th class="r">Variação até hoje</th></tr></thead>
          <tbody>{''.join(brand_rows) if brand_rows else '<tr><td colspan="3" class="muted">Sem dados de marca.</td></tr>'}</tbody>
        </table></div>
        <div class="foot">Quando o volume histórico é 0, o cálculo de variação usa base 100. DataForSEO = volume de busca; Semrush = tráfego estimado.{(' · <a href="' + _esc(dfs_url or brand_url) + '" target="_blank" rel="noopener">Abrir ↗</a>') if (dfs_url or brand_url) else ''}</div>
      </div>"""

    seo_card = f"""
      <div class="card" id="seo">
        <div class="card-head"><h3>SEO orgânico</h3><span class="src">Semrush · {_esc(market)}</span></div>
        <div class="kstrip" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-top:14px;border-top:1px solid var(--line);border-bottom:0">
          <div class="k"><div class="k-l">Tráfego orgânico</div><div class="k-v num">{_esc(seo_row.get("traffic_fmt") or seo.get("total_traffic_fmt") or "—")} <small>visitas/mês</small></div></div>
          <div class="k"><div class="k-l">Crescimento</div><div class="k-v num {seo_g_cls}">{_esc(seo_g)}</div></div>
        </div>
        <div class="foot">{('<a href="' + _esc(seo_url) + '" target="_blank" rel="noopener">Abrir no Semrush ↗</a>') if seo_url else 'Semrush organic traffic'}</div>
      </div>"""

    busca_html = f"""
    <section class="sec" id="busca">
      <div class="sec-head"><h2>Busca &amp; tráfego</h2></div>
      {sw_card}
      <div class="g2">{marca_card}{seo_card}</div>
    </section>"""

    # --- paid ---
    def paid_row(key: str, label: str) -> str:
        skipped = not has_channel(key)
        sec = section(key) or {}
        row = client_row(key) or {}
        ads = "—" if skipped else str(row.get("ads_fmt") or row.get("value_fmt") or sec.get("total_ads_fmt") or "0")
        spend = "—" if skipped else str(row.get("investimento_fmt") or "—")
        metric = None if skipped else _channel_metric_value(key, sec, row)
        score = "0" if skipped else _channel_score(key, metric)
        note = "Etapa não executada nesta rodada." if skipped else (row.get("note") or sec.get("insight") or "—")
        url = _summary_channel_url(key, sec, row, market=market)
        src = f'<a href="{_esc(url)}" target="_blank" rel="noopener">Biblioteca ↗</a>' if url else "—"
        return (
            f"<tr><td><b>{_esc(label)}</b></td><td class=\"r\">{_esc(ads)}</td>"
            f"<td class=\"r\">{_esc(spend)}</td><td>{badge(score, skipped)}</td>"
            f"<td class=\"muted\">{_esc(str(note)[:180])}</td><td class=\"r\">{src}</td></tr>"
        )

    paid_html = f"""
    <section class="sec" id="paga">
      <div class="sec-head"><h2>Mídia paga</h2><span class="sec-note">Bibliotecas públicas de anúncios · {_esc(market)}</span></div>
      <div class="card"><div class="tw"><table>
        <thead><tr><th>Canal</th><th class="r">Anúncios ativos</th><th class="r">Gasto estimado</th><th>Status</th><th>Observação</th><th class="r">Fonte</th></tr></thead>
        <tbody>
          {paid_row("google_ads", "Google Ads")}
          {paid_row("meta", "Meta Ads")}
          {paid_row("linkedin", "LinkedIn Ads")}
        </tbody>
      </table></div></div>
    </section>"""

    # --- social profiles ---
    def profile_row(key: str, label: str, audience_label: str) -> str:
        skipped = not has_channel(key)
        sec = section(key) or {}
        row = client_row(key) or {}
        url = str(row.get("url") or "")
        handle = str(row.get("handle") or "").lstrip("@")
        profile = "não encontrado"
        if url:
            lab = f"@{handle} ↗" if handle else "Perfil ↗"
            profile = f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(lab)}</a>'
        elif handle:
            profile = f"@{_esc(handle)}"
        val = "—" if skipped else str(
            row.get("followers_fmt") or row.get("value_fmt") or row.get("traffic_fmt") or "0"
        )
        metric = None if skipped else _channel_metric_value(key, sec, row)
        score = "0" if skipped else _channel_score(key, metric)
        detail = "não encontrado" if (not skipped and not url and (metric in (None, 0))) else audience_label
        if skipped:
            detail = "não coletado"
        return (
            f"<tr><td><b>{_esc(label)}</b></td><td>{profile if url or handle else f'<span class=\"muted\">{_esc(profile)}</span>'}</td>"
            f"<td class=\"r\">{_esc(val)}</td><td>{badge(score, skipped)}</td>"
            f"<td class=\"muted\">{_esc(detail)}</td></tr>"
        )

    profiles_html = f"""
    <div class="card" id="perfis">
      <div class="card-head"><h3>Perfis oficiais</h3><span class="src">seguidores / inscritos</span></div>
      <div class="tw" style="margin-top:12px"><table>
        <thead><tr><th>Rede</th><th>Perfil</th><th class="r">Audiência</th><th>Nota</th><th>Detalhe</th></tr></thead>
        <tbody>
          {profile_row("twitter", "X / Twitter", "seguidores")}
          {profile_row("instagram", "Instagram", "seguidores")}
          {profile_row("linkedin_profile", "LinkedIn", "seguidores")}
          {profile_row("youtube", "YouTube", "inscritos")}
          {profile_row("tiktok", "TikTok", "seguidores")}
        </tbody>
      </table></div>
    </div>"""

    def item_li(title: str, href: str, meta: str, val: str, official: bool = False) -> str:
        own = '<span class="own">Oficial</span>' if official else ""
        title_html = f'<a class="it" href="{_esc(href)}" target="_blank" rel="noopener">{own}{_esc(title)}</a>' if href else f'<span class="it">{own}{_esc(title)}</span>'
        return f'<li>{title_html}<span class="im">{_esc(meta)}</span><span class="iv">{_esc(val)}</span></li>'

    yt = section("youtube_influencers") or {}
    yt_row = client_row("youtube_influencers") or {}
    yt_card = ""
    if has_channel("youtube_influencers"):
        top_off = list(yt_row.get("top5_official") or [])
        top_unoff = list(yt_row.get("top5_unofficial") or [])
        if not top_off and not top_unoff:
            for t in yt_row.get("top5") or []:
                (top_off if t.get("is_official") else top_unoff).append(t)
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
        v30 = _coerce(yt_row.get("views_30d")) or 0
        v6 = _coerce(yt_row.get("views_6m")) or 0
        v1 = _coerce(yt_row.get("views_1y_plus")) or 0
        tot = v30 + v6 + v1 or 1
        yt_url = yt_row.get("url") or yt.get("url") or ""
        yt_card = f"""
    <div class="card" id="youtube">
      <div class="card-head"><h3>YouTube — vídeos sobre a marca</h3><span class="src">1ª página{(' · <a href="' + _esc(yt_url) + '" target="_blank" rel="noopener">abrir busca ↗</a>') if yt_url else ''}</span></div>
      <div class="kstrip" style="margin-top:14px;border-top:1px solid var(--line)">
        <div class="k"><div class="k-l">Views totais</div><div class="k-v num">{_esc(yt_row.get("traffic_fmt") or yt.get("total_traffic_fmt") or "—")}</div></div>
        <div class="k"><div class="k-l">Canal oficial</div><div class="k-v num">{_esc(yt_row.get("views_official_fmt") or "—")}</div></div>
        <div class="k"><div class="k-l">Outros canais</div><div class="k-v num">{_esc(yt_row.get("views_unofficial_fmt") or "—")}</div></div>
        <div class="k"><div class="k-l">Vídeos na página</div><div class="k-v num">{_esc(str(yt_row.get("about_count") or "—"))}</div></div>
        <div class="k"><div class="k-l">Por idade do vídeo</div>
          <div class="split" aria-hidden="true"><span style="width:{v30/tot*100:.1f}%;background:#0E1116"></span><span style="width:{v6/tot*100:.1f}%;background:#8A939E"></span><span style="width:{v1/tot*100:.1f}%;background:#C9D0D8"></span></div>
          <div style="font-size:12.5px;color:var(--muted)"><b class="num" style="color:var(--ink)">{_esc(yt_row.get("views_30d_fmt") or "0")}</b> 30d · <b class="num" style="color:var(--ink)">{_esc(yt_row.get("views_6m_fmt") or "0")}</b> 6m · <b class="num" style="color:var(--ink)">{_esc(yt_row.get("views_1y_plus_fmt") or "0")}</b> 1a+</div>
        </div>
      </div>
      <div class="g2" style="gap:0">
        <div><p class="sub-h">Mais vistos · outros canais</p><ul class="items">{''.join(un_lis) or '<li><span class="it">—</span></li>'}</ul></div>
        <div style="border-left:1px solid var(--line)"><p class="sub-h">Mais vistos · canal oficial</p><ul class="items">{''.join(off_lis) or '<li><span class="it">—</span></li>'}</ul></div>
      </div>
    </div>"""

    ig = section("instagram_influencers") or {}
    ig_row = client_row("instagram_influencers") or {}
    ig_card = ""
    if has_channel("instagram_influencers"):
        posts = list(ig_row.get("top5_page") or [])
        if not posts and ig_row.get("top5"):
            posts = [t for t in ig_row.get("top5") or [] if not t.get("is_influencer")]
        ig_lis = [
            item_li(
                str(t.get("caption") or (f"@{t.get('username')}" if t.get("username") else "post")),
                str(t.get("url") or ""),
                "próprio" if not t.get("is_influencer") else (f"@{t.get('username')}" if t.get("username") else "influenciador"),
                str(_compact_num(t.get("likes")) if t.get("likes") is not None else t.get("likes_fmt") or "—"),
            )
            for t in posts[:5]
        ]
        ig_url = ig_row.get("url") or ""
        handle = str(ig_row.get("handle") or "").lstrip("@")
        ig_card = f"""
      <div class="card" id="instagram">
        <div class="card-head"><h3>Instagram — 1ª página</h3><span class="src">{('<a href="' + _esc(ig_url) + '" target="_blank" rel="noopener">@' + _esc(handle or 'perfil') + ' ↗</a>') if ig_url else ''}</span></div>
        <div class="kstrip" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-top:14px;border-top:1px solid var(--line)">
          <div class="k"><div class="k-l">Curtidas</div><div class="k-v num">{_esc(ig_row.get("total_likes_fmt") or ig.get("total_traffic_fmt") or "—")}</div></div>
          <div class="k"><div class="k-l">Posts próprios</div><div class="k-v num">{_esc(str(ig_row.get("own_posts") or 0))}</div></div>
          <div class="k"><div class="k-l">Influenciadores</div><div class="k-v num">{_esc(str(ig_row.get("total_influencers") or 0))}</div></div>
        </div>
        <p class="sub-h">Posts mais curtidos</p>
        <ul class="items">{''.join(ig_lis) or '<li><span class="it">—</span></li>'}</ul>
      </div>"""

    rd = section("reddit") or {}
    rd_row = client_row("reddit") or {}
    rd_card = ""
    if has_channel("reddit"):
        rd_lis = []
        for t in list(rd_row.get("top_posts") or [])[:5]:
            sub = f"r/{t.get('subreddit')}" if t.get("subreddit") else ""
            rd_lis.append(
                f'<li><a class="it" href="{_esc(t.get("url") or "")}" target="_blank" rel="noopener">{_esc(t.get("title") or "post")}</a>'
                f'<span class="im">{_esc(sub)}</span></li>'
            )
        rd_url = rd_row.get("url") or rd.get("url") or ""
        rd_card = f"""
      <div class="card" id="reddit">
        <div class="card-head"><h3>Reddit — 1ª página</h3><span class="src">{('<a href="' + _esc(rd_url) + '" target="_blank" rel="noopener">abrir ↗</a>') if rd_url else ''}</span></div>
        <div class="kstrip" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-top:14px;border-top:1px solid var(--line)">
          <div class="k"><div class="k-l">Posts</div><div class="k-v num">{_esc(str(rd_row.get("posts_first_page") or 0))}</div></div>
          <div class="k"><div class="k-l">Comentários</div><div class="k-v num">{_esc(rd_row.get("total_comments_fmt") or rd_row.get("traffic_fmt") or "0")}</div></div>
          <div class="k"><div class="k-l">Resultados no Google</div><div class="k-v num">{_esc(rd_row.get("total_results_fmt") or "—")}</div></div>
        </div>
        <p class="sub-h">Principais posts</p>
        <ul class="items">{''.join(rd_lis) or '<li><span class="it">—</span></li>'}</ul>
      </div>"""

    social_html = f"""
    <section class="sec" id="social">
      <div class="sec-head"><h2>Social &amp; comunidade</h2></div>
      {profiles_html}
      {yt_card}
      <div class="g2">{ig_card}{rd_card}</div>
    </section>"""

    # --- exec ---
    payload = _resolve_run_log(report, meta) or {}
    channels = payload.get("channels") or []
    lines = payload.get("lines") or []
    totals = payload.get("totals") or {}
    log_text = "\n".join(str(x) for x in lines)
    exec_html = ""
    if channels or lines:
        exec_html = f"""
    <details class="exec" id="execucao">
      <summary><span><span class="t">Execução</span> <span class="s num">&nbsp;{_esc(totals.get("sec_fmt") or "")}{(' · custo est. ' + _esc(totals.get("cost_fmt"))) if totals.get("cost_fmt") else ''}{(' · ' + str(len(channels)) + ' etapas') if channels else ''}</span></span><span class="o">Detalhes</span></summary>
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
    market_label = "EUA" if market == "US" else "Brasil"
    kicker_bits = ["Relatório de canais"]
    if nicho:
        kicker_bits.append(str(nicho))
    kicker_bits.append(market_label)
    site_link = (
        f'<a class="site" href="{_esc(site_url)}" target="_blank" rel="noopener">{_esc(site_host or site_url)} ↗</a>'
        if site_url else ""
    )
    comps_tag = '<span class="tag-comps">Com concorrentes</span>' if with_competitors else ""
    snap = (client_row("similarweb") or {}).get("snapshot_label") or (section("similarweb") or {}).get("latest_label") or ""

    from report_analysis_compare import COLORS
    from report_cmp import build_cmp_html, build_cmp_payload

    solo_cos = companies or [{"name": client, "domain": site_host, "is_client": True, "_key": ""}]
    cmp_html = build_cmp_html(
        build_cmp_payload(report, solo_cos[:1], market=market, colors=[COLORS[0]]),
        profile_only=True,
        root_id="cmp",
    )

    return f"""
<div id="analysis-v2">
  <nav class="anav" aria-label="Seções">
    <div class="anav-in">
      {('<a href="#perfil">Perfil</a>' if cmp_html else "")}
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
        <div class="title"><h1>{_esc(client)}</h1>{site_link}{comps_tag}</div>
      </div>
      <dl class="meta">
        {f'<div><dt>Nicho</dt><dd>{_esc(nicho)}</dd></div>' if nicho else ""}
        {f'<div><dt>Escopo</dt><dd>{_esc(escopo)} · {_esc(market_label)}</dd></div>' if escopo else f'<div><dt>Mercado</dt><dd>{_esc(market_label)}</dd></div>'}
        {f'<div><dt>Dados até</dt><dd>{_esc(snap)}</dd></div>' if snap else ""}
        {f'<div><dt>Run</dt><dd class="num">{_esc(run_id)}</dd></div>' if run_id else ""}
      </dl>
    </section>
    {analysis_add_form_html(run_id, companies or [{"name": client, "domain": site_host, "is_client": True}])}
    {cmp_html}
    {summary_html}
    {busca_html}
    {paid_html}
    {social_html}
    {exec_html}
    <footer class="av2-foot">WinnerTracker{(' · run ' + _esc(run_id)) if run_id else ""}</footer>
  </main>
</div>"""
