(function () {
  var root = document.getElementById("find-v2");
  var dataEl = document.getElementById("spy-find-v2-data");
  if (!root || !dataEl) return;
  var D;
  try { D = JSON.parse(dataEl.textContent || "{}"); } catch (e) { return; }

  var I = window.SpyI18n;
  var t = function (k, a) { return I ? I.t(k, a) : k; };
  var loc = function () { return I ? I.locale() : "en-US"; };

  var META = D.meta || {};
  var R = (D.rows || []).slice();
  var ME = {
    n: META.client || "WinnerTracker",
    d: String(META.domain || "").toLowerCase(),
    visits: META.visits
  };
  var MAX = Number(META.max) || 3;
  var RUN = String(META.run_id || "");
  var PAL = ["#0F6B5C", "#4A6FA5", "#C2702E", "#7B5BB0", "#2E9C8A", "#B5476B", "#5B6470", "#8A6100"];
  R.forEach(function (r, i) { if (!r.color) r.color = PAL[i % PAL.length]; });

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };
  var dec = function () { return loc() === "pt-BR" ? "," : "."; };
  var fmt = function (n) {
    if (n == null) return "—";
    n = Number(n);
    if (!isFinite(n)) return "—";
    var d = dec();
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 1).replace(/\.0$/, "").replace(".", d) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e5 ? 0 : 1).replace(/\.0$/, "").replace(".", d) + "k";
    return String(Math.round(n));
  };
  var gOf = function (a, b) { return b ? (a - b) / b * 100 : null; };
  function bestG(r) {
    if (!r.b) return null;
    var a = r.b[0], b1 = r.b[1], b2 = r.b[2];
    var opts = [[gOf(a, b1), 1], [gOf(a, b2), 2]].filter(function (x) { return x[0] != null; });
    if (!opts.length) return a ? { g: Infinity, y: null } : null;
    opts.sort(function (x, z) { return z[0] - x[0]; });
    return { g: opts[0][0], y: opts[0][1] };
  }
  var yoy = function (r) { var b = bestG(r); return b ? b.g : null; };
  var pctTxt = function (p) {
    return (p > 0 ? "+" : "−") + Math.abs(Math.round(p)).toLocaleString(loc()) + "%";
  };
  function srcName(k) { return t("find.src." + k); }
  function lvPack() {
    return {
      u: [t("find.lvl.u"), "gl-u"],
      3: [t("find.lvl.3"), "gl-3"],
      2: [t("find.lvl.2"), "gl-2"],
      1: [t("find.lvl.1"), "gl-1"]
    };
  }
  function shortPack() {
    return { u: t("find.short.u"), 3: t("find.short.3"), 2: t("find.short.2"), 1: t("find.short.1") };
  }

  var CHECK = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
  var sel = [];
  var show = "all", sort = "traffic", lvl = null;
  var busy = false;
  try {
    var stored = JSON.parse(localStorage.getItem("spy-cmp-sel:" + RUN) || "null");
    if (Array.isArray(stored)) sel = stored.filter(function (d) { return R.some(function (r) { return r.d === d; }); }).slice(0, MAX);
  } catch (e) {}

  function brandCell(r) {
    if (!r.b) return '<span class="vb"><span class="na">' + t("find.brand.none") + "</span></span>";
    var bg = bestG(r);
    var pill = !bg ? "" : bg.g === Infinity
      ? '<span class="pill new">' + t("find.brand.new") + "</span>"
      : '<span class="pill ' + (bg.g >= 0 ? "up" : "dn") + '">' + (bg.g >= 0 ? "▲" : "▼") + " " + pctTxt(bg.g).replace(/^[+−]/, "") + "</span>";
    var per = !bg || bg.y == null ? t("find.brand.unit") : (bg.y === 1 ? t("find.brand.vs1") : t("find.brand.vs2"));
    var g1 = gOf(r.b[0], r.b[1]), g2 = gOf(r.b[0], r.b[2]);
    var gl = function (g) {
      return g == null ? "<em>—</em>" : '<em class="' + (g >= 0 ? "u" : "d") + '">' + (g >= 0 ? "▲" : "▼") + " " + pctTxt(g).replace(/^[+−]/, "") + "</em>";
    };
    return '<span class="br hv" tabindex="0"><b class="num">' + fmt(r.b[0]) + "</b>" + pill + "<small>" + per + "</small>" +
      '<span class="tt" role="tooltip"><b>' + t("find.brand.tip") + "</b>" +
      '<span class="tr"><span>2026</span><span class="num">' + fmt(r.b[0]) + "</span><span></span></span>" +
      '<span class="tr"><span>2025</span><span class="num">' + fmt(r.b[1]) + "</span>" + gl(g1) + "</span>" +
      '<span class="tr"><span>2024</span><span class="num">' + fmt(r.b[2]) + "</span>" + gl(g2) + "</span>" +
      "<small>" + t("find.brand.tip_s") + "</small></span></span>";
  }

  var mxv = Math.max.apply(null, R.map(function (r) { return r.v || 0; }).concat([1]));
  function visitCell(r) {
    if (r.added) return '<span class="vb"><span class="na">' + t("find.vis.added") + "</span></span>";
    if (!r.v) return '<span class="vb"><span class="na">' + t("find.vis.na") + "</span></span>";
    var w = Math.max(3, Math.log10(r.v) / Math.log10(mxv) * 100 - (r.v < mxv ? 30 * (1 - r.v / mxv) : 0));
    return '<span class="vb"><b class="num">' + fmt(r.v) + '</b><span class="tk"><i style="width:' + w.toFixed(0) + "%;background:" + r.color + '"></i></span></span>';
  }
  var av = function (r) {
    return '<span class="av" style="background:' + r.color + '">' + esc((r.n || "?").charAt(0)) + "</span>";
  };

  function paintChrome() {
    var bits = [];
    if (META.nicho) bits.push(META.nicho);
    bits.push(t(String(META.market_code || "US").toUpperCase() === "BR" ? "market.br" : "market.us"));
    if (ME.d) bits.push(ME.d);
    var eye = $("find-eyebrow");
    if (eye) eye.textContent = bits.join(" · ");
    var title = $("find-title");
    if (title) title.innerHTML = t("find.h", { name: esc(ME.n) }) + " <span>" + t("find.pick", { n: MAX }) + "</span>";
    var steps = $("find-steps");
    if (steps) {
      steps.innerHTML =
        '<span class="done"><i>✓</i>' + t("find.step.brief") + "</span>" +
        '<span class="done"><i>✓</i>' + t("find.step.found", { n: R.length }) + "</span>" +
        '<span class="now"><i>' + MAX + "</i>" + t("find.step.choose", { n: MAX }) + "</span>" +
        "<span><i>4</i>" + t("find.step.report") + "</span>";
    }
    if (I) I.apply(root);
  }

  function renderKpis() {
    var c = function (l) { return R.filter(function (r) { return r.lvl === l; }).length; };
    $("find-kpis").innerHTML =
      "<div><span>" + t("find.kpi.found") + '</span><b class="num">' + R.length + "</b></div>" +
      "<div><span>" + t("find.kpi.high") + '</span><b class="num">' + c(3) + "</b></div>" +
      "<div><span>" + t("find.kpi.traffic") + '</span><b class="num">' + R.filter(function (r) { return r.v; }).length + "<small>" + t("find.kpi.of", { n: R.length }) + "</small></b></div>" +
      "<div><span>" + t("find.kpi.off") + '</span><b class="num">' + R.filter(function (r) { return r.off; }).length + "</b></div>" +
      "<div><span>" + t("find.kpi.you", { name: esc(ME.n) }) + '</span><b class="num">' + fmt(ME.visits) + "<small>" + t("find.kpi.visits") + "</small></b></div>";
  }

  function rowHtml(r, flat) {
    var LV = lvPack();
    var SHORT = shortPack();
    var on = sel.indexOf(r.d) >= 0, full = !on && sel.length >= MAX;
    var tip = full ? t("find.pick_full", { n: MAX }) : (on ? t("find.pick_off") : t("find.pick_on"));
    var badge = flat
      ? '<span class="lvb ' + LV[r.lvl][1] + '" title="' + esc(LV[r.lvl][0]) + '">' +
        (r.lvl === "u" ? "" : '<span class="bb b' + r.lvl + '"><i></i></span>') + SHORT[r.lvl] + "</span>"
      : "";
    var srcs = (r.src || []).map(srcName).join(" + ");
    var title = r.t || t("find.title.none");
    return '<tr class="c' + (on ? " on" : "") + (full ? " dis" : "") + '" data-pick="' + esc(r.d) + '" tabindex="0" aria-selected="' + on + '" title="' + esc(tip) + '">' +
      '<td style="width:36px"><span class="cb">' + CHECK + "</span></td>" +
      "<td><span class=\"co\">" + av(r) + '<span class="nmw"><b>' + esc(r.n) + badge + '</b><span class="dm">' + esc(r.d) + "</span></span></span></td>" +
      "<td>" + visitCell(r) + "</td>" +
      '<td class="hs">' + brandCell(r) + "</td>" +
      '<td class="hm r num">' + (r.since == null ? "—" : esc(r.since)) + "</td>" +
      '<td class="hm nc"><span class="niche">' + esc(r.niche || "—") + (r.off ? '<br><span class="off">' + esc(r.off) + "</span>" : "") + "</span></td>" +
      '<td class="hm ttc"><span class="tip" tabindex="0" aria-label="' + t("find.title.lab") + ": " + esc(title) + '"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4M8 4.9v.1" stroke-linecap="round"/></svg><span class="tsn">' + esc(title) + '</span><span class="tt" role="tooltip"><b>' + t("find.title.lab") + "</b>" + esc(title) + "<small>" + t("find.title.via", { src: srcs || "—" }) + "</small></span></span></td></tr>";
  }

  function renderList() {
    var rows = R.filter(function (r) {
      return show === "all" || (show === "traffic" && r.v) || (show === "grow" && yoy(r) > 0);
    });
    var gr = function (r) { var g = yoy(r); return g === Infinity ? 1e9 : (g == null ? -1e9 : g); };
    var key = { traffic: function (r) { return -(r.v || 0); }, brand: function (r) { return -(r.b ? r.b[0] : -1); }, grow: function (r) { return -gr(r); }, "new": function (r) { return -(r.since || 0); } }[sort];
    var h = "<thead><tr><th></th><th>" + t("find.th.company") + "</th><th>" + t("find.th.visits") + '</th><th class="hs">' + t("find.th.brand") + '</th><th class="hm r">' + t("find.th.since") + '</th><th class="hm">' + t("find.th.niche") + '</th><th class="hm">' + t("find.th.title") + "</th></tr></thead><tbody>";
    var sorted = function (arr) {
      return arr.slice().sort(function (a, b) { return key(a) - key(b) || String(a.n).localeCompare(String(b.n)); });
    };
    if (lvl === "all") h += sorted(rows).map(function (r) { return rowHtml(r, true); }).join("");
    else (lvl ? [lvl] : ["u", 3, 2, 1]).forEach(function (l) {
      var g = sorted(rows.filter(function (r) { return r.lvl === l; }));
      if (!g.length) return;
      var LV = lvPack();
      if (!lvl) {
        h += '<tr class="gr"><td colspan="7"><span class="gl ' + LV[l][1] + '">' +
          (l === "u" ? '<span class="plus">+</span>' : '<span class="bb b' + l + '"><i></i></span>') +
          LV[l][0] + " <small>" + g.length + "</small></span></td></tr>";
      }
      h += g.map(function (r) { return rowHtml(r, false); }).join("");
    });
    if (!rows.length) h += '<tr><td colspan="7" style="text-align:center;color:var(--soft);padding:32px">' + t("find.empty") + "</td></tr>";
    $("find-list").innerHTML = h + "</tbody>";
  }

  function renderLvt() {
    var c = function (l) { return R.filter(function (r) { return r.lvl === l; }).length; };
    var LV = lvPack();
    var tabs = [["all", t("find.lvl.all"), R.length, "lvt-all", t("find.lvl.all_tip")], [3, LV[3][0], c(3), "gl-3"], [2, LV[2][0], c(2), "gl-2"], [1, LV[1][0], c(1), "gl-1"]];
    if (c("u")) tabs.push(["u", LV.u[0], c("u"), "gl-u"]);
    $("find-lvt").innerHTML = tabs.map(function (row) {
      var k = row[0], l = row[1], n = row[2], cls = row[3], tip = row[4];
      return '<button type="button" class="gl ' + cls + '" data-lvl="' + k + '" aria-pressed="' + (String(lvl) === String(k)) + '"' + (tip ? ' title="' + esc(tip) + '"' : "") + ">" +
        (k === "all" ? "" : k === "u" ? '<span class="plus">+</span>' : '<span class="bb b' + k + '"><i></i></span>') +
        l + " <small>" + n + "</small></button>";
    }).join("") + (lvl != null ? '<button type="button" class="lvx" data-lvl="">' + t("find.groups") + "</button>" : "");
  }

  function renderCtl() {
    $("find-fShow").innerHTML = [["all", t("find.show.all")], ["traffic", t("find.show.traffic")], ["grow", t("find.show.grow")]].map(function (pair) {
      return '<button type="button" data-show="' + pair[0] + '" aria-pressed="' + (show === pair[0]) + '">' + pair[1] + "</button>";
    }).join("");
    $("find-fSort").innerHTML = [["traffic", t("find.sort.traffic")], ["brand", t("find.sort.brand")], ["grow", t("find.sort.grow")], ["new", t("find.sort.new")]].map(function (pair) {
      return '<button type="button" data-sort="' + pair[0] + '" aria-pressed="' + (sort === pair[0]) + '">' + pair[1] + "</button>";
    }).join("");
  }

  function renderBar() {
    var picked = sel.map(function (d) { return R.find(function (r) { return r.d === d; }); }).filter(Boolean);
    $("find-cnt").innerHTML = t("find.cnt", { n: sel.length, max: MAX });
    $("find-chips").innerHTML = picked.map(function (r) {
      return '<span class="chip">' + esc(r.n) + '<button type="button" data-rm="' + esc(r.d) + '" aria-label="' + t("find.rm", { name: r.n }) + '">×</button></span>';
    }).join("") + Array(MAX - sel.length).fill('<span class="slot">' + t("find.slot") + "</span>").join("");
    var go = $("find-go");
    go.disabled = busy || !sel.length;
    go.textContent = busy ? t("find.go_wait") : (sel.length ? t("find.go", { name: ME.n, n: sel.length }) : t("find.go_empty"));
    try { localStorage.setItem("spy-cmp-sel:" + RUN, JSON.stringify(sel)); } catch (e) {}
  }

  function renderAll() {
    paintChrome();
    renderKpis();
    renderLvt();
    renderCtl();
    renderList();
    renderBar();
  }

  function toggle(d) {
    if (busy) return;
    if (sel.indexOf(d) >= 0) sel = sel.filter(function (x) { return x !== d; });
    else if (sel.length < MAX) sel = sel.concat([d]);
    renderList();
    renderBar();
  }

  function addSite(raw) {
    var d = String(raw || "").trim().toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").split(/[/?#\s]/)[0];
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(d)) return { ok: false, msg: t("find.add.invalid") };
    if (d === ME.d) return { ok: false, msg: t("find.add.self", { name: ME.n }) };
    var ex = R.find(function (r) { return r.d === d; });
    if (ex) {
      if (sel.indexOf(d) < 0 && sel.length < MAX) sel = sel.concat([d]);
      return { ok: true, local: true, msg: t("find.add.already", { name: ex.n, marked: sel.indexOf(d) >= 0 ? t("find.add.marked") : "" }) };
    }
    return { ok: true, domain: d };
  }

  function startAnalysis() {
    if (!sel.length || busy) return;
    busy = true;
    renderBar();
    var urls = [ME.d].concat(sel.filter(function (d) { return d !== ME.d; })).join("\n");
    fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: urls,
        compare_all: true,
        site_only: true,
        market: String(META.market_code || "US").toLowerCase() === "br" ? "br" : "us",
        include_google_ads: true,
        include_linkedin: false,
        include_youtube_influencers: true,
        include_instagram_influencers: true,
        include_tiktok_influencers: true,
        include_reddit: true,
        include_twitter: true,
        include_linkedin_profile: true
      })
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        return d;
      });
    }).then(function (data) {
      var job = (data.jobs && data.jobs[0]) || data;
      var url = job.html_url || ("/runs/" + (job.job_id || job.id) + "/report.html");
      location.href = url;
    }).catch(function (err) {
      busy = false;
      renderBar();
      $("find-addm").textContent = err.message || String(err);
    });
  }

  if (!root.dataset.bound) {
    root.dataset.bound = "1";
    root.addEventListener("click", function (e) {
      var rm = e.target.closest("[data-rm]"); if (rm) { toggle(rm.dataset.rm); return; }
      var lv = e.target.closest("[data-lvl]");
      if (lv) {
        var k = lv.dataset.lvl;
        var v = k === "" ? null : (k === "all" || k === "u") ? k : +k;
        lvl = (lvl === v) ? null : v;
        renderLvt(); renderList();
        return;
      }
      var p = e.target.closest("[data-pick]"); if (p) { toggle(p.dataset.pick); return; }
      var s = e.target.closest("[data-show]"); if (s) { show = s.dataset.show; renderCtl(); renderList(); return; }
      var o = e.target.closest("[data-sort]"); if (o) { sort = o.dataset.sort; renderCtl(); renderList(); return; }
      if (e.target.closest("#find-go")) startAnalysis();
    });
    root.addEventListener("keydown", function (e) {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("tr[data-pick]")) {
        e.preventDefault();
        toggle(e.target.dataset.pick);
      }
    });
    $("find-addf").addEventListener("submit", function (e) {
      e.preventDefault();
      if (busy) return;
      var parsed = addSite($("find-addi").value);
      if (!parsed.ok) { $("find-addm").textContent = parsed.msg; return; }
      if (parsed.local) {
        $("find-addm").textContent = parsed.msg;
        $("find-addi").value = "";
        renderLvt(); renderList(); renderBar();
        return;
      }
      if (!RUN) { $("find-addm").textContent = parsed.msg || t("find.add.invalid"); return; }
      $("find-addm").textContent = t("find.add.adding");
      fetch("/api/runs/" + encodeURIComponent(RUN) + "/competitors/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: parsed.domain, similaridade: "" })
      }).then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
          return d;
        });
      }).then(function () {
        if (sel.indexOf(parsed.domain) < 0 && sel.length < MAX) {
          sel = sel.concat([parsed.domain]);
          try { localStorage.setItem("spy-cmp-sel:" + RUN, JSON.stringify(sel)); } catch (err) {}
        }
        location.reload();
      }).catch(function (err) {
        $("find-addm").textContent = err.message || String(err);
      });
    });
    document.addEventListener("spy-lang", renderAll);
  }

  renderAll();
})();
