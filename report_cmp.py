# -*- coding: utf-8 -*-
"""Perfil da empresa + scoreboard de concorrentes (concorrentes-completo.html)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from report_analysis_compare import COLORS, MAX_COMPANIES

SCORE_LVL = {"high": 3, "medium": 2, "low": 1, "0": 0}

GROUPS = (
    ("paid", "Mídia paga", "g-paid", (("google", "Google"), ("meta", "Meta"), ("li_ads", "LinkedIn"))),
    ("org", "Orgânico", "g-org", (("seo", "SEO"), ("x", "X"), ("ig", "Insta"), ("li", "LinkedIn"), ("yt", "YouTube"), ("tt", "TikTok"), ("rd", "Reddit"))),
    ("inf", "Influenciadores", "g-inf", (("yt_inf", "YouTube"), ("ig_inf", "Insta"), ("tt_inf", "TikTok"))),
)
LBL = ("Sem presença", "Baixo", "Médio", "Alto")
FULL = {
    "x": "X",
    "ig": "Instagram",
    "ig_inf": "Instagram",
    "li": "LinkedIn",
    "li_ads": "LinkedIn",
    "yt": "YouTube",
    "yt_inf": "YouTube",
    "tt_inf": "TikTok",
    "tt": "TikTok",
    "rd": "Reddit",
    "seo": "SEO",
    "google": "Google",
    "meta": "Meta",
}
MAC_SHORT = {"paid": "Pago", "org": "Orgânico", "inf": "Influência"}
UNIT_L = {
    "seo": "visitas/mês",
    "rd": "comentários",
    "visits": "visitas/mês",
    "brand": "buscas/mês",
}
QG_CHANS = (
    ("visits", "Popularidade", "Visitas"),
    ("brand", "Popularidade", "Busca pela marca"),
) + tuple(
    (mk, label, FULL.get(mk, lab))
    for _k, label, _cls, subs in GROUPS
    for mk, lab in subs
)
UNIT = {
    "google": "anúncios",
    "meta": "anúncios",
    "li_ads": "anúncios",
    "seo": "visitas",
    "x": "seguidores",
    "ig": "seguidores",
    "li": "seguidores",
    "yt": "inscritos",
    "tt": "seguidores",
    "rd": "coment.",
    "yt_inf": "views",
    "ig_inf": "curtidas",
    "tt_inf": "views",
}

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
    "tt_inf": "tiktok_influencers",
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


def _fmt_cmp(n: Any) -> str:
    if n is None or n == "":
        return "—"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 1e6:
        s = f"{v / 1e6:.1f}" if abs(v) >= 1e7 else f"{v / 1e6:.2f}"
        return s.rstrip("0").rstrip(".").replace(".", ",") + "M"
    if abs(v) >= 1e3:
        s = f"{v / 1e3:.0f}" if abs(v) >= 1e5 else f"{v / 1e3:.1f}"
        return s.replace(".0", "").replace(".", ",") + "k"
    return str(int(round(v)))


def _pct_cmp(p: Any) -> str:
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    digits = 0 if abs(v) >= 100 else 1
    return f"{sign}{abs(v):.{digits}f}%".replace(".", ",")


def _group_level(row: dict[str, Any], subs: tuple[tuple[str, str], ...]) -> Optional[int]:
    """Category score = strongest collected channel (at least one Alto → Alto)."""
    vals = [row.get("s", {}).get(k) for k, _ in subs]
    nums: list[int] = []
    for v in vals:
        if v is None:
            continue
        try:
            nums.append(int(v))
        except (TypeError, ValueError):
            continue
    if not nums:
        return None
    return max(nums)


def _lvl_cell_cls(v: Any) -> str:
    if v is None:
        return " isna"
    try:
        n = int(v)
    except (TypeError, ValueError):
        return " isna"
    if n == 0:
        return " isz isl0"
    return f" isl{n}"


def _bars_html(vals: list[Any], labels: list[str]) -> str:
    from report_html import _esc

    nums = []
    for v in vals:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            nums.append(0.0)
    if not nums:
        return '<p class="sec-note">Sem série histórica.</p>'
    mx = max(nums + [1.0])
    bars = "".join(
        f'<span><b class="num">{_esc(_fmt_cmp(v))}</b>'
        f'<i style="height:{max(v / mx * 100, 0.5):.1f}%"></i></span>'
        for v in nums
    )
    labs = "".join(f"<span>{_esc(l)}</span>" for l in labels[: len(nums)])
    return f'<div class="pf2-bars">{bars}</div><div class="pf2-bl">{labs}</div>'


def _m3_html(lvl: Any, *, big: bool = False) -> str:
    if lvl is None:
        return '<span class="na">n/c</span>'
    try:
        n = int(lvl)
    except (TypeError, ValueError):
        return '<span class="na">n/c</span>'
    lab = LBL[n] if 0 <= n < len(LBL) else ""
    cls = "z" if n == 0 else f"l{n}"
    bigc = "big " if big else ""
    return f'<span class="m3 {bigc}{cls}" role="img" aria-label="{lab}"><i></i><i></i><i></i></span>'


def _legend_v4_html() -> str:
    return (
        '<span>Escala:</span>'
        + "".join(f"<span>{_m3_html(l)}{LBL[l]}</span>" for l in (3, 2, 1, 0))
        + '<span><span class="na">n/c</span>Não coletado</span>'
    )


def build_pcard_html(payload: dict[str, Any], *, profile_only: bool = False, variant: str = "v4") -> str:
    from report_html import _esc

    rows = payload.get("rows") or []
    if not rows:
        return ""
    row = next((r for r in rows if r.get("me")), rows[0])
    me = next((r for r in rows if r.get("me")), None)
    scores = row.get("s") or {}
    data = row.get("d") or {}
    warns = row.get("w") or {}
    series = row.get("series") or {}
    v_series = list(series.get("v") or [])
    b_series = list(series.get("b") or [])
    tag = '<span class="you">você</span>' if row.get("me") else ""
    host = str(row.get("dom") or "")
    href = host if "://" in host else (f"https://{host}" if host else "")
    dm = (
        f'<a class="dm" href="{_esc(href)}/" target="_blank" rel="noopener">{_esc(host)} ↗</a>'
        if href
        else (f'<span class="dm">{_esc(host)}</span>' if host else "")
    )
    nav = (
        ""
        if profile_only or len(rows) < 2
        else (
            '<div class="nav2">'
            '<button type="button" data-step="-1" aria-label="Empresa anterior">‹</button>'
            '<button type="button" data-step="1" aria-label="Próxima empresa">›</button>'
            "</div>"
        )
    )
    is_v4 = variant != "v3"
    macros = []
    for _k, label, cls, subs in GROUPS:
        lv = _group_level(row, subs)
        segs = "".join('<i class="on"></i>' if lv is not None and i < lv else "<i></i>" for i in range(3))
        tags = []
        for mk, lab in subs:
            v = scores.get(mk)
            w = warns.get(mk)
            dv = data.get(mk)
            full = FULL.get(mk, lab)
            if v is None:
                title = f"{full}: não coletado"
                if is_v4:
                    tags.append(
                        f'<span class="pt3 pna" title="{_esc(title)}">{_esc(full)}<span class="pt-s">n/c</span></span>'
                    )
                else:
                    tags.append(
                        f'<span class="pt na" title="{_esc(title)}">{_esc(lab)}<span class="pt-s">n/c</span></span>'
                    )
                continue
            try:
                lvl = int(v)
            except (TypeError, ValueError):
                lvl = 0
            tip_n = f"{int(dv):,} {UNIT.get(mk, '')} · " if isinstance(dv, (int, float)) else ""
            title = f"{full}: {tip_n}{LBL[lvl] if 0 <= lvl < len(LBL) else ''}{(' — verificar: ' + str(w)) if w else ''}"
            warn = '<span class="warn" style="margin:0">!</span>' if w else ""
            if is_v4:
                zcls = " z" if lvl == 0 else ""
                tags.append(
                    f'<span class="pt3 lv{lvl}{zcls}" title="{_esc(title)}">{_esc(full)}'
                    f'<b class="num">{_esc(_fmt_cmp(dv))}</b>{_m3_html(lvl)}{warn}</span>'
                )
            else:
                dots = "".join('<i class="on"></i>' if i < lvl else "<i></i>" for i in range(3))
                zcls = " z" if lvl == 0 else ""
                tags.append(
                    f'<span class="pt{zcls}" title="{_esc(title)}">{_esc(lab)}'
                    f'<span class="pt-m" aria-label="{_esc(LBL[lvl] if 0 <= lvl < len(LBL) else "")}">{dots}</span>'
                    f'{warn}</span>'
                )
        lv_lab = "—" if lv is None else LBL[lv]
        zlab = " z" if lv == 0 else ""
        lvl_cls = f" lvl{lv}" if is_v4 and lv is not None else ""
        macros.append(
            f'<div class="pm {cls}{lvl_cls}"><div class="pm-h"><b>{_esc(label)}</b>'
            f'<span class="pm-l{zlab}">{_esc(lv_lab)}</span>'
            f'<span class="pm-m" role="img" aria-label="{_esc(lv_lab)}">{segs}</span></div>'
            f'<div class="pm-t">{"".join(tags)}</div></div>'
        )
    vg = row.get("vg") or 0
    bg = row.get("bg") or 0
    try:
        vg_f = float(vg)
    except (TypeError, ValueError):
        vg_f = 0.0
    try:
        bg_f = float(bg)
    except (TypeError, ValueError):
        bg_f = 0.0
    dcls = lambda p: "" if p >= 0 else ' style="background:#FDF0EF;color:var(--down)"'
    v_last = v_series[-1] if v_series else row.get("visits")
    b_last = b_series[-1] if b_series else row.get("brand")
    ref_v = (
        f'<div class="ref">você: <b class="num">{_esc(_fmt_cmp(me.get("visits")))}</b></div>'
        if me and not row.get("me")
        else ""
    )
    ref_b = (
        f'<div class="ref">você: <b class="num">{_esc(_fmt_cmp(me.get("brand")))}</b></div>'
        if me and not row.get("me")
        else ""
    )
    legend = f'<div class="pf-legend">{_legend_v4_html()}</div>' if is_v4 else ""
    return f"""
    <div class="ch2"><span class="cdot" style="background:{_esc(row.get("color") or "#9AA3AE")};width:11px;height:11px"></span><b>{_esc(row.get("name") or "—")}</b>{tag}{dm}{nav}</div>
    {legend}
    <div class="pf2">
      <div class="pf2-col"><div class="pf-lab">Força por categoria</div>{"".join(macros)}</div>
      <div class="pf2-col pf2-chart"><div class="pf-lab">Visitas · SimilarWeb</div>
        <div class="pf2-top"><span class="pf2-v num">{_esc(_fmt_cmp(v_last))}<small>/mês</small></span><span class="pf2-d num"{dcls(vg_f)}>{_esc(_pct_cmp(vg_f))} no período</span></div>
        {ref_v}{_bars_html(v_series, list(payload.get("visit_labels") or []))}</div>
      <div class="pf2-col pf2-chart"><div class="pf-lab">Busca pela marca · DataForSEO</div>
        <div class="pf2-top"><span class="pf2-v num">{_esc(_fmt_cmp(b_last))}<small>/mês</small></span><span class="pf2-d num"{dcls(bg_f)}>{_esc(_pct_cmp(bg_f))} em 1 ano</span></div>
        {ref_b}{_bars_html(b_series, list(payload.get("brand_labels") or []))}</div>
    </div>"""


def _meter_html(lvl: Any) -> str:
    if lvl is None:
        return '<span class="na">n/c</span>'
    try:
        n = int(lvl)
    except (TypeError, ValueError):
        return '<span class="na">n/c</span>'
    cls = "z" if n == 0 else f"on{n}"
    lab = LBL[n] if 0 <= n < len(LBL) else ""
    return f'<span class="m {cls}" role="img" aria-label="{lab}"><i></i><i></i><i></i></span>'


def _sb(key: str, label: str, title: str = "") -> str:
    from report_html import _esc

    return (
        f'<button type="button" class="sb" data-sort="{_esc(key)}" title="{_esc(title)}">'
        f"{label}<span class=\"ar\"></span></button>"
    )


def _prep_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    rows = list(payload.get("rows") or [])
    for r in rows:
        scores = r.get("s") or {}
        for gk, _lab, _cls, subs in GROUPS:
            r[f"m_{gk}"] = _group_level({"s": scores}, subs)
    me = [r for r in rows if r.get("me")]
    rest = [r for r in rows if not r.get("me")]
    ordered = me + rest
    sel = next((r.get("name") for r in me), ordered[0].get("name") if ordered else "")
    return rows, ordered, str(sel or "")


def build_table_html(payload: dict[str, Any], *, variant: str = "v4") -> str:
    from report_html import _esc

    rows, ordered, sel = _prep_rows(payload)
    if not rows:
        return ""
    if variant != "v3":
        return _build_table_html_v4(rows, ordered, sel)

    best_v = max((float(r.get("visits") or 0) for r in rows), default=0)
    best_b = max((float(r.get("brand") or 0) for r in rows), default=0)

    h = (
        '<thead><tr class="grp"><th class="co" rowspan="2" style="padding:10px 14px;vertical-align:bottom">Empresa</th>'
        '<th rowspan="2" class="r" style="padding:10px 12px;vertical-align:bottom">'
        + _sb("visits", "Visitas", "Visitas/mês e variação no período")
        + "</th>"
        '<th rowspan="2" class="r" style="padding:10px 12px;vertical-align:bottom">'
        + _sb("brand", "Marca", "Buscas/mês e variação em 1 ano")
        + "</th>"
    )
    for _gk, label, cls, subs in GROUPS:
        h += f'<th class="gc mac {cls}" colspan="{len(subs) + 1}" data-span="{len(subs) + 1}">{_esc(label)}</th>'
    h += '</tr><tr class="colrow">'
    for gk, _label, cls, subs in GROUPS:
        h += f'<th class="gc mac c {cls}">{_sb("m_" + gk, "Geral", "Melhor canal da categoria")}</th>'
        for mk, lab in subs:
            h += f'<th class="gc c subc {cls}">{_sb(mk, lab)}</th>'
    h += "</tr></thead><tbody>"

    for i, r in enumerate(ordered):
        name = str(r.get("name") or "—")
        tag = '<span class="you">você</span>' if r.get("me") else ""
        tr_cls = ("me" if r.get("me") else "") + (" sel" if name == sel else "")
        vg = r.get("vg") or 0
        bg = r.get("bg") or 0
        try:
            vg_f = float(vg)
        except (TypeError, ValueError):
            vg_f = 0.0
        try:
            bg_f = float(bg)
        except (TypeError, ValueError):
            bg_f = 0.0
        kd = lambda v: (
            f'<span class="kd {"up" if v > 0.5 else ("dn" if v < -0.5 else "fl")}">{_esc(_pct_cmp(v))}</span>'
        )
        visits = r.get("visits") or 0
        brand = r.get("brand") or 0
        h += (
            f'<tr class="{tr_cls.strip()}"><td class="co" data-pick="{_esc(name)}" title="Ver perfil de {_esc(name)}">'
            f'<div class="cn"><span class="rk num">{"" if r.get("me") else i}</span>'
            f'<span class="cdot" style="background:{_esc(r.get("color") or "#9AA3AE")}"></span>'
            f'<span class="nm">{_esc(name)}</span>{tag}</div>'
            f'<div class="dom">{_esc(r.get("dom") or "")}</div></td>'
        )
        star_v = '<span class="best" title="Maior da coluna"></span>' if visits == best_v and visits else ""
        star_b = '<span class="best" title="Maior da coluna"></span>' if brand == best_b and brand else ""
        h += f'<td class="kpi num"><div class="kv">{star_v}{_esc(_fmt_cmp(visits))}</div>{kd(vg_f)}</td>'
        h += f'<td class="kpi num"><div class="kv">{star_b}{_esc(_fmt_cmp(brand))}</div>{kd(bg_f)}</td>'
        scores = r.get("s") or {}
        data = r.get("d") or {}
        warns = r.get("w") or {}
        for gk, _lab, cls, subs in GROUPS:
            mv = r.get(f"m_{gk}")
            ml = "—" if mv is None else LBL[mv]
            h += (
                f'<td class="macv c {cls}{_lvl_cell_cls(mv)}">{_meter_html(mv)}'
                f'<span class="ml{" z" if mv == 0 else ""}">{_esc(ml)}</span></td>'
            )
            for mk, lab in subs:
                v = scores.get(mk)
                w = warns.get(mk)
                dv = data.get(mk)
                if v is None:
                    tip = f"{name} · {lab}: não coletado"
                else:
                    try:
                        lvl = int(v)
                    except (TypeError, ValueError):
                        lvl = 0
                    tip_n = f"{int(dv):,} {UNIT.get(mk, '')} · " if isinstance(dv, (int, float)) else ""
                    tip = f"{name} · {lab}: {tip_n}{LBL[lvl] if 0 <= lvl < len(LBL) else ''}"
                if w:
                    tip += f" — {w}"
                body = _meter_html(v)
                warn = f'<span class="warn" aria-label="Verificar: {_esc(w)}">!</span>' if w else ""
                h += (
                    f'<td class="cell subc {cls}{_lvl_cell_cls(v)}" '
                    f'title="{_esc(tip)}">{body}{warn}</td>'
                )
        h += "</tr>"

    def _mean(vals: list[Any]) -> Optional[int]:
        nums = []
        for v in vals:
            if v is None:
                continue
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                continue
        if not nums:
            return None
        return int(round(sum(nums) / len(nums)))

    h += '</tbody><tfoot><tr><td class="co">Média do grupo</td>'
    mean_vis = _mean([r.get("visits") for r in rows])
    mean_br = _mean([r.get("brand") for r in rows])
    h += f'<td class="kpi num">{_esc(_fmt_cmp(mean_vis))}</td><td class="kpi num">{_esc(_fmt_cmp(mean_br))}</td>'
    for gk, _lab, cls, subs in GROUPS:
        h += f'<td class="macv c {cls}">{_meter_html(_mean([r.get(f"m_{gk}") for r in rows]))}</td>'
        for mk, _lab2 in subs:
            h += f'<td class="cell subc {cls}">{_meter_html(_mean([(r.get("s") or {}).get(mk) for r in rows]))}</td>'
    h += "</tr></tfoot>"
    return h


def _build_table_html_v4(rows: list[dict[str, Any]], ordered: list[dict[str, Any]], sel: str) -> str:
    from report_html import _esc

    best_v = max((float(r.get("visits") or 0) for r in rows), default=0)
    best_b = max((float(r.get("brand") or 0) for r in rows), default=0)

    h = (
        '<colgroup><col class="c-co"><col class="c-kpi"><col class="c-kpi"></colgroup>'
        '<thead><tr class="grp"><th class="co" rowspan="2" style="padding:10px 14px;vertical-align:bottom">Empresa</th>'
        '<th rowspan="2" class="r" style="padding:10px 12px;vertical-align:bottom">'
        + _sb("visits", "Visitas", "Visitas/mês e variação no período")
        + "</th>"
        '<th rowspan="2" class="r" style="padding:10px 12px;vertical-align:bottom">'
        + _sb("brand", "Marca", "Buscas/mês e variação em 1 ano")
        + "</th>"
        f'<th class="hg hsum" colspan="{len(GROUPS)}">Resumo geral</th>'
    )
    for _gk, label, cls, subs in GROUPS:
        h += f'<th class="hg subc {cls}" colspan="{len(subs)}">{_esc(label)}</th>'
    h += '</tr><tr class="colrow">'
    for gi, (gk, _label, cls, _subs) in enumerate(GROUPS):
        short = MAC_SHORT.get(gk, "Geral")
        h += (
            f'<th class="hsc {cls}{" c0" if gi == 0 else ""}">'
            f'{_sb("m_" + gk, short, "Melhor canal da categoria")}</th>'
        )
    for _gk, _label, cls, subs in GROUPS:
        for si, (mk, lab) in enumerate(subs):
            h += (
                f'<th class="hcs subc {cls}{" c0" if si == 0 else ""}">'
                f'{_sb(mk, lab)}<span class="un">{_esc(UNIT.get(mk, ""))}</span></th>'
            )
    h += "</tr></thead><tbody>"

    for i, r in enumerate(ordered):
        name = str(r.get("name") or "—")
        tag = '<span class="you">você</span>' if r.get("me") else ""
        tr_cls = ("me" if r.get("me") else "") + (" sel" if name == sel else "")
        vg = r.get("vg") or 0
        bg = r.get("bg") or 0
        try:
            vg_f = float(vg)
        except (TypeError, ValueError):
            vg_f = 0.0
        try:
            bg_f = float(bg)
        except (TypeError, ValueError):
            bg_f = 0.0
        kd = lambda v: (
            f'<span class="kd {"up" if v > 0.5 else ("dn" if v < -0.5 else "fl")}">{_esc(_pct_cmp(v))}</span>'
        )
        visits = r.get("visits") or 0
        brand = r.get("brand") or 0
        h += (
            f'<tr class="{tr_cls.strip()}"><td class="co" data-pick="{_esc(name)}" title="Ver perfil de {_esc(name)}">'
            f'<div class="cn"><span class="rk num">{"" if r.get("me") else i}</span>'
            f'<span class="cdot" style="background:{_esc(r.get("color") or "#9AA3AE")}"></span>'
            f'<span class="nm">{_esc(name)}</span>{tag}</div>'
            f'<div class="dom">{_esc(r.get("dom") or "")}</div></td>'
        )
        star_v = '<span class="best" title="Maior da coluna"></span>' if visits == best_v and visits else ""
        star_b = '<span class="best" title="Maior da coluna"></span>' if brand == best_b and brand else ""
        h += f'<td class="kpi num"><div class="kv">{star_v}{_esc(_fmt_cmp(visits))}</div>{kd(vg_f)}</td>'
        h += f'<td class="kpi num"><div class="kv">{star_b}{_esc(_fmt_cmp(brand))}</div>{kd(bg_f)}</td>'
        scores = r.get("s") or {}
        data = r.get("d") or {}
        warns = r.get("w") or {}
        for gi, (gk, label, cls, _subs) in enumerate(GROUPS):
            mv = r.get(f"m_{gk}")
            lab = "—" if mv is None else LBL[mv]
            h += (
                f'<td class="hcell sumc {cls}{" c0" if gi == 0 else ""}{_lvl_cell_cls(mv)}" '
                f'title="{_esc(name)} · {_esc(label)}: {_esc(lab)}">'
                f'<span class="cw">{_m3_html(mv, big=True)}<span class="lt L{mv if mv is not None else ""}">{_esc(lab)}</span></span></td>'
            )
        for _gk, _label, cls, subs in GROUPS:
            for si, (mk, lab) in enumerate(subs):
                v = scores.get(mk)
                w = warns.get(mk)
                dv = data.get(mk)
                if v is None:
                    tip = f"{name} · {lab}: não coletado"
                    txt = ""
                else:
                    try:
                        lvl = int(v)
                    except (TypeError, ValueError):
                        lvl = 0
                    tip_n = f"{int(dv):,} {UNIT.get(mk, '')} · " if isinstance(dv, (int, float)) else ""
                    tip = f"{name} · {lab}: {tip_n}{LBL[lvl] if 0 <= lvl < len(LBL) else ''}"
                    txt = _fmt_cmp(dv)
                if w:
                    tip += f" — {w}"
                warn = f'<span class="hw" aria-label="Verificar: {_esc(w)}">!</span>' if w else ""
                vn = (
                    ""
                    if v is None
                    else f'<span class="vn num{" z" if v == 0 else ""}">{_esc(txt)}</span>'
                )
                h += (
                    f'<td class="hcell subc {cls}{" c0" if si == 0 else ""}{_lvl_cell_cls(v)}" '
                    f'title="{_esc(tip)}"><span class="cw">{_m3_html(v)}{vn}</span>{warn}</td>'
                )
        h += "</tr>"
    h += "</tbody>"
    return h


def _qg_value(row: dict[str, Any], key: str) -> Any:
    if key == "visits":
        return row.get("visits")
    if key == "brand":
        return row.get("brand")
    return (row.get("d") or {}).get(key)


def _ratio_txt(a: float, b: float) -> str:
    if not b:
        return ""
    r = a / b
    if r >= 10:
        return f"{int(round(r))}×"
    return f"{r:.1f}".replace(".", ",") + "×"


def build_qg_html(payload: dict[str, Any], selected: str = "google") -> str:
    from report_html import _esc

    rows = list(payload.get("rows") or [])
    if not rows:
        return ""
    keys = {k for k, _g, _l in QG_CHANS}
    if selected not in keys:
        selected = "google"
    groups: list[str] = []
    for _k, g, _l in QG_CHANS:
        if g not in groups:
            groups.append(g)
    filters = []
    for g in groups:
        btns = []
        for k, gg, lab in QG_CHANS:
            if gg != g:
                continue
            any_v = any(_qg_value(r, k) is not None for r in rows)
            pressed = "true" if k == selected else "false"
            dis = "" if any_v else ' disabled title="Não coletado para nenhuma empresa"'
            btns.append(
                f'<button type="button" data-qg="{_esc(k)}" aria-pressed="{pressed}"{dis}>{_esc(lab)}</button>'
            )
        filters.append(f'<div class="qg-gr"><span class="qg-gl">{_esc(g)}</span>{"".join(btns)}</div>')
    chan = next((c for c in QG_CHANS if c[0] == selected), QG_CHANS[0])
    key, gname, label = chan
    unit = UNIT_L.get(key) or UNIT.get(key, "")
    have = []
    miss = []
    for r in rows:
        v = _qg_value(r, key)
        if v is None:
            miss.append(r)
        else:
            try:
                have.append((r, float(v)))
            except (TypeError, ValueError):
                miss.append(r)
    have.sort(key=lambda x: x[1], reverse=True)
    mx = have[0][1] if have else 0
    pos = next((i for i, (r, _v) in enumerate(have) if r.get("me")), -1)
    mine = have[pos] if pos >= 0 else None
    if not have:
        verdict = "Nenhuma empresa tem dado neste canal."
    elif have[0][1] == 0:
        verdict = '<b class="down">Ninguém do grupo tem presença</b> neste canal — espaço livre.'
    elif pos < 0:
        verdict = "Sua empresa não tem dado coletado neste canal."
    elif mine and mine[1] == 0:
        verdict = (
            f'<b class="down">Você não tem presença</b> — {_esc(have[0][0].get("name"))} '
            f"lidera com {_esc(_fmt_cmp(have[0][1]))} {_esc(unit)}."
        )
    elif pos == 0:
        if len(have) > 1:
            nxt = have[1]
            if nxt[1]:
                extra = f"{_ratio_txt(mine[1], nxt[1])} o 2º colocado ({_esc(nxt[0].get('name'))})"
            else:
                extra = f"{_esc(nxt[0].get('name'))} não tem presença"
            verdict = f'<b class="up">Você lidera</b> — {extra}.'
        else:
            verdict = '<b class="up">Você lidera</b>.'
    else:
        verdict = (
            f"Você é <b>{pos + 1}º de {len(have)}</b> — {_esc(have[0][0].get('name'))} "
            f'tem <b class="down">{_ratio_txt(have[0][1], mine[1])}</b> o seu volume.'
        )
    items = []
    for i, (r, v) in enumerate(have):
        lead = " lead" if i == 0 and v > 0 else ""
        me = " me" if r.get("me") else ""
        rk = "★" if i == 0 and v > 0 else str(i + 1)
        you = '<span class="you">você</span>' if r.get("me") else ""
        width = 0.0
        if mx:
            width = max(v / mx * 100, 1.5 if v else 0)
        w = (r.get("w") or {}).get(key)
        warn = (
            f'<span class="hw" style="position:static" title="Verificar: {_esc(w)}">!</span>'
            if w
            else "<span></span>"
        )
        items.append(
            f'<li class="{me.strip()}{lead}"><span class="rk num">{rk}</span>'
            f'<button type="button" class="qg-n" data-pick="{_esc(r.get("name"))}" title="Ver perfil de {_esc(r.get("name"))}">'
            f'<span class="cdot" style="background:{_esc(r.get("color") or "#9AA3AE")}"></span>'
            f'{_esc(r.get("name"))}{you}</button>'
            f'<span class="qg-t"><i style="width:{width:.1f}%;background:{_esc(r.get("color") or "#9AA3AE")}"></i></span>'
            f'<span class="qg-v num{" z" if v == 0 else ""}">{_esc(_fmt_cmp(v))}</span>{warn}</li>'
        )
    miss_html = (
        f'<div class="qg-miss">Não coletado: {_esc(", ".join(str(r.get("name") or "") for r in miss))}</div>'
        if miss
        else ""
    )
    return f"""
