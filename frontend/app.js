/* Rebellsystem CRM — Single-Page Frontend (vanilla JS) */
"use strict";

const State = {
  meta: null,
  stages: [],
  areaFilter: "",
  projectFilter: "",
  leadKind: "all",          // "all" | "normal" | "signal"
  leadSort: "score_desc",
  search: "",
  view: "dashboard",
  token: localStorage.getItem("crm_token") || "",
};

/* ---------- API ---------- */
async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (State.token) headers["X-CRM-Token"] = State.token;
  if (opts.json) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    showLogin("Token ungültig.");
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

/* ---------- Helpers ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; };
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));
const stageLabel = (k) => (State.stages.find((s) => s.key === k) || {}).label || k;

function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast hidden"), 2600);
}

function gradeClass(g) {
  if (!g) return "";
  const k = g.replace(/[^A-Za-z-]/g, "");
  return "grade-" + k;
}

function fmtImport(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    const date = d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
    const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    return `${date} ${time}`;
  } catch { return "—"; }
}

/* ---------- Boot ---------- */
async function boot() {
  try {
    State.meta = await api("/api/meta");
  } catch (e) {
    if (e.message === "unauthorized") return;
    // Wenn Auth nötig und kein Token → /api/meta ist offen, daher hierher nur bei echtem Fehler
    showLogin("");
    return;
  }
  State.stages = State.meta.stages;
  if (State.meta.auth_required && !State.token) { showLogin(""); return; }
  startApp();
}

function showLogin(err) {
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  $("#login-error").textContent = err || "";
}

function startApp() {
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  bindChrome();
  refreshFilters();
  refreshDueBadge();
  navigate("agenda");
}

/* ---------- Chrome (Nav, Suche, Filter) ---------- */
function bindChrome() {
  document.querySelectorAll(".nav-item").forEach((a) =>
    a.addEventListener("click", () => navigate(a.dataset.view))
  );
  $("#global-area").addEventListener("change", async (e) => {
    State.areaFilter = e.target.value;
    State.projectFilter = "";
    await loadProjectsIntoFilter();
    render();
  });
  $("#global-project").addEventListener("change", (e) => {
    State.projectFilter = e.target.value;
    render();
  });
  let to;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(to);
    to = setTimeout(() => { State.search = e.target.value.trim(); if (["leads", "pipeline"].includes(State.view)) render(); }, 250);
  });
  $("#drawer").addEventListener("click", (e) => {
    if (e.target.hasAttribute("data-close-drawer")) closeDrawer();
  });
}

async function refreshFilters() {
  await loadAreasIntoFilter();
  await loadProjectsIntoFilter();
}

async function loadAreasIntoFilter() {
  const areas = await api("/api/areas");
  const sel = $("#global-area");
  sel.innerHTML = '<option value="">Alle Bereiche</option>' +
    areas.map((a) => `<option value="${esc(a.name)}">${esc(a.name)} (${a.lead_count})</option>`).join("");
  sel.value = State.areaFilter;
  return areas;
}

async function loadProjectsIntoFilter() {
  const qs = State.areaFilter ? "?area=" + encodeURIComponent(State.areaFilter) : "";
  const projects = await api("/api/projects" + qs);
  const sel = $("#global-project");
  sel.innerHTML = '<option value="">Alle Projekte</option>' +
    projects.map((p) => `<option value="${p.id}">${esc(p.name)} (${p.lead_count})</option>`).join("");
  sel.value = State.projectFilter;
  return projects;
}

