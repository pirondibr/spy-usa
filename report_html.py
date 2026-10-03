# -*- coding: utf-8 -*-
"""HTML tables report for Spy USA (no chatbot)."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Optional


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _md_lite(text: str) -> str:
    import re

    raw = _esc(text or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", raw)


def _rows_table(headers: list[str], rows: list[list[str]]) -> str:
    thead = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    if not body:
        body.append(f'<tr><td colspan="{len(headers)}">No data</td></tr>')
    return (
        f'<div class="table-wrap"><table><thead><tr>{thead}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _link_cell(url: Any, label: str = "Open") -> str:
    u = str(url or "").strip()
    if not u or u in ("—", "-", "n/a", "None"):
        return "—"
    return (
        f'<a class="ext" href="{_esc(u)}" target="_blank" rel="noopener noreferrer">'
        f"{_esc(label)}</a>"
    )


def _client_row(section: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not section:
        return None
    rows = section.get("rows") or []
    for r in rows:
        if r.get("is_client"):
            return r
    return rows[0] if len(rows) == 1 else None


def _report_market(report: dict[str, Any], run_meta: Optional[dict[str, Any]] = None) -> str:
    raw = (
        (report or {}).get("market")
        or (run_meta or {}).get("market")
        or "US"
    )
    m = str(raw).strip().upper()
    return "BR" if m in ("BR", "BRAZIL", "BRASIL") else "US"


def _main_datum(
    section: Optional[dict[str, Any]],
    kind: str,
    row: Optional[dict[str, Any]] = None,
) -> str:
    """Valor principal (cliente ou row específica) para a tabela resumo."""
    if not section:
        return "—"
    if row is None:
        row = _client_row(section)
    if kind == "ads":
        if row:
            return str(row.get("ads_fmt") or row.get("value_fmt") or "0")
        return str(section.get("total_ads_fmt") or "—")
    if kind in ("seo", "brand"):
        if row:
            return str(row.get("traffic_fmt") or "0")
        return str(section.get("total_traffic_fmt") or "—")
    if kind == "brand_dfs":
        if row:
            return str(
                row.get("traffic_fmt")
                or row.get("latest_volume")
                or "0"
            )
        return str(section.get("total_traffic_fmt") or "—")
    if kind == "similarweb":
        if row:
            return str(row.get("traffic_fmt") or "0")
        return str(section.get("total_traffic_fmt") or "—")
    # count / social / linkedin
    if row:
        return str(row.get("value_fmt") or row.get("ads_fmt") or "0")
    return str(section.get("total_fmt") or "—")


def _summary_channel_url(
    key: str,
    section: dict[str, Any],
    row: Optional[dict[str, Any]],
    *,
    market: str = "US",
) -> str:
    """URL do cliente para o resumo (biblioteca / Semrush / perfil / site)."""
    row = row or {}
    url = str(row.get("url") or section.get("url") or "").strip()
    if url and url not in ("—", "-", "n/a", "None"):
        return url

    domain = str(row.get("domain") or section.get("client_domain") or "").strip()
    name = str(row.get("name") or "").strip()
    site = str(row.get("site_url") or "").strip()
    from urllib.parse import quote

    mkt = "BR" if str(market).upper() in ("BR", "BRAZIL", "BRASIL") else "US"
    semrush_db = "br" if mkt == "BR" else "us"
    meta_country = "BR" if mkt == "BR" else "US"
    google_region = "BR" if mkt == "BR" else "US"

    if key in ("seo", "brand") and domain:
        return (
            "https://www.semrush.com/analytics/overview/"
            f"?q={quote(domain)}&searchType=domain&db={semrush_db}"
        )
    if key == "brand_dataforseo":
        kw = str(row.get("brand_keyword") or section.get("client_keyword") or "").strip()
        if kw:
            return f"https://www.semrush.com/analytics/keywordoverview/?q={quote(kw)}&db={semrush_db}"
    if key == "linkedin":
        q = name or domain
        if q:
            return (
                f"https://www.linkedin.com/ad-library/search?accountOwner={quote(q)}"
                f"&countries={meta_country}"
            )
        return f"https://www.linkedin.com/ad-library/search?countries={meta_country}"
    if key == "meta":
        q = name or domain
        if q:
            return (
                "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
                f"&country={meta_country}&q={quote(q)}&search_type=keyword_unordered"
            )
        return (
            "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
            f"&country={meta_country}"
        )
    if key == "google_ads" and domain:
        return f"https://adstransparency.google.com/?region={google_region}&domain={quote(domain)}"
    if key == "similarweb":
        return site or (f"https://{domain}/" if domain else "")
    if key in ("youtube", "instagram", "tiktok"):
        return site
    return site or (f"https://{domain}/" if domain else "")


def _summary_channels(report: dict[str, Any], *, run_meta: Optional[dict[str, Any]] = None) -> str:
    """Tabela resumo no topo: Canal | Dados principal + link (ordem fixa)."""
    # Ordem: Google → Meta → LinkedIn → Marca Semrush → SEO → YT → IG → TT → DFS
    channels: list[tuple[str, str, str]] = [
        ("Google Ads", "google_ads", "ads"),
        ("Meta Ads", "meta", "ads"),
        ("LinkedIn Ads", "linkedin", "count"),
        ("Marca Semrush", "brand", "brand"),
        ("SEO Orgânico", "seo", "seo"),
        ("SimilarWeb", "similarweb", "similarweb"),
        ("YouTube", "youtube", "count"),
        ("Instagram", "instagram", "count"),
        ("TikTok", "tiktok", "count"),
        ("Marca DataForSEO", "brand_dataforseo", "brand_dfs"),
    ]
    unit_fallback = {
        "ads": "ads",
        "count": "",
        "seo": "visits",
        "brand": "visits",
        "brand_dfs": "vol.",
        "similarweb": "visits/mo",
    }
    link_labels = {
        "google_ads": "Library",
        "meta": "Library",
        "linkedin": "Library",
        "brand": "Semrush",
        "seo": "Semrush",
        "similarweb": "Site",
        "youtube": "Profile",
        "instagram": "Profile",
        "tiktok": "Profile",
        "brand_dataforseo": "Semrush",
    }
    market = _report_market(report, run_meta)
    compare_all = bool(report.get("compare_all") or (run_meta or {}).get("compare_all"))
    table_rows: list[list[str]] = []
    for label, key, kind in channels:
        section = report.get(key)
        if not isinstance(section, dict):
            continue
        rows_data = section.get("rows") or []
        if not (
            rows_data
            or section.get("total_fmt")
            or section.get("total_ads_fmt")
            or section.get("total_traffic_fmt")
        ):
            continue
        unit = (section.get("unit") or unit_fallback.get(kind) or "").strip()
        link_label = link_labels.get(key, "Open")

        if compare_all and len(rows_data) > 1:
            parts: list[str] = []
            for r in rows_data:
                name = str(r.get("name") or r.get("domain") or "—")
                if r.get("is_client"):
                    name = f"{name} (you)"
                value = _main_datum(section, kind, r)
                if unit and value not in ("—", "n/d") and unit.lower() not in value.lower():
                    value = f"{value} {unit}"
                url = _summary_channel_url(key, section, r, market=market)
                link = _link_cell(url, link_label)
                line = f"<strong>{_esc(name)}</strong>: {_esc(value)}"
                if link != "—":
                    line = f"{line} · {link}"
                parts.append(line)
            table_rows.append([_esc(label), "<br>".join(parts)])
            continue

        value = _main_datum(section, kind)
        if unit and value not in ("—", "n/d") and unit.lower() not in value.lower():
            value = f"{value} {unit}"
        row = _client_row(section)
        url = _summary_channel_url(key, section, row, market=market)
        link = _link_cell(url, link_label)
        datum = _esc(value)
        if link != "—":
            datum = f"{datum} · {link}"
        table_rows.append([_esc(label), datum])

    if not table_rows:
        return ""
    title = "Resumo — canais (All)" if compare_all else "Resumo — canais"
    return f"""
    <section>
      <h2>{_esc(title)}</h2>
      {_rows_table(["Canal", "Dados principal"], table_rows)}
    </section>
    """


def _section_rank(
    title: str,
    section: Optional[dict[str, Any]],
    kind: str = "ads",
    *,
    link_label: str = "Open",
) -> str:
    if not section:
        return ""
    rows_data = section.get("rows") or []
    if not rows_data and not section.get("insight"):
        return ""

    table_rows: list[list[str]] = []
    if kind == "meta":
        headers = ["#", "Company", "Ads", "Est. spend", "%", "Similarity", "Link"]
        for i, r in enumerate(rows_data, 1):
            name = _esc(r.get("name") or r.get("domain") or "—")
            if r.get("is_client"):
                name += ' <span class="you">you</span>'
            table_rows.append([
                str(i),
                name,
                _esc(r.get("ads_fmt") or r.get("value_fmt") or "0"),
                _esc(r.get("investimento_fmt") or "—"),
                _esc(r.get("pct_fmt") or "—"),
                _esc(r.get("similaridade") or "—"),
                _link_cell(r.get("url"), link_label),
            ])
        hero = _esc(section.get("total_invest_fmt") or section.get("total_fmt") or "—")
        hero_sub = f"{_esc(section.get('total_ads_fmt') or '')} · leader {_esc(section.get('leader') or '—')}"
    elif kind in ("seo", "brand"):
        headers = ["#", "Company", "Traffic", "Growth", "Similarity", "Link"]
        for i, r in enumerate(rows_data, 1):
            name = _esc(r.get("name") or r.get("domain") or "—")
            if r.get("is_client"):
                name += ' <span class="you">you</span>'
            table_rows.append([
                str(i),
                name,
                _esc(r.get("traffic_fmt") or "0"),
                _esc(r.get("growth_fmt") or "n/a"),
                _esc(r.get("similaridade") or "—"),
                _link_cell(r.get("url"), link_label),
            ])
        hero = _esc(section.get("total_traffic_fmt") or "—")
        hero_sub = f"leader {_esc(section.get('leader') or '—')}"
    else:
        headers = ["#", "Company", "Value", "Similarity", "Link"]
        for i, r in enumerate(rows_data, 1):
            name = _esc(r.get("name") or r.get("domain") or "—")
            if r.get("is_client"):
                name += ' <span class="you">you</span>'
            table_rows.append([
                str(i),
                name,
                _esc(r.get("value_fmt") or r.get("ads_fmt") or "0"),
                _esc(r.get("similaridade") or "—"),
                _link_cell(r.get("url"), link_label),
            ])
        hero = _esc(section.get("total_fmt") or section.get("total_invest_fmt") or "—")
        hero_sub = f"{_esc(section.get('unit') or '')} · leader {_esc(section.get('leader') or '—')}"

    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or ""
    return f"""
    <section>
      <h2>{_esc(title)}</h2>
      <div class="hero"><div class="hero-val">{hero}</div><div class="hero-sub">{hero_sub}</div></div>
      {_rows_table(headers, table_rows)}
      {f'<p class="insight"><strong>{_esc(analysis)}</strong><br>{_md_lite(insight)}</p>' if insight else ''}
    </section>
    """


def _section_brand_dfs(section: Optional[dict[str, Any]]) -> str:
    if not section:
        return ""
    rows_data = section.get("rows") or []
    if not rows_data and not section.get("insight"):
        return ""

    def _fmt_vol(v: Any) -> str:
        if v is None:
            return "—"
        try:
            return f"{int(v):,}"
        except Exception:
            return str(v)

    def _fmt_g(v: Any) -> str:
        if not isinstance(v, (int, float)):
            return "n/a"
        return f"{v:+.1f}%"

    headers = ["#", "Company", "Keyword", "Latest", "Vol", "1y", "2y", "3y", "5y", "Δ1y", "Link"]
    table_rows: list[list[str]] = []
    for i, r in enumerate(rows_data, 1):
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        table_rows.append([
            str(i),
            name,
            _esc(r.get("brand_keyword") or "—"),
            _esc(r.get("latest_label") or "—"),
            _esc(r.get("traffic_fmt") or _fmt_vol(r.get("latest_volume") or r.get("traffic"))),
            _esc(_fmt_vol(r.get("volume_1y"))),
            _esc(_fmt_vol(r.get("volume_2y"))),
            _esc(_fmt_vol(r.get("volume_3y"))),
            _esc(_fmt_vol(r.get("volume_5y"))),
            _esc(_fmt_g(r.get("growth_1y_pct"))),
            _link_cell(r.get("url"), "Semrush"),
        ])

    latest = _esc(section.get("latest_label") or "—")
    kw = _esc(section.get("client_keyword") or "—")
    hero = _esc(section.get("total_traffic_fmt") or "—")
    hero_sub = f"keyword {kw} · latest {latest} · DataForSEO US"
    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or ""
    return f"""
    <section>
      <h2>Brand Search — DataForSEO (US)</h2>
      <div class="hero"><div class="hero-val">{hero}</div><div class="hero-sub">{hero_sub}</div></div>
      {_rows_table(headers, table_rows)}
      {f'<p class="insight"><strong>{_esc(analysis)}</strong><br>{_md_lite(insight)}</p>' if insight else ''}
    </section>
    """


def _section_similarweb(section: Optional[dict[str, Any]]) -> str:
    if not section:
        return ""
    rows_data = section.get("rows") or []
    if not rows_data and not section.get("insight"):
        return ""

    # 1) Overview / Engagement
    overview_headers = [
        "#", "Company", "Domain", "Visits", "Snapshot",
        "Bounce", "Pages/visit", "Time on site", "GA?", "Link",
    ]
    overview_rows: list[list[str]] = []
    for i, r in enumerate(rows_data, 1):
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        if r.get("error"):
            name += f' <span class="note">({_esc(r.get("error"))})</span>'
        overview_rows.append([
            str(i),
            name,
            _esc(r.get("domain") or "—"),
            _esc(r.get("traffic_fmt") or "—"),
            _esc(r.get("snapshot_label") or "—"),
            _esc(r.get("bounce_fmt") or "—"),
            _esc(r.get("pages_fmt") or "—"),
            _esc(r.get("time_fmt") or "—"),
            "Yes" if r.get("is_data_from_ga") else "No",
            _link_cell(r.get("url"), "Site"),
        ])

    # 2) Monthly visits — union of month labels (chronological)
    month_keys: list[str] = []
    seen_m: set[str] = set()
    for r in rows_data:
        for m in r.get("visits_monthly") or []:
            d = str(m.get("date") or "")
            if d and d not in seen_m:
                seen_m.add(d)
                month_keys.append(d)
    month_keys.sort()
    month_labels = []
    label_by_date: dict[str, str] = {}
    for d in month_keys:
        for r in rows_data:
            for m in r.get("visits_monthly") or []:
                if str(m.get("date")) == d:
                    label_by_date[d] = str(m.get("label") or d[:7])
                    break
            if d in label_by_date:
                break
        month_labels.append(label_by_date.get(d, d[:7]))

    monthly_html = ""
    if month_keys:
        m_headers = ["Company"] + month_labels
        m_rows: list[list[str]] = []
        for r in rows_data:
            by_date = {
                str(m.get("date")): (m.get("visits_fmt") or "—")
                for m in (r.get("visits_monthly") or [])
            }
            name = _esc(r.get("name") or r.get("domain") or "—")
            if r.get("is_client"):
                name += ' <span class="you">you</span>'
            m_rows.append([name] + [_esc(by_date.get(d, "—")) for d in month_keys])
        monthly_html = f"""
      <h3 style="font-size:14px;margin:18px 0 8px;color:#334155;">Monthly visits</h3>
      {_rows_table(m_headers, m_rows)}
        """

    # 3) Traffic sources
    source_names = [
        "Direct", "Search", "Social", "Referrals", "Paid Referrals", "Mail",
    ]
    extra_sources: list[str] = []
    for r in rows_data:
        for s in r.get("sources") or []:
            n = str(s.get("name") or "")
            if n and n not in source_names and n not in extra_sources:
                extra_sources.append(n)
    all_sources = source_names + extra_sources
    sources_html = ""
    if any(r.get("sources") for r in rows_data):
        s_headers = ["Company"] + all_sources
        s_rows: list[list[str]] = []
        for r in rows_data:
            by_name = {
                str(s.get("name")): (s.get("share_fmt") or "—")
                for s in (r.get("sources") or [])
            }
            name = _esc(r.get("name") or r.get("domain") or "—")
            if r.get("is_client"):
                name += ' <span class="you">you</span>'
            s_rows.append([name] + [_esc(by_name.get(n, "—")) for n in all_sources])
        sources_html = f"""
      <h3 style="font-size:14px;margin:18px 0 8px;color:#334155;">Traffic sources</h3>
      {_rows_table(s_headers, s_rows)}
        """

    # 4) Top countries (long form: Company | Country | Share)
    country_rows: list[list[str]] = []
    for r in rows_data:
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        countries = r.get("countries") or []
        if not countries:
            country_rows.append([name, "—", "—"])
            continue
        for c in countries:
            country_rows.append([
                name,
                _esc(c.get("code") or "—"),
                _esc(c.get("share_fmt") or "—"),
            ])
            name = ""  # group visually under first row
    countries_html = ""
    if any(r.get("countries") for r in rows_data):
        countries_html = f"""
      <h3 style="font-size:14px;margin:18px 0 8px;color:#334155;">Top countries</h3>
      {_rows_table(["Company", "Country", "Share"], country_rows)}
        """

    hero = _esc(section.get("total_traffic_fmt") or "—")
    hero_sub = (
        f"domain {_esc(section.get('client_domain') or '—')} · "
        f"snapshot {_esc(section.get('latest_label') or '—')} · SimilarWeb"
    )
    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or ""
    return f"""
    <section>
      <h2>SimilarWeb Traffic</h2>
      <div class="hero"><div class="hero-val">{hero}</div><div class="hero-sub">{hero_sub}</div></div>
      <h3 style="font-size:14px;margin:0 0 8px;color:#334155;">Overview &amp; engagement</h3>
      {_rows_table(overview_headers, overview_rows)}
      {monthly_html}
      {sources_html}
      {countries_html}
      {f'<p class="insight"><strong>{_esc(analysis)}</strong><br>{_md_lite(insight)}</p>' if insight else ''}
    </section>
    """


def render_report_html(
    report: dict[str, Any],
    *,
    run_meta: Optional[dict[str, Any]] = None,
) -> str:
    meta = run_meta or {}
    client = report.get("client") or meta.get("company") or meta.get("slug") or "Company"
    briefing = report.get("briefing") or {}
    comps = report.get("competitors") or []
    note = report.get("competitors_note") or ""

    comp_rows = []
    for i, c in enumerate(comps, 1):
        name = _esc(c.get("name") or c.get("domain") or "—")
        if c.get("is_client"):
            name += ' <span class="you">you</span>'
        site = (c.get("url") or c.get("site_url") or "").strip()
        if not site and c.get("domain"):
            site = f"https://{c.get('domain')}/"
        comp_rows.append([
            str(i),
            name,
            _esc(c.get("domain") or "—"),
            _esc(c.get("similaridade") or ("Client" if c.get("is_client") else "—")),
            _esc(c.get("nicho") or "—"),
            _link_cell(site, "Site"),
        ])

    market = _report_market(report, meta)
    compare_all = bool(report.get("compare_all") or meta.get("compare_all"))
    summary = _summary_channels(report, run_meta=meta)
    # Mesma ordem do resumo: Google → Meta → LinkedIn → Marca → SEO → YT → IG → TT → DFS
    sections = [
        _section_rank(f"Google Ads Library ({market})", report.get("google_ads"), "meta", link_label="Library"),
        _section_rank(f"Meta Ads ({market})", report.get("meta"), "meta", link_label="Library"),
        _section_rank(f"LinkedIn Ads Library ({market})", report.get("linkedin"), "count", link_label="Library"),
        _section_rank(f"Brand Search Semrush ({market})", report.get("brand"), "brand", link_label="Semrush"),
        _section_rank(f"SEO Organic ({market})", report.get("seo"), "seo", link_label="Semrush"),
        _section_similarweb(report.get("similarweb")),
        _section_rank("YouTube", report.get("youtube"), "count", link_label="Profile"),
        _section_rank("Instagram", report.get("instagram"), "count", link_label="Profile"),
        _section_rank("TikTok", report.get("tiktok"), "count", link_label="Profile"),
        _section_brand_dfs(report.get("brand_dataforseo")),
    ]

    run_line = " · ".join(
        x for x in [
            f"Market: {market}",
            "Mode: All" if compare_all else "",
            _esc(meta.get("id") or ""),
            _esc(meta.get("slug") or ""),
            _esc(meta.get("url") or briefing.get("url") or ""),
        ] if x
    )

    return f"""<!DOCTYPE html>
