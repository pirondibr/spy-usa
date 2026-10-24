# -*- coding: utf-8 -*-
"""v5 analysis report — spy-usa-minimal.html wired to live report data."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from report_analysis_compare import COLORS, MAX_COMPANIES, SOURCE_META
from report_cmp import CHAN, GROUPS, SCORE_LVL, build_cmp_payload

CH_META = (
    ("google", "paid", "Google Ads", "ads", 200),
    ("meta", "paid", "Meta Ads", "ads", 80),
    ("liads", "paid", "LinkedIn Ads", "ads", 0),
    ("seo", "org", "SEO", "visits/mo", 0),
    ("x", "org", "X", "followers", 0),
    ("ig", "org", "Instagram", "followers", 0),
    ("li", "org", "LinkedIn", "followers", 0),
    ("yt", "org", "YouTube", "subscribers", 0),
    ("tk", "org", "TikTok", "followers", 0),
    ("rd", "org", "Reddit", "comments", 0),
    ("ytv", "inf", "YouTube", "video views", 0),
    ("igl", "inf", "Instagram", "likes", 0),
)
CH_TO_CMP = {
    "google": "google",
    "meta": "meta",
    "liads": "li_ads",
    "seo": "seo",
    "x": "x",
    "ig": "ig",
    "li": "li",
    "yt": "yt",
    "tk": "tt",
    "rd": "rd",
    "ytv": "yt_inf",
    "igl": "ig_inf",
}


def _num(v: Any) -> Optional[float]:
    from report_html import _coerce_number

    return _coerce_number(v)


def _pct_num(raw: Any) -> Optional[float]:
    n = _num(raw)
    if n is None:
        s = str(raw or "").strip().replace("%", "").replace(",", ".")
        try:
            n = float(s)
        except (TypeError, ValueError):
            return None
    if n <= 1.5:
        return round(n * 100, 1)
    return round(float(n), 1)


def _growth_num(raw: Any) -> Optional[float]:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw or "").strip().replace("%", "").replace("−", "-").replace(",", ".")
    if s in ("", "n/a", "n/d", "—", "-"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _yt_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from report_html import _compact_num

    out = []
    for t in items[:5]:
        if not isinstance(t, dict):
            continue
        views = _num(t.get("views"))
        out.append({
            "title": str(t.get("title") or "vídeo"),
            "url": str(t.get("url") or ""),
            "channel": str(t.get("channel_name") or ""),
            "age": str(t.get("upload_age") or ""),
            "views": views,
            "views_fmt": _compact_num(views) if views is not None else str(t.get("views_fmt") or "—"),
        })
    return out


def _ig_items(items: list[dict[str, Any]], *, handle: str = "") -> list[dict[str, Any]]:
    from report_html import _compact_num

    out = []
    for t in items[:5]:
        if not isinstance(t, dict):
            continue
        likes = _num(t.get("likes"))
        url = str(t.get("url") or "")
        user = str(t.get("username") or handle or "").lstrip("@")
        kind = "reel" if "reel" in url.lower() or str(t.get("type") or "").lower() == "reel" else "post"
        if not url and user and t.get("shortcode"):
            path = "reel" if kind == "reel" else "p"
            url = f"https://www.instagram.com/{user}/{path}/{t.get('shortcode')}/"
        out.append({
            "title": str(t.get("caption") or (f"@{user}" if user else "post")),
            "url": url,
            "likes": likes,
            "likes_fmt": _compact_num(likes) if likes is not None else str(t.get("likes_fmt") or "—"),
            "kind": kind,
            "own": not bool(t.get("is_influencer")),
        })
    return out


def build_v5_payload(
    report: dict[str, Any],
    meta: dict[str, Any],
    *,
    briefing: dict[str, Any],
    client: str,
    site_host: str,
    run_id: str,
    market: str,
) -> dict[str, Any]:
    from report_cmp import _brand_series, _has_channel as has_ch, _month_series
    from report_html import (
        _channel_metric_value,
        _channel_score,
        _compact_num,
        _resolve_run_log,
        _row_for_company,
        _summary_channel_url,
        _summary_companies,
    )

    raw_cos = _summary_companies(report) or [
        {"name": client, "domain": site_host, "is_client": True, "_key": ""}
    ]
    raw_cos = raw_cos[:MAX_COMPANIES]
    colors = [COLORS[i % len(COLORS)] for i in range(len(raw_cos))]
    cmp = build_cmp_payload(report, raw_cos, market=market, colors=colors)
    cmp_rows = list(cmp.get("rows") or [])

    def section(key: str) -> dict[str, Any]:
        sec = report.get(key)
        return sec if isinstance(sec, dict) else {}

    companies: list[dict[str, Any]] = []
    for i, (company, crow) in enumerate(zip(raw_cos, cmp_rows)):
        k = f"c{i}"
        sw = _row_for_company(section("similarweb"), company) or {}
        dfs = _row_for_company(section("brand_dataforseo"), company) or {}
        br = _row_for_company(section("brand"), company) or {}
        months, month_labels = _month_series(sw)
        brand_vals, brand_labels = _brand_series(dfs)
        bounce = _num(sw.get("bounce_rate"))
        if bounce is not None and bounce <= 1.5:
            bounce = bounce * 100
        ppv = _num(sw.get("pages_per_visit"))
        sem = _num(br.get("traffic"))
        semg = _growth_num(br.get("growth_fmt") or br.get("growth_pct") or br.get("growth"))
        scores = crow.get("s") or {}
        cat: dict[str, Optional[int]] = {}
        for gkey, _lab, _cls, subs in GROUPS:
            vals = [scores.get(mk) for mk, _ in subs if scores.get(mk) is not None]
            cat[gkey] = max(vals) if vals else None
        companies.append({
            "k": k,
            "name": crow.get("name") or company.get("name") or "—",
            "dom": crow.get("dom") or company.get("domain") or "",
            "color": crow.get("color") or colors[i],
            "me": bool(crow.get("me") or company.get("is_client")),
            "visits": _num(crow.get("visits")) or 0,
            "vg": float(crow.get("vg") or 0),
            "months": months,
            "month_labels": month_labels or list(cmp.get("visit_labels") or []),
            "brand": brand_vals if brand_vals else [0, 0, 0, float(crow.get("brand") or 0)],
            "brand_labels": brand_labels or list(cmp.get("brand_labels") or []),
            "bg": float(crow.get("bg") or 0),
            "bounce": bounce,
            "ppv": ppv,
            "time": str(sw.get("time_fmt") or "—"),
            "sem": sem,
            "semg": semg,
            "cat": cat,
        })

    channels: list[dict[str, Any]] = []
    extra_flags: list[str] = []
    ig_all_nc = True
    for mk, g, label, unit, spend in CH_META:
        cmp_k = CH_TO_CMP[mk]
        report_key = CHAN[cmp_k]
        sec = section(report_key)
        collected = has_ch(sec if sec else None)
        scores_map: dict[str, list[Any]] = {}
        warns: dict[str, str] = {}
        for company, co in zip(raw_cos, companies):
            k = co["k"]
            if not collected:
                scores_map[k] = [None]
                continue
            row = _row_for_company(sec, company)
            if row is None:
                scores_map[k] = [None]
                continue
            metric = _channel_metric_value(report_key, sec, row)
            lvl = SCORE_LVL.get(_channel_score(report_key, metric), 0)
            scores_map[k] = [lvl, metric if metric is not None else 0]
            note = str(row.get("note") or row.get("flag") or "").strip()
            if report_key == "meta" and metric and not (row.get("confirmed") or row.get("meta_confirmed")):
                extra = f"{int(metric)} ads not confirmed in Ad Library"
                note = f"{note} · {extra}".strip(" ·") if note else extra
            if note:
                warns[k] = note
            if mk == "ig":
                ig_all_nc = False
        if mk == "ig" and collected:
            ig_all_nc = False
        if mk == "ig" and not collected:
            ig_all_nc = True
        ch = {"k": mk, "g": g, "l": label, "u": unit, "s": scores_map}
        if spend:
            ch["spend"] = spend if str(market).upper() != "BR" else (250 if mk == "meta" else 600)
        if warns:
            ch["w"] = warns
        channels.append(ch)
    if ig_all_nc:
        extra_flags.append("ig_followers_missing")

    # traffic sources
    src_order: list[str] = []
    seen_src: set[str] = set()
    for company in raw_cos:
        row = _row_for_company(section("similarweb"), company) or {}
        for s in row.get("sources") or []:
            raw = str(s.get("name") or "").strip()
            if raw and raw.lower() not in seen_src:
                seen_src.add(raw.lower())
                src_order.append(raw)
    src_labels, src_colors, src_paid = [], [], []
    for raw in src_order:
        lab, col, paid = SOURCE_META.get(raw.lower(), (raw, "#9AA3AE", False))
        src_labels.append(lab)
        src_colors.append(col)
        if paid:
            src_paid.append(len(src_labels) - 1)
    src_vals: dict[str, list[float]] = {}
    for company, co in zip(raw_cos, companies):
        row = _row_for_company(section("similarweb"), company) or {}
        by_name = {}
        for s in row.get("sources") or []:
            n = _pct_num(s.get("share") if s.get("share") is not None else s.get("share_fmt"))
            by_name[str(s.get("name") or "")] = n or 0
        src_vals[co["k"]] = [float(by_name.get(raw, 0) or 0) for raw in src_order]

    # ads libraries
    ads_lib: dict[str, dict[str, str]] = {}
    for company, co in zip(raw_cos, companies):
        ads_lib[co["k"]] = {
            "google": _summary_channel_url("google_ads", section("google_ads"), _row_for_company(section("google_ads"), company) or {}, market=market),
            "meta": _summary_channel_url("meta", section("meta"), _row_for_company(section("meta"), company) or {}, market=market),
            "liads": _summary_channel_url("linkedin", section("linkedin"), _row_for_company(section("linkedin"), company) or {}, market=market),
        }

    # youtube
    youtube: dict[str, Any] = {}
    yt_sec = section("youtube_influencers")
    for company, co in zip(raw_cos, companies):
        row = _row_for_company(yt_sec, company) or {}
        top_off = list(row.get("top5_official") or [])
        top_unoff = list(row.get("top5_unofficial") or [])
        if not top_off and not top_unoff:
            for t in row.get("top5") or []:
                (top_off if t.get("is_official") else top_unoff).append(t)
        oc = row.get("official_channel") or {}
        ch_url = ""
        if isinstance(oc, dict):
            ch_url = str(oc.get("url") or "")
        if not ch_url and top_off:
            # no dedicated field on older rows — leave empty rather than guess
            ch_url = ""
        q = str(row.get("query") or company.get("name") or "").strip()
        search = str(row.get("search_url") or row.get("url") or "")
        if not search and q:
            from urllib.parse import quote_plus

            search = f"https://www.youtube.com/results?search_query={quote_plus(q)}&hl=en&gl=US"
        youtube[co["k"]] = {
            "views": _compact_num(_num(row.get("traffic")) or ((_num(row.get("views_official")) or 0) + (_num(row.get("views_unofficial")) or 0))),
            "off": _compact_num(_num(row.get("views_official")) or 0),
            "oth": _compact_num(_num(row.get("views_unofficial")) or 0),
            "n": int(row.get("about_count") or 0),
            "d30": _compact_num(_num(row.get("views_30d")) or 0),
            "m6": _compact_num(_num(row.get("views_6m")) or 0),
            "y1": _compact_num(_num(row.get("views_1y_plus")) or 0),
            "q": q,
            "search": search,
            "ch": ch_url,
            "o": _yt_items(top_off),
            "x": _yt_items(top_unoff),
            "w": str(row.get("note") or ""),
        }

    # instagram
    instagram: dict[str, Any] = {}
    ig_sec = section("instagram_influencers")
    ig_prof = section("instagram")
    for company, co in zip(raw_cos, companies):
        row = _row_for_company(ig_sec, company) or {}
        prow = _row_for_company(ig_prof, company) or {}
        handle = str(row.get("handle") or prow.get("handle") or "").lstrip("@")
        own = list(row.get("top5_page") or [])
        infs = list(row.get("top5_influencers") or [])
        if not own and not infs:
            for t in row.get("top5") or []:
                (infs if t.get("is_influencer") else own).append(t)
        instagram[co["k"]] = {
            "h": handle or None,
            "likes": _compact_num(_num(row.get("total_likes")) or 0),
            "own": int(row.get("own_posts") or 0),
            "inf": int(row.get("total_influencers") or 0),
            "infp": int(row.get("influencer_posts") or 0),
            "followers": prow.get("followers_fmt") or prow.get("value_fmt") or None,
            "p": _ig_items(own, handle=handle),
            "inf_posts": _ig_items(infs, handle=handle),
            "profile": str(prow.get("url") or row.get("url") or (f"https://www.instagram.com/{handle}/" if handle else "")),
            "w": str(row.get("note") or prow.get("note") or ""),
        }

    # reddit
    reddit: dict[str, Any] = {}
    rd_sec = section("reddit")
    for company, co in zip(raw_cos, companies):
        row = _row_for_company(rd_sec, company) or {}
        posts = []
        for t in list(row.get("top_posts") or [])[:5]:
            if not isinstance(t, dict):
                continue
            sub = t.get("subreddit") or ""
            posts.append({
                "title": str(t.get("title") or "post"),
                "sub": f"r/{sub}" if sub and not str(sub).startswith("r/") else str(sub or ""),
                "url": str(t.get("url") or ""),
            })
        reddit[co["k"]] = {
            "posts": int(row.get("posts_first_page") or 0),
            "com": int(_num(row.get("total_comments")) or 0),
            "g": str(row.get("total_results_fmt") or "—"),
            "search": str(row.get("search_url") or row.get("url") or ""),
            "l": posts,
            "w": str(row.get("note") or ""),
        }

    log = _resolve_run_log(report, meta) or {}
    totals = log.get("totals") or {}
    steps = []
    for ch in log.get("channels") or []:
        blob = " ".join(str(ch.get(k) or "") for k in ("detail", "cost_note", "status")).lower()
        skipped = "skip" in blob or "pulado" in blob
        status = str(ch.get("status") or "").strip().lower()
        if skipped:
            sit = "skipped"
        elif status in ("n/d", "nd"):
            sit = "n/a"
        else:
            sit = "done"
        steps.append({
            "label": str(ch.get("label") or ch.get("id") or "—"),
            "time": str(ch.get("sec_fmt") or "—"),
            "cost": str(ch.get("cost_fmt") or "—"),
            "apis": str(ch.get("apis_fmt") or "—"),
            "status": sit,
            "skipped": skipped,
        })
    lines = [str(x) for x in (log.get("lines") or [])]

    n_peers = max(0, len(companies) - 1)
    market_code = "US" if str(market).upper() == "US" else "BR"
    nicho = str(briefing.get("nicho") or "").strip()
    snap = ""
    for company in raw_cos:
        row = _row_for_company(section("similarweb"), company) or {}
        snap = str(row.get("snapshot_label") or snap)

    return {
        "meta": {
            "client": client,
            "peers": n_peers,
            "market_code": market_code,
            "market": market_code,
            "nicho": nicho,
            "snap": snap,
            "run_id": run_id,
            "duration": str(totals.get("sec_fmt") or ""),
            "cost": str(totals.get("cost_fmt") or ""),
            "home": "/",
        },
        "companies": companies,
        "channels": channels,
        "flags": extra_flags,
        "visit_labels": list(cmp.get("visit_labels") or []),
        "brand_labels": list(cmp.get("brand_labels") or []),
        "sources": {
            "l": src_labels,
            "c": src_colors,
            "paid": src_paid,
            "v": src_vals,
        },
        "ads_lib": ads_lib,
        "youtube": youtube,
        "instagram": instagram,
        "reddit": reddit,
        "exec": {
            "duration": str(totals.get("sec_fmt") or "—"),
            "cost": str(totals.get("cost_fmt") or "—"),
            "companies": len(companies),
            "steps": steps,
            "log": "\n".join(lines),
            "rates": str(log.get("rates_note") or ""),
        },
    }


def build_analysis_v5(payload: dict[str, Any], *, ui_ver: str) -> str:
    from report_html import _esc, analysis_add_form_html, lang_switch_html

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
    return f"""