function navigate(view) {
  _clearEnginePoller();
  State.view = view;
  document.querySelectorAll(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $("#view-title").textContent = { dashboard: "Dashboard", agenda: "Agenda", pipeline: "Pipeline", leads: "Leads", deliveries: "Lieferungen", projects: "Projekte", import: "Import" }[view];
  render();
}

function render() {
  const v = State.view;
  if (v === "dashboard") return renderDashboard();
  if (v === "agenda") return renderAgenda();
  if (v === "pipeline") return renderPipeline();
  if (v === "leads") return renderLeads();
  if (v === "deliveries") return renderDeliveries();
  if (v === "projects") return renderProjects();
  if (v === "import") return renderImport();
}

/* Wiedervorlage-Badge in der Navigation aktualisieren */
async function refreshDueBadge() {
  try {
    const s = await api("/api/stats");
    const due = (s.overdue || 0) + (s.due_today || 0);
    const b = $("#nav-due");
    if (due > 0) { b.textContent = due; b.classList.remove("hidden"); b.classList.toggle("overdue", s.overdue > 0); }
    else b.classList.add("hidden");
  } catch (_) {}
}

/* ---------- Dashboard ---------- */
let _enginePollTimer = null;

function _clearEnginePoller() {
  if (_enginePollTimer) { clearInterval(_enginePollTimer); _enginePollTimer = null; }
}

async function _refreshEngineBanner() {
  const slot = $("#engine-banner-slot");
  if (!slot) return _clearEnginePoller();
  const eng = await api("/api/search-status").catch(() => null);
  if (!eng) return;
  if (eng.pending > 0) {
    slot.innerHTML = `
      <div class="engine-status-banner">
        <div class="engine-status-left">
          <span class="engine-status-count">${eng.pending}</span>
          <span class="engine-status-text">neue Leads aus KundenAgent warten auf Import
            <small class="engine-status-meta">${eng.total_in_file} gefunden · Stand ${esc(eng.file_mtime || "")}</small>
          </span>
        </div>
        <button class="btn primary sm" id="engine-import-btn">Jetzt importieren</button>
      </div>`;
    const btn = slot.querySelector("#engine-import-btn");
    btn.addEventListener("click", async () => {
      btn.disabled = true; btn.textContent = "Importiere…";
      try {
        const r = await api("/api/import-engine", { method: "POST" });
        toast(`✅ ${r.inserted} Leads → „${r.project}" (${r.skipped_duplicates} Dubletten, ${r.dropped_noise} Müll verworfen)`);
        renderDashboard();
      } catch (err) {
        toast(err.message, true);
        btn.disabled = false; btn.textContent = "Jetzt importieren";
      }
    });
  } else {
    slot.innerHTML = "";
  }
}

async function renderDashboard() {
  const view = $("#view");
  view.innerHTML = '<div class="empty">Lade…</div>';
  _clearEnginePoller();
  const s = await api("/api/stats" + statsQuery());
  const maxStage = Math.max(1, ...State.stages.map((st) => s.by_stage[st.key] || 0));

  view.innerHTML = `<div id="engine-banner-slot"></div>` + `
    <div class="kpi-grid">
      <div class="kpi primary"><div class="label">Leads gesamt</div><div class="value">${s.total}</div><div class="sub">im gewählten Bereich</div></div>
      <div class="kpi ${s.overdue ? "danger" : ""}" data-go-agenda style="cursor:pointer"><div class="label">Überfällig</div><div class="value">${s.overdue || 0}</div><div class="sub">Wiedervorlage offen →</div></div>
      <div class="kpi ${s.due_today ? "warn" : ""}" data-go-agenda style="cursor:pointer"><div class="label">Heute fällig</div><div class="value">${s.due_today || 0}</div><div class="sub">heute kontaktieren →</div></div>
      <div class="kpi accent"><div class="label">Conversion</div><div class="value">${s.conversion_rate}%</div><div class="sub">Gewonnen / Abgeschlossen</div></div>
    </div>
    <div class="kpi-grid">
      <div class="kpi"><div class="label">Mit E-Mail</div><div class="value">${s.with_email}</div><div class="sub">${pct(s.with_email, s.total)}% erreichbar</div></div>
      <div class="kpi"><div class="label">Mit Telefon</div><div class="value">${s.with_phone}</div><div class="sub">${pct(s.with_phone, s.total)}% telefonisch</div></div>
      <div class="kpi"><div class="label">Gewonnen</div><div class="value">${s.by_stage.won || 0}</div><div class="sub">Deals abgeschlossen</div></div>
      <div class="kpi"><div class="label">In Bearbeitung</div><div class="value">${(s.by_stage.contacted || 0) + (s.by_stage.offer || 0)}</div><div class="sub">Kontaktiert + Angebot</div></div>
    </div>
    <div class="panel">
      <h3>Pipeline-Verteilung</h3>
      ${State.stages.map((st) => {
        const c = s.by_stage[st.key] || 0;
        return `<div class="bar-row"><div class="bl">${esc(st.label)}</div><div class="bar-track"><div class="bar-fill" style="width:${(c / maxStage) * 100}%"></div></div><div class="bv">${c}</div></div>`;
      }).join("")}
    </div>
    <div class="panel">
      <h3>Lead-Qualität (Grade aus KundenAgent)</h3>
      ${s.by_grade.length ? s.by_grade.map((g) =>
        `<div class="bar-row"><div class="bl"><span class="badge ${gradeClass(g.grade)}">${esc(g.grade)}</span></div><div class="bar-track"><div class="bar-fill" style="width:${pct(g.count, s.total)}%"></div></div><div class="bv">${g.count}</div></div>`
      ).join("") : '<div class="muted">Noch keine Grades vorhanden.</div>'}
    </div>
    <div class="panel">
      <h3>Wartung & Datensicherung</h3>
      <div class="row" style="justify-content:space-between">
        <div class="muted" id="dup-hint">Prüfe Datenqualität…</div>
        <div class="row">
          <button class="btn sm" id="dash-dups">🔁 Duplikate prüfen</button>
          <button class="btn sm" id="dash-backup">💾 Backup jetzt</button>
        </div>
      </div>
      <div id="dup-list" style="margin-top:12px"></div>
    </div>`;

  view.querySelectorAll("[data-go-agenda]").forEach((k) => k.addEventListener("click", () => navigate("agenda")));
  _refreshEngineBanner();
  _enginePollTimer = setInterval(_refreshEngineBanner, 30_000);
  $("#dash-backup").addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Sichere…";
    try { const r = await api("/api/backup", { method: "POST" }); toast(`💾 Backup: ${r.file} (${r.size_mb} MB)`); }
    catch (err) { toast(err.message, true); }
    e.target.disabled = false; e.target.textContent = "💾 Backup jetzt";
  });
  $("#dash-dups").addEventListener("click", () => showDuplicates());
  // Duplikat-Hinweis vorab laden
  api("/api/duplicates").then((d) => {
    $("#dup-hint").textContent = d.length
      ? `${d.length} Firma(en) liegen in mehreren Projekten — mögliche Doppel-Ansprache.`
      : "Keine projektübergreifenden Duplikate. 👍";
  }).catch(() => {});
  refreshDueBadge();
}
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);

