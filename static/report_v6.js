(function () {
  var root = document.getElementById("analysis-v6");
  var dataEl = document.getElementById("spy-v6-data");
  if (!root || !dataEl) return;
  var D;
  try {
    D = JSON.parse(dataEl.textContent || "{}");
  } catch (e) {
    return;
  }
  var I = window.SpyI18n;
  var t = function (k, a) { return I ? I.t(k, a) : k; };
  var loc = function () { return I ? I.locale() : "en-US"; };
  var nth = function (n) { return I ? I.nth(n) : String(n); };
  var unitOf = function (ch) { return I ? I.unitOf(ch) : (ch && ch.u) || ""; };
  var srcL = function (l) { return I ? I.src(l) : l; };
  var stL = function (s) { return I ? I.status(s) : s; };

  var CO = D.companies || [];
  var CH = D.channels || [];
  var SRC = D.sources || { l: [], c: [], paid: [], v: {} };
  var LIB = D.ads_lib || {};
  var YT = D.youtube || {};
  var IG = D.instagram || {};
  var TT = D.tiktok || {};
  var RD = D.reddit || {};
  var EX = D.exec || {};
  var META = D.meta || {};
  var extraFlags = D.flags || [];
  if (!CO.length) return;

  var GR = {};
  var LBL = [];
  var $ = function (id) { return root.querySelector("#" + id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };
  var dec = function () { return loc() === "pt-BR" ? "," : "."; };
  var fmt = function (n) {
    if (n == null || n === "") return "—";
    n = Number(n);
    if (!isFinite(n)) return "—";
    var d = dec();
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2).replace(/\.?0+$/, "").replace(".", d) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e5 ? 0 : 1).replace(/\.0$/, "").replace(".", d) + "k";
    return String(Math.round(n));
  };
  var pct = function (p) {
    if (p == null || !isFinite(Number(p))) return "—";
    p = Number(p);
    return (p > 0 ? "+" : p < 0 ? "−" : "") + Math.abs(p).toLocaleString(loc(), { maximumFractionDigits: Math.abs(p) >= 100 ? 0 : 1 }) + "%";
  };
  var num = function (n) { return Number(n).toLocaleString(loc()); };
  var dec1 = function (n) { return Number(n).toFixed(1).replace(".", dec()); };
  var gOf = function (a, b) {
    a = Number(a); b = Number(b);
    if (!isFinite(a) || !isFinite(b) || b === 0) return null;
    return (a - b) / b * 100;
  };
  var pctTxt = function (p) {
    return (p > 0 ? "+" : "−") + Math.abs(Math.round(p)).toLocaleString(loc()) + "%";
  };
  function brandBest(c) {
    var series = c.brand || [];
    if (!series.length) return null;
    var now = series[series.length - 1];
    var opts = [];
    for (var i = 1; i <= 3; i++) {
      var idx = series.length - 1 - i;
      if (idx < 0) break;
      var g = gOf(now, series[idx]);
      if (g != null) opts.push({ g: g, y: i });
    }
    if (!opts.length) return now ? { g: Infinity, y: null, now: now } : null;
    opts.sort(function (x, z) { return z.g - x.g; });
    return { g: opts[0].g, y: opts[0].y, now: now };
  }
  function brandCell(c) {
    var series = c.brand || [];
    var labs = c.brand_labels || D.brand_labels || [];
    if (!series.length || !series.some(function (v) { return Number(v) > 0; })) {
      return '<span class="br"><span class="na">' + t("find.brand.none") + "</span></span>";
    }
    var bg = brandBest(c);
    var now = series[series.length - 1];
    var pill = !bg ? "" : bg.g === Infinity
      ? '<span class="pill new">' + t("find.brand.new") + "</span>"
      : '<span class="pill ' + (bg.g >= 0 ? "up" : "dn") + '">' + (bg.g >= 0 ? "▲" : "▼") + " " + pctTxt(bg.g).replace(/^[+−]/, "") + "</span>";
    var per = !bg || bg.y == null ? t("find.brand.unit")
      : (bg.y === 1 ? t("find.brand.vs1") : bg.y === 2 ? t("find.brand.vs2") : t("find.brand.vs3"));
    var gl = function (g) {
      return g == null ? "<em>—</em>" : '<em class="' + (g >= 0 ? "u" : "d") + '">' + (g >= 0 ? "▲" : "▼") + " " + pctTxt(g).replace(/^[+−]/, "") + "</em>";
    };
    var rows = "";
    for (var i = series.length - 1; i >= 0; i--) {
      var yearsAgo = series.length - 1 - i;
      rows += '<span class="tr"><span>' + esc(labs[i] || "") + '</span><span class="num">' + fmt(series[i]) + "</span>" + (yearsAgo ? gl(gOf(now, series[i])) : "<span></span>") + "</span>";
    }
    return '<span class="br hv" tabindex="0"><b class="num">' + fmt(now) + "</b>" + pill + "<small>" + per + "</small>" +
      '<span class="tt" role="tooltip"><b>' + t("find.brand.tip") + "</b>" + rows +
      "<small>" + t("find.brand.tip_s") + "</small></span></span>";
  }

  var ME = CO.find(function (c) { return c.me; }) || CO[0];
  var coDot = function (c) { return '<span class="dot" style="background:' + c.color + '"></span>'; };
  var chVal = function (ch, c) {
    var s = (ch.s || {})[c.k];
    if (!s || s[0] == null) return null;
    return s[1] == null ? null : s[1];
  };
  var chSlot = function (ch, c) {
    var s = (ch.s || {})[c.k];
    return s && s.length ? s : [null];
  };
  var chName = function (ch) {
    return ch.g === "inf" ? t("ch.creators", { name: ch.l }) : ch.l;
  };
  var you = function () { return '<span class="you">' + t("you") + "</span>"; };
  var allMetrics = function () {
    return [
      { k: "visits", l: t("m.visits"), u: t("unit.visits"), get: function (c) { return c.visits; } },
      { k: "brand", l: t("m.brand"), u: t("unit.brand"), get: function (c) { return (c.brand && c.brand[c.brand.length - 1]) || 0; } },
    ].concat(CH.map(function (ch) {
      return { k: ch.k, l: chName(ch), u: unitOf(ch), ch: ch, get: function (c) { return chVal(ch, c); } };
    }));
  };
  function vsText() {
    var n = META.peers != null ? Number(META.peers) : 0;
    if (!n && META.vs) return META.vs;
    return t(n === 1 ? "vs.one" : "vs.many", { n: n });
  }
  function eyebrowText() {
    var bits = [];
    if (META.nicho) bits.push(META.nicho);
    var code = String(META.market_code || META.market || "US").toUpperCase();
    bits.push(t(code.indexOf("BR") === 0 || code === "BRASIL" ? "market.br" : "market.us"));
    if (META.snap) bits.push(t("eyebrow.snap", { snap: META.snap }));
    return bits.join(" · ");
  }
  function flagText(x) {
    if (x === "ig_followers_missing" || /Instagram \(seguidores\)/.test(String(x))) return t("flag.ig");
    return x;
  }

  function chStats(ch) {
    var vals = CO.map(function (c) {
      var s = chSlot(ch, c);
      return { c: c, n: s[1] != null ? s[1] : null, flag: !!(ch.w && ch.w[c.k]) };
    }).filter(function (x) { return x.n != null; });
    var clean = vals.filter(function (x) { return !x.flag; }).sort(function (a, b) { return b.n - a.n; });
    var lead = clean[0];
    return { lead: lead && lead.n > 0 ? lead : null, free: vals.length > 0 && vals.every(function (x) { return x.n === 0; }) };
  }
  var isLead = function (ch, c) {
    var st = chStats(ch);
    return !!(st.lead && st.lead.c === c);
  };
  var bub = function (v) {
    if (v == null) return '<span class="bb bn-c"><span style="font-size:11px;color:var(--soft)">' + t("nc") + "</span></span>";
    return '<span class="bb b' + v + '" role="img" aria-label="' + LBL[v] + '"><i></i></span>';
  };

  var sel = ME.k;
  var flt = "all";
  var rkSel = "visits";
  var tabCo = { yt: ME.k, ig: ME.k, tt: ME.k, rd: ME.k };
  var FIXED = ["perfil", "canais"];
  var open = null;
  try { open = localStorage.getItem("spy-min-tab"); } catch (e) {}

  function panels() {
    return [
      { id: "perfil", t: t("p.perfil"), d: t("p.perfil_d") },
      { id: "canais", t: t("p.canais"), d: t("p.canais_d") },
      { id: "ganha", t: t("p.ganha"), d: t("p.ganha_d") },
      { id: "trafego", t: t("p.trafego"), d: t("p.trafego_d"), grp: "det" },
      { id: "origem", t: t("p.origem"), d: t("p.origem_d"), grp: "det" },
      { id: "ads", t: t("p.ads"), d: t("p.ads_d"), grp: "det" },
      { id: "yt", t: t("p.yt"), d: t("p.yt_d"), grp: "det" },
      { id: "ig", t: t("p.ig"), d: t("p.ig_d"), grp: "det" },
      { id: "tt", t: t("p.tt"), d: t("p.tt_d"), grp: "det" },
      { id: "rd", t: t("p.rd"), d: t("p.rd_d"), grp: "det" },
      { id: "exec", t: t("p.exec"), d: t("p.exec_d"), grp: "det" },
    ];
  }

  function paintChrome() {
    var titleEl = $("v6-title");
    if (titleEl) {
      titleEl.innerHTML = esc(META.client || ME.name) + ' <span class="vs">vs ' + esc(vsText()) + "</span>";
    }
    var eye = $("v6-eyebrow");
    if (eye) eye.textContent = eyebrowText();
    $("v6-cos").innerHTML = CO.map(function (c) {
      return '<span data-domain="' + esc(c.dom || "") + '">' + coDot(c) + esc(c.name) + (c.me ? " " + you() : ' <span style="color:var(--soft)">' + esc(c.dom) + "</span>") + "</span>";
    }).join("");

    var metrics = allMetrics();
    var lead = [], behind = [], free = [];
    metrics.forEach(function (m) {
      var vals = CO.map(function (c) { return { c: c, v: m.get(c) }; }).filter(function (x) { return x.v != null; });
      if (!vals.length) return;
      var mx = Math.max.apply(null, vals.map(function (x) { return x.v; }));
      if (mx === 0) { free.push(m.l); return; }
      var top = vals.find(function (x) { return x.v === mx; }).c;
      var mine = m.get(ME);
      if (top.me) lead.push(m.l);
      else if (mine != null && mine < mx) behind.push({ l: m.l, who: top.name });
    });
    $("v6-ins").innerHTML =
      '<li class="f"><div class="k">' + t("ins.lead") + '</div><div class="v">' + (lead.length ? lead.map(function (x) { return "<b>" + esc(x) + "</b>"; }).join(", ") : "—") + "</div></li>" +
      '<li class="w"><div class="k">' + t("ins.behind") + '</div><div class="v">' + (behind.slice(0, 5).map(function (x) { return "<b>" + esc(x.l) + "</b> (" + esc(x.who) + ")"; }).join(", ") || "—") + "</div></li>" +
      "<li><div class=\"k\">" + t("ins.free") + "</div><div class=\"v\">" + (free.length ? free.map(function (x) { return "<b>" + esc(x) + "</b>"; }).join(", ") : "—") + "</div></li>";

    var flags = CH.flatMap(function (ch) {
      return Object.entries(ch.w || {}).map(function (pair) {
        var co = CO.find(function (c) { return c.k === pair[0]; });
        return "<li><b>" + esc(co ? co.name : pair[0]) + " · " + chName(ch) + ":</b> " + esc(pair[1]) + "</li>";
      });
    });
    extraFlags.forEach(function (x) { flags.push("<li>" + esc(flagText(x)) + "</li>"); });
    $("v6-flags").innerHTML = flags.length
      ? "<summary>" + t("flags.n", { n: flags.length }) + "</summary><ul>" + flags.join("") + "</ul>"
      : "";

    var foot = $("v6-foot");
    if (foot) {
      var bits = ["WinnerTracker"];
      if (META.run_id) bits.push("run " + META.run_id);
      if (META.duration || META.cost) bits.push([META.duration, META.cost ? t("foot.cost", { n: META.cost }) : ""].filter(Boolean).join(" · "));
      bits.push(t("foot.src"));
      foot.innerHTML = bits.map(function (b) { return "<span>" + esc(b) + "</span>"; }).join("");
    }
    if (I) I.apply(root);
  }

  function renderShell() {
    var P = panels();
    var TABS = P.filter(function (p) { return FIXED.indexOf(p.id) < 0; });
    if (!TABS.some(function (p) { return p.id === open; })) open = null;
    var panel = function (p, fixed) {
      return '<section class="pn' + (fixed ? " fx" : "") + '" id="v6-pn-' + p.id + '"' + (fixed ? "" : " hidden") + ' aria-labelledby="v6-h-' + p.id + '"><div class="ph"><h3 id="v6-h-' + p.id + '">' + p.t + "</h3><p>" + p.d + "</p>" + (fixed ? "" : '<button type="button" class="x" data-close="' + p.id + '" aria-label="' + t("close", { name: p.t }) + '">×</button>') + '</div><div class="pb" id="v6-pb-' + p.id + '"></div></section>';
    };
    $("v6-fixed").innerHTML = P.filter(function (p) { return FIXED.indexOf(p.id) >= 0; }).map(function (p) { return panel(p, true); }).join("");
    $("v6-panels").innerHTML = TABS.map(function (p) { return panel(p, false); }).join("");
    $("v6-tags").innerHTML = TABS.map(function (p) {
      return '<button type="button" class="tg" data-tag="' + p.id + '" aria-pressed="' + (open === p.id) + '" aria-controls="v6-pn-' + p.id + '">' + p.t + "</button>";
    }).join("");
    TABS.forEach(function (p) { $("v6-pn-" + p.id).hidden = open !== p.id; });
    try { open ? localStorage.setItem("spy-min-tab", open) : localStorage.removeItem("spy-min-tab"); } catch (e) {}
  }

  function renderTags() {
    var TABS = panels().filter(function (p) { return FIXED.indexOf(p.id) < 0; });
    $("v6-tags").innerHTML = TABS.map(function (p) {
      return '<button type="button" class="tg" data-tag="' + p.id + '" aria-pressed="' + (open === p.id) + '" aria-controls="v6-pn-' + p.id + '">' + p.t + "</button>";
    }).join("");
    TABS.forEach(function (p) {
      var el = $("v6-pn-" + p.id);
      if (el) el.hidden = open !== p.id;
    });
    try { open ? localStorage.setItem("spy-min-tab", open) : localStorage.removeItem("spy-min-tab"); } catch (e) {}
  }

  function renderBoard() {
    var rows = CH.filter(function (ch) {
      if (ch.g === "inf") return true;
      return !CO.every(function (c) { return chSlot(ch, c)[0] == null; });
    });
    var order = CO.slice().sort(function (x, y) { return (y.visits || 0) - (x.visits || 0); });
    var mxv = Math.max.apply(null, CO.map(function (c) { return c.visits || 0; }).concat([1]));
    var mxb = Math.max.apply(null, CO.map(function (c) { return (c.brand && c.brand[c.brand.length - 1]) || 0; }).concat([1]));
    var vbar = function (v, mx, col, chg, per) {
      var w = mx ? Math.max(2, (v || 0) / mx * 100) : 2;
      return '<div class="vb"><div class="tp"><span class="val num">' + fmt(v) + '</span><span class="pill ' + (chg >= 0 ? "up" : "dn") + '">' + (chg >= 0 ? "▲" : "▼") + " " + pct(Math.abs(chg)).replace("+", "") + '</span></div><div class="tk"><i style="width:' + w.toFixed(1) + "%;background:" + col + '"></i></div><span class="per">' + esc(per) + "</span></div>";
    };
    var h = "<thead><tr><th></th><th>" + t("board.company") + "</th><th>" + t("board.visits") + '</th><th class="hide-s">' + t("board.brand") + '</th><th class="c">' + t("board.groups") + "</th><th>" + t("board.leads") + '</th><th class="hide-s">' + t("board.active") + "</th></tr></thead><tbody>";
    order.forEach(function (c, i) {
      var L = rows.filter(function (ch) { return isLead(ch, c) && !chStats(ch).free; });
      var A = rows.filter(function (ch) { return (chSlot(ch, c)[0] || 0) > 0; });
      var brandNow = (c.brand && c.brand[c.brand.length - 1]) || 0;
      h += '<tr class="row' + (c.k === sel ? " sel" : "") + '" data-co="' + c.k + '" tabindex="0" aria-label="' + t("board.see", { name: c.name }) + '">' +
        '<td class="pos">' + nth(i + 1) + "</td>" +
        "<td><div class=\"nm\">" + coDot(c) + esc(c.name) + (c.me ? you() : "") + "</div></td>" +
        "<td>" + vbar(c.visits, mxv, c.color, c.vg, t("board.mo2")) + "</td>" +
        '<td class="hide-s">' + vbar(brandNow, mxb, c.color, c.bg, t("board.yr1")) + "</td>" +
        '<td class="c"><span class="trio" title="' + ["paid", "org", "inf"].map(function (g) { return GR[g] + ": " + LBL[(c.cat || {})[g] || 0]; }).join(" · ") + '">' +
        ["paid", "org", "inf"].map(function (g) { return bub((c.cat || {})[g]); }).join("") + "</span></td>" +
        '<td><div class="ldr">' + (L.length ? L.map(function (ch) { return "<span>" + esc(chName(ch)) + "</span>"; }).join("") : '<span class="no">' + t("board.none") + "</span>") + "</div></td>" +
        '<td class="hide-s act"><b class="num">' + A.length + "</b> <span>" + t("board.of") + " " + rows.length + '</span><div class="mt">' +
        rows.map(function (ch) { return '<i class="' + ((chSlot(ch, c)[0] || 0) > 0 ? "on" : "") + '" title="' + esc(chName(ch)) + '"></i>'; }).join("") +
        "</div></td></tr>";
    });
    $("v6-board").innerHTML = h + "</tbody>";
  }

  function chipTip(ch, c) {
    var s = chSlot(ch, c);
    var v = s[0], n = s[1], st = chStats(ch);
    var tip = chName(ch) + ": " + (n == null ? "—" : num(n)) + " " + unitOf(ch) + " · " + (v == null ? t("nc") : LBL[v]);
    if (st.free) tip += " · " + t("tip.none");
    else if (st.lead && st.lead.c === c) tip += " · " + t("tip.leads");
    else if (st.lead) tip += " · " + t("tip.leader", { name: st.lead.c.name, n: fmt(st.lead.n) });
    if (ch.w && ch.w[c.k]) tip += " · " + t("tip.check", { note: ch.w[c.k] });
    return esc(tip);
  }
  function perfilF(c) {
    var rows = CH.filter(function (ch) { return chSlot(ch, c)[0] != null; });
    var by = [3, 2, 1, 0].map(function (v) {
      return { v: v, chs: rows.filter(function (ch) { return chSlot(ch, c)[0] === v; }) };
    });
    var names = function (arr) { return esc(arr.map(chName).join(", ")); };
    var top = by[0].chs.length ? by[0].chs : by[1].chs;
    var leads = rows.filter(function (ch) { return isLead(ch, c); });
    var miss = by[3].chs.filter(function (ch) { return !chStats(ch).free; });
    var s = "<b>" + esc(c.name) + "</b> " + (top.length ? t("pf.strong", { names: names(top) }) : t("pf.none"));
    if (leads.length) s += t("pf.leads", { names: names(leads) });
    s += ".";
    if (miss.length) s += t("pf.out", { names: names(miss) });
    var LV2 = [t("lv.abs"), t("lv.1"), t("lv.2"), t("lv.3")];
    var chip = function (ch) {
      var s2 = chSlot(ch, c);
      var v = s2[0], n = s2[1];
      return '<span class="cp v' + v + '" title="' + chipTip(ch, c) + '"><span class="gm g-' + ch.g + '"></span>' +
        (ch.g === "inf" ? t("ch.creators_short", { name: ch.l }) : ch.l) + ' <b class="num">' + fmt(n) + "</b>" +
        (isLead(ch, c) ? '<span class="r1">' + nth(1) + "</span>" : "") +
        (ch.w && ch.w[c.k] ? ' <span class="wf" aria-label="' + t("tip.check", { note: "" }) + '">!</span>' : "") + "</span>";
    };
    return '<p class="sumline">' + s + "</p>" +
      by.filter(function (x) { return x.chs.length; }).map(function (x) {
        return '<div class="lvr"><div class="lb">' + bub(x.v) + LV2[x.v] + " <small>" + x.chs.length + '</small></div><div class="chs">' + x.chs.map(chip).join("") + "</div></div>";
      }).join("") +
      '<div class="hint"><span><span class="gm g-paid"></span>' + GR.paid + '</span><span><span class="gm g-org"></span>' + GR.org + '</span><span><span class="gm g-inf"></span>' + GR.inf + '</span><span><span class="r1">' + nth(1) + "</span> " + t("pf.hint_lead") + "</span><span>" + t("pf.hint_hover") + "</span></div>";
  }

  function renderPerfil() {
    var c = CO.find(function (x) { return x.k === sel; }) || ME;
    var seg = '<div class="seg" role="group" aria-label="' + t("seg.company") + '">' + CO.map(function (x) {
      return '<button type="button" data-co="' + x.k + '" aria-pressed="' + (x.k === sel) + '">' + coDot(x) + esc(x.name) + "</button>";
    }).join("") + "</div>";
    var cats = perfilF(c);
    var months = c.months || [];
    var mlab = c.month_labels || D.visit_labels || [];
    var vis = months.length
      ? '<div class="bars">' + months.map(function (v) {
          var mx = Math.max.apply(null, months.concat([1]));
          return "<span><i style=\"height:" + ((v / mx) * 100).toFixed(0) + '%"></i></span>';
        }).join("") + "</div><div class=\"bl\">" + months.map(function (_, i) { return "<span>" + esc(mlab[i] || "") + "</span>"; }).join("") + "</div>"
      : '<div class="ref">' + t("pf.no_series") + "</div>";
    var brand = c.brand || [];
    var blab = c.brand_labels || D.brand_labels || [];
    var bm = Math.max.apply(null, brand.concat([1]));
    $("v6-pb-perfil").innerHTML = seg + '<div class="pf"><div>' + cats + "</div><div>" +
      '<div class="mini"><div class="k">' + t("pf.visits") + '</div><div class="v num">' + fmt(c.visits) + "<small class=\"" + (c.vg >= 0 ? "up" : "dn") + '">' + pct(c.vg) + " " + t("board.mo2") + "</small></div>" + (c.me ? "" : '<div class="ref">' + t("pf.you", { n: fmt(ME.visits) }) + "</div>") + vis + "</div>" +
      '<div class="mini"><div class="k">' + t("pf.brand") + '</div><div class="v num">' + fmt(brand[brand.length - 1]) + "<small class=\"" + (c.bg >= 0 ? "up" : "dn") + '">' + pct(c.bg) + " " + t("board.yr1") + "</small></div>" + (c.me ? "" : '<div class="ref">' + t("pf.you", { n: fmt((ME.brand || [])[(ME.brand || []).length - 1]) }) + "</div>") +
      '<div class="bars">' + brand.map(function (v) { return "<span><i style=\"height:" + ((v / bm) * 100).toFixed(1) + '%"></i></span>'; }).join("") + "</div><div class=\"bl\">" + brand.map(function (_, i) { return "<span>" + esc(blab[i] || "") + "</span>"; }).join("") + "</div></div></div></div>";
  }

  function renderCanais() {
    var rows = CH.filter(function (ch) {
      if (ch.g === "inf") return true;
      return !CO.every(function (c) { return chSlot(ch, c)[0] == null; });
    });
    var nc = CH.filter(function (ch) {
      if (ch.g === "inf") return false;
      return CO.every(function (c) { return chSlot(ch, c)[0] == null; });
    });
    var free = rows.filter(function (ch) {
      return CO.every(function (c) { return chSlot(ch, c)[0] === 0; });
    });
    var F = [["all", t("flt.all")], ["3", t("lv.3")], ["2", t("lv.2")], ["1", t("lv.1")], ["0", t("lv.0")]];
    var h = '<div class="seg" role="group" aria-label="' + t("flt.aria") + '"><span class="seglab">' + t("flt.label") + "</span>" + F.map(function (pair) {
      return '<button type="button" data-flt="' + pair[0] + '" aria-pressed="' + (flt === pair[0]) + '">' + (pair[0] === "all" ? "" : bub(+pair[0])) + pair[1] + "</button>";
    }).join("") + "</div>";
    h += '<div class="bx' + (flt !== "all" ? " fon" : "") + '"><table><thead><tr><th class="cl"></th>' +
      CO.map(function (c) {
        return '<th class="' + (c.me ? "me" : "") + '"><span class="ch-h">' + coDot(c) + esc(c.name) + "</span>" + (c.me ? you() : "") + "</th>";
      }).join("") + "</tr></thead><tbody>";
    ["paid", "org", "inf"].forEach(function (g) {
      var chs = rows.filter(function (ch) { return ch.g === g; });
      if (!chs.length) return;
      h += '<tr class="gr"><td colspan="' + (CO.length + 1) + '"><span class="gl gl-' + g + '"><span class="gm g-' + g + '"></span>' + GR[g] + "</span></td></tr>";
      chs.forEach(function (ch) {
        var empty = free.indexOf(ch) >= 0;
        h += "<tr" + (empty ? ' class="er"' : "") + '><td class="cl"><b>' + esc(ch.l) + "</b><span>" + esc(unitOf(ch)) + (empty ? " · <em>" + t("flt.nobody") + "</em>" : "") + "</span></td>" +
          CO.map(function (c) {
            var s = chSlot(ch, c);
            var v = s[0], n = s[1], w = (ch.w || {})[c.k];
            var tip = esc(c.name) + " · " + esc(ch.l) + ": " + (v == null ? t("tip.not_collected") : (n == null ? "—" : num(n) + " " + unitOf(ch) + " · " + LBL[v])) + (w ? " — " + t("tip.verify", { note: w }) : "");
            return '<td class="c' + (c.me ? " me" : "") + (flt !== "all" && String(v) === flt ? " hit" : "") + '" title="' + tip + '"><span class="bc">' + bub(v) + '<span class="bv num' + (v === 0 ? " z" : "") + '">' + (v == null ? "" : fmt(n)) + (w ? ' <span class="wf">!</span>' : "") + "</span></span></td>";
          }).join("") + "</tr>";
      });
    });
    h += '</tbody></table></div><div class="note">' +
      '<span class="blg">' + [3, 2, 1, 0].map(function (v) { return "<span>" + bub(v) + LBL[v] + "</span>"; }).join("") + "</span>" +
      (free.length ? "<span>" + t("flt.free") + " <b>" + free.map(function (x) { return x.l; }).join(" · ") + "</b></span>" : "") +
      (nc.length ? "<span>" + t("flt.nc") + " <b>" + nc.map(function (x) { return x.g === "inf" ? t("ch.creators", { name: x.l }) : t("ch.followers", { name: x.l }); }).join(" · ") + "</b></span>" : "") +
      "</div>";
    $("v6-pb-canais").innerHTML = h;
  }

  function renderGanha() {
    var choices = allMetrics().filter(function (m) { return CO.some(function (c) { return (m.get(c) || 0) > 0; }); });
    var m = choices.find(function (x) { return x.k === rkSel; }) || choices[0];
    if (!m) { $("v6-pb-ganha").innerHTML = '<div class="none">' + t("rk.none") + "</div>"; return; }
    var rows = CO.map(function (c) { return { c: c, v: m.get(c) }; }).filter(function (x) { return x.v != null; }).sort(function (a, b) { return b.v - a.v; });
    if (!rows.length) { $("v6-pb-ganha").innerHTML = '<div class="none">' + t("rk.nodata") + "</div>"; return; }
    var mx = rows[0].v, pos = rows.findIndex(function (x) { return x.c.me; }), mine = rows[pos];
    var r = function (a, b) { var q = a / b; return q >= 10 ? Math.round(q) + "×" : dec1(q) + "×"; };
    var verdict = "—";
    if (!mine || mine.v === 0) verdict = t("rk.out", { name: esc(rows[0].c.name), n: fmt(rows[0].v), unit: m.u });
    else if (pos === 0) verdict = t("rk.lead") + (rows[1] && rows[1].v ? t("rk.lead2", { x: r(mine.v, rows[1].v), name: esc(rows[1].c.name) }) : "") + ".";
    else verdict = t("rk.pos", { nth: nth(pos + 1), n: rows.length, name: esc(rows[0].c.name), x: r(rows[0].v, mine.v) });
    $("v6-pb-ganha").innerHTML = '<div class="seg" role="group" aria-label="' + t("rk.channel") + '">' + choices.map(function (x) {
      return '<button type="button" data-rk="' + x.k + '" aria-pressed="' + (x.k === m.k) + '">' + x.l + "</button>";
    }).join("") + "</div>" +
      '<ol class="rk">' + rows.map(function (x, i) {
        return '<li class="' + (x.c.me ? "me" : "") + '"><span class="p num">' + (i + 1) + '</span><span class="nmr">' + coDot(x.c) + esc(x.c.name) + '</span><span class="t"><i style="width:' + (mx ? Math.max(x.v / mx * 100, x.v ? 1.5 : 0).toFixed(1) : 0) + "%;background:" + x.c.color + '"></i></span><span class="v num' + (x.v === 0 ? " z" : "") + '">' + fmt(x.v) + "</span></li>";
      }).join("") + "</ol><div class=\"verdict\">" + verdict + "</div>";
  }

  function nmCell(c, href) {
    var name = href
      ? '<a href="' + esc(href) + '" target="_blank" rel="noopener">' + esc(c.name) + "</a>"
      : esc(c.name);
    return '<td><span class="nm">' + coDot(c) + name + (c.me ? you() : "") + "</span></td>";
  }

  function renderTrafego() {
    $("v6-pb-trafego").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>' + t("tr.company") + "</th><th>" + t("tr.visits") + "</th><th>" + t("tr.julset") + "</th><th>" + t("tr.bounce") + "</th><th>" + t("tr.ppv") + "</th><th>" + t("tr.time") + "</th></tr></thead><tbody>" +
      CO.map(function (c) {
        return "<tr>" + nmCell(c) + '<td class="num"><b>' + (c.visits ? num(c.visits) : "—") + '</b></td><td class="num ' + (c.vg >= 0 ? "up" : "dn") + '">' + pct(c.vg) + '</td><td class="num">' + (c.bounce == null ? "—" : dec1(c.bounce) + "%") + '</td><td class="num">' + (c.ppv == null ? "—" : Number(c.ppv).toFixed(2).replace(".", dec())) + '</td><td class="num">' + esc(c.time || "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="sub-h">' + t("tr.brand") + '</div><div class="mx brand-mx"><table class="tb"><thead><tr><th>' + t("tr.company") + "</th><th class="brc">' + t("find.th.brand") + "</th><th>" + t("tr.sem") + "</th></tr></thead><tbody>" +
      CO.map(function (c) {
        return "<tr>" + nmCell(c) + '<td class="brc">' + brandCell(c) + '</td><td class="num">' + (c.sem == null ? "—" : fmt(c.sem)) + (c.semg == null ? "" : ' <span class="' + (c.semg >= 0 ? "up" : "dn") + '" style="font-size:12.5px">' + pct(c.semg) + "</span>") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="note"><span>' + t("find.brand.tip_s") + "</span></div>";
  }

  function renderOrigem() {
    if (!(SRC.l || []).length) {
      $("v6-pb-origem").innerHTML = '<div class="none">' + t("or.none") + "</div>";
      return;
    }
    var rows = CO.map(function (c) {
      var v = SRC.v[c.k] || [];
      var paid = (SRC.paid || []).reduce(function (a, i) { return a + (v[i] || 0); }, 0);
      return '<div class="srow"><span class="nm">' + coDot(c) + esc(c.name) + '</span><div class="stack">' +
        v.map(function (x, i) { return x > 0 ? '<span style="width:' + x + "%;background:" + SRC.c[i] + '" title="' + esc(srcL(SRC.l[i])) + ": " + dec1(x) + '%"></span>' : ""; }).join("") +
        '</div><span class="pd num">' + t("or.paid", { n: dec1(paid) }) + "</span></div>";
    }).join("");
    var legend = '<div class="slg">' + SRC.l.map(function (l, i) { return "<span><i style=\"background:" + SRC.c[i] + '"></i>' + esc(srcL(l)) + "</span>"; }).join("") + "</div>";
    var tbl = '<div class="mx" style="margin-top:22px"><table class="tb"><thead><tr><th>' + t("or.source") + "</th>" + CO.map(function (c) { return "<th>" + esc(c.name) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      SRC.l.map(function (l, i) {
        return "<tr><td>" + esc(srcL(l)) + ((SRC.paid || []).indexOf(i) >= 0 ? ' <span style="color:var(--soft);font-size:12px">' + t("or.paid_tag") + "</span>" : "") + "</td>" +
          CO.map(function (c) { return '<td class="num">' + dec1((SRC.v[c.k] || [])[i] || 0) + "%</td>"; }).join("") + "</tr>";
      }).join("") + "</tbody></table></div>";
    $("v6-pb-origem").innerHTML = rows + legend + tbl;
  }

  function renderExec() {
    var steps = EX.steps || [];
    var log = EX.log || "";
    var nLog = log ? log.split("\n").filter(function (l) { return l.trim(); }).length : 0;
    var rowHtml = function (r) {
      if (Array.isArray(r)) {
        return "<tr><td>" + esc(r[0]) + '</td><td class="num">' + esc(r[1]) + '</td><td class="num">' + esc(r[3]) + '</td><td class="num">—</td><td></td></tr>';
      }
      return '<tr class="' + (r.skipped ? "sk" : "") + '"><td>' + esc(r.label) + '</td><td class="num">' + esc(r.time) + '</td><td class="num">' + esc(r.cost) + '</td><td class="num">' + esc(r.pct || "—") + "</td><td" + (r.skipped ? ' class="muted"' : "") + ">" + esc(stL(r.status || "done")) + "</td></tr>";
    };
    $("v6-pb-exec").innerHTML = '<div class="kv3"><div><span>' + t("ex.time") + "</span><b>" + esc(EX.duration || "—") + "</b></div><div><span>" + t("ex.cost") + "</span><b>" + esc(EX.cost || "—") + "</b></div><div><span>" + t("ex.cos") + "</span><b>" + esc(String(EX.companies || CO.length)) + "</b></div><div><span>" + t("ex.steps") + "</span><b>" + steps.length + "</b></div></div>" +
      '<div class="ex-switch"><div class="ex-tabs" role="tablist" aria-label="' + t("ex.aria") + '">' +
      '<button type="button" data-ex="resumo" aria-pressed="true">' + t("ex.summary") + "</button>" +
      '<button type="button" data-ex="log" aria-pressed="false">' + t("ex.log") + (nLog ? " · " + nLog : "") + "</button></div>" +
      '<div class="ex-pane" data-ex-pane="resumo"><div class="mx"><table class="tb"><thead><tr><th>' + t("ex.area") + "</th><th>" + t("ex.time_col") + "</th><th>" + t("ex.cost_col") + "</th><th>" + t("ex.pct_col") + "</th><th>" + t("ex.status") + "</th></tr></thead><tbody>" +
      (steps.length ? steps.map(rowHtml).join("") : '<tr><td colspan="5" class="none">' + t("ex.none") + "</td></tr>") +
      '</tbody><tfoot><tr class="runlog-total"><th>' + t("ex.total") + '</th><th class="num">' + esc(EX.duration || "—") + '</th><th class="num">' + esc(EX.cost || "—") + '</th><th class="num">' + esc(EX.pct || "—") + "</th><th></th></tr></tfoot></table></div>" +
      (EX.rates ? '<p class="muted" style="margin-top:12px;font-size:12.5px;color:var(--soft)">' + esc(EX.rates) + "</p>" : "") +
      "</div>" +
      '<div class="ex-pane" data-ex-pane="log" hidden>' + (log ? "<pre>" + esc(log) + "</pre>" : '<div class="none">' + t("ex.empty") + "</div>") + "</div></div>";
  }

  var coSeg = function (tab) {
    return '<div class="seg" role="group" aria-label="' + t("seg.company") + '">' + CO.map(function (c) {
      return '<button type="button" data-tco="' + tab + ":" + c.k + '" aria-pressed="' + (tabCo[tab] === c.k) + '">' + coDot(c) + esc(c.name) + "</button>";
    }).join("") + "</div>";
  };
  var warnBox = function (txt) { return txt ? '<div class="warn">' + esc(txt) + "</div>" : ""; };

  function renderYT() {
    var c = CO.find(function (x) { return x.k === tabCo.yt; }) || ME;
    var y = YT[c.k] || { o: [], x: [], views: "0", off: "0", oth: "0", n: 0, d30: "0", m6: "0", y1: "0" };
    var list = function (arr, empty) {
      arr = arr || [];
      if (!arr.length) return '<div class="none">' + empty + "</div>";
      return '<ol class="vl">' + arr.map(function (it) {
        var href = it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + "</a>" : "<span>" + esc(it.title) + "</span>";
        return "<li>" + href + '<span class="vm">' + esc(it.channel || "") + (it.age ? " · " + esc(it.age) : "") + '</span><span class="vv num">' + esc(it.views_fmt || fmt(it.views)) + "</span></li>";
      }).join("") + "</ol>";
    };
    $("v6-pb-yt").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>' + t("yt.company") + "</th><th>" + t("yt.views") + "</th><th>" + t("yt.off") + "</th><th>" + t("yt.oth") + "</th><th>" + t("yt.videos") + "</th><th>" + t("yt.d30") + "</th><th>" + t("yt.m6") + "</th><th>" + t("yt.y1") + "</th></tr></thead><tbody>" +
      CO.map(function (k) {
        var z = YT[k.k] || { views: "0", off: "0", oth: "0", n: 0, d30: "0", m6: "0", y1: "0" };
        return '<tr class="' + (k.k === c.k ? "on" : "") + '" data-tco="yt:' + k.k + '">' + nmCell(k, z.ch || k.yt_url) + '<td class="num"><b>' + esc(z.views) + "</b>" + (z.w ? ' <span class="wf" title="' + esc(z.w) + '">!</span>' : "") + '</td><td class="num">' + esc(z.off) + '</td><td class="num">' + esc(z.oth) + '</td><td class="num">' + esc(String(z.n || 0)) + '</td><td class="num">' + esc(z.d30) + '</td><td class="num">' + esc(z.m6) + '</td><td class="num">' + esc(z.y1) + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="det-h"><span>' + t("yt.page") + "</span>" + coSeg("yt") + "</div>" +
      warnBox(y.w) +
      '<div class="two"><div><div class="sub-h">' + t("yt.off_h") + " <span>" + esc(y.off) + " views</span></div>" + list(y.o, t("yt.empty_off")) + "</div>" +
      "<div><div class=\"sub-h\">" + t("yt.oth_h") + " <span>" + esc(y.oth) + " views</span></div>" + list(y.x, t("yt.empty_oth")) + "</div></div>" +
      '<div class="note">' + (y.search ? '<a class="lnk" href="' + esc(y.search) + '" target="_blank" rel="noopener">' + t("yt.search") + "</a>" : "") + (y.ch ? '<a class="lnk" href="' + esc(y.ch) + '" target="_blank" rel="noopener">' + t("yt.ch") + "</a>" : "") + "</div>";
  }

  function renderIG() {
    var c = CO.find(function (x) { return x.k === tabCo.ig; }) || ME;
    var g = IG[c.k] || { p: [], inf_posts: [], likes: "0", own: 0, inf: 0, infp: 0 };
    $("v6-pb-ig").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>' + t("ig.company") + "</th><th>" + t("ig.followers") + "</th><th>" + t("ig.likes") + "</th><th>" + t("ig.own") + "</th><th>" + t("ig.inf") + "</th><th>" + t("ig.infp") + "</th></tr></thead><tbody>" +
      CO.map(function (k) {
        var z = IG[k.k] || { likes: "0", own: 0, inf: 0, infp: 0 };
        return '<tr class="' + (k.k === c.k ? "on" : "") + '" data-tco="ig:' + k.k + '">' + nmCell(k, z.profile || k.ig_url) + '<td class="num" style="color:var(--soft)">' + esc(z.followers || t("nc")) + '</td><td class="num"><b>' + esc(z.likes) + "</b>" + (z.w ? ' <span class="wf" title="' + esc(z.w) + '">!</span>' : "") + '</td><td class="num">' + esc(String(z.own || 0)) + '</td><td class="num">' + esc(String(z.inf || 0)) + '</td><td class="num">' + esc(String(z.infp || 0)) + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="det-h"><span>' + t("ig.posts_of") + "</span>" + coSeg("ig") + "</div>" + warnBox(g.w) +
      '<div class="two"><div><div class="sub-h">' + t("ig.own_h") + " " + (g.h ? "<span>@" + esc(g.h) + "</span>" : "") + "</div>" +
      ((g.p || []).length ? '<ol class="vl">' + g.p.map(function (it, i) {
        var lab = (it.kind === "reel" ? "Reel" : "Post") + " " + (i + 1) + (g.h ? " · @" + g.h : "");
        var href = it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title || lab) + "</a>" : esc(it.title || lab);
        return "<li>" + href + '<span class="vm">' + t("ig.own_tag") + '</span><span class="vv num">' + t("ig.likes_n", { n: it.likes_fmt || fmt(it.likes) }) + "</span></li>";
      }).join("") + "</ol>" : '<div class="none">' + t("ig.empty_own") + "</div>") +
      '</div><div><div class="sub-h">' + t("ig.inf_h") + "</div>" +
      ((g.inf_posts || []).length ? '<ol class="vl">' + g.inf_posts.map(function (it) {
        var href = it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + "</a>" : esc(it.title);
        return "<li>" + href + '<span class="vm">' + t("ig.inf_tag") + '</span><span class="vv num">' + t("ig.likes_n", { n: it.likes_fmt || fmt(it.likes) }) + "</span></li>";
      }).join("") + "</ol>" : '<div class="none">' + t("ig.empty_inf") + "</div>") +
      "</div></div>" +
      '<div class="note">' + (g.profile || g.h ? '<a class="lnk" href="' + esc(g.profile || ("https://www.instagram.com/" + g.h + "/")) + '" target="_blank" rel="noopener">' + t("ig.profile") + (g.h ? " @" + esc(g.h) : "") + " ↗</a>" : "") + "<span>" + t("ig.note") + "</span></div>";
  }

  function renderTT() {
    var c = CO.find(function (x) { return x.k === tabCo.tt; }) || ME;
    var y = TT[c.k] || { o: [], x: [], views: "0", off: "0", oth: "0", n: 0 };
    var list = function (arr, empty) {
      arr = arr || [];
      if (!arr.length) return '<div class="none">' + empty + "</div>";
      return '<ol class="vl">' + arr.map(function (it) {
        var href = it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + "</a>" : "<span>" + esc(it.title) + "</span>";
        return "<li>" + href + '<span class="vm">' + esc(it.channel || "") + (it.age ? " · " + esc(it.age) : "") + '</span><span class="vv num">' + esc(it.views_fmt || fmt(it.views)) + "</span></li>";
      }).join("") + "</ol>";
    };
    $("v6-pb-tt").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>' + t("tt.company") + "</th><th>" + t("tt.followers") + "</th><th>" + t("tt.views") + "</th><th>" + t("tt.off") + "</th><th>" + t("tt.oth") + "</th><th>" + t("tt.posts") + "</th></tr></thead><tbody>" +
      CO.map(function (k) {
        var z = TT[k.k] || { views: "0", off: "0", oth: "0", n: 0 };
        return '<tr class="' + (k.k === c.k ? "on" : "") + '" data-tco="tt:' + k.k + '">' + nmCell(k, z.profile || k.tt_url) + '<td class="num" style="color:var(--soft)">' + esc(z.followers || t("nc")) + '</td><td class="num"><b>' + esc(z.views) + "</b>" + (z.w ? ' <span class="wf" title="' + esc(z.w) + '">!</span>' : "") + '</td><td class="num">' + esc(z.off) + '</td><td class="num">' + esc(z.oth) + '</td><td class="num">' + esc(String(z.n || 0)) + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="det-h"><span>' + t("tt.page") + "</span>" + coSeg("tt") + "</div>" +
      warnBox(y.w) +
      (y.collected === false
        ? '<div class="none">' + t("tt.none_run") + "</div>"
        : '<div class="two"><div><div class="sub-h">' + t("tt.off_h") + " <span>" + esc(y.off) + " views</span></div>" + list(y.o, t("tt.empty_off")) + "</div>" +
          "<div><div class=\"sub-h\">" + t("tt.oth_h") + " <span>" + esc(y.oth) + " views</span></div>" + list(y.x, t("tt.empty_oth")) + "</div></div>") +
      '<div class="note">' + (y.search ? '<a class="lnk" href="' + esc(y.search) + '" target="_blank" rel="noopener">' + t("tt.search") + "</a>" : "") + (y.profile || y.h ? '<a class="lnk" href="' + esc(y.profile || ("https://www.tiktok.com/@" + y.h)) + '" target="_blank" rel="noopener">' + t("tt.ch") + (y.h ? " @" + esc(y.h) : "") + "</a>" : "") + "<span>" + (y.collected === false ? t("tt.none_run") : t("tt.note")) + "</span></div>";
  }

  function renderRD() {
    var c = CO.find(function (x) { return x.k === tabCo.rd; }) || ME;
    var r = RD[c.k] || { posts: 0, com: 0, g: "—", l: [] };
    $("v6-pb-rd").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>' + t("rd.company") + "</th><th>" + t("rd.posts") + "</th><th>" + t("rd.com") + "</th><th>" + t("rd.g") + "</th></tr></thead><tbody>" +
      CO.map(function (k) {
        var z = RD[k.k] || { posts: 0, com: 0, g: "—" };
        return '<tr class="' + (k.k === c.k ? "on" : "") + '" data-tco="rd:' + k.k + '">' + nmCell(k) + '<td class="num">' + esc(String(z.posts || 0)) + (z.w ? ' <span class="wf" title="' + esc(z.w) + '">!</span>' : "") + '</td><td class="num">' + esc(String(z.com || 0)) + '</td><td class="num" style="color:var(--soft)">' + esc(z.g || "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="det-h"><span>' + t("rd.about") + "</span>" + coSeg("rd") + "</div>" + warnBox(r.w) +
      ((r.l || []).length ? '<ol class="vl" style="max-width:820px">' + r.l.map(function (it) {
        var href = it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + "</a>" : esc(it.title);
        return "<li>" + href + '<span class="vm">' + esc(it.sub || "") + "</span></li>";
      }).join("") + "</ol>" : '<div class="none">' + t("rd.empty") + "</div>") +
      '<div class="note">' + (r.search ? '<a class="lnk" href="' + esc(r.search) + '" target="_blank" rel="noopener">' + t("rd.search") + "</a>" : "") + "<span>" + t("rd.note") + "</span></div>";
  }

  function renderAds() {
    var paid = CH.filter(function (ch) { return ch.g === "paid"; });
    $("v6-pb-ads").innerHTML = paid.map(function (ch) {
      var rows = CO.map(function (c) {
        var s = chSlot(ch, c);
        return { c: c, v: s[0] == null ? 0 : (s[1] || 0) };
      }).sort(function (a, b) { return b.v - a.v; });
      var mx = Math.max.apply(null, rows.map(function (x) { return x.v; }).concat([0]));
      return '<div class="sub-h" style="margin-top:' + (ch === paid[0] ? 0 : 30) + 'px">' + ch.l + (ch.spend ? t("ads.spend", { n: ch.spend }) : "") + "</div>" +
        (mx === 0 ? '<div class="none" style="margin-bottom:8px">' + t("ads.none") + "</div>" : "") +
        '<ol class="rk ads">' + rows.map(function (x, i) {
          var w = (ch.w || {})[x.c.k];
          var lib = (LIB[x.c.k] || {})[ch.k] || "";
          return '<li class="' + (x.c.me ? "me" : "") + '"><span class="p num">' + (i + 1) + '</span><span class="nmr">' + coDot(x.c) + esc(x.c.name) + '</span><span class="t"><i style="width:' + (mx ? (x.v / mx * 100).toFixed(1) : 0) + "%;background:" + x.c.color + '"></i></span><span class="v num' + (x.v === 0 ? " z" : "") + '" title="' + (w ? esc(w) : "") + '">' + x.v + (w ? ' <span style="color:#8A6100">!</span>' : "") + (ch.spend && x.v ? '<span class="sp2">≈ US$ ' + (x.v * ch.spend).toLocaleString(loc()) + "</span>" : "") + "</span>" + (lib ? '<a class="lib" href="' + esc(lib) + '" target="_blank" rel="noopener">' + t("ads.lib") + "</a>" : "<span></span>") + "</li>";
        }).join("") + "</ol>";
    }).join("") + '<div class="note"><span>' + t("ads.note") + "</span></div>";
  }

  function pick(k) { sel = k; renderBoard(); renderPerfil(); }

  function renderAll() {
    GR = { paid: t("g.paid"), org: t("g.org"), inf: t("g.inf") };
    LBL = [t("lv.0"), t("lv.1"), t("lv.2"), t("lv.3")];
    paintChrome();
    renderShell();
    renderBoard();
    renderPerfil();
    renderCanais();
    renderGanha();
    renderTrafego();
    renderAds();
    renderOrigem();
    renderYT();
    renderIG();
    renderTT();
    renderRD();
    renderExec();
  }

  if (!root.dataset.bound) {
    root.dataset.bound = "1";
    root.addEventListener("click", function (e) {
      var tg = e.target.closest("[data-tag]");
      if (tg && root.contains(tg)) { var id = tg.dataset.tag; open = open === id ? null : id; renderTags(); if (open) $("v6-tags").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
      var x = e.target.closest("[data-close]");
      if (x && root.contains(x)) { open = null; renderTags(); return; }
      var c = e.target.closest("[data-co]");
      if (c && root.contains(c)) { pick(c.dataset.co); if (c.tagName === "TR") $("v6-pn-perfil").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
      var tc = e.target.closest("[data-tco]");
      if (tc && root.contains(tc)) {
        var parts = tc.dataset.tco.split(":");
        tabCo[parts[0]] = parts[1];
        ({ yt: renderYT, ig: renderIG, tt: renderTT, rd: renderRD })[parts[0]]();
        return;
      }
      var fl = e.target.closest("[data-flt]");
      if (fl && root.contains(fl)) { flt = fl.dataset.flt; renderCanais(); return; }
      var r = e.target.closest("[data-rk]");
      if (r && root.contains(r)) { rkSel = r.dataset.rk; renderGanha(); }
    });
    root.addEventListener("keydown", function (e) {
      var tr = e.target.closest && e.target.closest("tr[data-co]");
      if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); tr.click(); }
    });
    document.addEventListener("spy-lang", renderAll);
  }

  renderAll();
})();
