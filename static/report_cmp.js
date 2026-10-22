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
  function avg(r, g) {
    var v = g.subs.map(function (s) { return r.s[s[0]]; }).filter(function (x) { return x != null; });
    return v.length ? Math.round(v.reduce(function (a, b) { return a + b; }, 0) / v.length) : null;
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
      payload = JSON.parse(dataEl.textContent || "{}");
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
      GROUPS.forEach(function (g) { r["m_" + g.k] = avg(r, g); });
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
    var weakEl = root.querySelector(".cmp-weak");

    function syncSpans() {
      var compact = root.classList.contains("compact");
      root.querySelectorAll("th[data-span]").forEach(function (th) {
        th.colSpan = compact ? 1 : +th.dataset.span;
      });
    }

    function render() {
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
        h += '<th class="gc mac c ' + g.cls + '">' + sb("m_" + g.k, "Geral", "Média dos canais") + "</th>";
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
          h += '<td class="macv c ' + g.cls + (mv === 0 ? " isz" : "") + '">' + meter(mv) + '<span class="ml' + (mv === 0 ? " z" : "") + '">' + (mv == null ? "—" : LBL[mv]) + "</span></td>";
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
            h += '<td class="cell subc ' + g.cls + (v === 0 ? " isz" : "") + (v == null ? " isna" : "") + '" title="' + esc(tip) + '">' + body + (w ? '<span class="warn" aria-label="Verificar: ' + esc(w) + '">!</span>' : "") + "</td>";
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
      var macro = function (g) {
        var lv = r["m_" + g.k];
        var segs = [0, 1, 2].map(function (i) {
          return "<i" + (lv != null && i < lv ? ' class="on"' : "") + "></i>";
        }).join("");
        var tags = g.subs.map(function (pair) {
          var k = pair[0];
          var l = pair[1];
          var v = r.s[k];
          var w = r.w[k];
          var dv = r.d[k];
          var title = l + ": " + (v == null ? "não coletado" : (dv != null ? Number(dv).toLocaleString("pt-BR") + " " + UNIT[k] + " · " : "") + LBL[v]) + (w ? " — verificar: " + w : "");
          if (v == null) return '<span class="pt na" title="' + esc(title) + '">' + l + '<span class="pt-s">n/c</span></span>';
          return '<span class="pt' + (v === 0 ? " z" : "") + '" title="' + esc(title) + '">' + l + '<span class="pt-m" aria-label="' + LBL[v] + '">' + [0, 1, 2].map(function (i) { return "<i" + (i < v ? ' class="on"' : "") + "></i>"; }).join("") + "</span>" + (w ? '<span class="warn" style="margin-left:0">!</span>' : "") + "</span>";
        }).join("");
        return '<div class="pm ' + g.cls + '"><div class="pm-h"><b>' + g.label + '</b><span class="pm-l' + (lv === 0 ? " z" : "") + '">' + (lv == null ? "—" : LBL[lv]) + '</span><span class="pm-m" role="img" aria-label="' + (lv == null ? "sem dado" : LBL[lv]) + '">' + segs + "</span></div><div class="pm-t">' + tags + "</div></div>";
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
      var v = e.target.closest("[data-view]");
      if (v && root.contains(v)) {
        root.querySelectorAll("[data-view]").forEach(function (b) {
          b.setAttribute("aria-pressed", b === v ? "true" : "false");
        });
        root.classList.toggle("compact", v.getAttribute("data-view") === "compact");
        syncSpans();
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
    if (weakEl) {
      weakEl.addEventListener("change", function (e) {
        root.classList.toggle("weak", e.target.checked);
      });
    }
    renderCard();
    render();
  }

  document.querySelectorAll("[data-cmp]").forEach(initCmp);
})();
