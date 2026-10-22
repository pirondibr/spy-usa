(function () {
  var KEY = "spy-report-ui";
  function currentUi() {
    try {
      var v = localStorage.getItem(KEY);
      return v === "v1" ? "v1" : "v2";
    } catch (e) {
      return "v2";
    }
  }
  function applyUi(v) {
    v = v === "v1" ? "v1" : "v2";
    document.documentElement.setAttribute("data-ui", v);
    try {
      localStorage.setItem(KEY, v);
    } catch (e) {}
    document.querySelectorAll(".ui-ver").forEach(function (b) {
      var on = b.getAttribute("data-ui") === v;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  applyUi(currentUi());
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest(".ui-ver");
    if (!b) return;
    applyUi(b.getAttribute("data-ui"));
  });
})();

(function () {
  var root = document.getElementById("analysis-v2");
  if (!root || !("IntersectionObserver" in window)) return;
  var links = [].slice.call(root.querySelectorAll(".anav a"));
  if (!links.length) return;
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (en) {
      if (!en.isIntersecting) return;
      links.forEach(function (a) {
        a.classList.toggle("active", a.getAttribute("href") === "#" + en.target.id);
      });
    });
  }, { rootMargin: "-35% 0px -60% 0px" });
  ["resumo", "busca", "paga", "social", "execucao"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) io.observe(el);
  });
})();

(function () {
  var root = document.getElementById("analysis-v2");
  if (!root) return;
  root.addEventListener("click", function (ev) {
    var b = ev.target.closest(".tb");
    if (!b || !root.contains(b)) return;
    var id = b.getAttribute("data-tabs");
    var i = b.getAttribute("data-i");
    root.querySelectorAll('.tb[data-tabs="' + id + '"]').forEach(function (x) {
      x.setAttribute("aria-selected", x.getAttribute("data-i") === i ? "true" : "false");
    });
    root.querySelectorAll('.tp[data-tabs="' + id + '"]').forEach(function (x) {
      x.hidden = x.getAttribute("data-i") !== i;
    });
  });
})();

