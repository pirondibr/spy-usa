(function () {
  var GROUPS = [
    { k: "paid", label: "Mídia paga", cls: "g-paid", subs: [["google", "Google"], ["meta", "Meta"], ["li_ads", "LinkedIn"]] },
    { k: "org", label: "Orgânico", cls: "g-org", subs: [["seo", "SEO"], ["x", "X"], ["ig", "Insta"], ["li", "LinkedIn"], ["yt", "YouTube"], ["tt", "TikTok"], ["rd", "Reddit"]] },
    { k: "inf", label: "Influenciadores", cls: "g-inf", subs: [["yt_inf", "YouTube"], ["ig_inf", "Insta"]] },
  ];
  var LBL = ["Sem presença", "Baixo", "Médio", "Alto"];
  var UNIT = {
    google: "anúncios", meta: "anúncios", li_ads: "anúncios", seo: "visitas",
    x: "seguidores", ig: "seguidores", li: "seguidores", yt: "inscritos",
    tt: "seguidores", rd: "coment.", yt_inf: "views", ig_inf: "curtidas",
  };
  var FULL = {
    x: "X", ig: "Instagram", ig_inf: "Instagram", li: "LinkedIn", li_ads: "LinkedIn",
    yt: "YouTube", yt_inf: "YouTube", tt: "TikTok", rd: "Reddit", seo: "SEO", google: "Google", meta: "Meta",
  };
  var MAC_SHORT = { paid: "Pago", org: "Orgânico", inf: "Influência" };
  var UNIT_L = { seo: "visitas/mês", rd: "comentários", visits: "visitas/mês", brand: "buscas/mês" };
  var QG = [
    { k: "visits", g: "Popularidade", label: "Visitas" },
    { k: "brand", g: "Popularidade", label: "Busca pela marca" },
  ].concat(
    GROUPS.flatMap(function (g) {
      return g.subs.map(function (pair) {
        return { k: pair[0], g: g.label, label: FULL[pair[0]] || pair[1] };
      });
    })
  );
  function qgVal(r, k) {
    if (k === "visits") return r.visits;
    if (k === "brand") return r.brand;
    return r.d[k];
  }
  function ratioTxt(a, b) {
    var r = a / b;
    return r >= 10 ? Math.round(r) + "×" : r.toFixed(1).replace(".", ",") + "×";
  }
  function isV4() {
    return true;
  }
  function m3(v, big) {
    if (v == null) return '<span class="na">n/c</span>';
    return '<span class="m3 ' + (big ? "big " : "") + (v === 0 ? "z" : "l" + v) + '" role="img" aria-label="' + LBL[v] + '"><i></i><i></i><i></i></span>';
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function fmt(n) {
    if (n == null || n === "") return "—";
    n = Number(n);
    if (!isFinite(n)) return "—";
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2).replace(/\.?0+$/, "").replace(".", ",") + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e5 ? 0 : 1).replace(/\.0$/, "").replace(".", ",") + "k";
    return String(Math.round(n));
  }
  function pct(p) {
    if (p == null || !isFinite(Number(p))) return "—";
    p = Number(p);
    return (p > 0 ? "+" : p < 0 ? "−" : "") + Math.abs(p).toLocaleString("pt-BR", { maximumFractionDigits: Math.abs(p) >= 100 ? 0 : 1 }) + "%";
  }
  function meter(lvl) {
    if (lvl == null) return '<span class="na">n/c</span>';
    return '<span class="m ' + (lvl === 0 ? "z" : "on" + lvl) + '" role="img" aria-label="' + LBL[lvl] + '"><i></i><i></i><i></i></span>';
  }
  function best(r, g) {
    var v = g.subs.map(function (s) { return r.s[s[0]]; }).filter(function (x) { return x != null; });
    return v.length ? Math.max.apply(null, v) : null;
  }
  function lvlCls(v) {
    if (v == null) return " isna";
    if (v === 0) return " isz isl0";
    return " isl" + v;
  }
  function bars(vals, labels) {
    if (!vals || !vals.length) return '<p class="sec-note">Sem série histórica.</p>';
    var mx = Math.max.apply(null, vals.concat([1]));
    return (
      '<div class="pf2-bars">' +
      vals.map(function (v) {
        return '<span><b class="num">' + fmt(v) + '</b><i style="height:' + Math.max((v / mx) * 100, 0.5).toFixed(1) + '%"></i></span>';
      }).join("") +
      "</div>" +
      '<div class="pf2-bl">' +
      (labels || []).map(function (l) { return "<span>" + esc(l) + "</span>"; }).join("") +
      "</div>"
    );
  }

  function initCmp(root) {
    var dataEl = root.querySelector(".cmp-data");
    if (!dataEl) return;
    var payload;
    try {
      payload = JSON.parse(dataEl.value || dataEl.textContent || "{}");
    } catch (e) {
      return;
    }
    var ROWS = payload.rows || [];
    if (!ROWS.length) return;
    ROWS.forEach(function (r) {
      r.s = r.s || {};
      r.d = r.d || {};
      r.w = r.w || {};
      r.series = r.series || { v: [], b: [] };
      GROUPS.forEach(function (g) { r["m_" + g.k] = best(r, g); });
    });
    var profileOnly = root.hasAttribute("data-profile-only");
    var visitLabels = payload.visit_labels || [];
    var brandLabels = payload.brand_labels || [];
    var mode = "lvl";
    var sortKey = null;
    var sortDir = -1;
    var meRow = ROWS.find(function (r) { return r.me; }) || ROWS[0];
    var sel = meRow.name;
    var tableEl = root.querySelector(".cmp-t");
    var pcard = root.querySelector(".pcard");
    var picker = root.querySelector(".picker");
    var hl = "";
    var tlegend = root.querySelector(".tlegend");
    var qgf = root.querySelector(".qg-f");
    var qgb = root.querySelector(".qg-b");
    var qgSel = "google";

    function syncVariant() {
      var v4 = isV4();
      root.classList.toggle("is-v4", v4);
      root.classList.toggle("datamode", v4 || mode === "data");
      if (tableEl) tableEl.classList.toggle("hm", v4);
    }

    function syncSpans() {
      var compact = root.classList.contains("compact");
      root.querySelectorAll("th[data-span]").forEach(function (th) {
        th.colSpan = compact ? 1 : +th.dataset.span;
      });
    }

    function render() {
      syncVariant();
      if (!tableEl || profileOnly) return;
      if (isV4()) renderV4();
      else renderV3();
    }

    function renderV4() {
      var best = {
        visits: Math.max.apply(null, ROWS.map(function (r) { return r.visits || 0; })),
        brand: Math.max.apply(null, ROWS.map(function (r) { return r.brand || 0; })),
      };
      var me = ROWS.filter(function (r) { return r.me; });
      var rest = ROWS.filter(function (r) { return !r.me; });
      if (sortKey) {
        rest.sort(function (a, b) {
          var va = a[sortKey] != null ? a[sortKey] : (a.d || {})[sortKey];
          var vb = b[sortKey] != null ? b[sortKey] : (b.d || {})[sortKey];
          var A = va == null ? -1 : va;
          var B = vb == null ? -1 : vb;
          return (A - B) * sortDir || String(a.name).localeCompare(String(b.name));
        });
      }
      var rows = me.concat(rest);
      var ar = function (k) { return sortKey === k ? (sortDir < 0 ? "↓" : "↑") : ""; };
      var sb = function (k, label, title) {
        return '<button type="button" class="sb" data-sort="' + esc(k) + '" title="' + esc(title || "") + '">' + label + '<span class="ar">' + ar(k) + "</span></button>";
      };
      var h =
        '<colgroup><col class="c-co"><col class="c-kpi"><col class="c-kpi"></colgroup>' +
        '<thead><tr class="grp"><th class="co" rowspan="2" style="padding:10px 14px;vertical-align:bottom">Empresa</th>' +
        '<th rowspan="2" class="r" style="padding:10px 12px;vertical-align:bottom">' + sb("visits", "Visitas", "Visitas/mês e variação no período") + "</th>" +
        '<th rowspan="2" class="r" style="padding:10px 12px;vertical-align:bottom">' + sb("brand", "Marca", "Buscas/mês e variação em 1 ano") + "</th>" +
        '<th class="hg hsum" colspan="' + GROUPS.length + '">Resumo geral</th>';
      GROUPS.forEach(function (g) {
        h += '<th class="hg subc ' + g.cls + '" colspan="' + g.subs.length + '">' + g.label + "</th>";
      });
      h += '</tr><tr class="colrow">';
      GROUPS.forEach(function (g, gi) {
        h += '<th class="hsc ' + g.cls + (gi === 0 ? " c0" : "") + '">' + sb("m_" + g.k, MAC_SHORT[g.k], "Melhor canal de " + g.label) + "</th>";
      });
      GROUPS.forEach(function (g) {
        g.subs.forEach(function (pair, si) {
          h += '<th class="hcs subc ' + g.cls + (si === 0 ? " c0" : "") + '">' + sb(pair[0], pair[1]) + '<span class="un">' + UNIT[pair[0]] + "</span></th>";
        });
      });
      h += "</tr></thead><tbody>";
      rows.forEach(function (r, i) {
        var tag = r.me ? '<span class="you">você</span>' : r.ex ? '<span class="ex">exemplo</span>' : "";
        var kd = function (v) {
          return '<span class="kd ' + (v > 0.5 ? "up" : v < -0.5 ? "dn" : "fl") + '">' + pct(v) + "</span>";
        };
        h +=
          '<tr class="' + (r.me ? "me" : "") + (r.name === sel ? " sel" : "") + '"><td class="co" data-pick="' + esc(r.name) + '" title="Ver perfil de ' + esc(r.name) + '"><div class="cn"><span class="rk num">' + (r.me ? "" : i) + '</span><span class="cdot" style="background:' + esc(r.color || "#9AA3AE") + '"></span><span class="nm">' + esc(r.name) + "</span>" + tag + '</div><div class="dom">' + esc(r.dom || "") + "</div></td>";
        h += '<td class="kpi num"><div class="kv">' + (r.visits === best.visits && r.visits ? '<span class="best" title="Maior da coluna"></span>' : "") + fmt(r.visits) + "</div>" + kd(r.vg) + "</td>";
        h += '<td class="kpi num"><div class="kv">' + (r.brand === best.brand && r.brand ? '<span class="best" title="Maior da coluna"></span>' : "") + fmt(r.brand) + "</div>" + kd(r.bg) + "</td>";
        GROUPS.forEach(function (g, gi) {
          var mv = r["m_" + g.k];
          h += '<td class="hcell sumc ' + g.cls + (gi === 0 ? " c0" : "") + lvlCls(mv) + '" title="' + esc(r.name + " · " + g.label + ": " + (mv == null ? "sem dado" : LBL[mv])) + '"><span class="cw">' + m3(mv, true) + '<span class="lt L' + mv + '">' + (mv == null ? "—" : LBL[mv]) + "</span></span></td>";
        });
        GROUPS.forEach(function (g) {
          g.subs.forEach(function (pair, si) {
            var k = pair[0];
            var l = pair[1];
            var v = r.s[k];
            var w = r.w[k];
            var dv = r.d[k];
            var tip = r.name + " · " + l + ": " + (v == null ? "não coletado" : (dv != null ? Number(dv).toLocaleString("pt-BR") + " " + UNIT[k] + " · " : "") + LBL[v]) + (w ? " — verificar: " + w : "");
            var txt = v == null ? "" : fmt(dv);
            h += '<td class="hcell subc ' + g.cls + (si === 0 ? " c0" : "") + lvlCls(v) + '" title="' + esc(tip) + '"><span class="cw">' + m3(v) + (v == null ? "" : '<span class="vn num' + (v === 0 ? " z" : "") + '">' + txt + "</span>") + "</span>" + (w ? '<span class="hw" aria-label="Verificar: ' + esc(w) + '">!</span>' : "") + "</td>";
          });
        });
        h += "</tr>";
      });
      h += "</tbody>";
      tableEl.innerHTML = h;
      tableEl.classList.add("hm");
      if (tlegend) {
        tlegend.innerHTML = "<span>Escala:</span>" + [3, 2, 1, 0].map(function (l) { return "<span>" + m3(l) + LBL[l] + "</span>"; }).join("") + '<span><span class="na">n/c</span>Não coletado</span><span><span class="hw" style="position:static">!</span>Verificar dado</span>';
      }
    }

    function renderV3() {
      if (!tableEl || profileOnly) return;
      var best = {
        visits: Math.max.apply(null, ROWS.map(function (r) { return r.visits || 0; })),
        brand: Math.max.apply(null, ROWS.map(function (r) { return r.brand || 0; })),
      };
      var me = ROWS.filter(function (r) { return r.me; });
      var rest = ROWS.filter(function (r) { return !r.me; });
      if (sortKey) {
        rest.sort(function (a, b) {
          var src = mode === "data" ? "d" : "s";
          var va = a[sortKey] != null ? a[sortKey] : (a[src] || {})[sortKey];
          var vb = b[sortKey] != null ? b[sortKey] : (b[src] || {})[sortKey];
          var A = va == null ? -1 : va;
          var B = vb == null ? -1 : vb;
          return (A - B) * sortDir || String(a.name).localeCompare(String(b.name));
        });
      }
      var rows = me.concat(rest);
      var ar = function (k) { return sortKey === k ? (sortDir < 0 ? "↓" : "↑") : ""; };
      var sb = function (k, label, title) {
        return '<button type="button" class="sb" data-sort="' + esc(k) + '" title="' + esc(title || "") + '">' + label + '<span class="ar">' + ar(k) + "</span></button>";
      };
      var h =
        '<thead><tr class="grp"><th class="co" rowspan="2" style="padding:10px 14px;vertical-align:bottom">Empresa</th>' +
        '<th rowspan="2" class="r" style="padding:10px 12px;vertical-align:bottom">' + sb("visits", "Visitas", "Visitas/mês e variação no período") + "</th>" +
        '<th rowspan="2" class="r" style="padding:10px 12px;vertical-align:bottom">' + sb("brand", "Marca", "Buscas/mês e variação em 1 ano") + "</th>";
      GROUPS.forEach(function (g) {
        h += '<th class="gc mac ' + g.cls + '" colspan="' + (g.subs.length + 1) + '" data-span="' + (g.subs.length + 1) + '">' + g.label + "</th>";
      });
      h += '</tr><tr class="colrow">';
      GROUPS.forEach(function (g) {
        h += '<th class="gc mac c ' + g.cls + '">' + sb("m_" + g.k, "Geral", "Melhor canal da categoria") + "</th>";
        g.subs.forEach(function (pair) {
          h += '<th class="gc c subc ' + g.cls + '">' + sb(pair[0], pair[1]) + (mode === "data" ? '<span class="un">' + UNIT[pair[0]] + "</span>" : "") + "</th>";
        });
      });
      h += "</tr></thead><tbody>";
      var colMax = {};
      GROUPS.forEach(function (g) {
        g.subs.forEach(function (pair) {
          colMax[pair[0]] = Math.max.apply(null, [0].concat(ROWS.map(function (r) { return r.d[pair[0]] || 0; })));
        });
      });
      rows.forEach(function (r, i) {
        var tag = r.me ? '<span class="you">você</span>' : r.ex ? '<span class="ex">exemplo</span>' : "";
        var kd = function (v) {
          return '<span class="kd ' + (v > 0.5 ? "up" : v < -0.5 ? "dn" : "fl") + '">' + pct(v) + "</span>";
        };
        h +=
          '<tr class="' + (r.me ? "me" : "") + (r.name === sel ? " sel" : "") + '"><td class="co" data-pick="' + esc(r.name) + '" title="Ver perfil de ' + esc(r.name) + '"><div class="cn"><span class="rk num">' + (r.me ? "" : i) + '</span><span class="cdot" style="background:' + esc(r.color || "#9AA3AE") + '"></span><span class="nm">' + esc(r.name) + "</span>" + tag + '</div><div class="dom">' + esc(r.dom || "") + "</div></td>";
        h += '<td class="kpi num"><div class="kv">' + (r.visits === best.visits && r.visits ? '<span class="best" title="Maior da coluna"></span>' : "") + fmt(r.visits) + "</div>" + kd(r.vg) + "</td>";
        h += '<td class="kpi num"><div class="kv">' + (r.brand === best.brand && r.brand ? '<span class="best" title="Maior da coluna"></span>' : "") + fmt(r.brand) + "</div>" + kd(r.bg) + "</td>";
        GROUPS.forEach(function (g) {
          var mv = r["m_" + g.k];
          h += '<td class="macv c ' + g.cls + lvlCls(mv) + '">' + meter(mv) + '<span class="ml' + (mv === 0 ? " z" : "") + '">' + (mv == null ? "—" : LBL[mv]) + "</span></td>";
          g.subs.forEach(function (pair) {
            var k = pair[0];
            var l = pair[1];
            var v = r.s[k];
            var w = r.w[k];
            var dv = r.d[k];
            var tip = r.name + " · " + l + ": " + (v == null ? "não coletado" : (dv != null ? Number(dv).toLocaleString("pt-BR") + " " + UNIT[k] + " · " : "") + LBL[v]) + (w ? " — " + w : "");
            var body =
              mode === "data"
                ? dv == null
                  ? '<span class="na">n/c</span>'
                  : '<span class="dv l' + v + ' num">' + (dv && dv === colMax[k] ? '<span class="best" title="Maior da coluna"></span>' : "") + fmt(dv) + "</span>"
                : meter(v);
            h += '<td class="cell subc ' + g.cls + lvlCls(v) + '" title="' + esc(tip) + '">' + body + (w ? '<span class="warn" aria-label="Verificar: ' + esc(w) + '">!</span>' : "") + "</td>";
          });
        });
        h += "</tr>";
      });
      h += "</tbody><tfoot><tr><td class=\"co\">Média do grupo</td>";
      var avgN = function (fn) {
        var v = ROWS.map(fn).filter(function (x) { return x != null && isFinite(x); });
        return v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : null;
      };
      var meanVis = avgN(function (r) { return r.visits; });
      var meanBr = avgN(function (r) { return r.brand; });
      h += '<td class="kpi num">' + (meanVis == null ? "—" : fmt(Math.round(meanVis))) + '</td><td class="kpi num">' + (meanBr == null ? "—" : fmt(Math.round(meanBr))) + "</td>";
      var mean = function (k) {
        var v = ROWS.map(function (r) { return r[k] != null ? r[k] : r.s[k]; }).filter(function (x) { return x != null; });
        return v.length ? Math.round(v.reduce(function (a, b) { return a + b; }, 0) / v.length) : null;
      };
      GROUPS.forEach(function (g) {
        h += '<td class="macv c ' + g.cls + '">' + meter(mean("m_" + g.k)) + "</td>";
        g.subs.forEach(function (pair) {
          var k = pair[0];
          if (mode === "data") {
            var v = ROWS.map(function (r) { return r.d[k]; }).filter(function (x) { return x != null; });
            h += '<td class="cell subc ' + g.cls + ' num">' + (v.length ? fmt(Math.round(v.reduce(function (a, b) { return a + b; }, 0) / v.length)) : "—") + "</td>";
          } else {
            h += '<td class="cell subc ' + g.cls + '">' + meter(mean(k)) + "</td>";
          }
        });
      });
      h += "</tr></tfoot>";
      tableEl.innerHTML = h;
      syncSpans();
    }

    function renderCard() {
      if (!pcard) return;
      var r = ROWS.find(function (x) { return x.name === sel; }) || ROWS[0];
      var S = r.series || { v: [], b: [] };
      var tag = r.me ? '<span class="you">você</span>' : r.ex ? '<span class="ex">exemplo</span>' : "";
      var v4 = isV4();
      var macro = function (g) {
        var lv = r["m_" + g.k];
        var segs = [0, 1, 2].map(function (i) {
          return "<i" + (lv != null && i < lv ? ' class="on"' : "") + "></i>";
        }).join("");
        var tags = g.subs.map(function (pair) {
          var k = pair[0];
          var l = pair[1];
          var full = FULL[k] || l;
          var v = r.s[k];
          var w = r.w[k];
          var dv = r.d[k];
          var title = full + ": " + (v == null ? "não coletado" : (dv != null ? Number(dv).toLocaleString("pt-BR") + " " + UNIT[k] + " · " : "") + LBL[v]) + (w ? " — verificar: " + w : "");
          if (v4) {
            if (v == null) return '<span class="pt3 pna" title="' + esc(title) + '">' + full + '<span class="pt-s">n/c</span></span>';
            return '<span class="pt3 lv' + v + (v === 0 ? " z" : "") + '" title="' + esc(title) + '">' + full + '<b class="num">' + fmt(dv) + "</b>" + m3(v) + (w ? '<span class="warn" style="margin:0">!</span>' : "") + "</span>";
          }
          if (v == null) return '<span class="pt na" title="' + esc(title) + '">' + l + '<span class="pt-s">n/c</span></span>';
          return '<span class="pt' + (v === 0 ? " z" : "") + '" title="' + esc(title) + '">' + l + '<span class="pt-m" aria-label="' + LBL[v] + '">' + [0, 1, 2].map(function (i) { return "<i" + (i < v ? ' class="on"' : "") + "></i>"; }).join("") + "</span>" + (w ? '<span class="warn" style="margin-left:0">!</span>' : "") + "</span>";
        }).join("");
        return '<div class="pm ' + g.cls + (v4 && lv != null ? " lvl" + lv : "") + '"><div class="pm-h"><b>' + g.label + '</b><span class="pm-l' + (lv === 0 ? " z" : "") + '">' + (lv == null ? "—" : LBL[lv]) + '</span><span class="pm-m" role="img" aria-label="' + (lv == null ? "sem dado" : LBL[lv]) + '">' + segs + '</span></div><div class="pm-t">' + tags + '</div></div>';
      };
      var vg = r.vg;
      var bg = r.bg;
      var dcls = function (p) { return p >= 0 ? "" : ' style="background:#FDF0EF;color:var(--down)"'; };
      var ref = function (val) {
        return r.me || !meRow ? "" : '<div class="ref">você: <b class="num">' + fmt(val) + "</b></div>";
      };
      var href = r.dom ? (r.dom.indexOf("://") >= 0 ? r.dom : "https://" + r.dom) : "";
      var nav = profileOnly || ROWS.length < 2
        ? ""
        : '<div class="nav2"><button type="button" data-step="-1" aria-label="Empresa anterior">‹</button><button type="button" data-step="1" aria-label="Próxima empresa">›</button></div>';
      var vLast = S.v && S.v.length ? S.v[S.v.length - 1] : r.visits;
      var bLast = S.b && S.b.length ? S.b[S.b.length - 1] : r.brand;
      pcard.innerHTML =
        '<div class="ch2"><span class="cdot" style="background:' + esc(r.color || "#9AA3AE") + ';width:11px;height:11px"></span><b>' + esc(r.name) + "</b>" + tag +
        (href ? '<a class="dm" href="' + esc(href) + '/" target="_blank" rel="noopener">' + esc(r.dom) + " ↗</a>" : (r.dom ? '<span class="dm">' + esc(r.dom) + "</span>" : "")) +
        nav + "</div>" +
        (v4 ? '<div class="pf-legend"><span>Escala:</span><span>' + m3(3) + "Alto</span><span>" + m3(2) + "Médio</span><span>" + m3(1) + "Baixo</span><span>" + m3(0) + 'Sem presença</span><span><span class="pt-s" style="border:1px dashed #D5DAE0;border-radius:4px;padding:0 4px;color:var(--soft)">n/c</span>Não coletado</span></div>' : "") +
        '<div class="pf2">' +
        '<div class="pf2-col"><div class="pf-lab">Força por categoria</div>' + GROUPS.map(macro).join("") + "</div>" +
        '<div class="pf2-col pf2-chart"><div class="pf-lab">Visitas · SimilarWeb</div>' +
        '<div class="pf2-top"><span class="pf2-v num">' + fmt(vLast) + "<small>/mês</small></span><span class=\"pf2-d num\"" + dcls(vg) + ">" + pct(vg) + " no período</span></div>" +
        ref(meRow.visits) + bars(S.v, visitLabels) + "</div>" +
        '<div class="pf2-col pf2-chart"><div class="pf-lab">Busca pela marca · DataForSEO</div>' +
        '<div class="pf2-top"><span class="pf2-v num">' + fmt(bLast) + "<small>/mês</small></span><span class=\"pf2-d num\"" + dcls(bg) + ">" + pct(bg) + " em 1 ano</span></div>" +
        ref(meRow.brand) + bars(S.b, brandLabels) + "</div>" +
        "</div>";
      if (picker) {
        picker.innerHTML = ROWS.map(function (x) {
          return '<button type="button" class="pk" data-pick="' + esc(x.name) + '" aria-pressed="' + (x.name === sel) + '"><span class="cdot" style="background:' + esc(x.color || "#9AA3AE") + '"></span>' + esc(x.name) + (x.me ? " · você" : "") + "</button>";
        }).join("");
      }
    }

    function renderQG() {
      if (!qgf || !qgb) return;
      var groups = [];
      QG.forEach(function (c) {
        if (groups.indexOf(c.g) < 0) groups.push(c.g);
      });
      qgf.innerHTML = groups.map(function (g) {
        return '<div class="qg-gr"><span class="qg-gl">' + esc(g) + "</span>" + QG.filter(function (c) { return c.g === g; }).map(function (c) {
          var any = ROWS.some(function (r) { return qgVal(r, c.k) != null; });
          return '<button type="button" data-qg="' + esc(c.k) + '" aria-pressed="' + (c.k === qgSel) + '"' + (any ? "" : ' disabled title="Não coletado para nenhuma empresa"') + ">" + esc(c.label) + "</button>";
        }).join("") + "</div>";
      }).join("");
      var c = QG.filter(function (x) { return x.k === qgSel; })[0] || QG[0];
      var unit = UNIT_L[c.k] || UNIT[c.k] || "";
      var have = ROWS.filter(function (r) { return qgVal(r, c.k) != null; }).map(function (r) {
        return { r: r, v: Number(qgVal(r, c.k)) || 0 };
      }).sort(function (a, b) { return b.v - a.v; });
      var miss = ROWS.filter(function (r) { return qgVal(r, c.k) == null; });
      var mx = have.length ? have[0].v : 0;
      var pos = have.findIndex(function (x) { return x.r.me; });
      var mine = pos >= 0 ? have[pos] : null;
      var verdict = "";
      if (!have.length) verdict = "Nenhuma empresa tem dado neste canal.";
      else if (have[0].v === 0) verdict = '<b class="down">Ninguém do grupo tem presença</b> neste canal — espaço livre.';
      else if (pos < 0) verdict = "Sua empresa não tem dado coletado neste canal.";
      else if (mine.v === 0) verdict = '<b class="down">Você não tem presença</b> — ' + esc(have[0].r.name) + " lidera com " + fmt(have[0].v) + " " + unit + ".";
      else if (pos === 0) verdict = have.length > 1 ? ('<b class="up">Você lidera</b> — ' + (have[1].v ? ratioTxt(mine.v, have[1].v) + " o 2º colocado (" + esc(have[1].r.name) + ")" : esc(have[1].r.name) + " não tem presença") + ".") : '<b class="up">Você lidera</b>.';
      else verdict = "Você é <b>" + (pos + 1) + "º de " + have.length + "</b> — " + esc(have[0].r.name) + ' tem <b class="down">' + ratioTxt(have[0].v, mine.v) + "</b> o seu volume.";
      qgb.innerHTML =
        '<div class="qg-h"><b>' + esc(c.label) + "</b><span>" + esc(c.g) + " · " + esc(unit) + "</span></div>" +
        '<ol class="qg-l">' + have.map(function (x, i) {
          var w = x.r.w && x.r.w[c.k];
          var width = mx ? Math.max((x.v / mx) * 100, x.v ? 1.5 : 0).toFixed(1) : "0";
          return '<li class="' + (x.r.me ? "me" : "") + (i === 0 && x.v > 0 ? " lead" : "") + '"><span class="rk num">' + (i === 0 && x.v > 0 ? "★" : i + 1) + "</span>" +
            '<button type="button" class="qg-n" data-pick="' + esc(x.r.name) + '" title="Ver perfil de ' + esc(x.r.name) + '"><span class="cdot" style="background:' + esc(x.r.color || "#9AA3AE") + '"></span>' + esc(x.r.name) + (x.r.me ? '<span class="you">você</span>' : "") + "</button>" +
            '<span class="qg-t"><i style="width:' + width + "%;background:" + esc(x.r.color || "#9AA3AE") + '"></i></span>' +
            '<span class="qg-v num' + (x.v === 0 ? " z" : "") + '">' + fmt(x.v) + "</span>" +
            (w ? '<span class="hw" style="position:static" title="Verificar: ' + esc(w) + '">!</span>' : "<span></span>") + "</li>";
        }).join("") + "</ol>" +
        (miss.length ? '<div class="qg-miss">Não coletado: ' + miss.map(function (r) { return esc(r.name); }).join(", ") + "</div>" : "") +
        '<div class="qg-v2">' + verdict + "</div>";
    }

    function pick(name, scroll) {
      sel = name;
      renderCard();
      render();
      if (scroll && pcard) pcard.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    root.addEventListener("click", function (e) {
      var s = e.target.closest("[data-sort]");
      if (s && root.contains(s)) {
        var k = s.getAttribute("data-sort");
        sortDir = sortKey === k ? -sortDir : -1;
        sortKey = k;
        render();
        return;
      }
      var md = e.target.closest("[data-mode]");
      if (md && root.contains(md)) {
        mode = md.getAttribute("data-mode");
        root.querySelectorAll("[data-mode]").forEach(function (b) {
          b.setAttribute("aria-pressed", b === md ? "true" : "false");
        });
        root.classList.toggle("datamode", mode === "data");
        render();
        return;
      }
      var hlBtn = e.target.closest("[data-hl]");
      if (hlBtn && root.contains(hlBtn)) {
        hl = hlBtn.getAttribute("data-hl") || "";
        root.classList.remove("weak", "hl-alto", "hl-medio", "hl-baixo");
        if (hl) root.classList.add("hl-" + hl);
        root.querySelectorAll("[data-hl]").forEach(function (b) {
          b.setAttribute("aria-pressed", (b.getAttribute("data-hl") || "") === hl ? "true" : "false");
        });
        return;
      }
      var v = e.target.closest("[data-view]");
      if (v && root.contains(v)) {
        root.querySelectorAll("[data-view]").forEach(function (b) {
          b.setAttribute("aria-pressed", b === v ? "true" : "false");
        });
        root.classList.toggle("compact", v.getAttribute("data-view") === "compact");
        syncSpans();
        return;
      }
      var qg = e.target.closest("[data-qg]");
      if (qg && root.contains(qg) && !qg.disabled) {
        qgSel = qg.getAttribute("data-qg");
        renderQG();
        return;
      }
      var p = e.target.closest("[data-pick]");
      if (p && root.contains(p)) {
        pick(p.getAttribute("data-pick"), p.tagName === "TD");
        return;
      }
      var st = e.target.closest("[data-step]");
      if (st && root.contains(st)) {
        var i = ROWS.findIndex(function (x) { return x.name === sel; });
        pick(ROWS[(i + Number(st.getAttribute("data-step")) + ROWS.length) % ROWS.length].name);
      }
    });
    window.addEventListener("spy-ui", function () {
      renderCard();
      render();
    });
    renderCard();
    render();
    renderQG();
  }

  document.querySelectorAll("[data-cmp]").forEach(initCmp);
})();