async function showDuplicates() {
  const box = $("#dup-list");
  box.innerHTML = '<div class="muted">Lade…</div>';
  const groups = await api("/api/duplicates");
  if (!groups.length) { box.innerHTML = '<div class="muted">Keine Duplikate gefunden.</div>'; return; }
  box.innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Firma</th><th>Projekte / Phasen</th><th></th></tr></thead>
    <tbody>${groups.map((g) => `
      <tr>
        <td><strong>${esc(g.company_name) || "—"}</strong><br><span class="muted">${esc(g.leads[0].email || g.leads[0].city || "")}</span></td>
        <td>${g.leads.map((l) => `<span class="badge soft" data-open="${l.id}" style="cursor:pointer">${esc(l.project_name)} · ${esc(stageLabel(l.stage))}</span>`).join(" ")}</td>
        <td class="muted">${g.count}×</td>
      </tr>`).join("")}</tbody></table></div>`;
  box.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openLead(b.dataset.open)));
}

/* ---------- Agenda (Wiedervorlagen) ---------- */
const AGENDA_SECTIONS = [
  ["overdue", "⛔ Überfällig", "overdue"],
  ["today", "🔔 Heute fällig", "today"],
  ["week", "📆 Diese Woche", "week"],
  ["later", "🗓️ Später", "later"],
];

async function renderAgenda() {
  const view = $("#view");
  view.innerHTML = '<div class="empty">Lade…</div>';
  const a = await api("/api/agenda" + statsQuery());
  const totalDue = a.counts.overdue + a.counts.today + a.counts.week + a.counts.later;

  if (!totalDue) {
    view.innerHTML = `<div class="panel"><h3>Keine offenen Wiedervorlagen 🎉</h3>
      <p class="muted">Setze bei einem Lead unter „Nächster Schritt" ein Datum — er taucht dann hier auf.
      Tipp: ${a.today ? "" : ""}gehe in <b>Leads</b>, öffne einen Lead und plane den nächsten Kontakt.</p></div>`;
    return;
  }

  view.innerHTML = AGENDA_SECTIONS.map(([key, title]) => {
    const items = a[key] || [];
    if (!items.length) return "";
    return `<div class="panel agenda-sec sec-${key}">
      <h3>${title} <span class="muted" style="font-weight:400">· ${items.length}</span></h3>
      <div class="agenda-list">
        ${items.map((l) => agendaRow(l, a.today_date)).join("")}
      </div></div>`;
  }).join("");

  view.querySelectorAll("[data-open]").forEach((r) => r.addEventListener("click", () => openLead(r.dataset.open)));
  view.querySelectorAll("[data-snooze]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation(); quickFollow(b.dataset.snooze, addDays(7), "📆 +1 Woche");
  }));
  view.querySelectorAll("[data-done]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation(); quickFollow(b.dataset.done, "clear", "✓ erledigt");
  }));
}

function agendaRow(l, today) {
  const overdue = l.next_action_date < today;
  return `<div class="agenda-item" data-open="${l.id}">
    <div class="ai-main">
      <div class="ai-comp">${esc(l.company_name) || "—"} ${l.grade ? `<span class="badge ${gradeClass(l.grade)}">${esc(l.grade)}</span>` : ""}</div>
      <div class="ai-meta">
        ${l.contact_name ? `👤 ${esc(l.contact_name)} ` : ""}${l.phone ? `· 📞 ${esc(l.phone)} ` : ""}${l.city ? `· 📍 ${esc(l.city)}` : ""}
      </div>
      ${l.next_action_label ? `<div class="ai-action">➡️ ${esc(l.next_action_label)}</div>` : ""}
    </div>
    <div class="ai-side">
      <span class="ai-date ${overdue ? "od" : ""}">${esc(l.next_action_date)}</span>
      <div class="row" style="gap:6px;margin-top:6px">
        <button class="btn sm" data-snooze="${l.id}" title="Um eine Woche verschieben">+7T</button>
        <button class="btn sm" data-done="${l.id}" title="Wiedervorlage entfernen">✓</button>
      </div>
    </div>
  </div>`;
}

async function quickFollow(id, date, label) {
  try {
    await api("/api/leads/" + id, { method: "PATCH", json: { next_action_date: date } });
    toast(label);
    refreshDueBadge();
    renderAgenda();
  } catch (e) { toast(e.message, true); }
}

const addDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

/* ---------- Pipeline (Kanban) ---------- */
async function renderPipeline() {
  const view = $("#view");
  view.innerHTML = '<div class="empty">Lade…</div>';
  const leads = await fetchLeads();
  const cols = State.stages.map((st) => {
    const items = leads.filter((l) => l.stage === st.key);
    return `
      <div class="kanban-col" data-stage="${st.key}">
        <div class="kanban-head">${esc(st.label)} <span class="count">${items.length}</span></div>
        <div class="kanban-body" data-drop="${st.key}">
          ${items.map(cardHtml).join("")}
        </div>
      </div>`;
  }).join("");
  view.innerHTML = `<div class="kanban">${cols}</div>`;
  bindKanban();
}

const todayStr = () => new Date().toISOString().slice(0, 10);

function nextActionPill(l) {
  if (!l.next_action_date) return "";
  const od = l.next_action_date < todayStr();
  return `<span class="na-pill ${od ? "od" : ""}" title="${esc(l.next_action_label) || "Wiedervorlage"}">${od ? "⏰" : "📅"} ${esc(l.next_action_date)}</span>`;
}

function cardHtml(l) {
  return `
    <div class="card" draggable="true" data-id="${l.id}">
      <div class="c-comp">${esc(l.company_name) || "—"}</div>
      <div class="c-meta">
        ${l.contact_name ? `<span>👤 ${esc(l.contact_name)}</span>` : ""}
        ${l.city ? `<span>📍 ${esc(l.city)}</span>` : ""}
        ${l.email ? `<span>✉️ ${esc(l.email)}</span>` : ""}
      </div>
      ${l.next_action_date ? `<div class="c-na">${nextActionPill(l)}</div>` : ""}
      <div class="c-foot">
        ${l.grade ? `<span class="badge ${gradeClass(l.grade)}">${esc(l.grade)}</span>` : "<span></span>"}
        ${l.score != null ? `<span class="badge score">${Math.round(l.score)}</span>` : ""}
      </div>
    </div>`;
}

function bindKanban() {
  let dragId = null;
  document.querySelectorAll(".card").forEach((c) => {
    c.addEventListener("dragstart", () => { dragId = c.dataset.id; c.style.opacity = ".4"; });
    c.addEventListener("dragend", () => { c.style.opacity = "1"; });
    c.addEventListener("click", () => openLead(c.dataset.id));
  });
  document.querySelectorAll(".kanban-col").forEach((col) => {
    const body = $(".kanban-body", col);
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("drag-over"); });
    col.addEventListener("dragleave", () => col.classList.remove("drag-over"));
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("drag-over");
      const stage = body.dataset.drop;
      if (!dragId) return;
      try {
        await api(`/api/leads/${dragId}`, { method: "PATCH", json: { stage } });
        toast("Phase aktualisiert → " + stageLabel(stage));
        renderPipeline();
      } catch (err) { toast(err.message, true); }
    });
  });
}

/* ---------- Leads Tabelle ---------- */
const SORT_LABELS = {
  score_desc: "Score (höchste zuerst)",
  nextaction_asc: "Wiedervorlage (früheste zuerst)",
  imported_desc: "Importiert (neueste zuerst)",
  imported_asc: "Importiert (älteste zuerst)",
  created_desc: "Lead-Datum (neueste zuerst)",
  created_asc: "Lead-Datum (älteste zuerst)",
  company_asc: "Firma (A–Z)",
};

async function renderLeads() {
  const view = $("#view");
  view.innerHTML = '<div class="empty">Lade…</div>';
  const leads = await fetchLeads(State.leadSort || "score_desc");
  const sortSel = `<select id="lead-sort">${Object.entries(SORT_LABELS).map(([k, v]) =>
    `<option value="${k}" ${(State.leadSort || "score_desc") === k ? "selected" : ""}>${v}</option>`).join("")}</select>`;
  const kinds = [["all", "Alle"], ["normal", "Normal"], ["signal", "📡 Signal"]];
  const kindToggle = `<div class="seg" id="lead-kind">${kinds.map(([k, label]) =>
    `<button class="seg-btn ${(State.leadKind || "all") === k ? "active" : ""}" data-kind="${k}">${label}</button>`).join("")}</div>`;
  const bindKindToggle = () => $("#lead-kind").querySelectorAll("[data-kind]").forEach((b) =>
    b.addEventListener("click", () => { State.leadKind = b.dataset.kind; renderLeads(); }));

  if (!leads.length) {
    view.innerHTML = `<div class="row" style="margin-bottom:14px;justify-content:space-between"><div class="row" style="gap:12px">${kindToggle}<span class="muted">0 Leads</span></div><div class="row"><span class="muted">Sortieren:</span>${sortSel}</div></div><div class="empty">Keine Leads in dieser Auswahl. Importiere welche über „Import".</div>`;
    $("#lead-sort").addEventListener("change", (e) => { State.leadSort = e.target.value; renderLeads(); });
    bindKindToggle();
    return;
  }
  const dlvs = await api("/api/deliveries").catch(() => []);
  const dlvOpts = dlvs.length
    ? '<option value="">— Lieferung wählen —</option>' + dlvs.map((d) =>
        `<option value="${d.id}">${esc(d.title)}${d.customer ? " · " + esc(d.customer) : ""} (${d.count})</option>`).join("")
    : '<option value="">— erst unter 📦 Lieferungen anlegen —</option>';

  // Nach Lauf gruppieren: jeder Import teilt EINEN imported_at-Zeitstempel = ein Lauf.
  const groupRun = State.leadGroupByRun !== false;   // Standard: an
  const projs = await api("/api/projects").catch(() => []);
  const projMap = {};
  projs.forEach((p) => { projMap[p.id] = p.name; });

  const leadRowHtml = (l, runKey) => `
          <tr data-id="${l.id}" data-run="${runKey ? esc(runKey) : ""}">
            <td class="lead-checkcell" style="text-align:center"><input type="checkbox" class="lead-check" data-id="${l.id}"></td>
            <td><strong>${esc(l.company_name) || "—"}</strong>${l.is_signal ? ' <span class="badge sig" title="Signal-Lead">📡</span>' : ""}</td>
            <td>${esc(l.contact_name) || ""}${l.role ? `<br><span class="muted">${esc(l.role)}</span>` : ""}</td>
            <td>${esc(l.email) || ""}</td>
            <td>${esc(l.phone) || ""}</td>
            <td>${esc(l.city) || ""}</td>
            <td>${esc(l.industry) || ""}</td>
            <td>${l.next_action_date ? nextActionPill(l) : '<span class="muted">—</span>'}</td>
            <td>${l.score != null ? `<span class="badge score">${Math.round(l.score)}</span>` : ""}</td>
            <td>${l.grade ? `<span class="badge ${gradeClass(l.grade)}">${esc(l.grade)}</span>` : ""}</td>
            <td>${esc(stageLabel(l.stage))}</td>
            <td class="muted" style="white-space:nowrap;font-size:12px">${fmtImport(l.imported_at || l.created_at)}</td>
          </tr>`;

  let bodyRows;
  if (groupRun) {
    const map = new Map();
    leads.forEach((l) => {
      const k = (l.imported_at || l.created_at || "—").slice(0, 19);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(l);
    });
    const keys = Array.from(map.keys()).sort((a, b) => (a < b ? 1 : a > b ? -1 : 0)); // neuester Lauf zuerst
    bodyRows = keys.map((k) => {
      const grp = map.get(k);
      const pname = projMap[grp[0].project_id] || "";
      const head = `<tr class="run-head"><td colspan="12"><input type="checkbox" class="run-check" data-run="${esc(k)}" title="Alle Leads dieses Laufs markieren"><span style="margin-left:7px">📅 ${fmtImport(k)}${pname ? " · " + esc(pname) : ""}</span><span class="rh-count"> · ${grp.length} Lead${grp.length !== 1 ? "s" : ""}</span></td></tr>`;
      return head + grp.map((l) => leadRowHtml(l, k)).join("");
    }).join("");
  } else {
    bodyRows = leads.map((l) => leadRowHtml(l)).join("");
  }

  view.innerHTML = `
    <div class="row" style="margin-bottom:10px;justify-content:space-between">
      <div class="row" style="gap:12px">${kindToggle}<span class="muted">${leads.length} Leads</span></div>
      <div class="row"><label class="muted" title="Leads nach Import-Lauf (Datum/Uhrzeit) gruppieren" style="display:flex;align-items:center;gap:6px;cursor:pointer"><input type="checkbox" id="lead-grouprun" ${groupRun ? "checked" : ""}> 📅 nach Lauf</label><span class="muted">Sortieren:</span>${sortSel}
        <button class="btn sm" id="lead-csv">⬇️ CSV</button></div>
    </div>
    <div class="row" id="lead-dlvbar" style="margin-bottom:12px;gap:8px;align-items:center;flex-wrap:wrap;background:var(--panel-2,#0f1626);padding:8px 10px;border:1px solid var(--border);border-radius:9px">
      <label class="muted" style="display:flex;align-items:center;gap:6px;cursor:pointer"><input type="checkbox" id="lead-all"> alle</label>
      <span class="muted" id="lead-selcount">0 ausgewählt</span>
      <span class="muted">→ in Lieferung:</span>
      <select id="lead-dlv-sel" style="padding:7px 10px;border:1px solid var(--border);border-radius:8px;max-width:280px">${dlvOpts}</select>
      <button class="btn sm primary" id="lead-add-dlv">＋ hinzufügen</button>
      <span style="flex:1"></span>
      <a class="muted" id="lead-go-dlv" style="cursor:pointer">📦 Lieferungen verwalten →</a>
    </div>
    <div class="table-wrap"><table>
      <thead><tr>
        <th style="width:32px"></th><th>Firma</th><th>Kontakt</th><th>E-Mail</th><th>Telefon</th><th>Stadt</th><th>Branche</th><th>Wiedervorlage</th><th>Score</th><th>Grade</th><th>Phase</th><th class="muted" style="white-space:nowrap">Importiert</th>
      </tr></thead>
      <tbody>${bodyRows}</tbody>
    </table></div>`;

  const checks = () => Array.from(view.querySelectorAll(".lead-check"));
  const selectedIds = () => checks().filter((c) => c.checked).map((c) => Number(c.dataset.id));
  const updateCount = () => { $("#lead-selcount").textContent = `${selectedIds().length} ausgewählt`; };

  view.querySelectorAll("tbody tr").forEach((tr) => tr.addEventListener("click", (e) => {
    if (tr.classList.contains("run-head")) return;     // Lauf-Überschrift öffnet keinen Lead
    if (e.target.closest(".lead-checkcell")) return;   // Klick auf die Checkbox öffnet den Lead NICHT
    openLead(tr.dataset.id);
  }));
  checks().forEach((c) => c.addEventListener("change", updateCount));
  $("#lead-all").addEventListener("change", (e) => { checks().forEach((c) => (c.checked = e.target.checked)); updateCount(); });
  // „ganzer Lauf": alle Leads eines Import-Laufs auf einmal an-/abwählen.
  view.querySelectorAll(".run-check").forEach((rc) => rc.addEventListener("change", () => {
    const key = rc.dataset.run;
    view.querySelectorAll("tbody tr[data-run]").forEach((tr) => {
      if (tr.dataset.run === key) { const cb = tr.querySelector(".lead-check"); if (cb) cb.checked = rc.checked; }
    });
    updateCount();
  }));
  $("#lead-go-dlv").addEventListener("click", () => navigate("deliveries"));
  $("#lead-add-dlv").addEventListener("click", async () => {
    const ids = selectedIds();
    const did = $("#lead-dlv-sel").value;
    if (!ids.length) { toast("Erst Leads anhaken", true); return; }
    if (!did) { toast("Erst eine Lieferung wählen/anlegen (📦 Lieferungen)", true); return; }
    try {
      const r = await api(`/api/deliveries/${did}/leads`, { method: "POST", json: { lead_ids: ids } });
      const label = $("#lead-dlv-sel").selectedOptions[0].textContent.split(" · ")[0].split(" (")[0];
      toast(`✅ ${r.added} hinzugefügt → „${label}" (jetzt ${r.count})`);
      checks().forEach((c) => (c.checked = false)); $("#lead-all").checked = false; updateCount();
      renderLeads();   // Anzahl in der Lieferungs-Auswahl aktualisieren
    } catch (err) { toast(err.message, true); }
  });
  $("#lead-sort").addEventListener("change", (e) => { State.leadSort = e.target.value; renderLeads(); });
  $("#lead-csv").addEventListener("click", () => exportCsv(leads));
  const grpToggle = $("#lead-grouprun");
  if (grpToggle) grpToggle.addEventListener("change", (e) => { State.leadGroupByRun = e.target.checked; renderLeads(); });
  bindKindToggle();
}

