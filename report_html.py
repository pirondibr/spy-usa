# -*- coding: utf-8 -*-
"""HTML tables report for Spy USA (no chatbot)."""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _brand_fp_domains(comps: list[dict[str, Any]], report: dict[str, Any]) -> set[str]:
    stored = {
        str(c.get("domain") or "").strip().lower()
        for c in comps
        if c.get("brand_false_positive")
    }
    stored.discard("")
    if report.get("brand_fp_checked") or stored:
        return stored
    vendor = Path(__file__).resolve().parent / "scripts" / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        from brand_false_positive import heuristic_false_positive_domains  # noqa: E402
        return heuristic_false_positive_domains(comps)
    except Exception:
        return set()


def _md_lite(text: str) -> str:
    raw = _esc(text or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", raw)


_NEUTRAL_CELLS = {"", "—", "-", "n/a", "n/d"}


def _fonte_cell(raw: Any) -> str:
    text = "" if raw is None else str(raw).strip()
    if not text or text in _NEUTRAL_CELLS:
        return "—"
    parts = [p.strip() for p in re.split(r"[,+]", text) if p.strip()]
    if not parts:
        return "—"
    return "".join(f'<span class="chip">{_esc(p)}</span>' for p in parts)


def _clip_cell(raw: Any, *, limit: int = 48) -> str:
    text = "" if raw is None else str(raw).strip()
    if not text or text in _NEUTRAL_CELLS:
        return "—"
    if len(text) <= limit:
        return _esc(text)
    short = text[: max(1, limit - 1)].rstrip() + "…"
    return f'<span class="clip" title="{_esc(text)}">{_esc(short)}</span>'


def _sort_num(value: Any) -> str:
    if value is None or value == "" or value == "—":
        return ""
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return ""


def _sort_sim(comp: dict[str, Any]) -> str:
    if comp.get("is_client"):
        return "4"
    sim = str(comp.get("similaridade") or "").strip().lower().replace("é", "e")
    return {"alto": "3", "medio": "2", "baixo": "1"}.get(sim, "0")


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


def _fmt_vol(v: Any) -> str:
    if v is None or v == "":
        return "—"
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_brand_vol(v: Any) -> str:
    """Compact brand volume: 165000 → 165k, 24900000 → 24.9m. Full number on hover."""
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return _esc(str(v))
    absn = abs(n)
    if absn >= 1_000_000:
        compact = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "m"
    elif absn >= 1_000:
        compact = f"{n / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    else:
        compact = f"{int(n):,}"
    full = f"{int(n):,}"
    if compact == full:
        return _esc(compact)
    return f'<span title="{_esc(full)}">{_esc(compact)}</span>'


def _row_title(c: dict[str, Any]) -> str:
    return str(c.get("title") or c.get("site_title") or c.get("page_title") or "").strip()


def _fmt_growth(v: Any) -> str:
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    sign = "+" if n > 0 else ""
    if abs(n) >= 100:
        return f"{sign}{n:.0f}%"
    return f"{sign}{n:.1f}%"


def _growth_pct(newer: Any, older: Any) -> Optional[float]:
    try:
        n = float(newer)
        o = float(older)
    except (TypeError, ValueError):
        return None
    if o == 0:
        return None
    return (n - o) / o * 100.0


def _brand_vol_text(v: Any) -> tuple[str, str]:
    """Return (compact, full) brand volume strings."""
    if v is None or v == "":
        return "—", ""
    try:
        n = float(v)
    except (TypeError, ValueError):
        s = str(v)
        return s, s
    absn = abs(n)
    full = f"{int(n):,}"
    if absn >= 1_000_000:
        compact = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "m"
    elif absn >= 1_000:
        compact = f"{n / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    else:
        compact = full
    return compact, full


def _brand_seq_cell(c: dict[str, Any]) -> str:
    parts = []
    tips = []
    labels = ("Aug 2026", "Aug 2025", "Aug 2024")
    vals = (c.get("brand_aug_2026"), c.get("brand_aug_2025"), c.get("brand_aug_2024"))
    for lab, val in zip(labels, vals):
        compact, full = _brand_vol_text(val)
        parts.append(compact)
        tips.append(f"{lab}: {full or compact}")
    if all(p == "—" for p in parts):
        return "—"
    kw = str(c.get("brand_keyword") or "").strip()
    title = "Brand search volume · " + " · ".join(tips)
    if kw:
        title += f" · keyword {kw}"
    inner = '<span class="seq-sep">></span>'.join(
        f'<span class="seq-n">{_esc(p)}</span>' for p in parts
    )
    return f'<span class="brand-seq" title="{_esc(title)}">{inner}</span>'


def _growth_chip(n: Optional[float]) -> str:
    if n is None:
        return '<span class="growth-flat">—</span>'
    if n > 0:
        cls = "growth-up"
    elif n < 0:
        cls = "growth-down"
    else:
        cls = "growth-flat"
    return f'<span class="{cls}">{_esc(_fmt_growth(n))}</span>'


def _growth_seq_cell(c: dict[str, Any]) -> str:
    total = c.get("brand_growth_26_24")
    try:
        total_n = float(total) if total is not None and total != "" else None
    except (TypeError, ValueError):
        total_n = None
    if total_n is None:
        total_n = _growth_pct(c.get("brand_aug_2026"), c.get("brand_aug_2024"))
    y1 = _growth_pct(c.get("brand_aug_2026"), c.get("brand_aug_2025"))
    if total_n is None and y1 is None:
        return "—"
    title = "Total Aug 2026 vs 2024 > 1 year Aug 2026 vs 2025"
    return (
        f'<span class="growth-seq" title="{_esc(title)}">'
        f"{_growth_chip(total_n)}"
        f'<span class="seq-sep">></span>'
        f"{_growth_chip(y1)}"
        f"</span>"
    )


def _rows_table(
    headers: list[str],
    rows: list[list[str]],
    *,
    page_size: int = 0,
    col_keys: Optional[list[str]] = None,
    compact_keys: Optional[set[str]] = None,
    sort_rows: Optional[list[list[Any]]] = None,
    interactive: bool = False,
    row_attrs: Optional[list[dict[str, Any]]] = None,
) -> str:
    num_cols: set[int] = set()
    for c, h in enumerate(headers):
        if h == "#":
            continue
        vals = [_plain(r[c]) for r in rows if c < len(r)]
        real = [v for v in vals if v.lower() not in _NEUTRAL_CELLS]
        if real and all(_NUM_CELL_RE.match(v) for v in real):
            num_cols.add(c)

    def _attr(c: int, *, header: bool = False) -> str:
        classes: list[str] = []
        extras: list[str] = []
        if c < len(headers) and headers[c] == "#":
            classes.append("idx")
        if c < len(headers) and str(headers[c]).lower() == "motivo":
            classes.append("motivo")
        if c in num_cols:
            classes.append("num")
        key = ""
        if col_keys and c < len(col_keys):
            key = str(col_keys[c] or "").strip()
        if key:
            extras.append(f'data-col="{_esc(key)}"')
            if compact_keys and key not in compact_keys:
                extras.append('data-extra="1"')
            if key in ("brand", "growth"):
                classes.append("num")
        if header and interactive and key not in ("brand", "growth"):
            extras.append(f'title="Clique para ordenar · × oculta {_esc(headers[c])}"')
        if header and interactive:
            classes.append("sortable")
        if key in ("idx", "company"):
            classes.append("col-frozen")
        cls = f' class="{" ".join(classes)}"' if classes else ""
        extra = (" " + " ".join(extras)) if extras else ""
        return f"{cls}{extra}"

    thead_cells = []
    for i, h in enumerate(headers):
        label = _esc(h)
        if interactive:
            key = str((col_keys[i] if col_keys and i < len(col_keys) else "") or "").strip()
            drag = ""
            if key not in ("idx", "company", "#"):
                drag = (
                    '<span class="col-drag" title="Mover coluna" draggable="true" '
                    'aria-label="Mover coluna">⋮⋮</span>'
                )
            help_q = ""
            if key == "brand":
                help_q = (
                    '<button type="button" class="col-help" data-tip="'
                    'DataForSEO brand search volume: Aug 2026 &gt; Aug 2025 &gt; Aug 2024">'
                    '?</button>'
                )
            elif key == "growth":
                help_q = (
                    '<button type="button" class="col-help" data-tip="'
                    'Total growth Aug 2026 vs 2024 &gt; last year Aug 2026 vs 2025">'
                    '?</button>'
                )
            label = (
                f'<span class="th-wrap">'
                f"{drag}"
                f'<span class="th-label">{_esc(h)}{help_q}</span>'
                f'<button type="button" class="col-hide" title="Ocultar {_esc(h)}" aria-label="Ocultar {_esc(h)}">×</button>'
                f"</span>"
            )
        thead_cells.append(f"<th{_attr(i, header=True)}>{label}</th>")
    thead = "".join(thead_cells)
    body = []
    for r_i, row in enumerate(rows):
        is_you = any('class="you"' in str(cell) for cell in row)
        tds = []
        sorts = (sort_rows[r_i] if sort_rows and r_i < len(sort_rows) else None) or []
        for i, cell in enumerate(row):
            sv = sorts[i] if i < len(sorts) else ""
            sort_attr = f' data-sort="{_esc(sv)}"' if sv not in (None, "") else ""
            tds.append(f"<td{_attr(i)}{sort_attr}>{cell}</td>")
        tds_html = "".join(tds)
        meta = (row_attrs[r_i] if row_attrs and r_i < len(row_attrs) else None) or {}
        extras = []
        if is_you:
            extras.append('class="is-you"')
        if meta.get("sim"):
            extras.append(f'data-sim="{_esc(meta.get("sim"))}"')
        if meta.get("domain"):
            extras.append(f'data-domain="{_esc(meta.get("domain"))}"')
        attr = (" " + " ".join(extras)) if extras else ""
        body.append(f"<tr{attr}>{tds_html}</tr>")
    if not body:
        body.append(f'<tr><td class="empty" colspan="{len(headers)}">No data</td></tr>')
    wrap = "table-wrap paged-table" if page_size else "table-wrap"
    if interactive:
        wrap += " interactive-table"
    extra = f' data-page-size="{int(page_size)}"' if page_size else ""
    pager = (
        '<div class="pager">'
        '<button type="button" class="pager-prev">Anterior</button>'
        '<span class="pager-status"></span>'
        '<button type="button" class="pager-next">Próxima</button>'
        "</div>"
        if page_size and len(rows) > page_size
        else ""
    )
    tray = '<div class="hidden-cols" hidden></div>' if interactive else ""
    return (
        f'{tray}<div class="{wrap}"{extra}><table><thead><tr>{thead}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>{pager}</div>"
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


def _sim_edit_cell(comp: dict[str, Any], *, editable: bool) -> str:
    raw = str(comp.get("similaridade") or ("Cliente" if comp.get("is_client") else "—"))
    if comp.get("is_client") or not editable:
        return _esc(raw)
    cur = raw.strip().lower().replace("é", "e")
    if cur == "alto":
        cur_val = "Alto"
    elif cur == "medio":
        cur_val = "Medio"
    elif cur == "baixo":
        cur_val = "Baixo"
    else:
        cur_val = ""
    opts = [("Alto", "Alto"), ("Medio", "Médio"), ("Baixo", "Baixo")]
    parts = [
        f'<select class="sim-edit" data-domain="{_esc(comp.get("domain") or "")}" title="Change similarity">'
    ]
    if cur_val not in {"Alto", "Medio", "Baixo"}:
        parts.append(f'<option value="{_esc(raw)}" selected>{_esc(raw)}</option>')
    for val, label in opts:
        sel = " selected" if val == cur_val else ""
        parts.append(f'<option value="{val}"{sel}>{label}</option>')
    parts.append("</select>")
    return "".join(parts)


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
            vol = str(
                row.get("traffic_fmt")
                or row.get("latest_volume")
                or "0"
            )
            g = row.get("growth_1y_pct")
            if not isinstance(g, (int, float)):
                g = _dfs_growth_pct(row.get("traffic") or row.get("latest_volume"), row.get("volume_1y"))
            if isinstance(g, (int, float)):
                return f"{vol} · {g:+.1f}%"
            return vol
        vol = str(section.get("total_traffic_fmt") or "—")
        g = section.get("growth_1y_pct")
        if isinstance(g, (int, float)):
            return f"{vol} · {g:+.1f}%"
        gf = section.get("growth_fmt")
        return f"{vol} · {gf}" if gf and gf != "n/a" else vol
    if kind == "similarweb":
        if row:
            return str(row.get("traffic_fmt") or "0")
        return str(section.get("total_traffic_fmt") or "—")
    # count / social / linkedin
    if row:
        return str(row.get("value_fmt") or row.get("ads_fmt") or "0")
    return str(section.get("total_fmt") or "—")


# Score tiers: 0 | low | medium | high  (boundary goes to higher tier)
_SCORE_RANK = {"high": 3, "medium": 2, "low": 1, "0": 0}
_SCORE_BANDS: dict[str, tuple[float, float]] = {
    # key → (low_max exclusive→medium, medium_max exclusive→high)
    "google_ads": (50, 100),
    "meta": (20, 50),
    "linkedin": (20, 50),
    "brand": (500, 2_000),
    "brand_dataforseo": (500, 2_000),
    "seo": (5_000, 50_000),
    "similarweb": (20_000, 100_000),
    "youtube": (20_000, 100_000),
    "instagram": (20_000, 100_000),
    "tiktok": (20_000, 100_000),
    "twitter": (20_000, 100_000),
    "linkedin_profile": (20_000, 100_000),
    "reddit": (50, 200),
    "youtube_influencers": (10_000, 50_000),
    "instagram_influencers": (10_000, 50_000),
}


def _coerce_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in _NEUTRAL_CELLS:
        return None
    s = s.replace("\u00a0", " ").replace(" ", "")
    # BR "7.000" / "204,0K" / EN "15.2K" / "3,1M"
    m = re.match(
        r"^[$€£R$]*([\d]+(?:[.,]\d+)*)([KkMmBb])?%?$",
        s,
    )
    if m:
        raw, suf = m.group(1), (m.group(2) or "").upper()
        if "," in raw and "." in raw:
            # 1.234,5 → 1234.5
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            left, _, right = raw.partition(",")
            raw = f"{left}{right}" if len(right) == 3 and right.isdigit() else f"{left}.{right}"
        elif "." in raw:
            parts = raw.split(".")
            if len(parts) > 2:
                raw = "".join(parts)
            else:
                left, right = parts[0], parts[1]
                # BR thousands "7.000" (no suffix) vs EN decimal "15.2" (+K)
                if not suf and len(right) == 3 and right.isdigit():
                    raw = f"{left}{right}"
        try:
            num = float(raw)
        except ValueError:
            return None
        mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get(suf, 1.0)
        return num * mult
    digits = re.sub(r"[^\d.]", "", s.replace(",", ""))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def _channel_metric_value(
    key: str,
    section: Optional[dict[str, Any]],
    row: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    """Número bruto usado no score do canal (cliente ou row)."""
    if not section:
        return None
    if row is None:
        row = _client_row(section) or {}
    else:
        row = row or {}

    if key == "youtube_influencers":
        n = _coerce_number(row.get("traffic"))
        if n is not None:
            return n
        a = _coerce_number(row.get("views_official")) or 0.0
        b = _coerce_number(row.get("views_unofficial")) or 0.0
        if a or b:
            return a + b

    if key in ("google_ads", "meta", "linkedin"):
        candidates: list[Any] = [
            row.get("ads"), row.get("value"), section.get("total_ads"), section.get("total"),
        ]
    elif key in ("brand", "seo", "brand_dataforseo", "similarweb"):
        candidates = [row.get("traffic"), row.get("latest_volume"), section.get("total_traffic")]
    elif key in ("youtube", "instagram", "tiktok"):
        candidates = [row.get("value"), row.get("followers"), row.get("traffic")]
    elif key == "reddit":
        candidates = [row.get("total_comments"), row.get("traffic")]
    elif key in ("twitter", "linkedin_profile"):
        candidates = [row.get("followers"), row.get("traffic")]
    elif key == "instagram_influencers":
        candidates = [row.get("total_likes"), row.get("traffic")]
    else:
        candidates = [row.get("traffic"), row.get("value"), row.get("ads")]

    for c in candidates:
        n = _coerce_number(c)
        if n is not None:
            return n
    for c in (
        row.get("ads_fmt"),
        row.get("value_fmt"),
        row.get("traffic_fmt"),
        row.get("total_comments_fmt"),
        row.get("followers_fmt"),
        row.get("total_likes_fmt"),
        section.get("total_ads_fmt"),
        section.get("total_traffic_fmt"),
        section.get("total_fmt"),
    ):
        n = _coerce_number(c)
        if n is not None:
            return n
    return None


def _channel_score(key: str, value: Optional[float]) -> str:
    """Retorna '0' | 'low' | 'medium' | 'high'."""
    if value is None or value <= 0:
        return "0"
    bands = _SCORE_BANDS.get(key)
    if not bands:
        return "0"
    low_max, med_max = bands
    if value < low_max:
        return "low"
    if value < med_max:
        return "medium"
    return "high"


def _score_badge(score: str) -> str:
    label = score if score != "0" else "0"
    return f'<span class="score score-{_esc(score)}" title="Channel score">{_esc(label)}</span>'


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


# "blocks" = fixed UX groups (current). "sorted" = legacy score-sorted grid with sort buttons.
SUMMARY_LAYOUT = "blocks"

_SUMMARY_UNIT_FALLBACK = {
    "ads": "ads",
    "count": "",
    "seo": "visits",
    "brand": "visits",
    "brand_dfs": "vol.",
    "similarweb": "visits/mo",
}
_SUMMARY_LINK_LABELS = {
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

# Legacy flat list (v1 sorted layout)
_SUMMARY_CHANNELS_V1: list[tuple[str, str, str]] = [
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

# Fixed Resumo blocks: (title, css slug, channels[(label, key, kind), ...])
_SUMMARY_BLOCKS: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "Popularidade",
        "popularidade",
        [
            ("SimilarWeb", "similarweb", "similarweb"),
            ("DataForSEO", "brand_dataforseo", "brand_dfs"),
            ("Marca", "brand", "brand"),
        ],
    ),
    (
        "Paid Ads",
        "paid",
        [
            ("Meta Ads", "meta", "ads"),
            ("Google Ads", "google_ads", "ads"),
            ("LinkedIn Ads", "linkedin", "count"),
        ],
    ),
    (
        "Orgânico",
        "organico",
        [
            ("SEO Orgânico", "seo", "seo"),
            ("Reddit", "reddit", "seo"),
            ("Twitter / X", "twitter", "seo"),
            ("LinkedIn Profile", "linkedin_profile", "seo"),
            ("YouTube", "youtube", "count"),
            ("Instagram", "instagram", "count"),
            ("TikTok", "tiktok", "count"),
        ],
    ),
    (
        "Influenciadores",
        "influenciadores",
        [
            ("YouTube Influencers", "youtube_influencers", "seo"),
            ("Instagram Influencers", "instagram_influencers", "seo"),
        ],
    ),
]


def _collect_summary_kpis(
    report: dict[str, Any],
    channels: list[tuple[str, str, str]],
    *,
    run_meta: Optional[dict[str, Any]] = None,
    show_you: bool = True,
    score_by_company: bool = True,
    score_centered: bool = False,
    inherit_block_color: bool = False,
    label_above: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """Build KPI cards for the given channel list. Returns (items, compare_all)."""
    market = _report_market(report, run_meta)
    compare_all = bool(report.get("compare_all") or (run_meta or {}).get("compare_all"))

    def _unit_for(value: str, unit: str) -> str:
        if not unit or value in ("—", "n/d") or unit.lower() in value.lower():
            return ""
        return unit

    built: list[dict[str, Any]] = []
    for order_idx, (label, key, kind) in enumerate(channels):
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
        unit = (section.get("unit") or _SUMMARY_UNIT_FALLBACK.get(kind) or "").strip()
        if key == "brand_dataforseo":
            unit = ""
        link_label = _SUMMARY_LINK_LABELS.get(key, "Open")
        group = SECTION_GROUPS.get(key, "overview")
        group_attr = "" if inherit_block_color else f' data-group="{group}"'
        anchor = f"#sec-{key}"
        client = _client_row(section)
        if key == "brand_dataforseo" and client is not None:
            if not isinstance(client.get("growth_1y_pct"), (int, float)):
                client["growth_1y_pct"] = _dfs_growth_pct(
                    client.get("traffic") or client.get("latest_volume"),
                    client.get("volume_1y"),
                )
            if isinstance(client.get("growth_1y_pct"), (int, float)):
                client["growth_fmt"] = f"{client['growth_1y_pct']:+.1f}%"
                section["growth_1y_pct"] = client["growth_1y_pct"]
                section["growth_fmt"] = client["growth_fmt"]
        metric = _channel_metric_value(key, section, client)
        score = _channel_score(key, metric)
        rank = _SCORE_RANK.get(score, 0)
        badge = _score_badge(score)

        if compare_all and len(rows_data) > 1:
            lines: list[str] = []
            for r in rows_data:
                name = str(r.get("name") or r.get("domain") or "—")
                value = _main_datum(section, kind, r)
                u = _unit_for(value, unit)
                url = _summary_channel_url(key, section, r, market=market)
                you = (
                    ' <span class="you">you</span>'
                    if show_you and r.get("is_client")
                    else ""
                )
                link = _link_cell(url, "↗")
                row_score = _channel_score(key, _channel_metric_value(key, section, r))
                if score_by_company and score_centered:
                    # name | score (center) | value
                    lines.append(
                        f'<li class="kpi-row">'
                        f'<span class="kpi-name">{_esc(name)}{you}</span>'
                        f'<span class="kpi-score-mid">{_score_badge(row_score)}</span>'
                        f'<span class="kpi-mini">{_esc(value)}{(" " + _esc(u)) if u else ""}'
                        f'{(" " + link) if link != "—" else ""}</span></li>'
                    )
                elif score_by_company:
                    lines.append(
                        f'<li><span class="kpi-name">{_esc(name)}{you} {_score_badge(row_score)}</span>'
                        f'<span class="kpi-mini">{_esc(value)}{(" " + _esc(u)) if u else ""}'
                        f'{(" " + link) if link != "—" else ""}</span></li>'
                    )
                else:
                    lines.append(
                        f'<li><span class="kpi-name">{_esc(name)}{you}</span>'
                        f'<span class="kpi-mini">{_esc(value)}{(" " + _esc(u)) if u else ""}'
                        f'{(" " + link) if link != "—" else ""}</span></li>'
                    )
            label_html = f'<a class="kpi-label" href="{anchor}">{_esc(label)}</a>'
            if score_centered and not score_by_company:
                head = f'{"" if label_above else label_html}<div class="kpi-score-center">{badge}</div>'
            elif score_centered:
                head = "" if label_above else label_html
            else:
                head = (
                    f'<div class="kpi-top">{label_html}{badge}</div>'
                )
            card = (
                f'<div class="kpi kpi-multi{(" kpi-score-centered" if score_centered else "")}"'
                f'{group_attr} data-score="{_esc(score)}" '
                f'data-rank="{rank}" data-order="{order_idx}" data-key="{_esc(key)}" '
                f'data-metric="{metric if metric is not None else -1}">'
                f"{head}"
                f'<ul class="kpi-list">{"".join(lines)}</ul></div>'
            )
            html = (
                f'<div class="kpi-unit-wrap">{label_html}{card}</div>'
                if label_above
                else card
            )
        else:
            value = _main_datum(section, kind)
            u = _unit_for(value, unit)
            url = _summary_channel_url(key, section, client, market=market)
            link = _link_cell(url, f"{link_label} ↗")
            label_html = f'<a class="kpi-label" href="{anchor}">{_esc(label)}</a>'
            if score_centered:
                card = (
                    f'<div class="kpi kpi-score-centered"{group_attr} data-score="{_esc(score)}" '
                    f'data-rank="{rank}" data-order="{order_idx}" data-key="{_esc(key)}" '
                    f'data-metric="{metric if metric is not None else -1}">'
                    f'{"" if label_above else label_html}'
                    f'<div class="kpi-score-center">{badge}</div>'
                    f'<div class="kpi-val">{_esc(value)}'
                    f'{f"<span class=kpi-unit>{_esc(u)}</span>" if u else ""}</div>'
                    f'{f"<div class=kpi-link>{link}</div>" if link != "—" else ""}'
                    f"</div>"
                )
                html = (
                    f'<div class="kpi-unit-wrap">{label_html}{card}</div>'
                    if label_above
                    else card
                )
            else:
                html = (
                    f'<div class="kpi"{group_attr} data-score="{_esc(score)}" '
                    f'data-rank="{rank}" data-order="{order_idx}" data-key="{_esc(key)}" '
                    f'data-metric="{metric if metric is not None else -1}">'
                    f'<div class="kpi-top">{label_html}{badge}</div>'
                    f'<div class="kpi-val">{_esc(value)}'
                    f'{f"<span class=kpi-unit>{_esc(u)}</span>" if u else ""}</div>'
                    f'{f"<div class=kpi-link>{link}</div>" if link != "—" else ""}'
                    f"</div>"
                )
        built.append({
            "html": html,
            "key": key,
            "rank": rank,
            "metric": metric if metric is not None else -1,
            "order": order_idx,
        })
    return built, compare_all


def _summary_channels_v1_sorted(
    report: dict[str, Any], *, run_meta: Optional[dict[str, Any]] = None
) -> str:
    """BACKUP — Resumo legado: grid plano ordenável por score (high→low)."""
    built, compare_all = _collect_summary_kpis(
        report, _SUMMARY_CHANNELS_V1, run_meta=run_meta
    )
    if not built:
        return ""
    built.sort(key=lambda t: (-t["rank"], -t["metric"], t["order"]))
    title = "Resumo — canais (All)" if compare_all else "Resumo — canais"
    return f"""
    <section>
      <div class="summary-head">
        <h2>{_esc(title)}</h2>
        <div class="sort-bar" role="group" aria-label="Ordenar canais">
          <button type="button" class="sort-btn is-active" data-sort="score-desc">Score high→low</button>
          <button type="button" class="sort-btn" data-sort="score-asc">Score low→high</button>
          <button type="button" class="sort-btn" data-sort="default">Ordem padrão</button>
        </div>
      </div>
      <p class="score-legend">Scores: <span class="score score-high">high</span>
        <span class="score score-medium">medium</span>
        <span class="score score-low">low</span>
        <span class="score score-0">0</span></p>
      <div class="kpis" id="summary-kpis">{''.join(t["html"] for t in built)}</div>
    </section>
    """


def _company_match_key(row: dict[str, Any]) -> str:
    dom = re.sub(r"^www\.", "", str(row.get("domain") or "").strip().lower())
    if dom:
        return f"d:{dom}"
    name = re.sub(r"\s+", " ", str(row.get("name") or "").strip().lower())
    return f"n:{name}" if name else ""


def _summary_companies(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered company list for scoreboard (client first)."""
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _add(row: dict[str, Any]) -> None:
        key = _company_match_key(row)
        if not key:
            return
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = {
                "name": row.get("name") or row.get("domain") or "—",
                "domain": row.get("domain") or "",
                "is_client": bool(row.get("is_client")),
                "_key": key,
            }
            order.append(key)
        else:
            if row.get("is_client"):
                prev["is_client"] = True
            if not prev.get("name") and row.get("name"):
                prev["name"] = row.get("name")
            if not prev.get("domain") and row.get("domain"):
                prev["domain"] = row.get("domain")

    for c in report.get("competitors") or []:
        if isinstance(c, dict):
            _add(c)
    for _, _, chans in _SUMMARY_BLOCKS:
        for _, key, _ in chans:
            section = report.get(key)
            if not isinstance(section, dict):
                continue
            for r in section.get("rows") or []:
                if isinstance(r, dict):
                    _add(r)

    comps = [by_key[k] for k in order]
    comps.sort(key=lambda c: (0 if c.get("is_client") else 1, str(c.get("name") or "").lower()))
    return comps


def _row_for_company(section: dict[str, Any], company: dict[str, Any]) -> Optional[dict[str, Any]]:
    want = company.get("_key") or _company_match_key(company)
    if not want:
        return None
    for r in section.get("rows") or []:
        if isinstance(r, dict) and _company_match_key(r) == want:
            return r
    return None


def _summary_scoreboard(
    report: dict[str, Any],
    *,
    available_keys: Optional[set[str]] = None,
) -> str:
    """Matrix: empresa × canais com apenas etiquetas de score."""
    companies = _summary_companies(report)
    if not companies:
        return ""

    # Channels that have data in this report (same filter as KPI cards)
    active_blocks: list[tuple[str, str, list[tuple[str, str, str]]]] = []
    for block_title, block_slug, chans in _SUMMARY_BLOCKS:
        kept = [
            (label, key, kind)
            for label, key, kind in chans
            if available_keys is None or key in available_keys
        ]
        # also require section present
        kept = [
            (label, key, kind)
            for label, key, kind in kept
            if isinstance(report.get(key), dict)
            and (
                (report[key].get("rows") or [])
                or report[key].get("total_fmt")
                or report[key].get("total_ads_fmt")
                or report[key].get("total_traffic_fmt")
            )
        ]
        if kept:
            active_blocks.append((block_title, block_slug, kept))
    if not active_blocks:
        return ""

    # Group header row
    group_cells = ['<th class="scoreboard-corp" rowspan="2">Empresa</th>']
    channel_cells: list[str] = []
    flat_channels: list[tuple[str, str, str]] = []
    for block_title, block_slug, chans in active_blocks:
        group_cells.append(
            f'<th class="scoreboard-group" data-block="{_esc(block_slug)}" '
            f'colspan="{len(chans)}">{_esc(block_title)}</th>'
        )
        for label, key, kind in chans:
            flat_channels.append((label, key, kind))
            channel_cells.append(
                f'<th class="scoreboard-chan" data-block="{_esc(block_slug)}" title="{_esc(label)}">'
                f"{_esc(label)}</th>"
            )

    body_rows: list[str] = []
    for company in companies:
        name = str(company.get("name") or company.get("domain") or "—")
        cells = [f'<th scope="row" class="scoreboard-corp">{_esc(name)}</th>']
        for _label, key, _kind in flat_channels:
            section = report.get(key) or {}
            row = _row_for_company(section, company)
            if row is None and len(companies) == 1:
                row = _client_row(section)
            metric = _channel_metric_value(key, section, row) if row is not None else None
            # Ensure DFS growth for scoring when present
            if key == "brand_dataforseo" and row is not None:
                if not isinstance(row.get("growth_1y_pct"), (int, float)):
                    row = dict(row)
                    row["growth_1y_pct"] = _dfs_growth_pct(
                        row.get("traffic") or row.get("latest_volume"),
                        row.get("volume_1y"),
                    )
                metric = _channel_metric_value(key, section, row)
            score = _channel_score(key, metric) if row is not None else "0"
            cells.append(
                f'<td class="scoreboard-cell" data-score="{_esc(score)}">{_score_badge(score)}</td>'
            )
        tr_cls = ' class="is-you"' if company.get("is_client") else ""
        body_rows.append(f"<tr{tr_cls}>{''.join(cells)}</tr>")

    return f"""
    <div class="summary-block scoreboard-block" data-block="scoreboard">
      <h3 class="summary-block-title">Scoreboard</h3>
      <div class="table-wrap scoreboard-wrap">
        <table class="scoreboard">
          <thead>
            <tr>{"".join(group_cells)}</tr>
            <tr>{"".join(channel_cells)}</tr>
          </thead>
          <tbody>
            {"".join(body_rows)}
          </tbody>
        </table>
      </div>
    </div>
    """


def _summary_channels_blocks(
    report: dict[str, Any], *, run_meta: Optional[dict[str, Any]] = None
) -> str:
    """Resumo com blocos fixos (Popularidade / Paid Ads / Orgânico / Influenciadores)."""
    all_channels: list[tuple[str, str, str]] = []
    for _, _, chans in _SUMMARY_BLOCKS:
        all_channels.extend(chans)
    built, compare_all = _collect_summary_kpis(
        report,
        all_channels,
        run_meta=run_meta,
        show_you=False,
        score_by_company=True,
        score_centered=True,
        inherit_block_color=True,
        label_above=True,
    )
    if not built:
        return ""
    by_key = {item["key"]: item for item in built}

    block_html: list[str] = []
    for block_title, block_slug, chans in _SUMMARY_BLOCKS:
        cards = [by_key[key]["html"] for _, key, _ in chans if key in by_key]
        if not cards:
            continue
        block_html.append(
            f'<div class="summary-block" data-block="{_esc(block_slug)}">'
            f'<h3 class="summary-block-title">{_esc(block_title)}</h3>'
            f'<div class="kpis">{"".join(cards)}</div>'
            f"</div>"
        )
    if not block_html:
        return ""

    scoreboard = _summary_scoreboard(report, available_keys=set(by_key.keys()))

    title = "Resumo — canais (All)" if compare_all else "Resumo — canais"
    return f"""
    <section>
      <div class="summary-head">
        <h2>{_esc(title)}</h2>
      </div>
      <p class="score-legend">Scores: <span class="score score-high">high</span>
        <span class="score score-medium">medium</span>
        <span class="score score-low">low</span>
        <span class="score score-0">0</span></p>
      <div class="summary-blocks">{''.join(block_html)}{scoreboard}</div>
    </section>
    """


def _summary_channels(report: dict[str, Any], *, run_meta: Optional[dict[str, Any]] = None) -> str:
    """Resumo no topo. Troque SUMMARY_LAYOUT para 'sorted' para voltar ao backup v1."""
    if SUMMARY_LAYOUT == "sorted":
        return _summary_channels_v1_sorted(report, run_meta=run_meta)
    return _summary_channels_blocks(report, run_meta=run_meta)


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


def _dfs_growth_pct(new: Any, old: Any) -> Optional[float]:
    """Growth % with 0/missing baseline treated as 100 (display volume stays 0)."""
    if new is None:
        return None
    try:
        new_i = int(new)
    except (TypeError, ValueError):
        return None
    if old is None or old == 0:
        if new_i == 0:
            return 0.0
        return round(((new_i - 100) / 100) * 100, 2)
    try:
        old_i = int(old)
    except (TypeError, ValueError):
        return None
    if old_i == 0:
        return round(((new_i - 100) / 100) * 100, 2) if new_i else 0.0
    return round(((new_i - old_i) / old_i) * 100, 2)


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

    def _growth_for(r: dict, years: str) -> Optional[float]:
        key = f"growth_{years}_pct"
        g = r.get(key)
        if isinstance(g, (int, float)):
            # Recompute when baseline was 0 (old runs stored n/a / None / wrong)
            vol_old = r.get(f"volume_{years}")
            if vol_old in (None, 0) or g is None:
                return _dfs_growth_pct(r.get("traffic") or r.get("latest_volume"), vol_old)
            return float(g)
        return _dfs_growth_pct(r.get("traffic") or r.get("latest_volume"), r.get(f"volume_{years}"))

    headers = [
        "#", "Company", "Keyword", "Latest", "Vol",
        "1y", "2y", "3y", "5y",
        "Δ1y", "Δ2y", "Δ3y", "Δ5y", "Link",
    ]
    table_rows: list[list[str]] = []
    client_g1: Optional[float] = None
    for i, r in enumerate(rows_data, 1):
        name = _esc(r.get("name") or r.get("domain") or "—")
        if r.get("is_client"):
            name += ' <span class="you">you</span>'
        g1 = _growth_for(r, "1y")
        g2 = _growth_for(r, "2y")
        g3 = _growth_for(r, "3y")
        g5 = _growth_for(r, "5y")
        if r.get("is_client") or client_g1 is None:
            client_g1 = g1
        # Keep volume 0 as 0 (not —)
        def _vol_cell(v: Any) -> str:
            if v is None:
                return "—"
            return _fmt_vol(v)

        table_rows.append([
            str(i),
            name,
            _esc(r.get("brand_keyword") or "—"),
            _esc(r.get("latest_label") or "—"),
            _esc(r.get("traffic_fmt") or _fmt_vol(r.get("latest_volume") or r.get("traffic"))),
            _esc(_vol_cell(r.get("volume_1y"))),
            _esc(_vol_cell(r.get("volume_2y"))),
            _esc(_vol_cell(r.get("volume_3y"))),
            _esc(_vol_cell(r.get("volume_5y"))),
            _esc(_fmt_g(g1)),
            _esc(_fmt_g(g2)),
            _esc(_fmt_g(g3)),
            _esc(_fmt_g(g5)),
            _link_cell(r.get("url"), "Semrush"),
        ])

    latest = _esc(section.get("latest_label") or "—")
    kw = _esc(section.get("client_keyword") or "—")
    hero_vol = _esc(section.get("total_traffic_fmt") or "—")
    if client_g1 is None:
        client_g1 = section.get("growth_1y_pct")
    hero_g = _fmt_g(client_g1) if isinstance(client_g1, (int, float)) else (
        str(section.get("growth_fmt") or "n/a")
    )
    hero = f"{hero_vol} <span class='kpi-unit'>· {_esc(hero_g)} Δ1y</span>"
    hero_sub = (
        f"keyword {kw} · latest {latest} · DataForSEO · "
        f"growth uses baseline 100 when historical volume is 0"
    )
    insight = section.get("insight") or ""
    analysis = section.get("analysis_title") or ""
    return f"""
    <section>
      <h2>Brand Search — DataForSEO (US)</h2>
      <div class="hero"><div class="hero-val">{hero}</div><div class="hero-sub">{_esc(hero_sub)}</div></div>
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


def _runs_dir() -> Path:
    data = (os.environ.get("RADAR_DATA_DIR") or os.environ.get("SPY_DATA_DIR") or "").strip()
    root = Path(data) / "outputs" if data else Path(__file__).resolve().parent / "outputs"
    return root / "runs"


def _resolve_run_log(
    report: dict[str, Any],
    run_meta: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    payload = report.get("run_log")
    if isinstance(payload, dict) and (payload.get("channels") or payload.get("lines")):
        return payload
    run_id = str((run_meta or {}).get("id") or "").strip()
    if not run_id:
        return None
    # Fallback: load persisted sidecar files (older / partial saves)
    try:
        run_dir = _runs_dir() / run_id
        stats_path = run_dir / "run_stats.json"
        log_path = run_dir / "run.log"
        stats: dict[str, Any] = {}
        if stats_path.exists():
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        if log_path.exists() and "lines" not in stats:
            stats["lines"] = [
                ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
        if stats.get("channels") or stats.get("lines"):
            return stats
    except Exception:
        return None
    return None


def _section_run_log(payload: Optional[dict[str, Any]]) -> str:
    if not payload:
        return ""
    channels = payload.get("channels") or []
    lines = payload.get("lines") or []
    totals = payload.get("totals") or {}
    rates = str(payload.get("rates_note") or "").strip()

    rows_html: list[str] = []
    for ch in channels:
        rows_html.append(
            "<tr>"
            f"<td>{_esc(ch.get('label') or ch.get('id') or '—')}</td>"
            f"<td class=\"num\">{_esc(ch.get('sec_fmt') or '—')}</td>"
            f"<td>{_esc(ch.get('apis_fmt') or '—')}</td>"
            f"<td class=\"num\">{_esc(ch.get('cost_fmt') or '—')}</td>"
            f"<td class=\"muted\">{_esc(ch.get('cost_note') or ch.get('detail') or '')}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html.append('<tr><td class="empty" colspan="5">Sem dados de canal</td></tr>')

    summary_table = f"""
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Canal</th><th class="num">Tempo</th><th>APIs</th>
          <th class="num">Custo est.</th><th>Detalhe</th>
        </tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
        <tfoot>
          <tr class="runlog-total">
            <th>Total</th>
            <th class="num">{_esc(totals.get('sec_fmt') or '—')}</th>
            <th></th>
            <th class="num">{_esc(totals.get('cost_fmt') or '—')}</th>
            <th></th>
          </tr>
        </tfoot>
      </table>
    </div>
    """

    log_text = "\n".join(str(x) for x in lines)
    log_block = (
        f'<pre class="runlog-pre">{_esc(log_text)}</pre>'
        if log_text.strip()
        else '<p class="muted">Log vazio para este run.</p>'
    )
    rates_html = f'<p class="muted runlog-rates">{_esc(rates)}</p>' if rates else ""

    return f"""
    <section>
      <h2>Log da execução</h2>
      <p class="muted">Linhas capturadas durante o pipeline ({_esc(str(payload.get('line_count') or len(lines)))}).</p>
      {log_block}
      <h3 class="subhead">Resumo por canal — tempo e custo estimado</h3>
      {summary_table}
      {rates_html}
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
    competitors_only = bool(report.get("competitors_only") or meta.get("competitors_only"))
    if competitors_only and report.get("competitors_raw"):
        comps = report.get("competitors_raw") or comps
    fp_domains = _brand_fp_domains(comps, report)
    run_id = str(meta.get("id") or "").strip()
    sim_editable = bool(competitors_only and run_id)

    comp_rows = []
    sort_rows: list[list[Any]] = []
    row_attrs: list[dict[str, Any]] = []
    for i, c in enumerate(comps, 1):
        raw_name = c.get("name") or c.get("domain") or "—"
        site = (c.get("url") or c.get("site_url") or "").strip()
        if not site and c.get("domain"):
            site = f"https://{c.get('domain')}/"
        name = _link_cell(site, raw_name) if site else _esc(raw_name)
        if c.get("is_client"):
            name += ' <span class="you">you</span>'
        if (c.get("domain") or "").strip().lower() in fp_domains:
            name += ' <span class="fp-mark" title="potential false positive">*</span>'
        row = [
            str(i),
            name,
            _esc(c.get("domain") or "—"),
            _sim_edit_cell(c, editable=sim_editable),
        ]
        if competitors_only:
            row.append(_fonte_cell(c.get("fonte")))
            row.append(_esc(c.get("perfil") or "—"))
        if competitors_only:
            row.append(_clip_cell(c.get("motivo"), limit=48))
        show_brand = bool(report.get("include_brand_growth") or meta.get("include_brand_growth"))
        show_sw = bool(report.get("include_similarweb_alto") or meta.get("include_similarweb_alto"))
        if show_brand:
            row.extend([
                _brand_seq_cell(c),
                _growth_seq_cell(c),
            ])
        if show_sw:
            sim = str(c.get("similaridade") or "").strip().lower().replace("é", "e")
            if c.get("is_client") or sim == "alto":
                compact, full = _brand_vol_text(c.get("similarweb_visits"))
                if compact == "—" and c.get("similarweb_fmt"):
                    row.append(_esc(c.get("similarweb_fmt")))
                elif not full or compact == full:
                    row.append(_esc(compact))
                else:
                    row.append(f'<span title="{_esc(full)}">{_esc(compact)}</span>')
            else:
                row.append("—")
        row.append(_clip_cell(_row_title(c), limit=22))
        row.append(_clip_cell(c.get("nicho"), limit=28))
        sort_row = [
            str(i),
            str(c.get("name") or c.get("domain") or "").lower(),
            str(c.get("domain") or "").lower(),
            _sort_sim(c),
        ]
        if competitors_only:
            sort_row += [str(c.get("fonte") or "").lower(), str(c.get("perfil") or "").lower()]
        if competitors_only:
            sort_row.append(str(c.get("motivo") or "").lower())
        if show_brand:
            sort_row += [
                _sort_num(c.get("brand_aug_2026")),
                _sort_num(c.get("brand_growth_26_24") or _growth_pct(
                    c.get("brand_aug_2026"), c.get("brand_aug_2024")
                )),
            ]
        if show_sw:
            sort_row.append(_sort_num(c.get("similarweb_visits")))
        sort_row += [_row_title(c).lower(), str(c.get("nicho") or "").lower()]
        comp_rows.append(row)
        sort_rows.append(sort_row)
        row_attrs.append({
            "sim": str(c.get("similaridade") or "").strip(),
            "domain": str(c.get("domain") or "").strip().lower(),
        })
    show_brand = bool(report.get("include_brand_growth") or meta.get("include_brand_growth"))
    show_sw = bool(report.get("include_similarweb_alto") or meta.get("include_similarweb_alto"))
    comp_headers = ["#", "Company", "Domain", "Similarity"]
    if competitors_only:
        comp_headers += ["Fonte", "Perfil"]
    if competitors_only:
        comp_headers.append("Motivo")
    if show_brand:
        comp_headers += ["Brand", "Growth"]
    if show_sw:
        comp_headers.append("SimilarWeb")
    comp_headers += ["Title", "Niche"]
    _COMP_KEY = {
        "#": "idx",
        "Company": "company",
        "Title": "title",
        "Domain": "domain",
        "Similarity": "similarity",
        "Fonte": "fonte",
        "Perfil": "perfil",
        "Niche": "niche",
        "Motivo": "motivo",
        "Brand": "brand",
        "Growth": "growth",
        "SimilarWeb": "similarweb",
    }
    comp_keys = [_COMP_KEY.get(h, h.lower()) for h in comp_headers]
    compact_keys = {
        "company", "title", "similarity", "niche",
        "brand", "growth", "similarweb",
    }

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
    run_log_payload = _resolve_run_log(report, meta)
    run_log_html = _section_run_log(run_log_payload)
    if run_log_html:
        toc["overview"].append('<a href="#sec-runlog">Log</a>')
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
    if competitors_only:
        chips.append('<span class="chip accent">Concorrentes only</span>')
    if report.get("include_brand_growth") or meta.get("include_brand_growth"):
        chips.append('<span class="chip">Brand Aug 26/25/24</span>')
    if report.get("include_similarweb_alto") or meta.get("include_similarweb_alto"):
        chips.append('<span class="chip">SimilarWeb Alto</span>')
    if meta.get("site_only") and not compare_all and not competitors_only:
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
    add_form = ""
    if sim_editable:
        add_form = """
      <form class="add-comp" id="add-competitor">
        <div class="add-comp-main">
          <textarea name="urls" rows="4" placeholder="One website per line — paste 15 at once&#10;junglescout.com&#10;helium10.com&#10;https://example.com"></textarea>
          <div class="add-comp-side">
            <select name="similaridade" title="Similarity">
              <option value="">Auto</option>
              <option value="Alto">Alto</option>
              <option value="Medio">Médio</option>
              <option value="Baixo">Baixo</option>
            </select>
            <button type="submit">Add websites</button>
          </div>
        </div>
        <p class="add-hint">Cole a lista — um por linha, vírgula ou espaço. Duplicados e sites já na tabela saem sozinhos. Cada site busca página + Brand (+ SimilarWeb se Alto) — mantenha esta aba aberta.</p>
        <div class="add-preview" hidden></div>
        <ul class="add-log" hidden></ul>
        <span class="add-status"></span>
      </form>"""

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

    <div class="card" id="sec-competitors" data-group="overview" data-view="compact" data-run-id="{_esc(run_id)}">
      <div class="card-head">
        <h2>Competitors <span class="count">{_esc(comp_count)}</span></h2>
        <div class="sort-bar" role="group" aria-label="Colunas dos concorrentes">
          <button type="button" class="sort-btn comp-view is-active" data-view="compact">Métricas</button>
          <button type="button" class="sort-btn comp-view" data-view="all">Todas</button>
          <button type="button" class="sort-btn sim-filter" data-hide="medio" title="Hide Médio rows">Hide Medium</button>
          <button type="button" class="sort-btn sim-filter" data-hide="baixo" title="Hide Baixo rows">Hide Low</button>
        </div>
      </div>
      {f"<p class='note'>{_esc(note)}</p>" if note else ''}
      <p class="muted table-hint">Clique no nome da coluna para ordenar. ⋮⋮ move a coluna. Company fica fixa ao rolar. O × oculta.</p>
      {add_form}
      {_rows_table(
          comp_headers, comp_rows,
          page_size=10 if competitors_only else 0,
          col_keys=comp_keys,
          compact_keys=compact_keys,
          sort_rows=sort_rows,
          interactive=True,
          row_attrs=row_attrs,
      )}
    </div>

    {cards}
    {f'<div class="card" id="sec-runlog" data-group="overview">{run_log_html}</div>' if run_log_html else ''}
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
.card-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:0 0 14px}
.card-head h2{margin:0}
#sec-competitors[data-view="compact"] [data-extra="1"]{display:none}
h2 .count{display:inline-block;margin-left:6px;padding:0 8px;border-radius:999px;background:#f1f5f9;color:var(--muted);
  font-size:12px;font-weight:700;vertical-align:3px}
.subhead{font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:22px 0 8px}
.subhead.first{margin-top:4px}

.hero{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin:0 0 16px;padding:14px 16px;border-radius:12px;
  background:linear-gradient(180deg,#f8fafc,#fff);border:1px solid var(--border)}
.hero-val{font-size:30px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.hero-sub{color:var(--muted);font-size:13px}

.summary-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:6px}
.summary-head h2{margin:0}
.sort-bar{display:flex;gap:6px;flex-wrap:wrap}
.sort-btn{border:1px solid var(--border);background:#fff;color:var(--muted);font:inherit;font-size:12px;font-weight:600;
  padding:5px 10px;border-radius:999px;cursor:pointer}
.sort-btn:hover{border-color:#cbd5e1;color:var(--text)}
.sort-btn.is-active{background:#0f172a;border-color:#0f172a;color:#fff}
.score-legend{margin:0 0 12px;font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.score{display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.04em;
  text-transform:uppercase;line-height:1.4;vertical-align:middle}
.score-high{background:#dcfce7;color:#166534}
.score-medium{background:#e0f2fe;color:#075985}
.score-low{background:#fef3c7;color:#92400e}
.score-0{background:#f1f5f9;color:#64748b}
.summary-blocks{display:flex;flex-direction:column;gap:18px}
.summary-block{--group:var(--overview);border:1px solid color-mix(in srgb,var(--group) 28%,var(--border));
  border-radius:14px;padding:14px 14px 12px;background:linear-gradient(180deg,color-mix(in srgb,var(--group) 6%,#fff) 0%,#fff 48px);
  box-shadow:inset 3px 0 0 var(--group)}
.summary-block[data-block=popularidade]{--group:var(--search)}
.summary-block[data-block=paid]{--group:var(--paid)}
.summary-block[data-block=organico]{--group:var(--overview)}
.summary-block[data-block=influenciadores]{--group:var(--social)}
.summary-block[data-block=scoreboard]{--group:var(--text)}
.summary-block-title{margin:0 0 10px;font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--group)}
.summary-block .kpi{--group:inherit;box-shadow:inset 0 3px 0 var(--group)}
.summary-block .kpi:hover{box-shadow:inset 0 3px 0 var(--group),var(--shadow)}
.kpi-unit-wrap{display:flex;flex-direction:column;gap:7px;min-width:0}
@media (min-width:640px){.kpi-unit-wrap:has(.kpi-multi){grid-column:span 2}}
.kpi-unit-wrap > .kpi-label{
  display:block;padding:0 2px;font-size:13px;font-weight:750;letter-spacing:-.01em;
  color:var(--group);text-decoration:none;line-height:1.25}
.kpi-unit-wrap > .kpi-label:hover{color:var(--text);text-decoration:underline;text-underline-offset:3px}
.summary-block .kpi-unit-wrap > .kpi-label{color:var(--group)}
.kpi-unit-wrap .kpi{height:100%}
.scoreboard-wrap{margin:0}
.scoreboard{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}
.scoreboard thead th{background:#f8fafc;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
  color:var(--muted);padding:8px 6px;border-bottom:1px solid var(--border);vertical-align:bottom}
.scoreboard th.scoreboard-group{text-align:center;color:var(--group);border-bottom:1px solid color-mix(in srgb,var(--group) 35%,var(--border));
  background:color-mix(in srgb,var(--group) 8%,#fff)}
.scoreboard th.scoreboard-group[data-block=popularidade]{--group:var(--search)}
.scoreboard th.scoreboard-group[data-block=paid]{--group:var(--paid)}
.scoreboard th.scoreboard-group[data-block=organico]{--group:var(--overview)}
.scoreboard th.scoreboard-group[data-block=influenciadores]{--group:var(--social)}
.scoreboard th.scoreboard-chan{text-align:center;font-size:10px;font-weight:600;text-transform:none;
  letter-spacing:0;max-width:72px;white-space:normal;line-height:1.25;padding:6px 4px}
.scoreboard th.scoreboard-corp,.scoreboard td.scoreboard-corp,.scoreboard th[scope=row].scoreboard-corp{
  text-align:left;position:sticky;left:0;z-index:1;background:#fff;min-width:110px;max-width:160px;
  padding:8px 10px;font-weight:700;border-right:1px solid var(--line)}
.scoreboard thead th.scoreboard-corp{background:#f8fafc;z-index:2}
.scoreboard tbody tr.is-you th.scoreboard-corp{background:var(--accent-soft)}
.scoreboard tbody tr.is-you td{background:color-mix(in srgb,var(--accent-soft) 55%,#fff)}
.scoreboard-cell{text-align:center;padding:8px 4px;border-bottom:1px solid var(--line)}
.scoreboard tbody tr:last-child td,.scoreboard tbody tr:last-child th{border-bottom:0}
.scoreboard .score{min-width:52px}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
.kpi{border:1px solid var(--border);border-radius:12px;padding:14px 14px 12px;background:#fff;display:flex;flex-direction:column;gap:6px;
  box-shadow:inset 0 3px 0 var(--group);transition:transform .15s,box-shadow .15s,border-color .15s}
.kpi:hover{transform:translateY(-1px);border-color:#cbd5e1;box-shadow:inset 0 3px 0 var(--group),var(--shadow)}
.kpi-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.kpi-label{font-size:12px;font-weight:600;color:var(--muted);text-decoration:none}
.kpi-label:hover{color:var(--text)}
.kpi-score-center{display:flex;justify-content:center;align-items:center;margin:2px 0 4px}
.kpi-score-centered .kpi-label{display:block;text-align:center}
.kpi-score-centered .kpi-val,.kpi-score-centered .kpi-link{text-align:center}
.kpi-val{font-size:24px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.15}
.kpi-unit{font-size:12px;font-weight:600;color:var(--soft);margin-left:5px;letter-spacing:0}
.kpi-link{margin-top:auto;font-size:12px}
.kpi-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
.kpi-list li{display:flex;justify-content:space-between;gap:8px;font-size:12.5px;align-items:center}
.kpi-list li.kpi-row{display:grid;grid-template-columns:minmax(0,1.2fr) auto minmax(0,1fr);gap:8px;align-items:center}
.kpi-score-mid{display:flex;justify-content:center;justify-self:center}
.kpi-name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kpi-mini{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--muted);text-align:right}
@media (min-width:640px){.kpi-multi{grid-column:span 2}}

.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:12px}
.pager{display:flex;align-items:center;justify-content:flex-end;gap:10px;padding:10px 12px;border-top:1px solid var(--border);background:#f8fafc}
.pager button{border:1px solid var(--border);background:#fff;border-radius:8px;padding:6px 10px;font:inherit;font-size:12px;font-weight:600;cursor:pointer}
.pager button:disabled{opacity:.4;cursor:default}
.pager-status{font-size:12px;color:var(--muted);font-weight:600}
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
th.motivo,td.motivo{max-width:168px}
td[data-col="title"] .clip,td[data-col="niche"] .clip{max-width:132px}
.clip{display:inline-block;max-width:156px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:help;vertical-align:bottom}
.table-hint{margin:0 0 10px}
th.sortable{cursor:pointer;user-select:none}
th.sortable .th-wrap{display:inline-flex;align-items:center;gap:4px;max-width:100%}
.col-help{display:inline-grid;place-items:center;margin-left:5px;width:16px;height:16px;border:0;border-radius:50%;
  background:#e2e8f0;color:#334155;font:800 11px/1 inherit;cursor:help;vertical-align:1px;padding:0}
.col-help:hover{background:#0f172a;color:#fff}
.float-tip{position:fixed;z-index:80;max-width:260px;padding:8px 10px;border-radius:8px;
  background:#0f172a;color:#fff;font-size:12px;font-weight:600;line-height:1.35;letter-spacing:0;
  text-transform:none;box-shadow:0 8px 24px rgba(15,23,42,.2);pointer-events:none;white-space:normal}
.brand-seq,.growth-seq{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;font-variant-numeric:tabular-nums}
.seq-sep{color:#94a3b8;font-weight:700;font-size:11px}
.seq-n{font-weight:650}
.growth-up{color:#166534;font-weight:750}
.growth-down{color:#b91c1c;font-weight:750}
.growth-flat{color:#64748b;font-weight:650}
.col-drag{cursor:grab;color:#94a3b8;font-size:11px;letter-spacing:-1px;line-height:1;padding:2px 1px;user-select:none}
.col-drag:active{cursor:grabbing}
th.is-dragging{opacity:.45}
th.drop-before{box-shadow:inset 3px 0 0 var(--accent)}
th.drop-after{box-shadow:inset -3px 0 0 var(--accent)}
#sec-competitors .table-wrap{position:relative}
#sec-competitors th.col-frozen,#sec-competitors td.col-frozen{
  position:sticky;z-index:2;background:#fff}
#sec-competitors thead th.col-frozen{z-index:4;background:#f8fafc}
#sec-competitors td[data-col="company"],#sec-competitors th[data-col="company"]{
  left:0;box-shadow:1px 0 0 var(--border)}
#sec-competitors[data-view="all"] td[data-col="idx"],#sec-competitors[data-view="all"] th[data-col="idx"]{
  left:0;z-index:3}
#sec-competitors[data-view="all"] td[data-col="company"],#sec-competitors[data-view="all"] th[data-col="company"]{
  left:36px}
#sec-competitors tbody tr.is-you td.col-frozen{background:var(--accent-soft)}
#sec-competitors tbody tr:hover td.col-frozen{background:#fafbfc}
#sec-competitors tbody tr.is-you:hover td.col-frozen{background:#d1fae5}
th.sortable .th-label{border-bottom:1px dashed transparent}
th.sortable:hover .th-label{border-bottom-color:#94a3b8}
th.is-sorted-desc .th-label::after,th.is-sorted-asc .th-label::after{margin-left:4px;font-size:10px;color:var(--accent)}
th.is-sorted-desc .th-label::after{content:"↓"}
th.is-sorted-asc .th-label::after{content:"↑"}
.col-hide{border:0;background:#f1f5f9;color:#64748b;width:18px;height:18px;border-radius:4px;font:inherit;font-size:12px;
  line-height:1;cursor:pointer;padding:0;opacity:0;transition:opacity .12s}
th.sortable:hover .col-hide,.col-hide:focus{opacity:1}
.col-hide:hover{background:#fee2e2;color:#b91c1c}
#sec-competitors [data-hidden="1"]{display:none!important}
.hidden-cols{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.hidden-cols[hidden]{display:none}
.hidden-chip{border:1px dashed var(--border);background:#fff;border-radius:999px;padding:3px 10px;font:inherit;font-size:12px;
  font-weight:600;color:var(--muted);cursor:pointer}
.hidden-chip:hover{border-color:#0f766e;color:var(--accent)}
td.empty{color:var(--soft);text-align:center;padding:22px}
.you{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:999px;background:var(--accent);color:#fff;font-size:10px;
  font-weight:700;text-transform:uppercase;letter-spacing:.04em;vertical-align:1px}
.fp-mark{margin-left:2px;color:#b45309;font-weight:800;cursor:help;font-size:14px;line-height:1}
.sim-edit{font:inherit;font-size:12px;font-weight:700;border:1px solid var(--border);border-radius:8px;padding:3px 6px;background:#fff;cursor:pointer;max-width:100%}
.sim-edit:disabled{opacity:.5}
.add-comp{display:flex;flex-direction:column;gap:8px;margin:0 0 12px;padding:12px;border:1px solid var(--border);border-radius:12px;background:#f8fafc}
.add-comp-main{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch}
.add-comp textarea{flex:1;min-width:260px;min-height:84px;resize:vertical;border:1px solid var(--border);border-radius:8px;padding:8px 10px;font:inherit;line-height:1.45}
.add-comp-side{display:flex;flex-direction:column;gap:8px;min-width:148px}
.add-comp select,.add-comp button{width:100%;border-radius:8px;padding:8px 12px;font:inherit}
.add-comp select{border:1px solid var(--border);background:#fff}
.add-comp button{border:0;background:#0f172a;color:#fff;font-weight:700;cursor:pointer}
.add-comp button:disabled{opacity:.55;cursor:default}
.add-hint{margin:0;font-size:12px;color:var(--muted);line-height:1.4}
.add-preview{display:flex;flex-wrap:wrap;gap:6px}
.add-preview[hidden],.add-log[hidden]{display:none}
.add-chip{font-size:11px;font-weight:650;padding:3px 8px;border-radius:999px;background:#e2e8f0;color:#334155}
.add-chip.is-dup{background:#fef3c7;color:#92400e}
.add-log{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px;max-height:170px;overflow:auto;font-size:12px}
.add-log li.ok{color:#166534}
.add-log li.skip{color:#92400e}
.add-log li.err{color:#b91c1c}
.add-log li.run{color:#0f172a;font-weight:700}
.add-status{font-size:12px;color:var(--muted)}
.sim-filter.is-active{background:#0f172a;border-color:#0f172a;color:#fff}
a.ext{color:var(--accent);font-weight:600;text-decoration:none;white-space:nowrap}
a.ext:hover{text-decoration:underline}
td[data-col="company"] a.ext{text-decoration:underline;text-underline-offset:2px;white-space:normal}

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
.runlog-pre{margin:0 0 16px;max-height:360px;overflow:auto;padding:12px 14px;border:1px solid var(--border);
  border-radius:12px;background:#0f172a;color:#e2e8f0;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  white-space:pre-wrap;word-break:break-word}
.runlog-rates{margin:10px 0 0;font-size:12px}
table tfoot tr.runlog-total th{background:#f1f5f9;border-top:1px solid var(--border);font-size:12px;
  text-transform:none;letter-spacing:0;color:var(--text);padding:12px}
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
  .summary-blocks{gap:12px}
  .summary-block{padding:12px 10px 10px}
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
  if(links.length && 'IntersectionObserver' in window){
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
  }

  var grid=document.getElementById('summary-kpis');
  var bar=document.querySelector('.sort-bar');
  if(!grid||!bar)return;
  function sortKpis(mode){
    var items=[].slice.call(grid.querySelectorAll('.kpi'));
    items.sort(function(a,b){
      var ra=+a.getAttribute('data-rank')||0, rb=+b.getAttribute('data-rank')||0;
      var ma=+a.getAttribute('data-metric')||0, mb=+b.getAttribute('data-metric')||0;
      var oa=+a.getAttribute('data-order')||0, ob=+b.getAttribute('data-order')||0;
      if(mode==='score-asc'){return ra-rb || ma-mb || oa-ob;}
      if(mode==='default'){return oa-ob;}
      return rb-ra || mb-ma || oa-ob;
    });
    items.forEach(function(el){grid.appendChild(el);});
  }
  bar.addEventListener('click',function(ev){
    var btn=ev.target.closest('.sort-btn');
    if(!btn)return;
    bar.querySelectorAll('.sort-btn').forEach(function(b){b.classList.remove('is-active');});
    btn.classList.add('is-active');
    sortKpis(btn.getAttribute('data-sort')||'score-desc');
  });
})();
(function(){
  document.querySelectorAll('.paged-table, .interactive-table').forEach(function(wrap){
    var table=wrap.querySelector('table');
    if(!table||!table.tBodies[0])return;
    var tbody=table.tBodies[0];
    var size=parseInt(wrap.getAttribute('data-page-size')||'0',10)||0;
    var status=wrap.querySelector('.pager-status');
    var prev=wrap.querySelector('.pager-prev');
    var next=wrap.querySelector('.pager-next');
    var page=0;
    var sortCol=-1;
    var sortDir='desc';
    var card=wrap.closest('#sec-competitors');
    var tray=card?card.querySelector('.hidden-cols'):null;
    var hideLow=false, hideMed=false;

    function rows(){return [].slice.call(tbody.querySelectorAll('tr'));}
    function simOf(tr){
      return String(tr.getAttribute('data-sim')||'').toLowerCase().replace('é','e').replace('á','a');
    }
    function visRows(){
      return rows().filter(function(tr){
        if(tr.classList.contains('is-you')) return true;
        var s=simOf(tr);
        if(hideLow && s==='baixo') return false;
        if(hideMed && s==='medio') return false;
        return true;
      });
    }
    function render(){
      var all=rows();
      var vis=visRows();
      var pages=size?Math.max(1,Math.ceil(vis.length/size)):1;
      if(page>pages-1)page=pages-1;
      if(page<0)page=0;
      all.forEach(function(tr){ tr.style.display='none'; });
      vis.forEach(function(tr,i){
        var on=!size||(i>=page*size && i<(page+1)*size);
        tr.style.display=on?'':'none';
      });
      if(status&&size){
        status.textContent='Top '+(vis.length?page*size+1:0)+'–'+Math.min(vis.length,(page+1)*size)+' de '+vis.length;
      }
      if(prev) prev.disabled=page<=0;
      if(next) next.disabled=page>=pages-1;
    }
    function parseSort(td){
      if(!td) return {empty:true,n:0,s:''};
      var raw=td.getAttribute('data-sort');
      if(raw!==null && raw!==''){
        var n=parseFloat(raw);
        if(!isNaN(n)) return {empty:false,n:n,s:''};
        return {empty:false,n:0,s:String(raw).toLowerCase()};
      }
      var t=(td.textContent||'').replace(/\\s+/g,' ').trim();
      if(!t || t==='—' || t==='-') return {empty:true,n:0,s:''};
      var n=parseFloat(t.replace(/[%+,]/g,'').replace(/\\s/g,''));
      if(!isNaN(n) && /\\d/.test(t)) return {empty:false,n:n,s:''};
      return {empty:false,n:0,s:t.toLowerCase()};
    }
    function sortBy(col){
      if(sortCol===col) sortDir=sortDir==='desc'?'asc':'desc';
      else {sortCol=col;sortDir='desc';}
      var all=rows();
      all.sort(function(a,b){
        var va=parseSort(a.children[col]);
        var vb=parseSort(b.children[col]);
        if(va.empty&&vb.empty) return 0;
        if(va.empty) return 1;
        if(vb.empty) return -1;
        var cmp=(va.s||vb.s)?va.s.localeCompare(vb.s):(va.n-vb.n);
        return sortDir==='desc'?-cmp:cmp;
      });
      all.forEach(function(tr){tbody.appendChild(tr);});
      table.querySelectorAll('thead th').forEach(function(th,i){
        th.classList.toggle('is-sorted-desc', i===col && sortDir==='desc');
        th.classList.toggle('is-sorted-asc', i===col && sortDir==='asc');
      });
      page=0;
      render();
    }
    function hideCol(col){
      var th=table.querySelectorAll('thead th')[col];
      if(!th) return;
      var key=th.getAttribute('data-col')||('c'+col);
      table.querySelectorAll('[data-col="'+key+'"]').forEach(function(el){el.setAttribute('data-hidden','1');});
      if(!tray) return;
      tray.hidden=false;
      if(tray.querySelector('[data-restore="'+key+'"]')) return;
      var chip=document.createElement('button');
      chip.type='button';
      chip.className='hidden-chip';
      chip.setAttribute('data-restore',key);
      var label=(th.querySelector('.th-label')||th).textContent.replace('×','').trim();
      chip.textContent='Mostrar '+label;
      tray.appendChild(chip);
    }
    function showCol(key){
      table.querySelectorAll('[data-col="'+key+'"]').forEach(function(el){el.removeAttribute('data-hidden');});
      if(!tray) return;
      var chip=tray.querySelector('[data-restore="'+key+'"]');
      if(chip) chip.remove();
      if(!tray.children.length) tray.hidden=true;
    }
    var head=table.tHead;
    if(head && wrap.classList.contains('interactive-table')){
      var dragKey='';
      var didDrag=false;
      function colKey(el){ return el ? (el.getAttribute('data-col')||'') : ''; }
      function frozenKey(key){ return key==='idx' || key==='company'; }
      function saveOrder(){
        if(!card) return;
        var keys=[].slice.call(table.querySelectorAll('thead th')).map(colKey).filter(Boolean);
        try{ localStorage.setItem('spy-col-order', JSON.stringify(keys)); }catch(e){}
      }
      function applyOrder(keys){
        if(!keys || !keys.length) return;
        var have=[].slice.call(table.querySelectorAll('thead th')).map(colKey);
        var frozen=['idx','company'].filter(function(k){ return have.indexOf(k)>=0; });
        var rest=keys.filter(function(k){ return frozen.indexOf(k)<0 && have.indexOf(k)>=0; });
        have.forEach(function(k){ if(frozen.indexOf(k)<0 && rest.indexOf(k)<0) rest.push(k); });
        var final=frozen.concat(rest);
        [].slice.call(table.querySelectorAll('thead tr, tbody tr')).forEach(function(row){
          final.forEach(function(k){
            var cell=row.querySelector('[data-col="'+k+'"]');
            if(cell) row.appendChild(cell);
          });
        });
      }
      function moveCol(fromKey, toKey, after){
        if(!fromKey || !toKey || fromKey===toKey || frozenKey(fromKey)) return;
        if(frozenKey(toKey)){ after=true; toKey='company'; }
        [].slice.call(table.querySelectorAll('thead tr, tbody tr')).forEach(function(row){
          var from=row.querySelector('[data-col="'+fromKey+'"]');
          var to=row.querySelector('[data-col="'+toKey+'"]');
          if(!from || !to) return;
          if(after && to.nextSibling) row.insertBefore(from, to.nextSibling);
          else if(after) row.appendChild(from);
          else row.insertBefore(from, to);
        });
        saveOrder();
      }
      try{
        var saved=JSON.parse(localStorage.getItem('spy-col-order')||'[]');
        if(saved && saved.length) applyOrder(saved);
      }catch(e){}
      head.addEventListener('dragstart',function(ev){
        var handle=ev.target.closest('.col-drag');
        var th=ev.target.closest('th');
        if(!handle || !th){ ev.preventDefault(); return; }
        dragKey=colKey(th);
        if(!dragKey || frozenKey(dragKey)){ ev.preventDefault(); return; }
        didDrag=false;
        th.classList.add('is-dragging');
        ev.dataTransfer.effectAllowed='move';
        ev.dataTransfer.setData('text/plain', dragKey);
      });
      head.addEventListener('dragend',function(){
        table.querySelectorAll('thead th').forEach(function(th){
          th.classList.remove('is-dragging','drop-before','drop-after');
        });
        dragKey='';
      });
      head.addEventListener('dragover',function(ev){
        if(!dragKey) return;
        var th=ev.target.closest('th');
        if(!th) return;
        ev.preventDefault();
        didDrag=true;
        var mid=th.getBoundingClientRect().left + th.offsetWidth/2;
        var after=ev.clientX>mid;
        table.querySelectorAll('thead th').forEach(function(el){
          el.classList.toggle('drop-before', el===th && !after);
          el.classList.toggle('drop-after', el===th && after);
        });
      });
      head.addEventListener('drop',function(ev){
        ev.preventDefault();
        var th=ev.target.closest('th');
        if(!th || !dragKey) return;
        var toKey=colKey(th);
        var mid=th.getBoundingClientRect().left + th.offsetWidth/2;
        moveCol(dragKey, toKey, ev.clientX>mid);
        table.querySelectorAll('thead th').forEach(function(el){
          el.classList.remove('is-dragging','drop-before','drop-after');
        });
      });
      head.addEventListener('click',function(ev){
        if(didDrag){ didDrag=false; ev.preventDefault(); return; }
        var hideBtn=ev.target.closest('.col-hide');
        if(ev.target.closest('.col-drag')) return;
        var th=ev.target.closest('th');
        if(!th) return;
        var col=[].indexOf.call(th.parentNode.children, th);
        if(col<0) return;
        if(ev.target.closest('.col-help')) return;
        if(hideBtn){ev.preventDefault();hideCol(col);return;}
        sortBy(col);
      });
    }
    if(tray){
      tray.addEventListener('click',function(ev){
        var chip=ev.target.closest('[data-restore]');
        if(chip) showCol(chip.getAttribute('data-restore'));
      });
    }
    if(prev) prev.addEventListener('click',function(){ if(page>0){page--;render();}});
    if(next) next.addEventListener('click',function(){
      var pages=size?Math.max(1,Math.ceil(visRows().length/size)):1;
      if(page<pages-1){page++;render();}
    });
    if(card){
      card.addEventListener('click',function(ev){
        var btn=ev.target.closest('.sim-filter');
        if(!btn) return;
        var key=btn.getAttribute('data-hide');
        btn.classList.toggle('is-active');
        if(key==='baixo') hideLow=btn.classList.contains('is-active');
        if(key==='medio') hideMed=btn.classList.contains('is-active');
        page=0;
        render();
      });
    }
    render();
  });
})();
(function(){
  var card=document.getElementById('sec-competitors');
  if(!card)return;
  card.addEventListener('click',function(ev){
    var btn=ev.target.closest('.comp-view');
    if(!btn)return;
    card.setAttribute('data-view', btn.getAttribute('data-view')||'compact');
    card.querySelectorAll('.comp-view').forEach(function(b){b.classList.toggle('is-active', b===btn);});
  });
})();
(function(){
  var card=document.getElementById('sec-competitors');
  if(!card) return;
  var runId=card.getAttribute('data-run-id')||'';
  if(!runId) return;
  function postJson(path, payload){
    return fetch(path,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload||{})
    }).then(function(r){ return r.json().then(function(d){ if(!r.ok||d.error) throw new Error(d.error||('HTTP '+r.status)); return d; }); });
  }
  card.addEventListener('change',function(ev){
    var sel=ev.target.closest('.sim-edit');
    if(!sel) return;
    sel.disabled=true;
    postJson('/api/runs/'+runId+'/competitors/classify',{
      domain:sel.getAttribute('data-domain')||'',
      similaridade:sel.value
    }).then(function(){ location.reload(); })
      .catch(function(err){ alert(err.message||err); sel.disabled=false; });
  });
  var form=card.querySelector('#add-competitor');
  if(!form) return;
  var area=form.querySelector('[name=urls]');
  var btn=form.querySelector('button[type=submit]');
  var st=form.querySelector('.add-status');
  var preview=form.querySelector('.add-preview');
  var log=form.querySelector('.add-log');
  function existingDomains(){
    var have={};
    card.querySelectorAll('tr[data-domain]').forEach(function(tr){
      var d=String(tr.getAttribute('data-domain')||'').toLowerCase();
      if(d) have[d]=1;
    });
    return have;
  }
  function hostOf(item){
    var host=String(item||'').trim();
    if(!host || host.charAt(0)==='#') return '';
    host=host.replace(/^https?:\\/\\//i,'').replace(/^www\\./i,'').split('/')[0].toLowerCase();
    host=host.replace(/:\\d+$/,'');
    if(!host || host.indexOf('.')<0) return '';
    return host;
  }
  function analyzeSites(text){
    var parts=String(text||'').split(/[\\s,;|]+/);
    var have=existingDomains();
    var seen={}, unique=[], fresh=[];
    var raw=0, repeatInPaste=0, already=0;
    parts.forEach(function(item){
      var host=hostOf(item);
      if(!host) return;
      raw++;
      if(seen[host]){ repeatInPaste++; return; }
      seen[host]=1;
      var site={domain:host, url:'https://'+host};
      unique.push(site);
      if(have[host]){ already++; return; }
      fresh.push(site);
    });
    return {raw:raw, unique:unique, fresh:fresh, repeatInPaste:repeatInPaste, already:already};
  }
  function parseSites(text){
    return analyzeSites(text).fresh;
  }
  function describeClean(info){
    var bits=[];
    if(info.repeatInPaste) bits.push(info.repeatInPaste+' repetido'+(info.repeatInPaste>1?'s':'')+' na cola');
    if(info.already) bits.push(info.already+' já na tabela');
    if(!bits.length) return '';
    return 'Removidos da lista: '+bits.join(' · ')+'. Restam '+info.fresh.length+'.';
  }
  function cleanList(opts){
    opts=opts||{};
    if(!area) return analyzeSites('');
    var info=analyzeSites(area.value);
    var next=info.fresh.map(function(s){ return s.domain; }).join('\\n');
    if(area.value!==next) area.value=next;
    if(st && (opts.announce || info.repeatInPaste || info.already)){
      st.textContent=describeClean(info) || (info.fresh.length?info.fresh.length+' sites novos.':'');
    }
    return info;
  }
  function refreshPreview(){
    if(!preview || !area) return;
    var info=analyzeSites(area.value);
    var sites=info.fresh;
    preview.innerHTML='';
    if(!sites.length){
      preview.hidden=true;
      if(btn) btn.textContent='Add websites';
      return;
    }
    preview.hidden=false;
    sites.forEach(function(s){
      var chip=document.createElement('span');
      chip.className='add-chip';
      chip.textContent=s.domain;
      preview.appendChild(chip);
    });
    if(btn) btn.textContent=sites.length===1?'Add 1 website':'Add '+sites.length+' websites';
  }
  function addLog(cls, text){
    if(!log) return;
    log.hidden=false;
    var li=document.createElement('li');
    li.className=cls||'';
    li.textContent=text;
    log.appendChild(li);
    log.scrollTop=log.scrollHeight;
    return li;
  }
  if(area){
    area.addEventListener('paste',function(){
      setTimeout(function(){ cleanList({announce:true}); refreshPreview(); },0);
    });
    area.addEventListener('blur',function(){ cleanList({announce:true}); refreshPreview(); });
    area.addEventListener('input',refreshPreview);
    refreshPreview();
  }
  form.addEventListener('submit',function(ev){
    ev.preventDefault();
    var info=cleanList({announce:true});
    refreshPreview();
    var sites=info.fresh;
    var sim=(form.querySelector('[name=similaridade]')||{}).value||'';
    var queue=sites;
    var skipped=info.already+info.repeatInPaste;
    if(!sites.length){
      if(st) st.textContent=describeClean(info) || 'Cole um ou mais sites válidos.';
      return;
    }
    if(btn) btn.disabled=true;
    if(area) area.disabled=true;
    if(log){ log.innerHTML=''; log.hidden=false; }
    if(skipped) addLog('skip', describeClean(info));
    var i=0, added=0, failed=0;
    function next(){
      if(i>=queue.length){
        if(st) st.textContent=added+' added · '+failed+' failed · '+skipped+' skipped. Reloading…';
        if(added){ location.reload(); return; }
        if(btn) btn.disabled=false;
        if(area) area.disabled=false;
        return;
      }
      var site=queue[i];
      var n=i+1;
      if(st) st.textContent='Adding '+n+'/'+queue.length+' — '+site.domain+' (page + Brand'+(sim==='Alto'?' + SimilarWeb':'')+')…';
      var row=addLog('run', n+'/'+queue.length+' '+site.domain+'…');
      postJson('/api/runs/'+runId+'/competitors/add',{url:site.url,similaridade:sim})
        .then(function(d){
          if(d && d.skipped){
            skipped++;
            if(row){ row.className='skip'; row.textContent=site.domain+' — already on the list'; }
          } else {
            added++;
            if(row){ row.className='ok'; row.textContent=site.domain+' — added'+(d && d.similaridade?' · '+d.similaridade:''); }
          }
        })
        .catch(function(err){
          failed++;
          if(row){ row.className='err'; row.textContent=site.domain+' — '+(err.message||err); }
        })
        .then(function(){ i++; next(); });
    }
    next();
  });
})();
(function(){
  var tip=document.querySelector('.float-tip');
  if(!tip){
    tip=document.createElement('div');
    tip.className='float-tip';
    tip.hidden=true;
    document.body.appendChild(tip);
  }
  function hide(){ tip.hidden=true; }
  function show(el){
    var text=el.getAttribute('data-tip')||'';
    if(!text){ hide(); return; }
    tip.textContent=text;
    tip.hidden=false;
    var r=el.getBoundingClientRect();
    var left=Math.min(window.innerWidth-tip.offsetWidth-8, Math.max(8, r.left+r.width/2-tip.offsetWidth/2));
    var top=r.bottom+8;
    if(top+tip.offsetHeight>window.innerHeight-8) top=Math.max(8, r.top-tip.offsetHeight-8);
    tip.style.left=left+'px';
    tip.style.top=top+'px';
  }
  document.addEventListener('mouseover',function(ev){
    var el=ev.target.closest('[data-tip]');
    if(el) show(el); else if(!ev.target.closest('.float-tip')) hide();
  });
  document.addEventListener('focusin',function(ev){
    var el=ev.target.closest('[data-tip]');
    if(el) show(el);
  });
  document.addEventListener('scroll',hide,true);
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