(function () {
  var dataEl = document.getElementById("comp-v2-data");
  var root = document.getElementById("comp-v2");
  var card = document.getElementById("sec-competitors");
  if (!dataEl || !root || !card) return;
  var D;
  try {
    D = JSON.parse(dataEl.textContent || "[]");
  } catch (e) {
    return;
  }
  var runId = card.getAttribute("data-run-id") || "";
  var editable = root.getAttribute("data-editable") === "1";

  var SIM = {
    Cliente: ["You", "sim-Cliente", "Client"],
    Alto: ["High", "sim-Alto", "High similarity"],
    Medio: ["Med", "sim-Medio", "Medium similarity"],
    Baixo: ["Low", "sim-Baixo", "Low similarity"],
    "—": ["—", "sim-none", "Similarity not rated"],
  };
  var esc = function (s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var fmt = function (n) {
    if (n == null || n === "") return "—";
    n = Number(n);
    if (!isFinite(n)) return "—";
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2).replace(/\.?0+$/, "") + "M";
    if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(Math.abs(n) >= 1e5 ? 0 : 1).replace(/\.0$/, "") + "k";
    return String(Math.round(n));
  };
  var pct = function (a, b) {
    a = Number(a);
    b = Number(b);
    if (!isFinite(a) || !isFinite(b) || !b) return null;
    return (a / b - 1) * 100;
  };
  var pctTxt = function (p) {
    if (p == null) return "—";
    if (Math.abs(p) < 0.05) return "0%";
    var s = Math.abs(p) >= 100 ? String(Math.round(p)) : p.toFixed(1);
    return (p > 0 ? "+" : "") + s + "%";
  };
  var pctCls = function (p) {
    return p == null ? "na" : Math.abs(p) < 0.05 ? "flat" : p > 0 ? "up" : "down";
  };
  var seriesOf = function (r) {
    if (r.view === "semrush") return r.semrush;
    if (r.view === "pesquisar") return r.pesquisar;
    return r.dfs;
  };
  var enrich = function (r, i) {
    var b = seriesOf(r);
    r.idx = i + 1;
    r.b = b && b.some(function (v) { return v != null; }) ? b : null;
    r.brand26 = r.b ? r.b[0] : null;
    r.g2 = r.b ? pct(r.b[0], r.b[2]) : null;
    r.g1 = r.b ? pct(r.b[0], r.b[1]) : null;
    return r;
  };
  var ROWS = D.map(enrich);
  var SIM_RANK = { Cliente: 4, Alto: 3, Medio: 2, Baixo: 1, "—": 0 };

  var state = {
    sim: "all",
    q: "",
    key: "default",
    dir: "desc",
    open: null,
    brand: null,
    growth: null,
    sw: null,
    picked: new Set(),
  };
  var parseNum = function (v) {
    v = String(v || "").trim().toLowerCase().replace(/[,%+\s]/g, "");
    if (!v) return null;
    var m = v.match(/^(-?[\d.]+)([km]?)$/);
    if (!m) return null;
    return parseFloat(m[1]) * (m[2] === "k" ? 1e3 : m[2] === "m" ? 1e6 : 1);
  };

  function brandHtml(r) {
    var b = r.b;
    var mx = b ? Math.max.apply(null, b.concat([1])) : 1;
    var h = function (v) {
      return b ? Math.max(3, Math.round((Number(v) || 0) / mx * 24)) : 3;
    };
    var bc = r.g1 == null || Math.abs(r.g1) < 0.05 ? "#8A939E" : r.g1 > 0 ? "#16A34A" : "#DC2626";
    var bars = b
      ? '<span style="height:' + h(b[0]) + "px;background:" + bc + '"></span>' +
        '<span style="height:' + h(b[1]) + "px;background:" + bc + ';opacity:.55"></span>' +
        '<span style="height:' + h(b[2]) + "px;background:" + bc + ';opacity:.3"></span>'
      : '<span style="height:3px;background:#E3E6EA"></span><span style="height:3px;background:#E3E6EA"></span><span style="height:3px;background:#E3E6EA"></span>';
    var tag = "";
    if (r.view === "semrush") tag = '<span class="brand-tag">Semrush</span>';
    if (r.view === "pesquisar") tag = '<span class="brand-tag">' + esc(r.kw || "pesquisar") + "</span>";
    var nums = b
      ? b
          .map(function (v, j) {
            return '<span class="bv' + (j ? "" : " now") + '">' + fmt(v) + "</span>";
          })
          .join(' <span class="arrow">→</span> ')
      : "no data";
    var title = b
      ? "Aug 2026: " + Number(b[0]).toLocaleString("en-US") +
        " · Aug 2025: " + Number(b[1]).toLocaleString("en-US") +
        " · Aug 2024: " + Number(b[2]).toLocaleString("en-US")
      : "";
    var inner =
      '<span class="spark" aria-hidden="true">' +
      bars +
      '</span><span class="btxt-wrap"><span class="btxt" title="' +
      esc(title) +
      '">' +
      nums +
      "</span>" +
      tag +
      "</span>";
    if (!editable) {
      return '<span class="brandcell">' + inner + "</span>";
    }
    return (
      '<span class="brandcell"><div class="brand-stack" data-domain="' +
      esc(r.domain) +
      '" data-view="' +
      esc(r.view || "dfs") +
      '" data-dfs=\'' +
      JSON.stringify(r.dfs || []) +
      "' data-semrush='" +
      JSON.stringify(r.semrush || []) +
      "' data-pesquisar='" +
      JSON.stringify(r.pesquisar || []) +
      "' data-kw=\"" +
      esc(r.kw || "") +
      '" data-brand-kw="' +
      esc(r.brandKw || "") +
      '"><button type="button" class="brand-hit" title="Choose Brand series">' +
      inner +
      "</button></div></span>"
    );
  }

  function swHtml(r) {
    if (r.sw == null) return '<span class="swn">—</span>';
    return (
      '<span class="swn" title="' +
      esc(Number(r.sw).toLocaleString("en-US")) +
      ' visits">' +
      fmt(r.sw) +
      "</span>"
    );
  }

  function simSelect(r) {
    if (!editable || r.isYou) return "";
    var cur = r.sim;
    var opts = [
      ["Alto", "High"],
      ["Medio", "Medium"],
      ["Baixo", "Low"],
    ];
    var html = '<select class="sim-edit" data-domain="' + esc(r.domain) + '" title="Change similarity">';
    if (cur !== "Alto" && cur !== "Medio" && cur !== "Baixo") {
      html += '<option value="' + esc(cur) + '" selected>' + esc(cur) + "</option>";
    }
    opts.forEach(function (o) {
      html += '<option value="' + o[0] + '"' + (o[0] === cur ? " selected" : "") + ">" + o[1] + "</option>";
    });
    html += "</select>";
    return html;
  }

  function rowHTML(r) {
    var open = state.open === r.domain;
    var pack = SIM[r.sim] || SIM["—"];
    var simLabel = pack[0],
      simCls = pack[1],
      simFull = pack[2];
    var pick = r.isYou
      ? ""
      : '<label class="pick" title="Select ' +
        esc(r.name) +
        '"><input type="checkbox" data-pick="' +
        esc(r.domain) +
        '" ' +
        (state.picked.has(r.domain) ? "checked" : "") +
        ' aria-label="Select ' +
        esc(r.name) +
        '"></label>';
    return (
      '<div class="row' +
      (r.isYou ? " you" : "") +
      (open ? " open" : "") +
      '" data-domain="' +
      esc(r.domain) +
      '">' +
      '<div class="grid">' +
      '<span class="idx">' +
      r.idx +
      "</span>" +
      '<span style="display:flex;align-items:flex-start;gap:6px;min-width:0">' +
      pick +
      '<button type="button" class="rowbtn" data-toggle="' +
      esc(r.domain) +
      '" aria-expanded="' +
      open +
      '">' +
      '<span class="chev" aria-hidden="true">›</span>' +
      '<span style="min-width:0"><span class="cname" title="' +
      esc(r.name) +
      '">' +
      esc(r.name) +
      "</span>" +
      (r.isYou ? '<span class="tag you">You</span>' : "") +
      (r.fp ? '<span class="tag check" title="Possible false positive">Check</span>' : "") +
      '<span class="cdom" title="' +
      esc(r.domain) +
      '">' +
      esc(r.domain) +
      "</span></span></button></span>" +
      '<span><span class="pill ' +
      simCls +
      '" title="' +
      esc(simFull) +
      '">' +
      esc(simLabel) +
      "</span></span>" +
      brandHtml(r) +
      '<span class="gseq" title="Total Aug 2026 vs 2024 › 1 year Aug 2026 vs 2025"><span class="g ' +
      pctCls(r.g2) +
      '">' +
      pctTxt(r.g2) +
      '</span><span class="gsep">›</span><span class="g ' +
      pctCls(r.g1) +
      '">' +
      pctTxt(r.g1) +
      "</span></span>" +
      swHtml(r) +
      '<span class="started">' +
      esc(r.startedTxt || "—") +
      "</span>" +
      '<span class="niche ttl" title="' +
      esc(r.title || "") +
      '">' +
      esc(r.title || "—") +
      "</span>" +
      '<span class="niche" title="' +
      esc(r.niche || "") +
      '">' +
      esc(r.niche || "—") +
      "</span></div>" +
      (open
        ? '<div class="detail">' +
          '<div class="wide"><span class="dl">Why it was matched</span>' +
          esc(r.motivo || "—") +
          "</div>" +
          '<div><span class="dl">Found via · Profile</span>' +
          esc(r.src || "—") +
          " · " +
          esc(r.profile || "—") +
          "</div>" +
          '<div><span class="dl">SimilarWeb</span>' +
          (r.sw == null ? "—" : fmt(r.sw)) +
          "</div>" +
          '<div><span class="dl">Open</span><a href="' +
          esc(r.url || "https://" + r.domain + "/") +
          '" target="_blank" rel="noopener" style="font-weight:600">' +
          esc(r.domain) +
          " ↗</a></div>" +
          (editable && !r.isYou
            ? '<div><span class="dl">Similarity</span>' + simSelect(r) + "</div>"
            : "") +
          "</div>"
        : "") +
      "</div>"
    );
  }

  function render() {
    var counts = {};
    ROWS.forEach(function (r) {
      counts[r.sim] = (counts[r.sim] || 0) + 1;
    });
    var tabs = document.getElementById("v2-tabs");
    if (tabs) {
      var others = ROWS.filter(function (r) {
        return !r.isYou;
      }).length;
      tabs.innerHTML = [
        ["all", "All", others],
        ["Alto", "High", counts.Alto || 0],
        ["Medio", "Medium", counts.Medio || 0],
        ["Baixo", "Low", counts.Baixo || 0],
        ["—", "Unrated", counts["—"] || 0],
      ]
        .map(function (t) {
          return (
            '<button type="button" class="tab" data-sim="' +
            t[0] +
            '" aria-pressed="' +
            (state.sim === t[0]) +
            '">' +
            t[1] +
            ' <span class="num">' +
            t[2] +
            "</span></button>"
          );
        })
        .join("");
    }
    var q = state.q.trim().toLowerCase();
    var match = function (r) {
      if (!q) return true;
      return (r.name + " " + r.domain + " " + r.niche + " " + (r.title || "")).toLowerCase().indexOf(q) >= 0;
    };
    var client = ROWS.filter(function (r) {
      return r.isYou && match(r);
    });
    var rest = ROWS.filter(function (r) {
      return (
        !r.isYou &&
        (state.sim === "all" || r.sim === state.sim) &&
        match(r) &&
        (state.brand == null || (r.brand26 != null && r.brand26 >= state.brand)) &&
        (state.growth == null || (r.g2 != null && r.g2 >= state.growth)) &&
        (state.sw == null || (r.sw != null && r.sw >= state.sw))
      );
    });
    var fsim = document.getElementById("v2-fsim");
    if (fsim) fsim.value = state.sim;
    var del = document.getElementById("v2-del");
    if (del) {
      del.disabled = state.picked.size === 0;
      del.textContent = state.picked.size ? "Delete selected (" + state.picked.size + ")" : "Delete selected";
    }
    var k = state.key;
    var dir = state.dir === "asc" ? 1 : -1;
    rest.sort(function (a, b) {
      if (k === "default") {
        var sa = SIM_RANK[a.sim] || 0;
        var sb = SIM_RANK[b.sim] || 0;
        if (sa !== sb) return sb - sa;
        var ba = a.brand26;
        var bb = b.brand26;
        if (ba == null && bb == null) return a.idx - b.idx;
        if (ba == null) return 1;
        if (bb == null) return -1;
        if (bb !== ba) return bb - ba;
        return a.idx - b.idx;
      }
      var va = a[k],
        vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return typeof va === "string" ? va.localeCompare(vb) * dir : (va - vb) * dir;
    });
    var defBtn = document.getElementById("v2-default-view");
    if (defBtn) {
      defBtn.setAttribute("aria-pressed", k === "default" ? "true" : "false");
    }
    var out = client.concat(rest);
    var shown = document.getElementById("v2-shown");
    if (shown) shown.textContent = rest.length + " shown";
    var rowsEl = document.getElementById("v2-rows");
    if (rowsEl) {
      rowsEl.innerHTML = out.length ? out.map(rowHTML).join("") : '<div class="empty">No competitors match this filter.</div>';
    }
    root.querySelectorAll("[data-sort]").forEach(function (b) {
      var on = b.getAttribute("data-sort") === state.key;
      var i = b.querySelector("i");
      if (i) i.textContent = on ? (state.dir === "asc" ? "↑" : "↓") : "";
      b.setAttribute("aria-sort", on ? (state.dir === "asc" ? "ascending" : "descending") : "none");
    });
  }

  window.__spyV2 = {
    setView: function (domain, view, vals, kw) {
      var r = ROWS.filter(function (x) {
        return x.domain === domain;
      })[0];
      if (!r) return;
      r.view = view || r.view;
      if (vals && vals.length) {
        if (view === "semrush") r.semrush = vals;
        else if (view === "pesquisar") r.pesquisar = vals;
        else if (view === "dfs") r.dfs = vals;
      }
      if (kw) r.kw = kw;
      enrich(r, r.idx - 1);
      render();
    },
  };

  root.addEventListener("click", function (e) {
    if (e.target.closest("[data-default-view]")) {
      state.key = "default";
      state.dir = "desc";
      render();
      return;
    }
    var s = e.target.closest("[data-sort]");
    if (s) {
      var k = s.getAttribute("data-sort");
      state.dir = state.key === k ? (state.dir === "asc" ? "desc" : "asc") : k === "idx" || k === "name" ? "asc" : "desc";
      state.key = k;
      render();
      return;
    }
    var t = e.target.closest("[data-sim]");
    if (t) {
      state.sim = t.getAttribute("data-sim");
      render();
      return;
    }
    if (e.target.closest(".brand-hit") || e.target.closest(".sim-edit") || e.target.closest("a") || e.target.closest(".pick")) {
      return;
    }
    var r = e.target.closest("[data-toggle]");
    if (r) {
      var d = r.getAttribute("data-toggle");
      state.open = state.open === d ? null : d;
      render();
    }
  });

  var qEl = document.getElementById("v2-q");
  if (qEl) {
    qEl.addEventListener("input", function (e) {
      state.q = e.target.value;
      render();
    });
  }
  var fsim = document.getElementById("v2-fsim");
  if (fsim) {
    fsim.addEventListener("change", function (e) {
      state.sim = e.target.value;
      render();
    });
  }
  [
    ["v2-fbrand", "brand"],
    ["v2-fgrowth", "growth"],
    ["v2-fsw", "sw"],
  ].forEach(function (pair) {
    var el = document.getElementById(pair[0]);
    if (!el) return;
    el.addEventListener("input", function (e) {
      state[pair[1]] = parseNum(e.target.value);
      render();
    });
  });
  var fclear = document.getElementById("v2-fclear");
  if (fclear) {
    fclear.addEventListener("click", function () {
      Object.assign(state, { sim: "all", q: "", brand: null, growth: null, sw: null });
      ["v2-q", "v2-fbrand", "v2-fgrowth", "v2-fsw"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.value = "";
      });
      render();
    });
  }
  var picktoggle = document.getElementById("v2-picktoggle");
  if (picktoggle) {
    picktoggle.addEventListener("change", function (e) {
      document.documentElement.classList.toggle("picking", e.target.checked);
      if (!e.target.checked) {
        state.picked.clear();
        render();
      }
    });
  }
  root.addEventListener("change", function (e) {
    var c = e.target.closest("[data-pick]");
    if (!c) return;
    if (c.checked) state.picked.add(c.getAttribute("data-pick"));
    else state.picked.delete(c.getAttribute("data-pick"));
    render();
  });
  var del = document.getElementById("v2-del");
  if (del && runId) {
    del.addEventListener("click", function () {
      var domains = Array.from(state.picked);
      if (!domains.length) return;
      if (!confirm("Delete " + domains.length + " competitor(s) from this list?")) return;
      del.disabled = true;
      fetch("/api/runs/" + runId + "/competitors/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domains: domains }),
      })
        .then(function (r) {
          return r.json().then(function (d) {
            if (!r.ok || d.error) throw new Error(d.error || "HTTP " + r.status);
            return d;
          });
        })
        .then(function () {
          location.reload();
        })
        .catch(function (err) {
          del.disabled = false;
          alert(err.message || err);
        });
    });
  }
  var density = document.getElementById("v2-density");
  if (density) {
    density.addEventListener("change", function (e) {
      document.documentElement.classList.toggle("compact", e.target.value === "compact");
    });
  }

  function postJson(path, payload) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok || d.error) throw new Error(d.error || "HTTP " + r.status);
        return d;
      });
    });
  }

  var swBtn = document.getElementById("v2-sw-fill");
  var swSt = document.getElementById("v2-sw-status");
  if (swBtn && runId) {
    swBtn.addEventListener("click", function () {
      var left = parseInt(swBtn.getAttribute("data-count") || "0", 10) || 0;
      var done = 0;
      swBtn.disabled = true;
      function step() {
        if (swSt) swSt.textContent = "Checking SimilarWeb… " + done + " done, " + left + " left";
        swBtn.textContent = "Checking SimilarWeb…";
        postJson("/api/runs/" + runId + "/competitors/similarweb", { limit: 6 })
          .then(function (d) {
            done += Number(d.checked || 0);
            left = Number(d.remaining || 0);
            swBtn.setAttribute("data-count", String(left));
            if (left > 0) {
              step();
              return;
            }
            if (swSt) swSt.textContent = done + " SimilarWeb checked. Reloading…";
            location.reload();
          })
          .catch(function (err) {
            swBtn.disabled = false;
            swBtn.textContent = "Check SimilarWeb" + (left ? " (" + left + ")" : "");
            if (swSt) swSt.textContent = err.message || String(err);
            alert(err.message || err);
          });
      }
      step();
    });
  }

  var area = document.getElementById("v2-urls");
  var addBtn = document.getElementById("v2-add");
  var addSt = document.getElementById("v2-add-status");
  var addLog = document.getElementById("v2-add-log");
  function existingDomains() {
    var have = {};
    ROWS.forEach(function (r) {
      if (r.domain) have[r.domain] = 1;
    });
    return have;
  }
  function hostOf(item) {
    var host = String(item || "").trim();
    if (!host || host.charAt(0) === "#") return "";
    host = host.replace(/^https?:\/\//i, "").replace(/^www\./i, "").split("/")[0].toLowerCase();
    host = host.replace(/:\d+$/, "");
    if (!host || host.indexOf(".") < 0) return "";
    return host;
  }
  function analyzeSites(text) {
    var parts = String(text || "").split(/[\s,;|]+/);
    var have = existingDomains();
    var seen = {},
      unique = [],
      fresh = [];
    var raw = 0,
      repeatInPaste = 0,
      already = 0;
    parts.forEach(function (item) {
      var host = hostOf(item);
      if (!host) return;
      raw++;
      if (seen[host]) {
        repeatInPaste++;
        return;
      }
      seen[host] = 1;
      var site = { domain: host, url: "https://" + host };
      unique.push(site);
      if (have[host]) {
        already++;
        return;
      }
      fresh.push(site);
    });
    return { raw: raw, unique: unique, fresh: fresh, repeatInPaste: repeatInPaste, already: already };
  }
  function describeClean(info) {
    var bits = [];
    if (info.repeatInPaste) bits.push(info.repeatInPaste + " duplicate" + (info.repeatInPaste > 1 ? "s" : "") + " in paste");
    if (info.already) bits.push(info.already + " already in the table");
    if (!bits.length) return "";
    return "Removed from list: " + bits.join(" · ") + ". " + info.fresh.length + " left.";
  }
  function cleanList() {
    if (!area) return analyzeSites("");
    var info = analyzeSites(area.value);
    var next = info.fresh
      .map(function (s) {
        return s.domain;
      })
      .join("\n");
    if (area.value !== next) area.value = next;
    return info;
  }
  function logLine(cls, text) {
    if (!addLog) return null;
    addLog.hidden = false;
    var li = document.createElement("li");
    li.className = cls || "";
    li.textContent = text;
    addLog.appendChild(li);
    addLog.scrollTop = addLog.scrollHeight;
    return li;
  }
  if (area) {
    area.addEventListener("paste", function () {
      setTimeout(function () {
        var info = cleanList();
        if (addSt) addSt.textContent = describeClean(info) || (info.fresh.length ? info.fresh.length + " new sites." : "");
      }, 0);
    });
    area.addEventListener("blur", function () {
      var info = cleanList();
      if (addSt && (info.repeatInPaste || info.already)) addSt.textContent = describeClean(info);
    });
  }
  if (addBtn && area && runId) {
    addBtn.addEventListener("click", function () {
      var info = cleanList();
      var sites = info.fresh;
      var sim = (document.getElementById("v2-add-sim") || {}).value || "";
      if (!sites.length) {
        if (addSt) addSt.textContent = describeClean(info) || "Paste one or more valid sites.";
        return;
      }
      addBtn.disabled = true;
      area.disabled = true;
      if (addLog) {
        addLog.innerHTML = "";
        addLog.hidden = false;
      }
      var skipped = info.already + info.repeatInPaste;
      if (skipped) logLine("skip", describeClean(info));
      var i = 0,
        added = 0,
        failed = 0;
      function next() {
        if (i >= sites.length) {
          if (addSt) addSt.textContent = added + " added · " + failed + " failed · " + skipped + " skipped. Reloading…";
          if (added) {
            location.reload();
            return;
          }
          addBtn.disabled = false;
          area.disabled = false;
          return;
        }
        var site = sites[i];
        var n = i + 1;
        if (addSt) addSt.textContent = "Adding " + n + "/" + sites.length + " — " + site.domain + "…";
        var row = logLine("run", n + "/" + sites.length + " " + site.domain + "…");
        postJson("/api/runs/" + runId + "/competitors/add", { url: site.url, similaridade: sim })
          .then(function (d) {
            if (d && d.skipped) {
              skipped++;
              if (row) {
                row.className = "skip";
                row.textContent = site.domain + " — already on the list";
              }
            } else {
              added++;
              if (row) {
                row.className = "ok";
                row.textContent = site.domain + " — added" + (d && d.similaridade ? " · " + d.similaridade : "");
              }
            }
          })
          .catch(function (err) {
            failed++;
            if (row) {
              row.className = "err";
              row.textContent = site.domain + " — " + (err.message || err);
            }
          })
          .then(function () {
            i++;
            next();
          });
      }
      next();
    });
  }

  render();
})();
