# -*- coding: utf-8 -*-
"""HTML tables report for Spy USA (no chatbot)."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _md_lite(text: str) -> str:
    raw = _esc(text or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", raw)


_NEUTRAL_CELLS = {"", "—", "-", "n/a", "n/d"}
_NUM_CELL_RE = re.compile(
    r"^[\s$€£+\-−]*(?:R\$\s*)?\d[\d.,]*\s*[%KMBkmb]?"
    r"(?:\s*(?:/mo|visits|views|likes|ads|vol\.?))?\s*$"
)

GROUP_LABELS = {
    "overview": "Overview",
    "paid": "Paid media",
    "search": "Search & traffic",
    "social": "Social",
}
SECTION_GROUPS = {
    "google_ads": "paid",
    "meta": "paid",
    "linkedin": "paid",
    "brand": "search",
    "seo": "search",
    "similarweb": "search",
    "brand_dataforseo": "search",
    "youtube": "social",
    "youtube_influencers": "social",
    "instagram": "social",
    "instagram_influencers": "social",
    "tiktok": "social",
    "reddit": "social",
    "twitter": "social",
    "linkedin_profile": "social",
}


def _plain(cell: Any) -> str:
    return re.sub(r"<[^>]+>", "", str(cell or "")).strip()


def _compact_num(n: Any) -> str:
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return "—"
    v = float(n)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.1f}".rstrip("0").rstrip(".") + suf
    return f"{int(v):,}"


def _rows_table(headers: list[str], rows: list[list[str]]) -> str:
    num_cols: set[int] = set()
    for c, h in enumerate(headers):
        if h == "#":
            continue
        vals = [_plain(r[c]) for r in rows if c < len(r)]
        real = [v for v in vals if v.lower() not in _NEUTRAL_CELLS]
        if real and all(_NUM_CELL_RE.match(v) for v in real):
            num_cols.add(c)

    def _cls(c: int) -> str:
        if c < len(headers) and headers[c] == "#":
            return ' class="idx"'
        return ' class="num"' if c in num_cols else ""

    thead = "".join(f"<th{_cls(i)}>{_esc(h)}</th>" for i, h in enumerate(headers))
    body = []
    for row in rows:
        is_you = any('class="you"' in str(cell) for cell in row)
        tds = "".join(f"<td{_cls(i)}>{cell}</td>" for i, cell in enumerate(row))
        body.append(f'<tr class="is-you">{tds}</tr>' if is_you else f"<tr>{tds}</tr>")
    if not body:
        body.append(f'<tr><td class="empty" colspan="{len(headers)}">No data</td></tr>')
    return (
        f'<div class="table-wrap"><table><thead><tr>{thead}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _top_list(items: list, label_fn, meta_fn, *, limit: int = 5) -> str:
    lis = []
    for t in (items or [])[:limit]:
        full = str(label_fn(t) or "")
        short = full if len(full) <= 64 else full[:61].rstrip() + "…"
        url = str(t.get("url") or "").strip()
        if url:
            label = (
                f'<a class="ext" href="{_esc(url)}" title="{_esc(full)}" target="_blank" '
                f'rel="noopener noreferrer">{_esc(short)}</a>'
            )
        else:
            label = _esc(short)
        meta = meta_fn(t)
        lis.append(f'<li>{label}{f"<span class=meta>{_esc(meta)}</span>" if meta else ""}</li>')
    return f'<ol class="toplist">{"".join(lis)}</ol>' if lis else "—"


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
    if key in (
        "youtube", "instagram", "tiktok",
        "youtube_influencers", "instagram_influencers",
        "reddit", "twitter", "linkedin_profile",
    ):
        return site
    return site or (f"https://{domain}/" if domain else "")


def _summary_channels(report: dict[str, Any], *, run_meta: Optional[dict[str, Any]] = None) -> str:
    """Tabela resumo no topo: Canal | Dados principal + link (ordem fixa)."""
    # Ordem por grupo: Paid → Search & traffic → Social (igual às seções)
    channels: list[tuple[str, str, str]] = [
        ("Google Ads", "google_ads", "ads"),
        ("Meta Ads", "meta", "ads"),
        ("LinkedIn Ads", "linkedin", "count"),
        ("Marca Semrush", "brand", "brand"),
        ("SEO Orgânico", "seo", "seo"),
        ("SimilarWeb", "similarweb", "similarweb"),
        ("Marca DataForSEO", "brand_dataforseo", "brand_dfs"),
        ("YouTube", "youtube", "count"),
        ("YouTube Influencers", "youtube_influencers", "seo"),
        ("Instagram", "instagram", "count"),
        ("Instagram Influencers", "instagram_influencers", "seo"),
        ("TikTok", "tiktok", "count"),
        ("Reddit", "reddit", "seo"),
        ("Twitter / X", "twitter", "seo"),
        ("LinkedIn Profile", "linkedin_profile", "seo"),
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
        "youtube_influencers": "Search",
        "instagram": "Profile",
        "instagram_influencers": "Profile",
        "tiktok": "Profile",
        "brand_dataforseo": "Semrush",
        "reddit": "Search",
        "twitter": "Profile",
        "linkedin_profile": "Profile",
    }
    market = _report_market(report, run_meta)
    compare_all = bool(report.get("compare_all") or (run_meta or {}).get("compare_all"))

    def _unit_for(value: str, unit: str) -> str:
        if not unit or value in ("—", "n/d") or unit.lower() in value.lower():
            return ""
        return unit

    tiles: list[str] = []
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
        group = SECTION_GROUPS.get(key, "overview")
        anchor = f"#sec-{key}"

        if compare_all and len(rows_data) > 1:
            lines: list[str] = []
            for r in rows_data:
                name = str(r.get("name") or r.get("domain") or "—")
                value = _main_datum(section, kind, r)
                u = _unit_for(value, unit)
                url = _summary_channel_url(key, section, r, market=market)
                you = ' <span class="you">you</span>' if r.get("is_client") else ""
                link = _link_cell(url, "↗")
                lines.append(
                    f'<li><span class="kpi-name">{_esc(name)}{you}</span>'
                    f'<span class="kpi-mini">{_esc(value)}{(" " + _esc(u)) if u else ""}'
                    f'{(" " + link) if link != "—" else ""}</span></li>'
                )
            tiles.append(
                f'<div class="kpi kpi-multi" data-group="{group}">'
                f'<a class="kpi-label" href="{anchor}">{_esc(label)}</a>'
                f'<ul class="kpi-list">{"".join(lines)}</ul></div>'
            )
            continue

        value = _main_datum(section, kind)
        u = _unit_for(value, unit)
        row = _client_row(section)
        url = _summary_channel_url(key, section, row, market=market)
        link = _link_cell(url, f"{link_label} ↗")
        tiles.append(
            f'<div class="kpi" data-group="{group}">'
            f'<a class="kpi-label" href="{anchor}">{_esc(label)}</a>'
            f'<div class="kpi-val">{_esc(value)}'
            f'{f"<span class=kpi-unit>{_esc(u)}</span>" if u else ""}</div>'
            f'{f"<div class=kpi-link>{link}</div>" if link != "—" else ""}'
            f"</div>"
        )

    if not tiles:
        return ""
    title = "Resumo — canais (All)" if compare_all else "Resumo — canais"
    return f"""
    <section>
      <h2>{_esc(title)}</h2>
      <div class="kpis">{''.join(tiles)}</div>
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