<section class="sec qg-sec" id="ganhando">
  <div class="sec-h"><h2>Quem está ganhando</h2><span class="sec-note">Ranking do grupo, um canal por vez</span></div>
  <div class="card qg">
    <div class="qg-f" role="group" aria-label="Escolher canal">{"".join(filters)}</div>
    <div class="qg-b">
      <div class="qg-h"><b>{_esc(label)}</b><span>{_esc(gname)} · {_esc(unit)}</span></div>
      <ol class="qg-l">{"".join(items)}</ol>
      {miss_html}
      <div class="qg-v2">{verdict}</div>
    </div>
  </div>
</section>"""


def build_picker_html(payload: dict[str, Any], selected: Optional[str] = None) -> str:
    from report_html import _esc

    rows = payload.get("rows") or []
    if len(rows) < 2:
        return ""
    sel = selected or next((r.get("name") for r in rows if r.get("me")), rows[0].get("name"))
    bits = []
    for r in rows:
        name = str(r.get("name") or "")
        pressed = "true" if name == sel else "false"
        you = " · você" if r.get("me") else ""
        bits.append(
            f'<button type="button" class="pk" data-pick="{_esc(name)}" aria-pressed="{pressed}">'
            f'<span class="cdot" style="background:{_esc(r.get("color") or "#9AA3AE")}"></span>'
            f"{_esc(name)}{you}</button>"
        )
    return "".join(bits)


def build_cmp_html(
    payload: dict[str, Any],
    *,
    profile_only: bool = False,
    root_id: str = "cmp",
    variant: str = "v4",
) -> str:
    from report_html import _esc

    rows = payload.get("rows") or []
    if not rows:
        return ""
    raw = json.dumps(payload, ensure_ascii=False)
    only = " data-profile-only" if profile_only else ""
    picker_note = (
        ""
        if profile_only or len(rows) < 2
        else '<span class="sec-note">Escolha a empresa aqui ou clicando no nome dela na tabela</span>'
    )
    picker_btns = "" if profile_only else build_picker_html(payload)
    picker = (
        f'<div class="picker" role="group" aria-label="Empresa do card">{picker_btns}</div>'
        if picker_btns
        else ""
    )
    is_v4 = variant != "v3"
    pcard = build_pcard_html(payload, profile_only=profile_only, variant="v4" if is_v4 else "v3")
    table = ""
    if not profile_only:
        table = f"""
