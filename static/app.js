(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
  const CHECK = '<svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
  const MAX_FULL = 12;
  const COLORS = ["#0F6B5C", "#4A6FA5", "#C2702E", "#7B5BB0", "#B42318", "#0E7490"];
  const state = { mode: "find", "find-market": "us", "full-market": "us", "full-report": "one", runs: "all" };
  try {
    const m = localStorage.getItem("wt-mode");
    if (m === "find" || m === "full") state.mode = m;
  } catch (e) { /* ignore */ }

  const norm = (raw) => String(raw || "").trim().toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").split(/[/?#\s]/)[0];
  const valid = (d) => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(d);
  const parse = (txt) => {
    const seen = new Set();
    return String(txt || "").split(/[\n,]+/).map(norm).filter(Boolean).filter((d) => !seen.has(d) && seen.add(d));
  };

  const CH = [
    { g: "paid", t: "Paid ads", items: [
      { k: "meta", n: "Meta Ads", d: "Active ads in the Meta Ad Library", core: 1 },
      { k: "google", n: "Google Ads", d: "Google Ads Transparency Center" },
      { k: "linkedin", n: "LinkedIn Ads", d: "LinkedIn Ad Library" },
    ] },
    { g: "org", t: "Organic", items: [
      { k: "seo", n: "SEO & brand search", d: "Organic traffic and brand searches", core: 1 },
      { k: "traffic", n: "Web traffic", d: "Monthly visits and engagement", core: 1 },
      { k: "x", n: "X / Twitter", d: "Profile and followers" },
      { k: "li", n: "LinkedIn page", d: "Company page followers" },
      { k: "reddit", n: "Reddit", d: "Posts and comments that mention the brand" },
    ] },
    { g: "inf", t: "Creators", items: [
      { k: "ytc", n: "YouTube creators", d: "Videos about the brand, page 1", time: "+1–2 min per site" },
      { k: "igc", n: "Instagram creators", d: "Posts about the brand, by likes" },
      { k: "social", n: "Own social profiles", d: "Instagram, YouTube and TikTok", core: 1 },
    ] },
  ];
  const on = new Set(["google", "linkedin", "x", "li", "reddit", "ytc", "igc"]);

  function renderCh() {
    $("chg").innerHTML = CH.map((grp) => `<div class="chc"><h4 class="${grp.g}"><i style="background:${{ paid: "#C2702E", org: "#4A6FA5", inf: "#7B5BB0" }[grp.g]}"></i>${grp.t}</h4>${grp.items.map((it) =>
      `<label class="ck"><input type="checkbox" data-ch="${it.k}" ${it.core || on.has(it.k) ? "checked" : ""} ${it.core ? "disabled" : ""}><span class="box">${CHECK}</span><span><b>${it.n}</b><small>${it.core ? "Always included · " : ""}${it.d}${it.time ? ` · <span class="t">${it.time}</span>` : ""}</small></span></label>`
    ).join("")}</div>`).join("");
    const all = CH.flatMap((g) => g.items);
    const opt = all.filter((i) => !i.core);
    $("ch-count").textContent = `${all.filter((i) => i.core || on.has(i.k)).length} of ${all.length} channels`;
    $("ch-all").textContent = opt.every((i) => on.has(i.k)) ? "Core only" : "Select all";
  }

  const HINT = {
    "find-market": { us: "Google US, Semrush US database and an English prompt.", br: "Google Brasil, Semrush BR database and a Portuguese prompt." },
    "full-report": { one: "All sites side by side in one report, like the scoreboard. Reuses saved data when it can.", each: "A separate report for every site." },
  };

  function renderSeg() {
    document.querySelectorAll("[data-seg]").forEach((s) => {
      const k = s.dataset.seg;
      s.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.v === state[k]));
    });
    document.querySelectorAll("[data-hint]").forEach((h) => {
      const table = HINT[h.dataset.hint];
      h.textContent = table ? (table[state[h.dataset.hint]] || "") : "";
    });
    const only = $("opt-only");
    if (only) only.closest(".tg").hidden = state["full-report"] === "one";
  }

  function renderMode() {
    document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === state.mode));
    $("f-find").hidden = state.mode !== "find";
    $("f-full").hidden = state.mode !== "full";
    try { localStorage.setItem("wt-mode", state.mode); } catch (e) { /* ignore */ }
  }

  function chips(list, max, youFirst) {
    return list.map((d, i) => {
      const bad = !valid(d);
      const over = i >= max;
      return `<span class="${bad || over ? "bad" : youFirst && i === 0 ? "you" : ""}" title="${bad ? "Not a valid site" : over ? "Over the limit" : ""}">${esc(d)}${youFirst && i === 0 && !bad ? " · you" : ""}${bad ? " · check" : ""}</span>`;
    }).join("");
  }

  function renderFind() {
    const list = parse($("find-sites").value);
    const bad = list.filter((d) => !valid(d));
    $("find-parsed").innerHTML = list.length > 1 || bad.length ? chips(list, 99, false) : "";
    $("find-count").innerHTML = list.length > 1 ? `${list.length} separate searches` : "";
    const n = Math.max(1, list.length);
    $("find-est").innerHTML = `About <b>${n === 1 ? "1½ minutes" : Math.ceil(n * 1.5) + " minutes"}</b> · ${$("opt-traffic").checked ? "with" : "without"} traffic check`;
  }

  function renderFull() {
    const list = parse($("full-sites").value);
    $("full-parsed").innerHTML = list.length ? chips(list, MAX_FULL, true) : "";
    $("full-count").innerHTML = `<span class="${list.length > MAX_FULL ? "bad" : ""}">${list.length} / ${MAX_FULL}</span>`;
    const n = Math.max(1, Math.min(list.length || 1, MAX_FULL));
    const ytc = on.has("ytc");
    const min = Math.round(1.5 + n * 0.45 + (ytc ? n * 0.4 : 0));
    $("full-est").innerHTML = `${list.length ? `<b>${n} site${n > 1 ? "s" : ""}</b> · ` : ""}about <b>${min} min</b>${ytc ? " (YouTube creators adds time)" : ""}`;
  }

  function colorFor(s) {
    let h = 0;
    const t = String(s || "");
    for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) >>> 0;
    return COLORS[h % COLORS.length];
  }

  function hostOf(url) {
    return norm(url) || String(url || "").replace(/^https?:\/\//, "").split("/")[0];
  }

  function nameOf(run) {
    return String(run.company || hostOf(run.url) || run.id || "Report").trim();
  }

  function fmtDur(a, b) {
    if (!a || !b) return "";
    const ms = new Date(b) - new Date(a);
    if (!Number.isFinite(ms) || ms < 0) return "";
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const r = s % 60;
    return r ? `${m}m ${r}s` : `${m}m`;
  }

  function peersOf(run) {
    return (run.peer_urls || []).map(hostOf).filter(Boolean);
  }

  function runType(run) {
    return run.competitors_only ? "find" : "full";
  }

  function statusInfo(run) {
    const st = String(run.status || "").toLowerCase();
    if (st === "done") return { cls: "ok", label: "Done" };
    if (st === "error" || st === "failed") return { cls: "err", label: "Error" };
    if (st === "pending") return { cls: "run", label: "Queued" };
    return { cls: "run", label: "Running" };
  }

  let RUNS = [];
  let confirmId = null;
  let es = null;
  let busy = false;
  let progressTotal = 10;

  function renderRuns() {
    const q = $("q").value.trim().toLowerCase();
    const rows = RUNS.filter((r) => {
      const type = runType(r);
      if (state.runs !== "all" && type !== state.runs) return false;
      if (!q) return true;
      const hay = [r.company, r.url, r.id, ...(r.peer_urls || [])].join(" ").toLowerCase();
      return hay.includes(q);
    });
    let h = "<thead><tr><th>Company</th><th>What</th><th>Status</th><th class=\"hm\">Market</th><th class=\"hm\">Time · cost</th><th></th></tr></thead><tbody>";
    h += rows.map((r) => {
      const type = runType(r);
      const n = nameOf(r);
      const d = hostOf(r.url);
      const vs = peersOf(r);
      const st = statusInfo(r);
      const href = r.html_url || (st.cls === "ok" ? `/runs/${r.id}/report.html` : "");
      const openLabel = type === "full" ? "Open report" : "Pick competitors";
      const what = type === "full"
        ? `Full analysis${vs.length ? `<small>vs ${vs.map(esc).join(", ")}</small>` : "<small>Single site</small>"}`
        : "Competitor search<small>Pick who goes into the report</small>";
      const time = fmtDur(r.created_at, r.updated_at || r.created_at);
      const cost = r.cost ? String(r.cost) : "";
      const metaTime = [time, cost].filter(Boolean).join(" · ") || "—";
      const err = st.cls === "err" && r.error ? `<small>${esc(String(r.error).slice(0, 140))}</small>` : "";
      const actions = confirmId === r.id
        ? `<span class="confirm">Delete this report? <span class="acts"><button type="button" class="del" data-del-yes="${esc(r.id)}">Delete</button><button type="button" data-del-no>Cancel</button></span></span>`
        : `<span class="acts">${href ? `<a class="open" href="${esc(href)}">${openLabel}</a>` : ""}${st.cls === "run" ? "" : `<button type="button" data-rerun="${esc(r.id)}">Run again</button>`}<button type="button" class="del" data-del="${esc(r.id)}" aria-label="Delete ${esc(n)}">Delete</button></span>`;
      return `<tr class="rr">
        <td><span class="co"><span class="a" style="background:${colorFor(n)}">${esc((n[0] || "?").toUpperCase())}</span><span><b>${esc(n)}</b><span class="dm">${esc(d || r.id)}</span></span></span></td>
        <td><span class="vs">${what}${err}</span></td>
        <td><span class="badge ${st.cls}">${st.label}</span></td>
        <td class="hm"><span class="meta">${esc((r.market || "US").toString().toUpperCase())}</span></td>
        <td class="hm"><span class="meta num">${esc(metaTime)}</span></td>
        <td>${actions}</td></tr>`;
    }).join("");
    if (!rows.length) h += `<tr><td colspan="6" class="empty">${RUNS.length ? "No reports match." : "No reports yet — run your first search above."}</td></tr>`;
    $("runs-tb").innerHTML = h + "</tbody>";
  }

  async function loadRuns() {
    try {
      const r = await fetch("/api/runs?limit=80");
      const j = await r.json();
      RUNS = j.runs || [];
      renderRuns();
    } catch (e) {
      $("runs-tb").innerHTML = `<tbody><tr><td colspan="6" class="empty">Could not load reports.</td></tr></tbody>`;
    }
  }

  function setBusy(on) {
    busy = on;
    $("find-go").disabled = on;
    $("full-go").disabled = on;
    if (on) {
      $("find-go").innerHTML = '<span class="spin"></span>Starting…';
      $("full-go").innerHTML = '<span class="spin"></span>Starting…';
    } else {
      $("find-go").textContent = "Find competitors →";
      $("full-go").textContent = "Run analysis →";
    }
  }

  function showJobs() {
    $("jobs").classList.add("show");
    $("jobs-err").textContent = "";
    $("jobs-done").innerHTML = "";
    $("jobs-log").textContent = "";
    $("jobs-bar").style.width = "2%";
    $("jobs-step").textContent = "Queuing…";
    $("jobs").scrollIntoView({ behavior: "smooth", block: "nearest" });
    if (es) { es.close(); es = null; }
  }

  function addDone(job, url, find) {
    const href = url || `/runs/${job.job_id || job.id}/report.html`;
    const label = find ? "Pick competitors" : (job.company || job.url || "Open report");
    $("jobs-done").insertAdjacentHTML("beforeend", `<a href="${esc(href)}">${esc(label)}</a>`);
  }

  function watchJob(job) {
    return new Promise((resolve) => {
      const streamUrl = job.stream || `/api/jobs/${job.job_id}/stream`;
      const source = new EventSource(streamUrl);
      es = source;
      source.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        if (msg.type === "ping") return;
        if (msg.type === "log" && msg.line) {
          $("jobs-log").textContent += msg.line + "\n";
          $("jobs-log").scrollTop = $("jobs-log").scrollHeight;
        }
        if (msg.type === "progress") {
          if (msg.total) progressTotal = Number(msg.total) || progressTotal;
          const pct = Math.min(98, Math.round((Number(msg.index || 0) / progressTotal) * 100));
          $("jobs-bar").style.width = (msg.state === "done" ? Math.min(100, pct + Math.round(100 / progressTotal)) : pct) + "%";
          $("jobs-step").textContent = `${msg.progress_label || ""} — ${msg.label || msg.step_id || ""}: ${msg.detail || msg.state || ""}`.replace(/^ — /, "");
        }
        if (msg.type === "error") {
          $("jobs-err").textContent = msg.message || "Error";
          source.close();
          resolve({ ok: false, job });
        }
        if (msg.type === "report_ready" && msg.html_url) {
          $("jobs-step").textContent = msg.detail || "Report ready — finishing extras…";
        }
        if (msg.type === "finished" || (msg.type === "done" && msg.html_url)) {
          const url = msg.html_url || `/runs/${job.job_id}/report.html`;
          $("jobs-bar").style.width = "100%";
          $("jobs-step").textContent = `Done — ${job.company || job.job_id}`;
          source.close();
          resolve({ ok: true, job, url });
        }
        if (msg.type === "eof") {
          source.close();
          poll(job.job_id).then(resolve);
        }
      };
      source.onerror = () => {
        source.close();
        poll(job.job_id).then(resolve);
      };
    });
  }

  async function poll(jobId) {
    return new Promise((resolve) => {
      const tick = async () => {
        try {
          const r = await fetch(`/api/jobs/${jobId}`);
          const j = await r.json();
          if (j.status === "done" && (j.html_url || true)) {
            const url = j.html_url || `/runs/${jobId}/report.html`;
            $("jobs-bar").style.width = "100%";
            $("jobs-step").textContent = "Done";
            resolve({ ok: true, job: { job_id: jobId, company: j.company, url: j.url }, url });
            return;
          }
          if (j.status === "error") {
            $("jobs-err").textContent = j.error || "Error";
            resolve({ ok: false, job: { job_id: jobId } });
            return;
          }
          $("jobs-step").textContent = j.current_step || "Working…";
          setTimeout(tick, 3000);
        } catch (e) {
          setTimeout(tick, 4000);
        }
      };
      tick();
    });
  }

  async function startAnalyze(payload, msgEl) {
    showJobs();
    setBusy(true);
    msgEl.className = "msg";
    msgEl.textContent = "";
    $("jobs-title").textContent = payload.competitors_only ? "Finding competitors…" : "Running analysis…";
    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to start");
      const list = (data.jobs && data.jobs.length) ? data.jobs : [data];
      progressTotal = data.competitors_only ? 2 : 10;
      $("jobs-meta").textContent = list.map((j) => j.company || j.url).join(", ") + " · " + (data.market || "").toString().toUpperCase();
      const find = !!data.competitors_only;
      const results = [];
      for (let i = 0; i < list.length; i++) {
        const job = list[i];
        $("jobs-step").textContent = list.length > 1
          ? `${i + 1} of ${list.length} — ${job.company || job.url}`
          : (job.company || job.url || "Working…");
        const result = await watchJob(job);
        if (result && result.url) {
          results.push({ company: job.company, url: result.url, id: job.job_id });
          addDone(job, result.url, find);
        }
        loadRuns();
      }
      $("jobs-bar").style.width = "100%";
      $("jobs-title").textContent = results.length ? "Done" : "Finished";
      $("jobs-step").textContent = list.length > 1
        ? `Done — ${results.length}/${list.length} reports`
        : "Done";
      msgEl.textContent = find
        ? "Search finished. Open the report to pick competitors."
        : "Analysis finished. Open it from Your reports.";
      setBusy(false);
      loadRuns();
    } catch (err) {
      $("jobs-err").textContent = err.message || String(err);
      msgEl.className = "msg err";
      msgEl.textContent = err.message || String(err);
      setBusy(false);
    }
  }

  async function deleteRun(runId) {
    if (!runId) return;
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Could not delete");
      RUNS = RUNS.filter((r) => r.id !== runId);
      confirmId = null;
      renderRuns();
    } catch (err) {
      confirmId = null;
      renderRuns();
      window.alert(err.message || String(err));
    }
  }

  async function rerun(runId) {
    if (!runId || busy) return;
    showJobs();
    setBusy(true);
    $("jobs-title").textContent = "Running again…";
    $("jobs-step").textContent = "Starting…";
    try {
      const res = await fetch(`/api/rerun/${encodeURIComponent(runId)}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to rerun");
      const list = (data.jobs && data.jobs.length) ? data.jobs : [data];
      const job = list[0];
      $("jobs-meta").textContent = `Rerun · ${job.company || job.url}`;
      progressTotal = data.competitors_only ? 2 : 10;
      const result = await watchJob(job);
      if (result && result.url) addDone(job, result.url, !!data.competitors_only);
      $("jobs-bar").style.width = "100%";
      $("jobs-title").textContent = "Done";
      setBusy(false);
      loadRuns();
    } catch (err) {
      $("jobs-err").textContent = err.message || String(err);
      setBusy(false);
    }
  }

  function findPayload(list) {
    return {
      url: list.join("\n"),
      force: $("opt-force-find").checked,
      competitors_only: true,
      market: state["find-market"],
      site_only: false,
      compare_all: false,
      include_google_ads: false,
      include_linkedin: false,
      include_youtube_influencers: false,
      include_instagram_influencers: false,
      include_reddit: false,
      include_twitter: false,
      include_linkedin_profile: false,
      include_brand_growth: $("opt-brand").checked,
      include_similarweb_alto: $("opt-traffic").checked,
    };
  }

  function fullPayload(list) {
    const one = state["full-report"] === "one";
    const onlyThese = one || $("opt-only").checked;
    return {
      url: list.join("\n"),
      force: $("opt-force-full").checked,
      market: state["full-market"],
      compare_all: one,
      site_only: onlyThese,
      competitors_only: false,
      include_google_ads: on.has("google"),
      include_linkedin: on.has("linkedin"),
      include_youtube_influencers: on.has("ytc"),
      include_instagram_influencers: on.has("igc"),
      include_reddit: on.has("reddit"),
      include_twitter: on.has("x"),
      include_linkedin_profile: on.has("li"),
    };
  }

  $("f-find").addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy) return;
    const list = parse($("find-sites").value);
    const msg = $("find-msg");
    if (!list.length) { msg.className = "msg err"; msg.textContent = "Enter your website first, like yourcompany.com"; $("find-sites").focus(); return; }
    const bad = list.filter((d) => !valid(d));
    if (bad.length) { msg.className = "msg err"; msg.textContent = `Check this site: ${bad.join(", ")}`; return; }
    startAnalyze(findPayload(list), msg);
  });

  $("f-full").addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy) return;
    const list = parse($("full-sites").value);
    const msg = $("full-msg");
    if (!list.length) { msg.className = "msg err"; msg.textContent = "Add at least one site."; $("full-sites").focus(); return; }
    const bad = list.filter((d) => !valid(d));
    if (bad.length) { msg.className = "msg err"; msg.textContent = `Check this site: ${bad.join(", ")}`; return; }
    if (list.length > MAX_FULL) { msg.className = "msg err"; msg.textContent = `That's ${list.length} sites — the limit is ${MAX_FULL}. Remove ${list.length - MAX_FULL}.`; return; }
    startAnalyze(fullPayload(list), msg);
  });

  document.addEventListener("click", (e) => {
    const m = e.target.closest("[data-mode]");
    if (m) { state.mode = m.dataset.mode; renderMode(); return; }
    const sb = e.target.closest("[data-seg] button");
    if (sb) {
      state[sb.closest("[data-seg]").dataset.seg] = sb.dataset.v;
      renderSeg();
      if (sb.closest('[data-seg="runs"]')) renderRuns();
      return;
    }
    if (e.target.closest("#ch-all")) {
      const opt = CH.flatMap((g) => g.items).filter((i) => !i.core);
      const allOn = opt.every((i) => on.has(i.k));
      opt.forEach((i) => (allOn ? on.delete(i.k) : on.add(i.k)));
      renderCh();
      renderFull();
      return;
    }
    const dl = e.target.closest("[data-del]");
    if (dl) { confirmId = dl.dataset.del; renderRuns(); return; }
    if (e.target.closest("[data-del-no]")) { confirmId = null; renderRuns(); return; }
    const dy = e.target.closest("[data-del-yes]");
    if (dy) { deleteRun(dy.dataset.delYes); return; }
    const rr = e.target.closest("[data-rerun]");
    if (rr) {
      const r = RUNS.find((x) => x.id === rr.dataset.rerun);
      if (r) {
        if (runType(r) === "find") {
          state.mode = "find";
          $("find-sites").value = hostOf(r.url);
          renderMode();
          renderFind();
        } else {
          state.mode = "full";
          $("full-sites").value = [hostOf(r.url), ...peersOf(r)].filter(Boolean).join("\n");
          renderMode();
          renderFull();
        }
      }
      rerun(rr.dataset.rerun);
    }
  });

  document.addEventListener("change", (e) => {
    const c = e.target.closest("[data-ch]");
    if (c) {
      if (c.checked) on.add(c.dataset.ch);
      else on.delete(c.dataset.ch);
      renderCh();
      renderFull();
      return;
    }
    if (e.target.id === "opt-traffic") renderFind();
  });

  $("find-sites").addEventListener("input", renderFind);
  $("full-sites").addEventListener("input", renderFull);
  $("q").addEventListener("input", renderRuns);

  (function bootFromQuery() {
    const q = new URLSearchParams(location.search);
    const tab = (q.get("tab") || "").toLowerCase();
    if (tab === "analyze" || tab === "full" || tab === "analysis") state.mode = "full";
    if (tab === "competitors" || tab === "find" || tab === "concorrentes") state.mode = "find";
    const pre = q.get("site") || q.get("url") || q.get("q") || q.get("company");
    if (pre && valid(norm(pre))) {
      $("find-sites").value = norm(pre);
      $("full-sites").value = norm(pre);
      if (!tab) state.mode = "find";
    }
    const rerunId = q.get("rerun") || q.get("redo");
    if (rerunId) {
      history.replaceState({}, "", "/app");
      rerun(rerunId);
    }
  })();

  renderMode();
  renderSeg();
  renderCh();
  renderFind();
  renderFull();
  loadRuns();
  setInterval(() => {
    if (RUNS.some((r) => ["running", "pending"].includes(String(r.status || "").toLowerCase()))) loadRuns();
  }, 8000);
})();