def _section_instagram_influencers(section: Optional[dict[str, Any]]) -> str:
    if not section:
        return ""
    rows_data = section.get("rows") or []
    if not rows_data and not section.get("insight"):
        return ""
    headers = [
        "#", "Company", "Influencers", "Total likes",
        "Own posts", "Influencer posts",
        "Top likes Page", "Top Likes Influencers", "Profile",
    ]

    def _top_likes_cell(items: list) -> str:
        return _top_list(
            items,
            lambda t: f"@{t.get('username')}" if t.get("username") else "post",
            lambda t: f"{_compact_num(t.get('likes'))} likes",
        )

    table_rows: list[list[str]] = []
    for i, r in enumerate(rows_data, 1):
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        top_page = r.get("top5_page") or []
        top_inf = r.get("top5_influencers") or []
        # Back-compat: older runs only have combined top5
        if not top_page and not top_inf and r.get("top5"):
            for t in r.get("top5") or []:
                (top_inf if t.get("is_influencer") else top_page).append(t)
        handles = ", ".join(f"@{_esc(h)}" for h in (r.get("influencer_handles") or [])[:8])
        table_rows.append([
            str(i),
            name,
            f"{_esc(str(r.get('total_influencers') or 0))}"
            + (f"<div class='muted'>{handles}</div>" if handles else ""),
            _esc(r.get("total_likes_fmt") or "0"),
            _esc(str(r.get("own_posts") or 0)),
            _esc(str(r.get("influencer_posts") or 0)),
            _top_likes_cell(top_page),
            _top_likes_cell(top_inf),
            _link_cell(r.get("url"), f"@{_esc(r.get('handle') or 'IG')}"),
        ])
    usage = section.get("usage_total") or {}
    hero = _esc(section.get("total_traffic_fmt") or "—")
    hero_sub = (
        f"1st page likes · fetch urls {_esc(str(usage.get('fetch_urls', '—')))} · "
        f"leader {_esc(section.get('leader') or '—')}"
    )
    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or "Instagram Influencers"
    return f"""
    <section>
      <h2>Instagram Influencers</h2>
      <div class="hero"><div class="hero-val">{hero}</div><div class="hero-sub">{hero_sub}</div></div>
      {_rows_table(headers, table_rows)}
      {f'<p class="insight"><strong>{_esc(analysis)}</strong><br>{_md_lite(insight)}</p>' if insight else ''}
    </section>
    """