/* ---------- Lieferungen (Kundenseiten) ---------- */
async function renderDeliveries() {
  const view = $("#view");
  view.innerHTML = '<div class="empty">Lade…</div>';
  let list;
  try {
    list = await api("/api/deliveries");
  } catch (e) {
    view.innerHTML = `<div class="empty">Lieferungen konnten nicht geladen werden.<br>
      <span class="muted">${esc(e.message)} — läuft der CRM-Server schon mit dem neuen Code?<br>
      Schwarzes CRM-Fenster schließen → <b>start.bat</b> neu starten → im Browser <b>Strg+F5</b>.</span></div>`;
    return;
  }
  view.innerHTML = `
    <div class="panel">
      <h3>＋ Neue Lieferung (Kundenseite)</h3>
      <div class="row" style="gap:8px;flex-wrap:wrap">
        <input id="dlv-title" placeholder="Titel — sieht der Kunde, z.B. „Vertriebs-Leads Juni“" style="flex:2;min-width:240px;padding:10px 12px;border:1px solid var(--border);border-radius:9px" />
        <input id="dlv-customer" placeholder="Kundenname (optional)" style="flex:1;min-width:160px;padding:10px 12px;border:1px solid var(--border);border-radius:9px" />
        <button class="btn primary" id="dlv-create">Anlegen</button>
      </div>
      <div class="muted" style="margin-top:8px">Danach unter <b>📇 Leads</b> die gewünschten Leads anhaken → „＋ hinzufügen". Den fertigen Link gibst du dem Kunden — er braucht kein Login.</div>
    </div>
    ${list.length ? list.map(deliveryCard).join("") : '<div class="empty">Noch keine Lieferungen. Lege oben deine erste an.</div>'}`;
  $("#dlv-create").addEventListener("click", async () => {
    const title = $("#dlv-title").value.trim();
    if (!title) { toast("Titel fehlt", true); return; }
    try {
      await api("/api/deliveries", { method: "POST", json: { title, customer: $("#dlv-customer").value.trim(), lead_ids: [] } });
      toast("Lieferung angelegt"); renderDeliveries();
    } catch (e) { toast(e.message, true); }
  });
  view.querySelectorAll("[data-dlv]").forEach(bindDeliveryCard);
}

