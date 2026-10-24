(function () {
  var root = document.getElementById("analysis-v5");
  var dataEl = document.getElementById("spy-v5-data");
  if (!root || !dataEl) return;
  var D;
  try {
    D = JSON.parse(dataEl.textContent || "{}");
  } catch (e) {
    return;
  }
  var CO = D.companies || [];
  var CH = D.channels || [];
  var GR = { paid: "Mídia paga", org: "Orgânico", inf: "Influenciadores" };
  var LBL = ["Sem presença", "Baixo", "Médio", "Alto"];
  var SRC = D.sources || { l: [], c: [], paid: [], v: {} };
  var LIB = D.ads_lib || {};
  var YT = D.youtube || {};
  var IG = D.instagram || {};
  var RD = D.reddit || {};
  var EX = D.exec || {};
  var META = D.meta || {};
  var extraFlags = D.flags || [];
  if (!CO.length) return;

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };
  var fmt = function (n) {
    if (n == null || n === "") return "—";
    n = Number(n);
    if (!isFinite(n)) return "—";
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2).replace(/\.?0+$/, "").replace(".", ",") + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e5 ? 0 : 1).replace(/\.0$/, "").replace(".", ",") + "k";
    return String(Math.round(n));
  };
  var pct = function (p) {
    if (p == null || !isFinite(Number(p))) return "—";
    p = Number(p);
    return (p > 0 ? "+" : p < 0 ? "−" : "") + Math.abs(p).toLocaleString("pt-BR", { maximumFractionDigits: Math.abs(p) >= 100 ? 0 : 1 }) + "%";
  };
  var meter = function (v) {
    if (v == null) return '<span style="color:var(--soft);font-size:12px">n/c</span>';
    return '<span class="m ' + (v === 0 ? "z" : "l" + v) + '" role="img" aria-label="' + LBL[v] + '"><i></i><i></i><i></i></span>';
  };
  var ME = CO.find(function (c) { return c.me; }) || CO[0];
  var coDot = function (c) { return '<span class="dot" style="background:' + c.color + '"></span>'; };
  var chVal = function (ch, c) {
    var s = (ch.s || {})[c.k];
    if (!s || s[0] == null) return null;
    return s[1] == null ? null : s[1];
  };
  var allMetrics = [
    { k: "visits", l: "Visitas", u: "visitas/mês", get: function (c) { return c.visits; } },
    { k: "brand", l: "Busca pela marca", u: "buscas/mês", get: function (c) { return (c.brand && c.brand[c.brand.length - 1]) || 0; } },
  ].concat(CH.map(function (ch) {
    return {
      k: ch.k,
      l: ch.g === "inf" ? ch.l + " (criadores)" : ch.l,
      u: ch.u,
      ch: ch,
      get: function (c) { return chVal(ch, c); },
    };
  }));

  var titleEl = $("v5-title");
  if (titleEl) {
    titleEl.innerHTML = esc(META.client || ME.name) + ' <span class="vs">vs ' + esc(META.vs || "") + "</span>";
  }
  var eye = $("v5-eyebrow");
  if (eye) eye.textContent = META.eyebrow || "";
  $("cos").innerHTML = CO.map(function (c) {
    return '<span data-domain="' + esc(c.dom || "") + '">' + coDot(c) + esc(c.name) + (c.me ? ' <span class="you">você</span>' : ' <span style="color:var(--soft)">' + esc(c.dom) + "</span>") + "</span>";
  }).join("");

  (function insights() {
    var lead = [], behind = [], free = [];
    allMetrics.forEach(function (m) {
      var vals = CO.map(function (c) { return { c: c, v: m.get(c) }; }).filter(function (x) { return x.v != null; });
      if (!vals.length) return;
      var mx = Math.max.apply(null, vals.map(function (x) { return x.v; }));
      if (mx === 0) { free.push(m.l); return; }
      var top = vals.find(function (x) { return x.v === mx; }).c;
      var mine = m.get(ME);
      if (top.me) lead.push(m.l);
      else if (mine != null && mine < mx) behind.push({ l: m.l, who: top.name });
    });
    $("ins").innerHTML =
      '<li class="f"><div class="k">Onde você lidera</div><div class="v">' + (lead.length ? lead.map(function (x) { return "<b>" + esc(x) + "</b>"; }).join(", ") : "—") + "</div></li>" +
      '<li class="w"><div class="k">Onde você está atrás</div><div class="v">' + (behind.slice(0, 5).map(function (x) { return "<b>" + esc(x.l) + "</b> (" + esc(x.who) + ")"; }).join(", ") || "—") + "</div></li>" +
      "<li><div class=\"k\">Espaço livre — ninguém do grupo está em</div><div class=\"v\">" + (free.length ? free.map(function (x) { return "<b>" + esc(x) + "</b>"; }).join(", ") : "—") + "</div></li>";
  })();

  var sel = ME.k;
  function renderBoard() {
    var h = '<thead><tr><th>Empresa</th><th class="r">Visitas/mês</th><th class="r hide-s">Busca pela marca</th>' +
      Object.values(GR).map(function (g) { return '<th class="c">' + g + "</th>"; }).join("") + "</tr></thead><tbody>";
    CO.forEach(function (c) {
      var brandNow = (c.brand && c.brand[c.brand.length - 1]) || 0;
      h += '<tr class="row' + (c.k === sel ? " sel" : "") + '" data-co="' + c.k + '" tabindex="0" aria-label="Ver perfil de ' + esc(c.name) + '">' +
        "<td><div class=\"nm\">" + coDot(c) + esc(c.name) + (c.me ? '<span class="you">você</span>' : "") + "</div></td>" +
        '<td class="r num"><span class="val">' + fmt(c.visits) + '</span><span class="d ' + (c.vg >= 0 ? "up" : "dn") + '">' + pct(c.vg) + "</span></td>" +
        '<td class="r num hide-s"><span class="val">' + fmt(brandNow) + '</span><span class="d ' + (c.bg >= 0 ? "up" : "dn") + '">' + pct(c.bg) + "</span></td>" +
        ["paid", "org", "inf"].map(function (g) {
          var lv = (c.cat || {})[g];
          return '<td class="c">' + meter(lv) + (lv == null ? "" : '<span class="lt">' + LBL[lv] + "</span>") + "</td>";
        }).join("") + "</tr>";
    });
    $("board").innerHTML = h + "</tbody>";
  }

  var flags = CH.flatMap(function (ch) {
    return Object.entries(ch.w || {}).map(function (pair) {
      var co = CO.find(function (c) { return c.k === pair[0]; });
      return "<li><b>" + esc(co ? co.name : pair[0]) + " · " + ch.l + (ch.g === "inf" ? " (criadores)" : "") + ":</b> " + esc(pair[1]) + "</li>";
    });
  });
  extraFlags.forEach(function (t) { flags.push("<li>" + esc(t) + "</li>"); });
  $("flags").innerHTML = flags.length
    ? "<summary>" + flags.length + " dados para verificar</summary><ul>" + flags.join("") + "</ul>"
    : "";

  var P = [
    { id: "perfil", t: "Perfil da empresa", d: "Força por categoria, canal a canal" },
    { id: "canais", t: "Canal a canal", d: "Todas as empresas em todos os canais" },
    { id: "ganha", t: "Quem está ganhando", d: "Ranking do grupo, um canal por vez" },
    { id: "trafego", t: "Tráfego e marca", d: "SimilarWeb · DataForSEO · Semrush", grp: "det" },
    { id: "origem", t: "Origem do tráfego", d: "SimilarWeb · estimativa, use com cautela", grp: "det" },
    { id: "ads", t: "Anúncios", d: "Bibliotecas públicas de anúncios", grp: "det" },
    { id: "yt", t: "YouTube", d: "1ª página da busca pelo nome da marca", grp: "det" },
    { id: "ig", t: "Instagram", d: "1ª página · posts próprios e de influenciadores", grp: "det" },
    { id: "rd", t: "Reddit", d: "Google: site:reddit.com + nome da marca", grp: "det" },
    { id: "exec", t: "Execução", d: "Tempo, custo e log da análise", grp: "det" },
  ];
  var FIXED = ["perfil", "canais"];
  var TABS = P.filter(function (p) { return FIXED.indexOf(p.id) < 0; });
  var open = null;
  try { open = localStorage.getItem("spy-min-tab"); } catch (e) {}
  if (!TABS.some(function (p) { return p.id === open; })) open = null;

  var panel = function (p, fixed) {
    return '<section class="pn' + (fixed ? " fx" : "") + '" id="pn-' + p.id + '"' + (fixed ? "" : " hidden") + ' aria-labelledby="h-' + p.id + '"><div class="ph"><h3 id="h-' + p.id + '">' + p.t + "</h3><p>" + p.d + "</p>" + (fixed ? "" : '<button type="button" class="x" data-close="' + p.id + '" aria-label="Fechar ' + p.t + '">×</button>') + '</div><div class="pb" id="pb-' + p.id + '"></div></section>';
  };
  $("fixed").innerHTML = P.filter(function (p) { return FIXED.indexOf(p.id) >= 0; }).map(function (p) { return panel(p, true); }).join("");
  $("panels").innerHTML = TABS.map(function (p) { return panel(p, false); }).join("");

  function renderTags() {
    $("tags").innerHTML = TABS.map(function (p) {
      return '<button type="button" class="tg" data-tag="' + p.id + '" aria-pressed="' + (open === p.id) + '" aria-controls="pn-' + p.id + '">' + p.t + "</button>";
    }).join("");
    TABS.forEach(function (p) { $("pn-" + p.id).hidden = open !== p.id; });
    try { open ? localStorage.setItem("spy-min-tab", open) : localStorage.removeItem("spy-min-tab"); } catch (e) {}
  }

  function renderPerfil() {
    var c = CO.find(function (x) { return x.k === sel; }) || ME;
    var seg = '<div class="seg" role="group" aria-label="Empresa">' + CO.map(function (x) {
      return '<button type="button" data-co="' + x.k + '" aria-pressed="' + (x.k === sel) + '">' + coDot(x) + esc(x.name) + "</button>";
    }).join("") + "</div>";
    var cats = ["paid", "org", "inf"].map(function (g) {
      return '<div class="cat"><div class="cat-h"><b>' + GR[g] + '</b><span class="lv">' + (c.cat[g] == null ? "n/c" : LBL[c.cat[g]]) + "</span>" + meter(c.cat[g]) + '</div><div class="chs">' +
        CH.filter(function (ch) { return ch.g === g; }).map(function (ch) {
          var s = (ch.s || {})[c.k] || [null];
          var v = s[0], n = s[1], w = (ch.w || {})[c.k];
          if (v == null) return '<span class="ch" style="color:var(--soft)" title="Não coletado">' + ch.l + ' <span style="font-size:11px">n/c</span></span>';
          return '<span class="ch v' + v + '" title="' + esc(ch.l) + ": " + (n == null ? "—" : Number(n).toLocaleString("pt-BR")) + " " + ch.u + " · " + LBL[v] + (w ? " — verificar: " + esc(w) : "") + '">' + ch.l + ' <b class="num">' + fmt(n) + "</b>" + meter(v) + (w ? '<span class="w">!</span>' : "") + "</span>";
        }).join("") + "</div></div>";
    }).join("");
    var months = c.months || [];
    var mlab = c.month_labels || D.visit_labels || [];
    var vis = months.length
      ? '<div class="bars">' + months.map(function (v) {
          var mx = Math.max.apply(null, months.concat([1]));
          return "<span><i style=\"height:" + ((v / mx) * 100).toFixed(0) + '%"></i></span>';
        }).join("") + "</div><div class=\"bl\">" + months.map(function (_, i) { return "<span>" + esc(mlab[i] || "") + "</span>"; }).join("") + "</div>"
      : '<div class="ref">Série mensal não disponível</div>';
    var brand = c.brand || [];
    var blab = c.brand_labels || D.brand_labels || [];
    var bm = Math.max.apply(null, brand.concat([1]));
    $("pb-perfil").innerHTML = seg + '<div class="pf"><div>' + cats + "</div><div>" +
      '<div class="mini"><div class="k">Visitas por mês</div><div class="v num">' + fmt(c.visits) + "<small class=\"" + (c.vg >= 0 ? "up" : "dn") + '">' + pct(c.vg) + "</small></div>" + (c.me ? "" : '<div class="ref">você: ' + fmt(ME.visits) + "</div>") + vis + "</div>" +
      '<div class="mini"><div class="k">Buscas pela marca por mês</div><div class="v num">' + fmt(brand[brand.length - 1]) + "<small class=\"" + (c.bg >= 0 ? "up" : "dn") + '">' + pct(c.bg) + "</small></div>" + (c.me ? "" : '<div class="ref">você: ' + fmt((ME.brand || [])[(ME.brand || []).length - 1]) + "</div>") +
      '<div class="bars">' + brand.map(function (v) { return "<span><i style=\"height:" + ((v / bm) * 100).toFixed(1) + '%"></i></span>'; }).join("") + "</div><div class=\"bl\">" + brand.map(function (_, i) { return "<span>" + esc(blab[i] || "") + "</span>"; }).join("") + "</div></div></div></div>";
  }

  var flt = "all";
  function renderCanais() {
    var live = CH.filter(function (ch) { return CO.some(function (c) { var s = (ch.s || {})[c.k]; return s && s[0] != null && s[0] > 0; }); });
    var off = CH.filter(function (ch) { return live.indexOf(ch) < 0; });
    var free = off.filter(function (ch) { return CO.every(function (c) { var s = (ch.s || {})[c.k]; return s && s[0] === 0; }); });
    var nc = off.filter(function (ch) { return CO.every(function (c) { var s = (ch.s || {})[c.k]; return !s || s[0] == null; }); });
    var groups = ["paid", "org", "inf"].map(function (g) { return { g: g, chs: live.filter(function (ch) { return ch.g === g; }) }; }).filter(function (x) { return x.chs.length; });
    var F = [["all", "Todos"], ["3", "Alto"], ["2", "Médio"], ["1", "Baixo"], ["0", "Sem presença"]];
    var h = '<div class="seg" role="group" aria-label="Destacar nível"><span class="seglab">Destacar</span>' + F.map(function (pair) {
      return '<button type="button" data-flt="' + pair[0] + '" aria-pressed="' + (flt === pair[0]) + '">' + (pair[0] === "all" ? "" : meter(+pair[0])) + pair[1] + "</button>";
    }).join("") + "</div>";
    h += '<div class="mx' + (flt !== "all" ? " fon" : "") + '"><table><thead><tr><th class="g"></th>' + groups.map(function (x) { return '<th class="g gs" colspan="' + x.chs.length + '">' + GR[x.g] + "</th>"; }).join("") + "</tr><tr><th>Empresa</th>" +
      groups.map(function (x) { return x.chs.map(function (ch, i) { return '<th class="' + (i === 0 ? "gs" : "") + '">' + ch.l + "</th>"; }).join(""); }).join("") + "</tr></thead><tbody>";
    CO.forEach(function (c) {
      h += "<tr><td><span class=\"nm\" style=\"display:inline-flex;align-items:center;gap:8px;font-weight:" + (c.me ? 700 : 500) + "\">" + coDot(c) + esc(c.name) + "</span></td>" +
        groups.map(function (x) {
          return x.chs.map(function (ch, i) {
            var s = (ch.s || {})[c.k] || [null];
            var v = s[0], n = s[1], w = (ch.w || {})[c.k];
            return '<td class="' + (i === 0 ? "gs" : "") + (flt !== "all" && String(v) === flt ? " hit" : "") + '" title="' + esc(c.name) + " · " + esc(ch.l) + ": " + (v == null ? "não coletado" : (n == null ? "—" : Number(n).toLocaleString("pt-BR") + " " + ch.u)) + (w ? " — verificar: " + esc(w) : "") + '">' + meter(v) + '<span class="n num' + (v === 0 ? " z" : "") + '">' + (v == null ? "" : fmt(n)) + (w ? ' <span style="color:#8A6100;font-weight:700">!</span>' : "") + "</span></td>";
          }).join("");
        }).join("") + "</tr>";
    });
    h += '</tbody></table></div><div class="note">' +
      (free.length ? "<span>Espaço livre (ninguém presente): <b>" + free.map(function (x) { return x.l; }).join(" · ") + "</b></span>" : "") +
      (nc.length ? "<span>Não coletado: <b>" + nc.map(function (x) { return x.l; }).join(" · ") + "</b></span>" : "") +
      "<span>Verde = Alto · amarelo = Médio · vermelho = Baixo · vazio = sem presença</span></div>";
    $("pb-canais").innerHTML = h;
  }

  var rkSel = "visits";
  function renderGanha() {
    var choices = allMetrics.filter(function (m) { return CO.some(function (c) { return (m.get(c) || 0) > 0; }); });
    var m = choices.find(function (x) { return x.k === rkSel; }) || choices[0];
    if (!m) { $("pb-ganha").innerHTML = '<div class="none">Sem canais com volume.</div>'; return; }
    var rows = CO.map(function (c) { return { c: c, v: m.get(c) }; }).filter(function (x) { return x.v != null; }).sort(function (a, b) { return b.v - a.v; });
    if (!rows.length) { $("pb-ganha").innerHTML = '<div class="none">Sem dados.</div>'; return; }
    var mx = rows[0].v, pos = rows.findIndex(function (x) { return x.c.me; }), mine = rows[pos];
    var r = function (a, b) { var q = a / b; return q >= 10 ? Math.round(q) + "×" : q.toFixed(1).replace(".", ",") + "×"; };
    var verdict = "—";
    if (!mine || mine.v === 0) verdict = '<b class="dn">Você não está neste canal.</b> ' + esc(rows[0].c.name) + " lidera com " + fmt(rows[0].v) + " " + m.u + ".";
    else if (pos === 0) verdict = '<b class="up">Você lidera</b>' + (rows[1] && rows[1].v ? " — " + r(mine.v, rows[1].v) + " o 2º colocado (" + esc(rows[1].c.name) + ")" : "") + ".";
    else verdict = "Você é <b>" + (pos + 1) + "º de " + rows.length + "</b>. " + esc(rows[0].c.name) + ' tem <b class="dn">' + r(rows[0].v, mine.v) + "</b> o seu volume.";
    $("pb-ganha").innerHTML = '<div class="seg" role="group" aria-label="Canal">' + choices.map(function (x) {
      return '<button type="button" data-rk="' + x.k + '" aria-pressed="' + (x.k === m.k) + '">' + x.l + "</button>";
    }).join("") + "</div>" +
      '<ol class="rk">' + rows.map(function (x, i) {
        return '<li class="' + (x.c.me ? "me" : "") + '"><span class="p num">' + (i + 1) + '</span><span class="nmr">' + coDot(x.c) + esc(x.c.name) + '</span><span class="t"><i style="width:' + (mx ? Math.max(x.v / mx * 100, x.v ? 1.5 : 0).toFixed(1) : 0) + "%;background:" + x.c.color + '"></i></span><span class="v num' + (x.v === 0 ? " z" : "") + '">' + fmt(x.v) + "</span></li>";
      }).join("") + "</ol><div class=\"verdict\">" + verdict + "</div>";
  }

  function nmCell(c) {
    return '<td><span class="nm">' + coDot(c) + esc(c.name) + (c.me ? '<span class="you">você</span>' : "") + "</span></td>";
  }

  function renderTrafego() {
    $("pb-trafego").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>Empresa</th><th>Visitas/mês</th><th>Variação</th><th>Rejeição</th><th>Páginas/visita</th><th>Tempo no site</th></tr></thead><tbody>' +
      CO.map(function (c) {
        return "<tr>" + nmCell(c) + '<td class="num"><b>' + (c.visits ? Number(c.visits).toLocaleString("pt-BR") : "—") + '</b></td><td class="num ' + (c.vg >= 0 ? "up" : "dn") + '">' + pct(c.vg) + '</td><td class="num">' + (c.bounce == null ? "—" : String(c.bounce.toFixed(1)).replace(".", ",") + "%") + '</td><td class="num">' + (c.ppv == null ? "—" : String(c.ppv.toFixed(2)).replace(".", ",")) + '</td><td class="num">' + esc(c.time || "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="sub-h">Busca pela marca</div><div class="mx"><table class="tb"><thead><tr><th>Empresa</th>' +
      (D.brand_labels || ["2023", "2024", "2025", "2026"]).map(function (l) { return "<th>" + esc(l) + "</th>"; }).join("") +
      "<th>Δ 1 ano</th><th>Tráfego de marca (Semrush)</th></tr></thead><tbody>" +
      CO.map(function (c) {
        var cells = (c.brand || []).map(function (v, i) {
          return '<td class="num">' + (i === (c.brand.length - 1) ? "<b>" + Number(v).toLocaleString("pt-BR") + "</b>" : Number(v).toLocaleString("pt-BR")) + "</td>";
        }).join("");
        return "<tr>" + nmCell(c) + cells + '<td class="num ' + (c.bg >= 0 ? "up" : "dn") + '">' + pct(c.bg) + '</td><td class="num">' + (c.sem == null ? "—" : fmt(c.sem)) + (c.semg == null ? "" : ' <span class="' + (c.semg >= 0 ? "up" : "dn") + '" style="font-size:12.5px">' + pct(c.semg) + "</span>") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function renderOrigem() {
    if (!(SRC.l || []).length) {
      $("pb-origem").innerHTML = '<div class="none">Origem do tráfego não coletada nesta rodada.</div>';
      return;
    }
    var rows = CO.map(function (c) {
      var v = SRC.v[c.k] || [];
      var paid = (SRC.paid || []).reduce(function (a, i) { return a + (v[i] || 0); }, 0);
      return '<div class="srow"><span class="nm">' + coDot(c) + esc(c.name) + '</span><div class="stack">' +
        v.map(function (x, i) { return x > 0 ? '<span style="width:' + x + "%;background:" + SRC.c[i] + '" title="' + esc(SRC.l[i]) + ": " + String(x).replace(".", ",") + '%"></span>' : ""; }).join("") +
        '</div><span class="pd num">pago ' + paid.toFixed(1).replace(".", ",") + "%</span></div>";
    }).join("");
    var legend = '<div class="slg">' + SRC.l.map(function (l, i) { return "<span><i style=\"background:" + SRC.c[i] + '"></i>' + esc(l) + "</span>"; }).join("") + "</div>";
    var tbl = '<div class="mx" style="margin-top:22px"><table class="tb"><thead><tr><th>Origem</th>' + CO.map(function (c) { return "<th>" + esc(c.name) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      SRC.l.map(function (l, i) {
        return "<tr><td>" + esc(l) + ((SRC.paid || []).indexOf(i) >= 0 ? ' <span style="color:var(--soft);font-size:12px">(pago)</span>' : "") + "</td>" +
          CO.map(function (c) { return '<td class="num">' + ((SRC.v[c.k] || [])[i] || 0).toFixed(1).replace(".", ",") + "%</td>"; }).join("") + "</tr>";
      }).join("") + "</tbody></table></div>";
    $("pb-origem").innerHTML = rows + legend + tbl;
  }

  function renderExec() {
    var steps = EX.steps || [];
    var log = EX.log || "";
    var nLog = log ? log.split("\n").filter(function (l) { return l.trim(); }).length : 0;
    var rowHtml = function (r) {
      if (Array.isArray(r)) {
        return "<tr><td>" + esc(r[0]) + '</td><td class="num">' + esc(r[1]) + '</td><td class="num">' + esc(r[3]) + "</td><td></td></tr>";
      }
      return '<tr class="' + (r.skipped ? "sk" : "") + '"><td>' + esc(r.label) + '</td><td class="num">' + esc(r.time) + '</td><td class="num">' + esc(r.cost) + "</td><td" + (r.skipped ? ' class="muted"' : "") + ">" + esc(r.status || "Feito") + "</td></tr>";
    };
    $("pb-exec").innerHTML = '<div class="kv3"><div><span>Tempo total</span><b>' + esc(EX.duration || "—") + "</b></div><div><span>Custo estimado</span><b>" + esc(EX.cost || "—") + "</b></div><div><span>Empresas</span><b>" + esc(String(EX.companies || CO.length)) + "</b></div><div><span>Etapas</span><b>" + steps.length + "</b></div></div>" +
      '<div class="ex-switch"><div class="ex-tabs" role="tablist" aria-label="Execução">' +
      '<button type="button" data-ex="resumo" aria-pressed="true">Resumo</button>' +
      '<button type="button" data-ex="log" aria-pressed="false">Log' + (nLog ? " · " + nLog : "") + "</button></div>" +
      '<div class="ex-pane" data-ex-pane="resumo"><div class="mx"><table class="tb"><thead><tr><th>Área</th><th>Tempo</th><th>Custo</th><th>Situação</th></tr></thead><tbody>' +
      (steps.length ? steps.map(rowHtml).join("") : '<tr><td colspan="4" class="none">Sem etapas.</td></tr>') +
      '</tbody><tfoot><tr class="runlog-total"><th>Total</th><th class="num">' + esc(EX.duration || "—") + '</th><th class="num">' + esc(EX.cost || "—") + "</th><th></th></tr></tfoot></table></div>" +
      (EX.rates ? '<p class="muted" style="margin-top:12px;font-size:12.5px;color:var(--soft)">' + esc(EX.rates) + "</p>" : "") +
      "</div>" +
      '<div class="ex-pane" data-ex-pane="log" hidden>' + (log ? "<pre>" + esc(log) + "</pre>" : '<div class="none">Log vazio para este run.</div>') + "</div></div>";
  }

  var tabCo = { yt: ME.k, ig: ME.k, rd: ME.k };
  var coSeg = function (tab) {
    return '<div class="seg" role="group" aria-label="Empresa">' + CO.map(function (c) {
      return '<button type="button" data-tco="' + tab + ":" + c.k + '" aria-pressed="' + (tabCo[tab] === c.k) + '">' + coDot(c) + esc(c.name) + "</button>";
    }).join("") + "</div>";
  };
  var warnBox = function (t) { return t ? '<div class="warn">' + esc(t) + "</div>" : ""; };

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
    $("pb-yt").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>Empresa</th><th>Views</th><th>Canal oficial</th><th>Outros canais</th><th>Vídeos</th><th>Últimos 30d</th><th>Até 6m</th><th>1 ano+</th></tr></thead><tbody>' +
      CO.map(function (k) {
        var z = YT[k.k] || { views: "0", off: "0", oth: "0", n: 0, d30: "0", m6: "0", y1: "0" };
        return '<tr class="' + (k.k === c.k ? "on" : "") + '" data-tco="yt:' + k.k + '">' + nmCell(k) + '<td class="num"><b>' + esc(z.views) + "</b>" + (z.w ? ' <span class="wf" title="' + esc(z.w) + '">!</span>' : "") + '</td><td class="num">' + esc(z.off) + '</td><td class="num">' + esc(z.oth) + '</td><td class="num">' + esc(String(z.n || 0)) + '</td><td class="num">' + esc(z.d30) + '</td><td class="num">' + esc(z.m6) + '</td><td class="num">' + esc(z.y1) + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="det-h"><span>Vídeos na 1ª página da busca por</span>' + coSeg("yt") + "</div>" +
      warnBox(y.w) +
      '<div class="two"><div><div class="sub-h">Canal oficial <span>' + esc(y.off) + " views</span></div>" + list(y.o, "Nenhum vídeo do canal oficial na 1ª página.") + "</div>" +
      "<div><div class=\"sub-h\">Outros canais <span>" + esc(y.oth) + " views</span></div>" + list(y.x, "Nenhum vídeo de outros canais.") + "</div></div>" +
      '<div class="note">' + (y.search ? '<a class="lnk" href="' + esc(y.search) + '" target="_blank" rel="noopener">Ver busca no YouTube ↗</a>' : "") + (y.ch ? '<a class="lnk" href="' + esc(y.ch) + '" target="_blank" rel="noopener">Canal oficial ↗</a>' : "") + "</div>";
  }

  function renderIG() {
    var c = CO.find(function (x) { return x.k === tabCo.ig; }) || ME;
    var g = IG[c.k] || { p: [], inf_posts: [], likes: "0", own: 0, inf: 0, infp: 0 };
    $("pb-ig").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>Empresa</th><th>Seguidores</th><th>Curtidas (1ª página)</th><th>Posts próprios</th><th>Influenciadores</th><th>Posts de influenciadores</th></tr></thead><tbody>' +
      CO.map(function (k) {
        var z = IG[k.k] || { likes: "0", own: 0, inf: 0, infp: 0 };
        return '<tr class="' + (k.k === c.k ? "on" : "") + '" data-tco="ig:' + k.k + '">' + nmCell(k) + '<td class="num" style="color:var(--soft)">' + esc(z.followers || "n/c") + '</td><td class="num"><b>' + esc(z.likes) + "</b>" + (z.w ? ' <span class="wf" title="' + esc(z.w) + '">!</span>' : "") + '</td><td class="num">' + esc(String(z.own || 0)) + '</td><td class="num">' + esc(String(z.inf || 0)) + '</td><td class="num">' + esc(String(z.infp || 0)) + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="det-h"><span>Posts de</span>' + coSeg("ig") + "</div>" + warnBox(g.w) +
      '<div class="two"><div><div class="sub-h">Posts próprios mais curtidos ' + (g.h ? "<span>@" + esc(g.h) + "</span>" : "") + "</div>" +
      ((g.p || []).length ? '<ol class="vl">' + g.p.map(function (it, i) {
        var lab = (it.kind === "reel" ? "Reel" : "Post") + " " + (i + 1) + (g.h ? " · @" + g.h : "");
        var href = it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title || lab) + "</a>" : esc(it.title || lab);
        return "<li>" + href + '<span class="vm">post próprio</span><span class="vv num">' + esc(it.likes_fmt || fmt(it.likes)) + " curtidas</span></li>";
      }).join("") + "</ol>" : '<div class="none">Nenhum post encontrado.</div>') +
      '</div><div><div class="sub-h">Posts de influenciadores</div>' +
      ((g.inf_posts || []).length ? '<ol class="vl">' + g.inf_posts.map(function (it) {
        var href = it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + "</a>" : esc(it.title);
        return "<li>" + href + '<span class="vm">influenciador</span><span class="vv num">' + esc(it.likes_fmt || fmt(it.likes)) + " curtidas</span></li>";
      }).join("") + "</ol>" : '<div class="none">Nenhum influenciador na 1ª página.</div>') +
      "</div></div>" +
      '<div class="note">' + (g.profile || g.h ? '<a class="lnk" href="' + esc(g.profile || ("https://www.instagram.com/" + g.h + "/")) + '" target="_blank" rel="noopener">Perfil' + (g.h ? " @" + esc(g.h) : "") + " ↗</a>" : "") + "<span>Seguidores do Instagram podem não ter sido coletados nesta rodada.</span></div>";
  }

  function renderRD() {
    var c = CO.find(function (x) { return x.k === tabCo.rd; }) || ME;
    var r = RD[c.k] || { posts: 0, com: 0, g: "—", l: [] };
    $("pb-rd").innerHTML = '<div class="mx"><table class="tb"><thead><tr><th>Empresa</th><th>Posts (1ª página)</th><th>Comentários</th><th>Resultados no Google</th></tr></thead><tbody>' +
      CO.map(function (k) {
        var z = RD[k.k] || { posts: 0, com: 0, g: "—" };
        return '<tr class="' + (k.k === c.k ? "on" : "") + '" data-tco="rd:' + k.k + '">' + nmCell(k) + '<td class="num">' + esc(String(z.posts || 0)) + (z.w ? ' <span class="wf" title="' + esc(z.w) + '">!</span>' : "") + '</td><td class="num">' + esc(String(z.com || 0)) + '</td><td class="num" style="color:var(--soft)">' + esc(z.g || "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="det-h"><span>Posts sobre</span>' + coSeg("rd") + "</div>" + warnBox(r.w) +
      ((r.l || []).length ? '<ol class="vl" style="max-width:820px">' + r.l.map(function (it) {
        var href = it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + "</a>" : esc(it.title);
        return "<li>" + href + '<span class="vm">' + esc(it.sub || "") + "</span></li>";
      }).join("") + "</ol>" : '<div class="none">Nenhum post na 1ª página.</div>') +
      '<div class="note">' + (r.search ? '<a class="lnk" href="' + esc(r.search) + '" target="_blank" rel="noopener">Ver busca no Google ↗</a>' : "") + '<span>"Resultados no Google" é a contagem genérica da busca e não mede presença real.</span></div>';
  }

  function renderAds() {
    var paid = CH.filter(function (ch) { return ch.g === "paid"; });
    $("pb-ads").innerHTML = paid.map(function (ch) {
      var rows = CO.map(function (c) {
        var s = (ch.s || {})[c.k] || [null, 0];
        return { c: c, v: s[0] == null ? 0 : (s[1] || 0) };
      }).sort(function (a, b) { return b.v - a.v; });
      var mx = Math.max.apply(null, rows.map(function (x) { return x.v; }).concat([0]));
      return '<div class="sub-h" style="margin-top:' + (ch === paid[0] ? 0 : 30) + 'px">' + ch.l + (ch.spend ? " <span>· gasto estimado ≈ US$ " + ch.spend + "/anúncio</span>" : "") + "</div>" +
        (mx === 0 ? '<div class="none" style="margin-bottom:8px">Nenhuma empresa do grupo anuncia aqui.</div>' : "") +
        '<ol class="rk ads">' + rows.map(function (x, i) {
          var w = (ch.w || {})[x.c.k];
          var lib = (LIB[x.c.k] || {})[ch.k] || "";
          return '<li class="' + (x.c.me ? "me" : "") + '"><span class="p num">' + (i + 1) + '</span><span class="nmr">' + coDot(x.c) + esc(x.c.name) + '</span><span class="t"><i style="width:' + (mx ? (x.v / mx * 100).toFixed(1) : 0) + "%;background:" + x.c.color + '"></i></span><span class="v num' + (x.v === 0 ? " z" : "") + '" title="' + (w ? esc(w) : "") + '">' + x.v + (w ? ' <span style="color:#8A6100">!</span>' : "") + (ch.spend && x.v ? '<span class="sp2">≈ US$ ' + (x.v * ch.spend).toLocaleString("pt-BR") + "</span>" : "") + "</span>" + (lib ? '<a class="lib" href="' + esc(lib) + '" target="_blank" rel="noopener">Biblioteca ↗</a>' : "<span></span>") + "</li>";
        }).join("") + "</ol>";
    }).join("") + '<div class="note"><span>Gasto é estimativa do pipeline, não valor declarado.</span></div>';
  }

  function pick(k) { sel = k; renderBoard(); renderPerfil(); }

  root.addEventListener("click", function (e) {
    var t = e.target.closest("[data-tag]");
    if (t && root.contains(t)) { var id = t.dataset.tag; open = open === id ? null : id; renderTags(); if (open) $("tags").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    var x = e.target.closest("[data-close]");
    if (x && root.contains(x)) { open = null; renderTags(); return; }
    var c = e.target.closest("[data-co]");
    if (c && root.contains(c)) { pick(c.dataset.co); if (c.tagName === "TR") $("pn-perfil").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    var tc = e.target.closest("[data-tco]");
    if (tc && root.contains(tc)) {
      var parts = tc.dataset.tco.split(":");
      tabCo[parts[0]] = parts[1];
      ({ yt: renderYT, ig: renderIG, rd: renderRD })[parts[0]]();
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

  var foot = $("v5-foot");
  if (foot) {
    var bits = ["Spy USA"];
    if (META.run_id) bits.push("run " + META.run_id);
    if (META.duration || META.cost) bits.push([META.duration, META.cost ? "custo est. " + META.cost : ""].filter(Boolean).join(" · "));
    bits.push("Fontes: SimilarWeb, DataForSEO, Semrush, bibliotecas de anúncios, perfis públicos");
    foot.innerHTML = bits.map(function (b) { return "<span>" + esc(b) + "</span>"; }).join("");
  }

  renderBoard(); renderTags(); renderPerfil(); renderCanais(); renderGanha();
  renderTrafego(); renderAds(); renderOrigem(); renderYT(); renderIG(); renderRD(); renderExec();
})();