def _section_reddit(section: Optional[dict[str, Any]]) -> str:
    if not section:
        return ""
    rows_data = section.get("rows") or []
    if not rows_data and not section.get("insight"):
        return ""
    headers = [
        "#", "Company", "Posts (1st page)", "Comments", "Google total",
        "Top posts", "Search",
    ]

    def _top_posts_cell(items: list) -> str:
        return _top_list(
            items,
            lambda t: t.get("title") or "post",
            lambda t: " · ".join(
                x for x in [
                    f"r/{t['subreddit']}" if t.get("subreddit") else "",
                    f"{_compact_num(t.get('comments'))} comments"
                    if t.get("comments") is not None else "",
                ] if x
            ),
        )

    table_rows: list[list[str]] = []
    for i, r in enumerate(rows_data, 1):
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        table_rows.append([
            str(i),
            name,
            _esc(str(r.get("posts_first_page") or 0)),
            _esc(r.get("total_comments_fmt") or r.get("traffic_fmt") or "0"),
            _esc(r.get("total_results_fmt") or "n/d"),
            _top_posts_cell(list(r.get("top_posts") or [])),
            _link_cell(r.get("url"), "Google"),
        ])
    usage = section.get("usage_total") or {}
    hero = _esc(section.get("total_traffic_fmt") or "—")
    hero_sub = (
        f"comments on 1st page · fetch urls {_esc(str(usage.get('fetch_urls', '—')))} · "
        f"SB credits {_esc(str(usage.get('scrapingbee_credits', '—')))} · "
        f"leader {_esc(section.get('leader') or '—')}"
    )
    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or "Reddit"
    return f"""
    <section>
      <h2>Reddit</h2>
      <div class="hero"><div class="hero-val">{hero}</div><div class="hero-sub">{hero_sub}</div></div>
      {_rows_table(headers, table_rows)}
      {f'<p class="insight"><strong>{_esc(analysis)}</strong><br>{_md_lite(insight)}</p>' if insight else ''}
    </section>
    """