function deliveryCard(d) {
  // Öffentlicher Link (feste ngrok-Domain) bevorzugt — den kann der Kunde öffnen,
  // auch wenn das Admin-CRM über localhost läuft. Sonst Fallback location.origin.
  const url = d.public_url || (location.origin + d.url);
  const hinweis = d.public_url
    ? '<span class="muted" style="font-size:11px">🌐 öffentlicher Link — direkt sendbar</span>'
    : '<span style="font-size:11px;color:#fbbf24">⚠ lokaler Link — Kunde kann ihn nicht öffnen. CRM per <b>start_crm_ngrok.bat</b> starten.</span>';
  return `<div class="panel" data-dlv="${d.id}">
    <div class="row" style="justify-content:space-between;align-items:flex-start;gap:10px">
      <div><h3 style="margin:0">${esc(d.title)}</h3>
        <div class="muted">${d.customer ? esc(d.customer) + " · " : ""}<b>${d.count}</b> Leads</div></div>
      <div class="row" style="gap:6px;flex-wrap:wrap">
        <button class="btn sm" data-act="open">Öffnen ↗</button>
        <button class="btn sm primary" data-act="copy">Link kopieren</button>
        <button class="btn sm" data-act="leads">Leads</button>
        <button class="btn sm" data-act="del" style="color:#d6455d">Löschen</button>
      </div>
    </div>
    <input readonly value="${esc(url)}" data-link style="width:100%;margin-top:10px;padding:9px 11px;border:1px solid var(--border);border-radius:8px;font-size:12.5px" />
    <div style="margin-top:5px">${hinweis}</div>
    <div data-leads hidden style="margin-top:12px"></div>
  </div>`;
}

function kbBadge(stufe, score) {
  const c = stufe === "hoch" ? "#34d399" : stufe === "mittel" ? "#fbbf24" : "#94a3b8";
  return `<span style="display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700;color:#06122b;background:${c}">${esc(stufe)} ${score}</span>`;
}

function bindDeliveryCard(card) {
  const id = card.dataset.dlv;
  const url = card.querySelector("[data-link]").value;
  card.querySelector('[data-act="open"]').addEventListener("click", () => window.open(url, "_blank", "noopener"));
  card.querySelector('[data-act="copy"]').addEventListener("click", () => copyText(url));
  card.querySelector('[data-act="del"]').addEventListener("click", async () => {
    if (!confirm("Diese Lieferung löschen? Der Kunden-Link wird ungültig.")) return;
    try { await api(`/api/deliveries/${id}`, { method: "DELETE" }); toast("Gelöscht"); renderDeliveries(); }
    catch (e) { toast(e.message, true); }
  });
  const slot = card.querySelector("[data-leads]");
  card.querySelector('[data-act="leads"]').addEventListener("click", async () => {
    if (!slot.hidden) { slot.hidden = true; return; }
    slot.innerHTML = '<div class="muted">Lade…</div>'; slot.hidden = false;
    try {
      const d = await api(`/api/deliveries/${id}`);
      slot.innerHTML = d.leads.length
        ? `<div class="table-wrap"><table><tbody>${d.leads.map((l) => `<tr>
            <td><strong>${esc(l.firma)}</strong></td>
            <td>${l.kaufbereitschaft_stufe ? kbBadge(l.kaufbereitschaft_stufe, l.kaufbereitschaft_score) : ""}</td>
            <td>${esc(l.email) || esc(l.telefon) || ""}</td>
            <td style="text-align:right"><button class="btn sm" data-rm="${l.lead_id || ""}" style="color:#d6455d">entfernen</button></td>
          </tr>`).join("")}</tbody></table></div>`
        : '<div class="muted">Noch keine Leads. Unter 📇 Leads anhaken → „＋ hinzufügen".</div>';
      slot.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", async () => {
        const lid = b.dataset.rm; if (!lid) return;
        try { await api(`/api/deliveries/${id}/leads/${lid}`, { method: "DELETE" }); b.closest("tr").remove(); toast("Entfernt"); }
        catch (e) { toast(e.message, true); }
      }));
    } catch (e) { slot.innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
  });
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast("Link kopiert"); return; }
  catch (_) {}
  const t = document.createElement("textarea");
  t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
  document.body.appendChild(t); t.select();
  try { document.execCommand("copy"); toast("Link kopiert"); } catch (e) { toast("Kopieren nicht möglich", true); }
  t.remove();
}