<div id="analysis-v5">
<script type="application/json" id="spy-v5-data">{data}</script>
<header class="top"><div class="wrap"><span class="logo">S</span><b>Spy USA</b>
  <div class="acts">
    {lang_switch_html()}
    <div class="ui-switch" role="group" aria-label="Report layout">
      <span class="ui-switch-lab" data-i18n="nav.layout">Layout</span>
      <button type="button" data-ui-set="v4">v4</button>
      <button type="button" data-ui-set="v5" aria-pressed="true">v5</button>
      <button type="button" data-ui-set="v6">v6</button>
    </div>
    <a href="/" data-i18n="nav.new">New analysis</a>
    <button type="button" onclick="window.print()" data-i18n="nav.export">Export PDF</button>
  </div>
</div></header>
<main class="wrap">
  <section class="head">
    <div class="eyebrow" id="v5-eyebrow"></div>
    <h1 id="v5-title">{client}</h1>
    <div class="cos" id="cos"></div>
    {add_form}
    <ul class="ins" id="ins"></ul>
  </section>
  <section class="sec">
    <div class="sh"><h2 data-i18n="score.h">Scoreboard</h2><p data-i18n="score.p5">Click a company to see the profile</p></div>
    <div class="bw"><table class="board" id="board"></table></div>
    <details class="flags" id="flags"></details>
  </section>
  <div id="fixed"></div>
  <section class="moresec" aria-labelledby="more-h">
    <div class="sh" style="margin-top:44px"><h2 id="more-h" data-i18n="more.h">More analysis</h2><p data-i18n="more.p">Click to open · one at a time</p></div>
    <nav class="tags" id="tags" aria-label="More analysis" data-i18n="more.h" data-i18n-attr="aria-label"></nav>
    <div id="panels"></div>
  </section>
  <footer class="foot" id="v5-foot"></footer>
</main>
</div>
<script src="/static/report_v5.js?v={_esc(ui_ver)}"></script>
"""