def _section_twitter(section: Optional[dict[str, Any]]) -> str:
    if not section:
        return ""
    rows_data = section.get("rows") or []
    if not rows_data and not section.get("insight"):
        return ""
    headers = ["#", "Company", "Handle", "Followers", "Source", "Profile", "Search"]
    table_rows: list[list[str]] = []
    for i, r in enumerate(rows_data, 1):
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        handle = str(r.get("handle") or "").lstrip("@")
        handle_label = f"@{handle}" if handle else "Profile"
        table_rows.append([
            str(i),
            name,
            _esc(f"@{handle}") if handle else "—",
            _esc(r.get("followers_fmt") or r.get("traffic_fmt") or "—"),
            _esc(r.get("followers_source") or "—"),
            _link_cell(r.get("url"), handle_label),
            _link_cell(r.get("search_url"), "Google"),
        ])
    hero = _esc(section.get("total_traffic_fmt") or "—")
    hero_sub = f"followers · leader {_esc(section.get('leader') or '—')}"
    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or "Twitter / X"
    return f"""
    <section>
      <h2>Twitter / X</h2>
      <div class="hero"><div class="hero-val">{hero}</div><div class="hero-sub">{hero_sub}</div></div>
      {_rows_table(headers, table_rows)}
      {f'<p class="insight"><strong>{_esc(analysis)}</strong><br>{_md_lite(insight)}</p>' if insight else ''}
    </section>
    """


def _section_linkedin_profile(section: Optional[dict[str, Any]]) -> str:
    if not section:
        return ""
    rows_data = section.get("rows") or []
    if not rows_data and not section.get("insight"):
        return ""
    headers = ["#", "Company", "Kind", "Followers", "Title", "Profile", "Search"]
    table_rows: list[list[str]] = []
    for i, r in enumerate(rows_data, 1):
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        title = _esc(r.get("title") or "—")
        if r.get("snippet"):
            title += f'<div class="muted">{_esc(str(r.get("snippet"))[:120])}</div>'
        table_rows.append([
            str(i),
            name,
            _esc(r.get("kind") or "—"),
            _esc(r.get("followers_fmt") or r.get("traffic_fmt") or "—"),
            title,
            _link_cell(r.get("url"), "LinkedIn"),
            _link_cell(r.get("search_url"), "Google"),
        ])
    hero = _esc(section.get("total_traffic_fmt") or "—")
    hero_sub = f"followers · leader {_esc(section.get('leader') or '—')}"
    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or "LinkedIn Profile"
    return f"""
    <section>
      <h2>LinkedIn Profile</h2>
      <div class="hero"><div class="hero-val">{hero}</div><div class="hero-sub">{hero_sub}</div></div>
      {_rows_table(headers, table_rows)}
      {f'<p class="insight"><strong>{_esc(analysis)}</strong><br>{_md_lite(insight)}</p>' if insight else ''}
    </section>
    """