function leadDate(l) {
  const d = l.created_at || l.imported_at || "";
  return d.slice(0, 10);
}

function exportCsv(leads) {
  const cols = ["company_name", "contact_name", "role", "email", "phone", "city", "industry", "score", "grade", "stage", "created_at", "imported_at"];
  const head = cols.join(",");
  const esc2 = (v) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const rows = leads.map((l) => cols.map((c) => esc2(l[c])).join(","));
  const blob = new Blob(["﻿" + head + "\n" + rows.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "leads_export.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function fetchLeads(sort) {
  const p = new URLSearchParams();
  if (State.projectFilter) p.set("project_id", State.projectFilter);
  else if (State.areaFilter) p.set("area", State.areaFilter);
  if (State.search) p.set("q", State.search);
  if (State.leadKind && State.leadKind !== "all") p.set("kind", State.leadKind);
  if (sort) p.set("sort", sort);
  return api("/api/leads?" + p.toString());
}

function statsQuery() {
  const p = new URLSearchParams();
  if (State.projectFilter) p.set("project_id", State.projectFilter);
  else if (State.areaFilter) p.set("area", State.areaFilter);
  const s = p.toString();
  return s ? "?" + s : "";
}

/* ---------- Projekte & Bereiche ---------- */
async function renderProjects() {
  const view = $("#view");
  const [areas, projects] = await Promise.all([api("/api/areas"), api("/api/projects")]);
  const areaNames = areas.map((a) => a.name);

  // Projekte nach Bereich gruppieren (inkl. leerer Bereiche)
  const grouped = {};
  areaNames.forEach((n) => (grouped[n] = []));
  projects.forEach((p) => {
    const a = p.area || "Ohne Bereich";
    (grouped[a] = grouped[a] || []).push(p);
  });

  const areaOptions = areaNames.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");

  view.innerHTML = `
    <div class="panel">
      <h3>Bereich anlegen</h3>
      <div class="row">
        <input id="na-name" style="flex:1;padding:10px 12px;border:1px solid var(--border);border-radius:9px" placeholder="Bereichsname, z.B. „Websiten“" />
        <button class="btn primary" id="na-add">Bereich anlegen</button>
      </div>
    </div>
    <div class="panel">
      <h3>Projekt anlegen</h3>
      <div class="row">
        <input id="np-name" style="flex:1;padding:10px 12px;border:1px solid var(--border);border-radius:9px" placeholder="Projektname, z.B. „Dachdecker Saarbrücken“" />
        <select id="np-area" style="padding:10px 12px;border:1px solid var(--border);border-radius:9px">
          <option value="">Ohne Bereich</option>${areaOptions}
        </select>
        <button class="btn primary" id="np-add">Anlegen</button>
      </div>
      <div class="muted">Tipp: Beim Import kannst du Leads automatisch nach Branche in eigene Projekte aufteilen.</div>
    </div>
    ${Object.entries(grouped).map(([area, ps]) => `
      <div class="panel">
        <h3>📁 ${esc(area)} <span class="muted" style="font-weight:400">· ${ps.length} Projekte · ${ps.reduce((s, p) => s + p.lead_count, 0)} Leads</span></h3>
        <div class="table-wrap"><table>
          <thead><tr><th>Projekt</th><th>Quelle</th><th>Leads</th><th>Angelegt</th><th></th></tr></thead>
          <tbody>
            ${ps.length ? ps.map((p) => `
              <tr>
                <td><strong>${esc(p.name)}</strong></td>
                <td>${esc(p.source) || ""}</td>
                <td>${p.lead_count}</td>
                <td class="muted">${esc((p.created_at || "").slice(0, 10))}</td>
                <td><button class="btn sm danger" data-del="${p.id}">Löschen</button></td>
              </tr>`).join("") : '<tr><td colspan="5" class="empty">Noch keine Projekte in diesem Bereich.</td></tr>'}
          </tbody>
        </table></div>
      </div>`).join("")}`;

  $("#na-add").addEventListener("click", async () => {
    const name = $("#na-name").value.trim();
    if (!name) return;
    await api("/api/areas", { method: "POST", json: { name } });
    toast("Bereich angelegt");
    await loadAreasIntoFilter();
    renderProjects();
  });
  $("#np-add").addEventListener("click", async () => {
    const name = $("#np-name").value.trim();
    if (!name) return;
    await api("/api/projects", { method: "POST", json: { name, area: $("#np-area").value || null } });
    toast("Projekt angelegt");
    await refreshFilters();
    renderProjects();
  });
  view.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("Projekt inkl. aller Leads wirklich löschen?")) return;
      await api("/api/projects/" + b.dataset.del, { method: "DELETE" });
      toast("Projekt gelöscht");
      State.projectFilter = "";
      await refreshFilters();
      renderProjects();
    })
  );
}

/* ---------- Import ---------- */
function renderImport() {
  const view = $("#view");
  view.innerHTML = `
    <div class="panel">
      <h3>Leads importieren</h3>
      <p class="muted">CSV oder JSON aus dem KundenAgent (z.B. <code>leads.csv</code>, <code>leads.json</code> oder <code>B2B_GESAMT_LEADS.json</code>). Es wird nur gelesen — der KundenAgent bleibt unberührt.</p>
      <div class="dropzone" id="dz">
        <input type="file" id="file" accept=".csv,.json" hidden />
        <div style="font-size:34px">📥</div>
        <p><strong>Datei hierher ziehen</strong> oder <button class="btn" id="pick">auswählen</button></p>
        <div id="fname" class="muted"></div>
      </div>
      <div id="import-config"></div>
    </div>`;

  const dz = $("#dz"), fileInput = $("#file");
  $("#pick").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => fileInput.files[0] && preview(fileInput.files[0]));
  ["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag-over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag-over"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) { fileInput.files = e.dataTransfer.files; preview(f); } });
}