<html lang="en-US">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Spy USA — {_esc(client)}</title>
<style>
  :root {{ --text:#0f172a; --muted:#64748b; --border:#e2e8f0; --accent:#0f766e; --bg:#f8fafc; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family: "Segoe UI", Georgia, serif; color:var(--text); background:#fff; margin:0; padding:28px 24px 60px; line-height:1.5; }}
  .wrap {{ max-width:960px; margin:0 auto; }}
  h1 {{ font-size:28px; margin:0 0 6px; letter-spacing:-.02em; font-family: Georgia, serif; }}
  h2 {{ font-size:18px; margin:0 0 12px; color:var(--accent); }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:22px; font-family:ui-monospace,monospace; }}
  .card {{ border:1px solid var(--border); border-radius:12px; padding:18px 20px; margin-bottom:18px; background:#fff; }}
  .hero {{ display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; margin-bottom:12px; }}
  .hero-val {{ font-size:28px; font-weight:800; font-family:ui-monospace,monospace; }}
  .hero-sub {{ color:var(--muted); font-size:13px; }}
  .table-wrap {{ overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); vertical-align:top; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }}
  .you {{ color:var(--accent); font-weight:700; font-size:11px; margin-left:4px; }}
  a.ext {{ color:var(--accent); font-weight:700; text-decoration:none; white-space:nowrap; }}
  a.ext:hover {{ text-decoration:underline; }}
  .insight {{ font-size:13px; color:#334155; background:var(--bg); border-radius:8px; padding:12px 14px; }}
  .note {{ color:#b45309; font-size:13px; margin-top:8px; }}
  .toolbar {{ position:sticky; top:0; background:rgba(255,255,255,.92); backdrop-filter:blur(6px); padding:10px 0 14px; margin-bottom:8px; display:flex; gap:8px; flex-wrap:wrap; z-index:5; }}
  .toolbar a, .toolbar button {{ border:1px solid var(--border); background:#fff; border-radius:8px; padding:8px 12px; font:inherit; font-size:13px; font-weight:600; cursor:pointer; text-decoration:none; color:inherit; }}
  .toolbar .primary {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  @media print {{ .toolbar {{ display:none !important; }} body {{ padding:0; }} }}
</style>
</head>
<body>
<div class="wrap">
  <div class="toolbar">
    <button type="button" class="primary" onclick="window.print()">Print / PDF</button>
    <a href="/">New analysis</a>
    {('<a href="/?rerun=' + _esc(meta.get('id')) + '">Refazer</a>') if meta.get('id') else ''}
  </div>
  <h1>Spy USA — {_esc(client)}</h1>
  <div class="sub">{run_line}</div>

  {f'<div class="card">{summary}</div>' if summary else ''}

  <div class="card">
    <h2>Briefing</h2>
    <p><strong>{_esc(briefing.get('client') or client)}</strong>
      {(' · ' + _esc(briefing.get('nicho'))) if briefing.get('nicho') else ''}
      {(' · ' + _esc(briefing.get('escopo'))) if briefing.get('escopo') else ''}
    </p>
    <p>{_md_lite(briefing.get('summary') or '')}</p>
    {f"<p class='sub'>URL: {_esc(briefing.get('url') or meta.get('url') or '')}</p>" if (briefing.get('url') or meta.get('url')) else ''}
  </div>

  <div class="card">
    <h2>Competitors ({_esc(report.get('competitors_count') or max(0, len(comps)-1))})</h2>
    {f"<p class='note'>{_esc(note)}</p>" if note else ''}
    {_rows_table(['#', 'Company', 'Domain', 'Similarity', 'Niche', 'Link'], comp_rows)}
  </div>

  {''.join(f'<div class="card">{s}</div>' for s in sections if s)}
</div>
</body>
</html>
"""


def load_saved_report(run_id: str, runs_dir: Path) -> Optional[dict[str, Any]]:
    path = runs_dir / run_id / "report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