def _section_youtube_influencers(section: Optional[dict[str, Any]]) -> str:
    if not section:
        return ""
    rows_data = section.get("rows") or []
    if not rows_data and not section.get("insight"):
        return ""
    headers = [
        "#", "Company", "Official views", "Unofficial views",
        "30d", "6m", "1y+", "About #",
        "Top links Official", "Top links Unofficial", "Search",
    ]

    def _top_links_cell(items: list) -> str:
        def _meta(t: dict) -> str:
            bits = [f"{_compact_num(t.get('views'))} views"]
            if t.get("upload_age"):
                bits.append(str(t["upload_age"]))
            if t.get("channel_name"):
                bits.append(str(t["channel_name"]))
            return " · ".join(bits)

        return _top_list(items, lambda t: t.get("title") or "video", _meta)

    table_rows: list[list[str]] = []
    for i, r in enumerate(rows_data, 1):
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        top_off = list(r.get("top5_official") or [])
        top_unoff = list(r.get("top5_unofficial") or [])
        # Back-compat: older runs only have combined top5
        if not top_off and not top_unoff and r.get("top5"):
            for t in r.get("top5") or []:
                (top_off if t.get("is_official") else top_unoff).append(t)
        table_rows.append([
            str(i),
            name,
            _esc(r.get("views_official_fmt") or "0"),
            _esc(r.get("views_unofficial_fmt") or "0"),
            _esc(r.get("views_30d_fmt") or "0"),
            _esc(r.get("views_6m_fmt") or "0"),
            _esc(r.get("views_1y_plus_fmt") or "0"),
            _esc(str(r.get("about_count") or 0)),
            _top_links_cell(top_off),
            _top_links_cell(top_unoff),
            _link_cell(r.get("url"), "YouTube"),
        ])
    usage = section.get("usage_total") or {}
    hero = _esc(section.get("total_traffic_fmt") or "—")
    hero_sub = (
        f"product-relevant 1st page · ScrapingBee credits="
        f"{_esc(str(usage.get('scrapingbee_credits', usage.get('estimated_usd', '—'))))} "
        f"· leader {_esc(section.get('leader') or '—')}"
    )
    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or "YouTube Influencers"
    return f"""
    <section>
      <h2>YouTube Influencers</h2>
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
      <h3 class="subhead">Monthly visits</h3>
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
      <h3 class="subhead">Traffic sources</h3>
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
      <h3 class="subhead">Top countries</h3>
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
      <h3 class="subhead first">Overview &amp; engagement</h3>
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
    # Mesma ordem do resumo (agrupado): Paid → Search & traffic → Social
    blocks: list[tuple[str, str, str]] = [
        ("google_ads", "Google Ads", _section_rank(
            f"Google Ads Library ({market})", report.get("google_ads"), "meta", link_label="Library")),
        ("meta", "Meta Ads", _section_rank(
            f"Meta Ads ({market})", report.get("meta"), "meta", link_label="Library")),
        ("linkedin", "LinkedIn Ads", _section_rank(
            f"LinkedIn Ads Library ({market})", report.get("linkedin"), "count", link_label="Library")),
        ("brand", "Brand Semrush", _section_rank(
            f"Brand Search Semrush ({market})", report.get("brand"), "brand", link_label="Semrush")),
        ("seo", "SEO Organic", _section_rank(
            f"SEO Organic ({market})", report.get("seo"), "seo", link_label="Semrush")),
        ("similarweb", "SimilarWeb", _section_similarweb(report.get("similarweb"))),
        ("brand_dataforseo", "Brand DataForSEO", _section_brand_dfs(report.get("brand_dataforseo"))),
        ("youtube", "YouTube", _section_rank(
            "YouTube", report.get("youtube"), "count", link_label="Profile")),
        ("youtube_influencers", "YouTube Influencers",
         _section_youtube_influencers(report.get("youtube_influencers"))),
        ("instagram", "Instagram", _section_rank(
            "Instagram", report.get("instagram"), "count", link_label="Profile")),
        ("instagram_influencers", "Instagram Influencers",
         _section_instagram_influencers(report.get("instagram_influencers"))),
        ("tiktok", "TikTok", _section_rank(
            "TikTok", report.get("tiktok"), "count", link_label="Profile")),
        ("reddit", "Reddit", _section_reddit(report.get("reddit"))),
        ("twitter", "Twitter / X", _section_twitter(report.get("twitter"))),
        ("linkedin_profile", "LinkedIn Profile",
         _section_linkedin_profile(report.get("linkedin_profile"))),
    ]
    blocks = [b for b in blocks if b[2]]

    def _card(key: str, body: str, group: str) -> str:
        return (
            f'<div class="card" id="sec-{key}" data-group="{group}">'
            f'<div class="eyebrow">{_esc(GROUP_LABELS[group])}</div>{body}</div>'
        )

    toc: dict[str, list[str]] = {g: [] for g in GROUP_LABELS}
    if summary:
        toc["overview"].append('<a href="#sec-summary">Resumo</a>')
    toc["overview"].append('<a href="#sec-briefing">Briefing</a>')
    toc["overview"].append('<a href="#sec-competitors">Competitors</a>')
    for key, label, _ in blocks:
        toc[SECTION_GROUPS.get(key, "overview")].append(f'<a href="#sec-{key}">{_esc(label)}</a>')
    toc_html = "".join(
        f'<div class="toc-group" data-group="{g}">'
        f'<div class="toc-title">{_esc(GROUP_LABELS[g])}</div>{"".join(links)}</div>'
        for g, links in toc.items() if links
    )

    site_url = str(meta.get("url") or briefing.get("url") or "").strip()
    site_host = urlparse(site_url if "://" in site_url else f"https://{site_url}").netloc if site_url else ""
    site_host = site_host[4:] if site_host.startswith("www.") else site_host
    chips = [f'<span class="chip accent">Market {_esc(market)}</span>']
    if compare_all:
        chips.append('<span class="chip">Mode: All</span>')
    if meta.get("site_only") and not compare_all:
        chips.append('<span class="chip">Sem concorrentes</span>')
    mast_meta = []
    if site_url:
        mast_meta.append(_link_cell(site_url, f"{site_host or site_url} ↗"))
    if meta.get("id"):
        mast_meta.append(f"<span>Run <code>{_esc(meta.get('id'))}</code></span>")

    brief_chips = "".join(
        f'<span class="chip">{_esc(v)}</span>'
        for v in (briefing.get("nicho"), briefing.get("escopo")) if v
    )
    comp_count = report.get("competitors_count") or max(0, len(comps) - 1)
    rerun = (
        f'<a href="/?rerun={_esc(meta.get("id"))}">Refazer</a>' if meta.get("id") else ""
    )
    cards = "".join(_card(k, body, SECTION_GROUPS.get(k, "overview")) for k, _, body in blocks)

    return f"""<!DOCTYPE html>