let importFile = null;
async function preview(file) {
  importFile = file;
  $("#fname").textContent = file.name;
  const fd = new FormData();
  fd.append("file", file);
  let p;
  try { p = await api("/api/import/preview", { method: "POST", body: fd }); }
  catch (e) { toast(e.message, true); return; }

  const [projects, areas] = await Promise.all([api("/api/projects"), api("/api/areas")]);
  const areaOpts = areas.map((a) => `<option value="${esc(a.name)}">${esc(a.name)}</option>`).join("");
  $("#import-config").innerHTML = `
    <div style="margin-top:18px">
      <div class="row" style="gap:24px;margin-bottom:16px">
        <div><span class="muted">Format</span><br><strong>${esc(p.format)}</strong></div>
        <div><span class="muted">Zeilen</span><br><strong>${p.total_rows}</strong></div>
        <div><span class="muted">Eindeutige Leads</span><br><strong>${p.unique_leads}</strong></div>
        <div><span class="muted">Branchen</span><br><strong>${p.industry_count}</strong></div>
        ${p.dropped_noise ? `<div><span class="muted">Test verworfen</span><br><strong>${p.dropped_noise}</strong></div>` : ""}
      </div>

      <div class="field">
        <label>Bereich</label>
        <select id="imp-area">
          <option value="">➕ Neuen Bereich anlegen…</option>
          ${areaOpts}
        </select>
      </div>
      <div class="field" id="new-area-wrap">
        <label>Name des neuen Bereichs</label>
        <input id="imp-newarea" placeholder="z.B. B2B Agenten System" />
      </div>

      <div class="field">
        <label>Aufteilung innerhalb des Bereichs</label>
        <select id="imp-mode">
          ${p.industry_count > 1 ? `<option value="per_industry">Nach Branche aufteilen (${p.industry_count} Projekte)</option>` : ""}
          <option value="single">Alles in EIN Projekt</option>
          ${p.campaign_count > 1 ? `<option value="per_campaign">Nach Kampagne aufteilen (${p.campaign_count} Projekte)</option>` : ""}
        </select>
      </div>

      <div class="field" id="single-target">
        <label>Projekt</label>
        <select id="imp-project">
          <option value="">➕ Neues Projekt anlegen…</option>
          ${projects.map((pr) => `<option value="${pr.id}">${esc(pr.name)}${pr.area ? " · " + esc(pr.area) : ""} (${pr.lead_count})</option>`).join("")}
        </select>
      </div>
      <div class="field" id="new-name-wrap">
        <label>Name des neuen Projekts</label>
        <input id="imp-newname" value="${esc(suggestName(file.name))}" />
      </div>

      <div class="table-wrap" style="margin:10px 0 16px">
        <table class="preview-table"><thead><tr><th>Firma</th><th>Kontakt</th><th>E-Mail</th><th>Stadt</th><th>Score</th></tr></thead>
        <tbody>${p.sample.map((s) => `<tr><td>${esc(s.company_name)}</td><td>${esc(s.contact_name)}</td><td>${esc(s.email)}</td><td>${esc(s.city)}</td><td>${s.score != null ? Math.round(s.score) : ""}</td></tr>`).join("")}</tbody></table>
      </div>
      <button class="btn primary" id="imp-go">⬆️ ${p.unique_leads} Leads importieren</button>
    </div>`;

  const modeSel = $("#imp-mode"), projSel = $("#imp-project"), areaSel = $("#imp-area");
  const refresh = () => {
    const single = modeSel.value === "single";
    $("#single-target").style.display = single ? "flex" : "none";
    $("#new-name-wrap").style.display = (single && projSel.value === "") ? "flex" : "none";
    $("#new-area-wrap").style.display = (areaSel.value === "") ? "flex" : "none";
  };
  [modeSel, projSel, areaSel].forEach((s) => s.addEventListener("change", refresh));
  refresh();

  $("#imp-go").addEventListener("click", doImport);
}

function suggestName(fname) {
  const base = fname.replace(/\.(csv|json)$/i, "");
  return "Import " + base.slice(0, 40);
}

async function doImport() {
  const mode = $("#imp-mode").value;
  const area = $("#imp-area").value || $("#imp-newarea").value.trim();
  const fd = new FormData();
  fd.append("file", importFile);
  fd.append("mode", mode);
  if (area) fd.append("area", area);
  if (mode === "single") {
    const pid = $("#imp-project").value;
    if (pid) fd.append("project_id", pid);
    else fd.append("project_name", $("#imp-newname").value.trim() || "Import");
  }
  $("#imp-go").disabled = true;
  $("#imp-go").textContent = "Importiere…";
  try {
    const r = await api("/api/import", { method: "POST", body: fd });
    const noise = r.dropped_noise ? ` · ${r.dropped_noise} Test verworfen` : "";
    toast(`✅ ${r.inserted} Leads importiert · ${r.projects_created} Projekte · ${r.skipped_duplicates} Duplikate${noise}`);
    await refreshFilters();
    navigate("leads");
  } catch (e) {
    toast(e.message, true);
    $("#imp-go").disabled = false;
    $("#imp-go").textContent = "Erneut versuchen";
  }
}

/* ---------- Lead Drawer ---------- */
const EDIT_FIELDS = [
  ["company_name", "Firma"], ["contact_name", "Kontakt"], ["role", "Rolle"],
  ["email", "E-Mail"], ["phone", "Telefon"], ["website", "Website"],
  ["street", "Straße"], ["zip", "PLZ"], ["city", "Stadt"], ["country", "Land"],
  ["grade", "Grade"],
];