<section class="sec" id="concorrentes">
  <div class="sec-h"><h2>Todos os concorrentes</h2><span class="sec-note">Onde cada empresa é forte ou fraca, canal a canal</span></div>
  <div class="bar">
    <div style="display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center">
      <div class="seg" role="group" aria-label="Nível de detalhe">
        <button type="button" data-view="full" aria-pressed="true">Por canal</button>
        <button type="button" data-view="compact" aria-pressed="false"><span class="lbl-v3">Só categorias</span><span class="lbl-v4">Só resumo</span></button>
      </div>
      <div class="seg mode-seg" role="group" aria-label="Mostrar">
        <button type="button" data-mode="lvl" aria-pressed="true">Notas</button>
        <button type="button" data-mode="data" aria-pressed="false">Dados</button>
      </div>
      <div class="hl-wrap">
        <span class="hl-lab">Destacar</span>
        <div class="seg hl-seg" role="group" aria-label="Destacar">
          <button type="button" data-hl="" aria-pressed="true">Nada</button>
          <button type="button" data-hl="alto" aria-pressed="false">Alto</button>
          <button type="button" data-hl="medio" aria-pressed="false">Médio</button>
          <button type="button" data-hl="baixo" aria-pressed="false">Baixo</button>
        </div>
      </div>
    </div>
    <div class="legend legend-v3">
      <span class="g-org"><span class="m on3" aria-hidden="true"><i></i><i></i><i></i></span>Alto</span>
      <span class="g-org"><span class="m on2" aria-hidden="true"><i></i><i></i><i></i></span>Médio</span>
      <span class="g-org"><span class="m on1" aria-hidden="true"><i></i><i></i><i></i></span>Baixo</span>
      <span><span class="m z" aria-hidden="true"><i></i><i></i><i></i></span>Sem presença</span>
      <span><span class="na">n/c</span>Não coletado</span>
      <span><span class="warn" style="margin:0">!</span>Verificar dado</span>
    </div>
    <div class="legend hl legend-v4 tlegend">
      {_legend_v4_html()}
      <span><span class="hw" style="position:static">!</span>Verificar dado</span>
    </div>
  </div>
  <div class="card">
    <div class="tw"><table class="cmp-t{' hm' if is_v4 else ''}">{build_table_html(payload, variant="v4" if is_v4 else "v3")}</table></div>
    <div class="foot">
      <span>Clique no nome de uma coluna para ordenar. A sua empresa fica sempre no topo.</span>
      <span>Visitas: {_esc(payload.get("foot_visits") or "SimilarWeb")}. Marca: {_esc(payload.get("foot_brand") or "DataForSEO")}.</span>
      <span class="foot-v3">● ao lado do número = maior valor da coluna. No modo Dados, o peso do número segue a nota (negrito = Alto, cinza = Baixo, vermelho = zero).</span>
      <span class="foot-v4">Barrinhas: verde = Alto, amarelo = Médio, vermelho = Baixo, vazias = sem presença. O número embaixo é o valor real do canal.</span>
    </div>
  </div>
</section>
{build_qg_html(payload)}"""

    perfil_id = "perfil" if root_id == "cmp" else f"perfil-{root_id}"
    return f"""
<div id="{_esc(root_id)}" class="cmp{' datamode is-v4' if is_v4 else ''}{' cmp-panel' if not profile_only else ''}" data-cmp{only}>
<textarea class="cmp-data" hidden>{_esc(raw)}</textarea>
<section class="sec" id="{_esc(perfil_id)}">
  <div class="sec-h"><h2>Perfil da empresa</h2>{picker_note}</div>
  {picker}
  <div class="card pcard">{pcard}</div>
</section>
{table}
</div>"""