<html lang="en-US">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Spy USA — {_esc(client)}</title>
<style>{_REPORT_CSS}</style>
</head>
<body>
<header class="topbar">
  <div class="topbar-inner">
    <div class="brand"><span class="logo">S</span>Spy USA<span class="crumb">/ {_esc(client)}</span></div>
    <div class="actions">
      <a href="/">New analysis</a>
      {rerun}
      <button type="button" class="primary" onclick="window.print()">Print / PDF</button>
    </div>
  </div>
</header>
<div class="layout">
  <aside class="toc"><nav>{toc_html}</nav></aside>
  <main>
    <section class="masthead">
      <div class="chips">{''.join(chips)}</div>
      <h1>{_esc(client)}</h1>
      <div class="mast-meta">{' · '.join(mast_meta)}</div>
    </section>

    {f'<div class="card" id="sec-summary" data-group="overview">{summary}</div>' if summary else ''}

    <div class="card brief" id="sec-briefing" data-group="overview">
      <h2>Briefing</h2>
      <p class="brief-lead"><strong>{_esc(briefing.get('client') or client)}</strong></p>
      {f'<div class="chips">{brief_chips}</div>' if brief_chips else ''}
      <p>{_md_lite(briefing.get('summary') or '')}</p>
    </div>

    <div class="card" id="sec-competitors" data-group="overview">
      <h2>Competitors <span class="count">{_esc(comp_count)}</span></h2>
      {f"<p class='note'>{_esc(note)}</p>" if note else ''}
      {_rows_table(['#', 'Company', 'Domain', 'Similarity', 'Niche', 'Link'], comp_rows)}
    </div>

    {cards}
    <footer class="foot">Spy USA{(' · run ' + _esc(meta.get('id'))) if meta.get('id') else ''}</footer>
  </main>
</div>
<script>{_REPORT_JS}</script>
</body>
</html>
"""


_REPORT_CSS = """
:root{
  --text:#0f172a;--muted:#64748b;--soft:#94a3b8;--border:#e2e8f0;--line:#eef2f6;
  --bg:#f4f6fa;--card:#fff;--accent:#0f766e;--accent-soft:#ecfdf5;
  --paid:#4f46e5;--search:#0f766e;--social:#db2777;--overview:#475569;
  --radius:14px;--shadow:0 1px 2px rgba(15,23,42,.04),0 6px 20px rgba(15,23,42,.05);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:76px}
body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--text);background:var(--bg);line-height:1.5;font-size:14px;-webkit-font-smoothing:antialiased}
[data-group=paid]{--group:var(--paid)}
[data-group=search]{--group:var(--search)}
[data-group=social]{--group:var(--social)}
[data-group=overview]{--group:var(--overview)}

.topbar{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.88);
  backdrop-filter:saturate(180%) blur(10px);-webkit-backdrop-filter:saturate(180%) blur(10px);border-bottom:1px solid var(--border)}
