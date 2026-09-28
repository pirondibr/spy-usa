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


def _main_datum(section: Optional[dict[str, Any]], kind: str) -> str:
    """Valor principal do cliente (ou unico row) para a tabela resumo."""
    if not section:
        return "—"
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
    # count / social / linkedin
    if row:
        return str(row.get("value_fmt") or row.get("ads_fmt") or "0")
    return str(section.get("total_fmt") or "—")


def _summary_channels(report: dict[str, Any]) -> str:
    """Tabela resumo no topo: Canal | Dados principal (ordem fixa)."""
    # Ordem: Google → Meta → LinkedIn → Marca Semrush → SEO → YT → IG → TT → DFS
    channels: list[tuple[str, str, str]] = [
        ("Google Ads", "google_ads", "ads"),
        ("Meta Ads", "meta", "ads"),
        ("LinkedIn Ads", "linkedin", "count"),
        ("Marca Semrush", "brand", "brand"),
        ("SEO Orgânico", "seo", "seo"),
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
    }
    table_rows: list[list[str]] = []
    for label, key, kind in channels:
        section = report.get(key)
        if not isinstance(section, dict):
            continue
        if not (
            section.get("rows")
            or section.get("total_fmt")
            or section.get("total_ads_fmt")
            or section.get("total_traffic_fmt")
        ):
            continue
        value = _main_datum(section, kind)
        unit = (section.get("unit") or unit_fallback.get(kind) or "").strip()
        if unit and value not in ("—", "n/d") and unit.lower() not in value.lower():
            value = f"{value} {unit}"
        table_rows.append([_esc(label), _esc(value)])

    if not table_rows:
        return ""
    return f"""
    <section>
      <h2>Resumo — canais</h2>
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

    summary = _summary_channels(report)
    # Mesma ordem do resumo: Google → Meta → LinkedIn → Marca → SEO → YT → IG → TT → DFS
    sections = [
        _section_rank("Google Ads Library (US)", report.get("google_ads"), "meta", link_label="Library"),
        _section_rank("Meta Ads (US)", report.get("meta"), "meta", link_label="Library"),
        _section_rank("LinkedIn Ads Library (US)", report.get("linkedin"), "count", link_label="Library"),
        _section_rank("Brand Search Semrush (US)", report.get("brand"), "brand", link_label="Semrush"),
        _section_rank("SEO Organic (US)", report.get("seo"), "seo", link_label="Semrush"),
        _section_rank("YouTube", report.get("youtube"), "count", link_label="Profile"),
        _section_rank("Instagram", report.get("instagram"), "count", link_label="Profile"),
        _section_rank("TikTok", report.get("tiktok"), "count", link_label="Profile"),
        _section_brand_dfs(report.get("brand_dataforseo")),
    ]

    run_line = " · ".join(
        x for x in [
            "Market: US",
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