async function openLead(id) {
  const lead = await api("/api/leads/" + id);
  const panel = $("#drawer-panel");
  const today = todayStr();
  const overdue = lead.next_action_date && lead.next_action_date < today;

  panel.innerHTML = `
    <div class="drawer-head">
      <div class="dh-top">
        <h2>${esc(lead.company_name) || "Lead"}</h2>
        <div class="row" style="gap:6px">
          <button class="btn sm" id="lead-coach">📞 Coach</button>
          <button class="btn sm" id="lead-call-import">📋 Call einlesen</button>
          <button class="btn sm" id="lead-edit">✏️ Bearbeiten</button>
        </div>
      </div>
      <div class="muted">${esc(lead.contact_name) || ""} ${lead.city ? "· " + esc(lead.city) : ""}</div>
      <div class="stage-pills">
        ${State.stages.map((s) => `<span class="stage-pill ${s.key === lead.stage ? "active" : ""}" data-stage="${s.key}">${esc(s.label)}</span>`).join("")}
      </div>
    </div>
    <div class="drawer-body">
      <div class="na-box ${overdue ? "od" : ""}">
        <div class="section-title" style="margin-top:0">📅 Nächster Schritt</div>
        ${lead.next_action_label ? `<div class="na-reco">Empfehlung KundenAgent: <strong>${esc(lead.next_action_label)}</strong></div>` : ""}
        <div class="row">
          <input type="date" id="na-date" value="${esc(lead.next_action_date) || ""}" />
          <button class="btn sm" data-na="${today}">Heute</button>
          <button class="btn sm" data-na="+3">+3 Tage</button>
          <button class="btn sm" data-na="+7">+1 Woche</button>
          ${lead.next_action_date ? `<button class="btn sm danger" data-na="clear">Entfernen</button>` : ""}
        </div>
        ${lead.next_action_date ? `<div class="muted" style="margin-top:6px">Aktuell: ${esc(lead.next_action_date)}${overdue ? " · <strong style='color:var(--danger)'>überfällig</strong>" : ""}</div>` : '<div class="muted" style="margin-top:6px">Keine Wiedervorlage gesetzt.</div>'}
      </div>

      <div id="lead-detail">${leadKvHtml(lead)}</div>

      <div class="section-title">Aktivität hinzufügen</div>
      <div class="field">
        <select id="act-type">
          <option value="note">📝 Notiz</option>
          <option value="call">📞 Anruf</option>
          <option value="email">✉️ E-Mail</option>
          <option value="meeting">🤝 Termin</option>
        </select>
        <textarea id="act-content" rows="2" placeholder="Was ist passiert? / Nächster Schritt…"></textarea>
        <button class="btn primary" id="act-add">Speichern</button>
      </div>

      <div class="section-title">Verlauf</div>
      <div class="timeline" id="timeline">${timelineHtml(lead.activities)}</div>

      <div class="row" style="margin-top:24px">
        <button class="btn danger" id="lead-del">Lead löschen</button>
      </div>
    </div>`;

  $("#drawer").classList.remove("hidden");

  const patch = async (json, msg) => {
    try { await api("/api/leads/" + id, { method: "PATCH", json }); if (msg) toast(msg); refreshDueBadge(); openLead(id); }
    catch (e) { toast(e.message, true); }
  };

  panel.querySelectorAll(".stage-pill").forEach((p) =>
    p.addEventListener("click", () => patch({ stage: p.dataset.stage }, "Phase → " + stageLabel(p.dataset.stage))));

  $("#na-date").addEventListener("change", (e) => patch({ next_action_date: e.target.value || "clear" }, "Wiedervorlage gesetzt"));
  panel.querySelectorAll("[data-na]").forEach((b) => b.addEventListener("click", () => {
    const v = b.dataset.na;
    const date = v === "clear" ? "clear" : (v.startsWith("+") ? addDays(parseInt(v.slice(1), 10)) : v);
    patch({ next_action_date: date }, v === "clear" ? "Wiedervorlage entfernt" : "Wiedervorlage: " + date);
  }));

  $("#lead-edit").addEventListener("click", () => openLeadEdit(id, lead));

  $("#lead-coach").addEventListener("click", async () => {
    const btn = $("#lead-coach");
    btn.disabled = true;
    btn.textContent = "⏳ …";
    try {
      await api(`/api/leads/${id}/coach`, { method: "POST" });
      btn.textContent = "✅ Kontext geladen";
      toast("ClouseAgent-Kontext gespeichert — jetzt start_coach.bat starten!");
    } catch (e) {
      btn.textContent = "📞 Coach";
      toast("Fehler: " + e.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  $("#lead-call-import").addEventListener("click", async () => {
    const btn = $("#lead-call-import");
    btn.disabled = true; btn.textContent = "⏳ …";
    try {
      const r = await api("/api/import-call-summary", { method: "POST" });
      toast(`✅ Call eingelesen (${r.turns} Turns) — Timeline aktualisiert`);
      openLead(id);
    } catch (e) {
      toast(e.message, true);
      btn.disabled = false; btn.textContent = "📋 Call einlesen";
    }
  });

  $("#act-add").addEventListener("click", async () => {
    const content = $("#act-content").value.trim();
    if (!content) return;
    await api(`/api/leads/${id}/activities`, { method: "POST", json: { type: $("#act-type").value, content } });
    openLead(id);
    toast("Aktivität gespeichert");
  });
  $("#lead-del").addEventListener("click", async () => {
    if (!confirm("Diesen Lead löschen?")) return;
    await api("/api/leads/" + id, { method: "DELETE" });
    closeDrawer();
    toast("Lead gelöscht");
    refreshDueBadge();
    render();
  });
}

function leadKvHtml(lead) {
  const fields = [
    ["Firma", lead.company_name], ["Kontakt", lead.contact_name], ["Rolle", lead.role],
    ["E-Mail", lead.email && `<a href="mailto:${esc(lead.email)}">${esc(lead.email)}</a>`],
    ["Telefon", lead.phone && `<a href="tel:${esc(lead.phone)}">${esc(lead.phone)}</a>`],
    ["Website", lead.website && `<a href="${esc(lead.website)}" target="_blank" rel="noopener">${esc(lead.website)}</a>`],
    ["Straße", lead.street], ["PLZ / Ort", [lead.zip, lead.city].filter(Boolean).join(" ")],
    ["Land", lead.country], ["Branche", lead.industry],
    ["Score", lead.score != null ? Math.round(lead.score) : null], ["Grade", lead.grade],
    ["Quelle", lead.source], ["Importiert", (lead.imported_at || "").slice(0, 16).replace("T", " ")],
  ].filter(([, v]) => v);
  return `<div class="section-title" style="margin-top:0">Stammdaten</div>
    <dl class="kv">${fields.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

function openLeadEdit(id, lead) {
  const box = $("#lead-detail");
  box.innerHTML = `<div class="section-title" style="margin-top:0">Stammdaten bearbeiten</div>
    <div class="edit-grid">
      ${EDIT_FIELDS.map(([k, label]) =>
        `<label class="ef"><span>${esc(label)}</span><input data-ef="${k}" value="${esc(lead[k]) || ""}" /></label>`).join("")}
    </div>
    <div class="row" style="margin-top:10px">
      <button class="btn primary" id="ef-save">Speichern</button>
      <button class="btn" id="ef-cancel">Abbrechen</button>
    </div>`;
  $("#ef-cancel").addEventListener("click", () => { box.innerHTML = leadKvHtml(lead); });
  $("#ef-save").addEventListener("click", async () => {
    const json = {};
    box.querySelectorAll("[data-ef]").forEach((inp) => {
      const k = inp.dataset.ef, v = inp.value.trim(), old = lead[k] || "";
      if (v !== old) json[k] = v === "" ? "clear" : v;   // leer = Feld leeren
    });
    if (!Object.keys(json).length) { box.innerHTML = leadKvHtml(lead); return; }
    try {
      await api("/api/leads/" + id, { method: "PATCH", json });
      toast("Lead aktualisiert");
      openLead(id);
    } catch (e) { toast(e.message, true); }
  });
}

function timelineHtml(acts) {
  if (!acts || !acts.length) return '<div class="muted">Noch keine Aktivität.</div>';
  const icon = { note: "📝", call: "📞", email: "✉️", meeting: "🤝", stage_change: "🔄", followup: "📅" };
  return acts.map((a) => `
    <div class="tl-item type-${a.type}">
      <div class="tl-dot"></div>
      <div class="tl-content">
        <div>${icon[a.type] || "•"} ${esc(a.content)}</div>
        <div class="t-meta">${(a.created_at || "").slice(0, 16).replace("T", " ")}</div>
      </div>
    </div>`).join("");
}

function closeDrawer() { $("#drawer").classList.add("hidden"); }

/* ---------- Login ---------- */
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  State.token = $("#token-input").value.trim();
  localStorage.setItem("crm_token", State.token);
  try {
    await api("/api/projects"); // Token testen
    boot();
  } catch (_) { /* showLogin schon ausgelöst */ }
});

boot();