.topbar-inner{max-width:1320px;margin:0 auto;padding:10px 24px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:-.01em;min-width:0;white-space:nowrap}
.logo{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,#0f766e,#4f46e5);color:#fff;
  display:grid;place-items:center;font-size:14px;font-weight:800;flex-shrink:0}
.crumb{color:var(--muted);font-weight:500;overflow:hidden;text-overflow:ellipsis}
.actions{display:flex;gap:8px;flex-shrink:0}
.actions a,.actions button{border:1px solid var(--border);background:#fff;border-radius:9px;padding:7px 12px;font:inherit;
  font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;color:var(--text);transition:background .15s,border-color .15s}
.actions a:hover,.actions button:hover{background:#f8fafc;border-color:#cbd5e1}
.actions .primary{background:var(--text);color:#fff;border-color:var(--text)}
.actions .primary:hover{background:#1e293b;border-color:#1e293b}

.layout{max-width:1320px;margin:0 auto;padding:24px;display:grid;grid-template-columns:210px minmax(0,1fr);gap:28px;align-items:start}
.toc{position:sticky;top:76px;max-height:calc(100vh - 96px);overflow:auto;padding-right:4px}
.toc-group{margin-bottom:18px}
.toc-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--group);margin:0 0 6px 12px}
.toc a{display:block;padding:6px 10px;border-radius:8px;text-decoration:none;color:var(--muted);font-size:13px;font-weight:500;
  border-left:2px solid transparent;transition:background .15s,color .15s}
.toc a:hover{background:#fff;color:var(--text)}
.toc a.active{background:#fff;color:var(--text);font-weight:600;border-left-color:var(--group);box-shadow:var(--shadow)}
main{min-width:0}

.masthead{padding:6px 2px 22px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.chip{display:inline-flex;align-items:center;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;
  background:#fff;border:1px solid var(--border);color:var(--muted)}
.chip.accent{background:var(--accent-soft);border-color:#a7f3d0;color:var(--accent)}
h1{font-size:34px;line-height:1.15;margin:0 0 8px;letter-spacing:-.025em;font-weight:800}
.mast-meta{color:var(--muted);font-size:13px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;background:#fff;border:1px solid var(--border);
  padding:1px 6px;border-radius:6px}

.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:22px 24px;margin-bottom:20px;
  box-shadow:var(--shadow);position:relative;overflow:hidden}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--group)}
.eyebrow{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--group);margin-bottom:4px}
h2{font-size:19px;margin:0 0 14px;letter-spacing:-.015em;font-weight:750}
h2 .count{display:inline-block;margin-left:6px;padding:0 8px;border-radius:999px;background:#f1f5f9;color:var(--muted);
  font-size:12px;font-weight:700;vertical-align:3px}
.subhead{font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:22px 0 8px}
.subhead.first{margin-top:4px}

.hero{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin:0 0 16px;padding:14px 16px;border-radius:12px;
  background:linear-gradient(180deg,#f8fafc,#fff);border:1px solid var(--border)}
.hero-val{font-size:30px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.hero-sub{color:var(--muted);font-size:13px}

.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
.kpi{border:1px solid var(--border);border-radius:12px;padding:14px 14px 12px;background:#fff;display:flex;flex-direction:column;gap:6px;
  box-shadow:inset 0 3px 0 var(--group);transition:transform .15s,box-shadow .15s,border-color .15s}
.kpi:hover{transform:translateY(-1px);border-color:#cbd5e1;box-shadow:inset 0 3px 0 var(--group),var(--shadow)}
.kpi-label{font-size:12px;font-weight:600;color:var(--muted);text-decoration:none}
.kpi-label:hover{color:var(--text)}
.kpi-val{font-size:24px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.15}
.kpi-unit{font-size:12px;font-weight:600;color:var(--soft);margin-left:5px;letter-spacing:0}
.kpi-link{margin-top:auto;font-size:12px}
.kpi-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
.kpi-list li{display:flex;justify-content:space-between;gap:8px;font-size:12.5px}
.kpi-name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kpi-mini{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--muted)}
@media (min-width:640px){.kpi-multi{grid-column:span 2}}

.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:12px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:13px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
thead th{background:#f8fafc;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  white-space:nowrap;border-bottom:1px solid var(--border)}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:#fafbfc}
tr.is-you td{background:var(--accent-soft)}
tr.is-you:hover td{background:#d1fae5}
tr.is-you td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
th.idx,td.idx{width:36px;color:var(--soft);font-variant-numeric:tabular-nums}
td.empty{color:var(--soft);text-align:center;padding:22px}
.you{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:999px;background:var(--accent);color:#fff;font-size:10px;
  font-weight:700;text-transform:uppercase;letter-spacing:.04em;vertical-align:1px}
a.ext{color:var(--accent);font-weight:600;text-decoration:none;white-space:nowrap}
a.ext:hover{text-decoration:underline}

.toplist{margin:0;padding:0;list-style:none;counter-reset:t;display:flex;flex-direction:column;gap:7px;min-width:230px}
.toplist li{counter-increment:t;display:grid;grid-template-columns:16px 1fr;column-gap:6px;line-height:1.35}
.toplist li::before{content:counter(t);grid-row:span 2;font-size:11px;font-weight:700;color:var(--soft);padding-top:1px}
.toplist a.ext{white-space:normal}
.toplist .meta{grid-column:2;font-size:11.5px;color:var(--muted)}
.muted{color:var(--muted);font-size:12px;margin-top:2px}

.insight{margin:16px 0 0;font-size:13.5px;color:#334155;background:#f8fafc;border:1px solid var(--border);
  border-left:3px solid var(--group);border-radius:10px;padding:12px 14px}
.insight strong{color:var(--text)}
.note{color:#b45309;font-size:13px}
p.note{margin:0 0 12px;background:#fffbeb;border:1px solid #fde68a;padding:8px 12px;border-radius:8px}
.brief p{margin:0 0 10px}
.brief-lead{font-size:15px}
.foot{color:var(--soft);font-size:12px;text-align:center;padding:12px 0 40px}

@media (max-width:1024px){
  .layout{grid-template-columns:1fr;padding:0 16px 16px;gap:0}
  .toc{top:53px;z-index:10;max-height:none;overflow-x:auto;overflow-y:hidden;background:var(--bg);
    margin:0 -16px 16px;padding:10px 16px;border-bottom:1px solid var(--border)}
  .toc nav{display:flex;gap:6px;white-space:nowrap}
  .toc-group{display:contents}
  .toc-title{display:none}
  .toc a{display:inline-block;border:1px solid var(--border);border-radius:999px;background:#fff;padding:5px 12px}
  .toc a.active{box-shadow:none;border-color:var(--group);color:var(--group)}
  h1{font-size:26px}
  .card{padding:18px}
  .topbar-inner{padding:10px 16px}
}
@media (max-width:560px){
  .crumb{display:none}
  .actions a{display:none}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .kpi{padding:12px 12px 10px}
  .kpi-val{font-size:20px}
  .kpi-multi{grid-column:span 2}
  .card{padding:16px 14px}
  .hero-val{font-size:24px}
}
@media print{
  .topbar,.toc{display:none!important}
  .layout{display:block;padding:0}
  body{background:#fff}
  .card{box-shadow:none}
  .kpi,tr{break-inside:avoid}
  .kpi:hover{transform:none}
}
"""

_REPORT_JS = """
(function(){
  var links=[].slice.call(document.querySelectorAll('.toc a[href^="#"]'));
  if(!links.length||!('IntersectionObserver' in window))return;
  var byId={};
  links.forEach(function(a){byId[a.getAttribute('href').slice(1)]=a;});
  var obs=new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(!e.isIntersecting)return;
      links.forEach(function(l){l.classList.remove('active');});
      var a=byId[e.target.id];
      if(!a)return;
      a.classList.add('active');
      if(window.innerWidth<=1024){a.scrollIntoView({block:'nearest',inline:'center'});}
    });
  },{rootMargin:'-15% 0px -75% 0px'});
  Object.keys(byId).forEach(function(id){var el=document.getElementById(id);if(el)obs.observe(el);});
})();
"""


def load_saved_report(run_id: str, runs_dir: Path) -> Optional[dict[str, Any]]:
    path = runs_dir / run_id / "report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
