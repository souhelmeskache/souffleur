/* Coderain SPA — library / play / characters / settings */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const view = $("#view");
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

/* ST-06: light, safe markdown for narrator prose — **bold**, *italic*, and
   "quoted dialogue" coloured. Escapes first, so no HTML injection. */
function renderProse(text) {
  let h = esc(text);
  h = h.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  h = h.replace(/(^|[^_\w])_([^_\n]+)_(?![_\w])/g, "$1<em>$2</em>");
  h = h.replace(/&quot;([\s\S]*?)&quot;/g,
                '<span class="say">&quot;$1&quot;</span>');
  return h;
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...opts,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_e) { /* text */ }
    throw new Error(msg);
  }
  return r.json();
}

/* POST + read an SSE body (fetch streaming — EventSource can't POST). */
async function sse(path, body, on) {
  const r = await fetch(path, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok || !r.body) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_e) { /* text */ }
    throw new Error(msg);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    buf += dec.decode(value, {stream: true});
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        let msg;
        try { msg = JSON.parse(line.slice(6)); } catch (_e) { continue; }
        (on[msg.t] || (() => {}))(msg);
      }
    }
  }
}

/* ---------- modal ---------- */
const modalRoot = $("#modal-root"), modalCard = $("#modal-card");
function openModal(html) {
  modalCard.innerHTML = html;
  modalRoot.classList.remove("hidden");
}
function closeModal() { modalRoot.classList.add("hidden"); }
$("#modal-back").addEventListener("click", closeModal);

/* ---------- router ---------- */
$("#brand").addEventListener("click", () => { location.hash = "#library"; });
window.addEventListener("hashchange", render);

function navMark() {
  const h = location.hash || "#library";
  document.querySelectorAll("#topbar nav a").forEach(a =>
    a.classList.toggle("active", a.getAttribute("href") === h));
}

// A slug segment is only real if it's a non-empty value that isn't a stray
// JS "undefined"/"null" — those slip in from a stale browser hash (e.g. an old
// #play/undefined left over from a prior session) and must not 404 the app.
const validSlug = seg => seg && seg !== "undefined" && seg !== "null";

async function render() {
  navMark();
  // The Talk drawer lives on <body> (not #view), so drop it on any navigation —
  // otherwise it orphans, floating over the next page with a stale slug handler.
  const td = document.getElementById("talk-drawer");
  if (td) td.remove();
  const h = location.hash || "#library";
  // A garbage per-item route → bounce home instead of a cryptic "no such save".
  for (const [pfx, n] of [["#play/", 6], ["#world/", 7], ["#edit/", 6]]) {
    if (h.startsWith(pfx) && !validSlug(decodeURIComponent(h.slice(n)))) {
      location.hash = "#library";
      return;                          // hashchange re-runs render() for #library
    }
  }
  try {
    if (h.startsWith("#play/")) await renderPlay(h.slice(6));
    else if (h.startsWith("#world/")) await renderBuilder(h.slice(7), "scenario");
    else if (h.startsWith("#edit/")) await renderBuilder(h.slice(6), "save");
    else if (h === "#combat") { view.innerHTML = ""; renderCombatView(view); }
    else if (h === "#characters") await renderCharacters();
    else if (h === "#defaults") await renderDefaults();
    else if (h === "#settings") await renderSettings();
    else await renderLibrary();
  } catch (e) {
    // A missing item (deleted save, dead bookmark) shouldn't read as a crash —
    // offer a way back rather than a dead end.
    const gone = /no such (save|scenario)/i.test(e.message || "");
    view.innerHTML = `<div class="page">
      <h1>${gone ? "Not found" : "Something broke"}</h1>
      <p class="muted">${esc(e.message)}</p>
      <button class="primary" onclick="location.hash='#library'"
        >← Back to Library</button></div>`;
  }
}

/* ---------- library ---------- */
async function renderLibrary() {
  const data = await api("/api/saves");
  const cards = data.saves.map(s => `
    <div class="card" data-slug="${esc(s.slug)}">
      <div class="title">${esc(s.title)}</div>
      <div class="meta">
        <span class="chip ${s.rpg_enabled || s.mode === "rpg" ? "rpg" : ""}">
          ${esc(s.mode || (s.rpg_enabled ? "rpg" : "simple"))}</span>
        ${s.scenario ? `<span>${esc(s.scenario)}</span>` : ""}
      </div>
      <div class="actions">
        <button data-act="open">Open</button>
        <button data-act="branch">Branch…</button>
        <button data-act="export">Export</button>
        <button data-act="delete" class="danger">Delete</button>
      </div>
    </div>`).join("");
  const worlds = data.scenarios.map(s => `
    <div class="card" data-scen="${esc(s.slug)}">
      <div class="title">${esc(s.title)}</div>
      <div class="muted">${esc(s.description || "")}</div>
      <div class="actions">
        <button data-act="play">Play</button>
        <button data-act="edit-scen">Edit</button>
        <button data-act="export-scen">Export</button>
        <button data-act="delete-scen" class="danger">Delete</button>
      </div>
    </div>`).join("");

  view.innerHTML = `<div class="page">
    <div class="page-head">
      <h1>Your stories</h1>
      <button id="import-save">Import…</button>
      <button class="primary" id="new-save">+ New story</button>
    </div>
    <div class="cards">${cards ||
      '<p class="muted">No stories yet — start one.</p>'}</div>
    <div class="page-head" style="margin-top:34px">
      <h1>Worlds</h1>
      <button id="import-card" title="import a SillyTavern / Tavern character card">Import card…</button>
      <button id="import-world">Import…</button>
      <button id="new-world">+ New world</button>
    </div>
    <p class="muted">A world is a reusable scenario: name, premise, and an
    introduction — the first message every story in it opens with. Open the
    builder to write every detail yourself, seed sections from an idea, or
    let the AI generate the rest.</p>
    <div class="cards">${worlds ||
      '<p class="muted">No worlds yet — build one.</p>'}</div>
  </div>`;

  $("#new-save").addEventListener("click", () => newSaveModal(data));
  $("#new-world").addEventListener("click", async () => {
    const out = await api("/api/scenarios",
                          {method: "POST", body: {title: "Untitled World"}});
    location.hash = `#world/${out.slug}`;
  });
  $("#import-save").addEventListener("click", () =>
    uploadFile("/api/saves-import", ".zip", () => render()));
  $("#import-world").addEventListener("click", () =>
    uploadFile("/api/scenarios-import", ".zip", () => render()));
  $("#import-card").addEventListener("click", () =>
    uploadFile("/api/cards-import", ".png,.json,.charx", out => {
      const c = out.counts || {};
      alert(`Imported "${out.slug}" — ${c.lore || 0} lore entr`
            + `${(c.lore || 0) === 1 ? "y" : "ies"} + the character. `
            + "Opening the builder to review.");
      location.hash = `#world/${out.slug}`;
    }));
  view.querySelectorAll(".card[data-scen]").forEach(card => {
    const scen = card.dataset.scen;
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      if (act === "delete-scen") {
        ev.stopPropagation();
        if (!confirm("Delete this world? Existing stories keep their copy."))
          return;
        await api(`/api/scenarios/${scen}`, {method: "DELETE"});
        render();
      } else if (act === "edit-scen") {
        ev.stopPropagation();
        location.hash = `#world/${scen}`;
      } else if (act === "export-scen") {
        ev.stopPropagation();
        window.location.href = `/api/scenarios/${scen}/export`;
      } else {
        newSaveModal(data, scen);
      }
    });
  });
  // Save cards ONLY — [data-slug] excludes world cards (which carry data-scen).
  // Without the filter a world card gets BOTH handlers, and this one's `else`
  // branch navigates to #play/undefined (its slug is undefined) — the "no such
  // save: undefined" crash when deleting a world.
  view.querySelectorAll(".card[data-slug]").forEach(card => {
    const slug = card.dataset.slug;
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      if (act === "delete") {
        ev.stopPropagation();
        if (!confirm("Delete this save for good?")) return;
        await api(`/api/saves/${slug}`, {method: "DELETE"});
        render();
      } else if (act === "branch") {
        ev.stopPropagation();
        const info = await api(`/api/saves/${slug}`);
        const n = prompt(`Branch from turn (1..${info.turns.length}):`);
        if (!n) return;
        const out = await api(`/api/saves/${slug}/branch`,
                              {method: "POST", body: {turn: Number(n)}});
        if (out.warnings && out.warnings.length) alert(out.warnings.join("\n"));
        location.hash = `#play/${out.slug}`;
      } else if (act === "export") {
        ev.stopPropagation();
        window.location.href = `/api/saves/${slug}/export`;
      } else {
        location.hash = `#play/${slug}`;
      }
    });
  });
}

function newSaveModal(data, preselect) {
  const scen = data.scenarios.map(s =>
    `<option value="${esc(s.slug)}" ${s.slug === preselect ? "selected" : ""}>
     ${esc(s.title)}</option>`).join("");
  openModal(`
    <h1>New story</h1>
    <label>Name</label><input id="ns-title" placeholder="My adventure">
    <label>World</label>
    <select id="ns-scenario">
      <option value="">(blank world — write a premise)</option>${scen}
    </select>
    <div id="ns-premise-wrap">
      <label>Premise</label>
      <textarea id="ns-premise" rows="3"
        placeholder="A dark-fantasy default is used when left empty."></textarea>
    </div>
    <label>Story mode</label>
    <div class="seg" id="ns-mode">
      <button data-v="simple" class="on">Simple</button>
      <button data-v="rpg">RPG campaign</button>
    </div>
    <label>Play as</label>
    <select id="ns-char"></select>
    <details class="howto" style="margin-top:14px">
      <summary>Starting day &amp; time (optional)</summary>
      <p class="muted">Not every story begins on Day 1 at dawn. Set where the
      in-world clock starts; the calendar label is free text for a fictional
      date the AI will honour.</p>
      <div class="row">
        <div><label>Day #</label>
          <input id="ns-day" type="number" min="1" value="1"></div>
        <div><label>Time of day</label>
          <input id="ns-phase" list="phases" value="morning"></div>
      </div>
      <datalist id="phases">
        <option>dawn</option><option>morning</option><option>midday</option>
        <option>afternoon</option><option>evening</option><option>dusk</option>
        <option>night</option><option>midnight</option>
      </datalist>
      <label>Calendar / date (fictional, optional)</label>
      <input id="ns-cal" placeholder="e.g. 3rd of Frostmoon, Year 812">
    </details>
    <div class="modal-actions">
      <button id="ns-cancel">Cancel</button>
      <button class="primary" id="ns-go">Begin</button>
    </div>`);
  let mode = "simple";
  // The offer depends on the world: a scenario offers ITS playable
  // characters (user-added or AI-generated); a blank world falls back to
  // your library's playable sheets.
  const fillPlayAs = async () => {
    const sel = $("#ns-char");
    const scenSlug = $("#ns-scenario").value;
    let opts = "";
    if (scenSlug) {
      try {
        const out = await api(`/api/scenarios/${scenSlug}/playable`);
        opts = out.playable.map(p =>
          `<option value="p:${esc(p.slug)}">${esc(p.title)}</option>`).join("");
      } catch (_e) { /* world without characters */ }
    } else {
      opts = data.characters.filter(c => (c.kind || "playable") === "playable")
        .map(c => `<option value="c:${esc(c.id)}">${esc(c.name)}</option>`)
        .join("");
    }
    sel.innerHTML = '<option value="">(let the story decide)</option>' + opts;
  };
  $("#ns-mode").addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    mode = ev.target.dataset.v;
    $("#ns-mode").querySelectorAll("button").forEach(b =>
      b.classList.toggle("on", b.dataset.v === mode));
  });
  $("#ns-premise-wrap").classList.toggle("hidden", Boolean(preselect));
  $("#ns-scenario").addEventListener("change", () => {
    $("#ns-premise-wrap").classList.toggle(
      "hidden", Boolean($("#ns-scenario").value));
    fillPlayAs();
  });
  fillPlayAs();
  $("#ns-cancel").addEventListener("click", closeModal);
  $("#ns-go").addEventListener("click", async () => {
    const pick = $("#ns-char").value;
    const out = await api("/api/saves", {method: "POST", body: {
      title: $("#ns-title").value.trim() || "Untitled",
      scenario: $("#ns-scenario").value,
      premise: $("#ns-premise").value.trim(),
      mode,
      character: pick.startsWith("c:") ? pick.slice(2) : "",
      playable: pick.startsWith("p:") ? pick.slice(2) : "",
      start_time: {
        day: Number($("#ns-day").value) || 1,
        phase: $("#ns-phase").value.trim(),
        note: $("#ns-cal").value.trim(),
      },
    }});
    closeModal();
    location.hash = `#play/${out.slug}`;
  });
}

/* ---------- user defaults (own nav page) ---------- */
async function renderDefaults() {
  view.innerHTML = `<div class="page">
    <div class="page-head">
      <h1>User defaults</h1>
      <button id="defaults-import">Import…</button>
      <button class="primary" id="defaults-export">Export</button>
    </div>
    <p class="muted">Your own starting templates — every NEW world and story is
    seeded from these instead of the shipped ones. Edit one to make it yours,
    or revert to the version the app ships with at any time.</p>
    <div class="cards" id="defaults-cards"><p class="muted">loading…</p></div>
  </div>`;
  $("#defaults-export").addEventListener("click", () => {
    window.location.href = "/api/defaults-export";
  });
  $("#defaults-import").addEventListener("click", () =>
    uploadFile("/api/defaults-import", ".zip", () => {
      alert("Defaults imported.");
      loadDefaultsSection();
    }));
  loadDefaultsSection();
}

/* Shared file-picker → POST multipart upload → callback. Used by every Import
   button (defaults, saves, worlds). */
function uploadFile(url, accept, done) {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = accept;
  inp.addEventListener("change", async () => {
    const f = inp.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await fetch(url, {method: "POST", body: fd});
      if (!r.ok) {
        let msg = r.statusText;
        try { msg = (await r.json()).detail || msg; } catch (_e) { /**/ }
        throw new Error(msg);
      }
      done(await r.json());
    } catch (e) { alert("Import failed: " + e.message); }
  });
  inp.click();
}

/* ---------- user defaults cards ---------- */
async function loadDefaultsSection() {
  const holder = $("#defaults-cards");
  if (!holder) return;
  const data = await api("/api/defaults");
  holder.innerHTML = data.defaults.map(d => `
    <div class="card" data-def="${esc(d.name)}">
      <div class="title" style="font-size:14px">${esc(d.name)}</div>
      <div class="meta">
        <span class="chip">${esc(d.kind)}</span>
        ${d.customized ? '<span class="chip rpg">customized</span>' : ""}
      </div>
      <div class="actions">
        <button data-act="edit-def">Edit</button>
        <button data-act="revert-def" class="danger"
          ${d.customized ? "" : "disabled"}>Revert to shipped</button>
      </div>
    </div>`).join("");
  holder.querySelectorAll(".card[data-def]").forEach(card => {
    const name = card.dataset.def;
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      if (act === "revert-def") {
        ev.stopPropagation();
        if (!confirm(`Revert ${name} to the shipped default?`)) return;
        await api(`/api/defaults/${name}/revert`, {method: "POST"});
        loadDefaultsSection();
      } else {
        const d = await api(`/api/defaults/${name}`);
        openModal(`
          <h1>${esc(name)}</h1>
          <p class="muted">Seeds every NEW world/story. Existing ones keep
          their copies.</p>
          <textarea id="def-text" rows="18"
            style="font-family:var(--mono);font-size:12px">${esc(d.text)}</textarea>
          <div class="modal-actions">
            <button id="def-cancel">Cancel</button>
            <button class="primary" id="def-save">Save</button>
          </div>`);
        $("#def-cancel").addEventListener("click", closeModal);
        $("#def-save").addEventListener("click", async () => {
          await api(`/api/defaults/${name}`, {
            method: "PUT", body: {text: $("#def-text").value}});
          closeModal();
          loadDefaultsSection();
        });
      }
    });
  });
}

/* ---------- world builder (#world/<slug>) ---------- */
const PIECE_LABELS = {
  "characters.md": "Characters", "locations.md": "Locations",
  "items.md": "Items", "factions.md": "Factions", "threads.md": "Threads",
  "events.md": "Events (when X, then Y)",
};
const PIECE_KIND = rel => {
  const base = rel.replace(".md", "");
  return {"characters": "character", "locations": "location",
          "items": "item", "factions": "faction", "threads": "thread",
          "events": "event"}[base] || base;
};
const KIND_REL = kind => ({
  character: "characters.md", location: "locations.md", item: "items.md",
  faction: "factions.md", thread: "threads.md", event: "events.md",
}[kind] || kind + ".md");

async function renderBuilder(slug, scope = "scenario") {
  const isSave = scope === "save";
  const base = isSave ? `/api/saves/${slug}/world` : `/api/scenarios/${slug}`;
  const backHash = isSave ? `#play/${slug}` : "#library";
  const w = await api(`${base}/full`);
  const field = (id, label, rows, val, ph) => `
    <div class="setting-panel">
      <div class="field-head">
        <h2 style="margin:0">${label}</h2>
        <span style="flex:1"></span>
        <button class="mini" data-seed="${id}">✨ Seed from idea</button>
        <button class="mini" data-improve="${id}">Improve with AI</button>
      </div>
      <textarea id="${id}" rows="${rows}"
        placeholder="${esc(ph)}">${esc(val)}</textarea>
    </div>`;

  const groups = Object.keys(w.pieces).map(rel => `
    <div class="setting-panel" data-group="${esc(rel)}">
      <div class="field-head">
        <h2 style="margin:0">${esc(PIECE_LABELS[rel] ||
          rel.replace(".md", "").replace(/-/g, " "))}
          <span class="muted">(${w.pieces[rel].length})</span></h2>
        <span style="flex:1"></span>
        <button class="mini" data-fromlib="${esc(rel)}">From library…</button>
        <button class="mini" data-exportsec="${esc(rel)}">Export</button>
        ${PIECE_LABELS[rel] ? "" :
          `<button class="mini danger" data-deltype="${esc(rel)}">Remove type</button>`}
        <button class="mini" data-newpiece="${esc(rel)}">+ New</button>
      </div>
      <div class="piece-row">${w.pieces[rel].map(p => `
        <button class="piece-chip" data-piece="${esc(rel)}|${esc(p.slug)}">
          ${esc(p.title)}${p.attrs && p.attrs.playable ? " ★" : ""}
          ${p.attrs && p.attrs.hidden === "true" ? " 🕯" : ""}
        </button>`).join("") ||
        '<span class="muted">none yet</span>'}</div>
    </div>
    ${rel === "characters.md" ? `<div style="margin:-6px 0 14px">
      <button class="mini" id="b-addtype">+ Add lore type…</button>
    </div>` : ""}`).join("");

  view.innerHTML = `<div class="page" id="builder">
    <div class="page-head">
      <button id="back">${isSave ? "← Story" : "← Library"}</button>
      <h1 style="margin:0">${isSave ? "Edit this story" : "World builder"}</h1>
      <span style="flex:1"></span>
      <label style="display:flex;align-items:center;gap:6px;margin:0;
                    text-transform:none;font-size:13px">
        <input type="checkbox" id="b-improve" style="width:auto">
        Use prompt improver on seeds
      </label>
      <button class="primary" id="b-save">${isSave ? "Save changes"
        : "Save world"}</button>
    </div>
    ${isSave ? `<p class="muted">These are THIS story's own live files — edits
      apply from your next turn. They started as copies of the world and have
      been evolving as you play.</p>` : ""}
    <div class="setting-panel">
      <h2 style="margin-top:0">Main details</h2>
      <div class="row">
        <div><label>Name</label><input id="b-title" value="${esc(w.title)}"></div>
        ${isSave ? "" : `<div><label>Description (card blurb)</label>
          <input id="b-desc" value="${esc(w.description)}"></div>`}
      </div>
    </div>
    ${field("b-premise", "Premise", 5, w.premise,
            isSave ? "The situation this story is set in (always in context)."
                   : "The situation every story in this world drops into.")}
    ${isSave ? "" : field("b-intro",
            "Introduction — the first message of every story", 6,
            w.introduction,
            "Second person, present tense. Blank = improvised per story.")}
    ${field("b-world", "World details", 8, w.world,
            "History, geography, factions, magic/technology, tone.")}
    ${groups}
    ${isSave ? "" : `<div class="setting-panel">
      <div class="field-head">
        <h2 style="margin:0">Generate the rest with AI</h2>
      </div>
      <p class="muted">Fills only what's empty (premise, introduction, world
      details, and lore groups up to the counts below). Everything you wrote
      is kept and new pieces are written to fit it.</p>
      <div class="row">
        <div><label>Type</label><input id="b-type" placeholder="optional"></div>
        <div><label>Tone</label><input id="b-tone" placeholder="optional"></div>
      </div>
      <div class="row">
        <div><label>NPCs</label>
          <input id="b-npcs" type="number" min="0" max="20" value="5"></div>
        <div><label>Locations</label>
          <input id="b-locs" type="number" min="0" max="20" value="5"></div>
        <div><label>Items</label>
          <input id="b-items" type="number" min="0" max="20" value="5"></div>
      </div>
      <pre class="table hidden" id="b-log"></pre>
      <div class="modal-actions" style="justify-content:flex-start">
        <button class="primary" id="b-complete">Generate the rest</button>
      </div>
    </div>`}
  </div>`;

  const saveMain = async () => api(`${base}/main`, {
    method: "PUT", body: {
      title: $("#b-title").value.trim(),
      description: $("#b-desc") ? $("#b-desc").value.trim() : "",
      premise: $("#b-premise").value.trim(),
      ...($("#b-intro") ? {introduction: $("#b-intro").value.trim()} : {}),
      world: $("#b-world").value.trim(),
    }});
  $("#back").addEventListener("click", async () => {
    await saveMain();
    location.hash = backHash;
  });
  $("#b-save").addEventListener("click", async () => {
    await saveMain();
    const label = isSave ? "Save changes" : "Save world";
    $("#b-save").textContent = "Saved ✓";
    setTimeout(() => { $("#b-save").textContent = label; }, 1500);
  });

  const FIELD_KIND = {"b-premise": "premise", "b-intro": "introduction",
                      "b-world": "world"};
  const assist = async (id, mode) => {
    const ta = $("#" + id);
    let text = ta.value.trim();
    if (mode === "seed") {
      text = prompt("Your idea in a line (blank = let the AI decide):",
                    "") ?? null;
      if (text === null) return;
    } else if (!text) {
      alert("Nothing to improve yet — write something or seed it first.");
      return;
    }
    ta.disabled = true;
    const old = ta.value;
    ta.value = mode === "seed" ? "✨ generating…" : "✨ improving…";
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind: FIELD_KIND[id], mode, text, scenario: slug,
        improve: $("#b-improve").checked,
      }});
      ta.value = out.text;
    } catch (e) {
      ta.value = old;
      alert(e.message);
    }
    ta.disabled = false;
  };
  view.querySelectorAll("[data-seed]").forEach(b => b.addEventListener(
    "click", () => assist(b.dataset.seed, "seed")));
  view.querySelectorAll("[data-improve]").forEach(b => b.addEventListener(
    "click", () => assist(b.dataset.improve, "improve")));

  view.querySelectorAll("[data-newpiece]").forEach(b => b.addEventListener(
    "click", () => pieceModal(slug, b.dataset.newpiece, null, null, base)));
  view.querySelectorAll("[data-piece]").forEach(b => b.addEventListener(
    "click", () => {
      const [rel, pslug] = b.dataset.piece.split("|");
      const p = w.pieces[rel].find(x => x.slug === pslug);
      pieceModal(slug, rel, p, null, base);
    }));

  view.querySelectorAll("[data-fromlib]").forEach(b => b.addEventListener(
    "click", async () => {
      const rel = b.dataset.fromlib;
      const isChar = rel === "characters.md";
      let items;
      if (isChar) {
        const data = await api("/api/characters");
        items = data.characters.map(c => ({
          id: c.id, title: c.name, tag: c.kind || "playable",
          blurb: c.description || ""}));
      } else {
        const data = await api(`/api/library?type=${PIECE_KIND(rel)}`);
        items = data.pieces.map(p => ({
          id: p.id, title: p.entry.title, tag: "",
          blurb: p.entry.body || ""}));
      }
      if (!items.length) {
        alert("Nothing of this type in your library yet — save a piece to "
              + "it first (piece editor → 'Save to library').");
        return;
      }
      openModal(`
        <h1>From your library</h1>
        <div class="cards">${items.map(it => `
          <div class="card" data-lib="${esc(it.id)}">
            <div class="title">${esc(it.title)}</div>
            ${it.tag ? `<div class="meta"><span class="chip ${
              it.tag === "playable" ? "rpg" : ""}">${esc(it.tag)}</span></div>`
              : ""}
            <div class="muted">${esc(it.blurb.slice(0, 90))}</div>
          </div>`).join("")}</div>
        <div class="modal-actions"><button id="lib-cancel">Cancel</button></div>`);
      $("#lib-cancel").addEventListener("click", closeModal);
      modalCard.querySelectorAll("[data-lib]").forEach(card =>
        card.addEventListener("click", async () => {
          await api(isChar ? `${base}/from-library`
                           : `${base}/from-piece-library`,
                    {method: "POST", body: {id: card.dataset.lib}});
          closeModal();
          await saveMain();
          render();
        }));
    }));

  view.querySelectorAll("[data-exportsec]").forEach(b => b.addEventListener(
    "click", () => {
      window.location.href =
        `${base}/pieces/${b.dataset.exportsec}/export`;
    }));

  view.querySelectorAll("[data-deltype]").forEach(b => b.addEventListener(
    "click", async () => {
      const rel = b.dataset.deltype;
      if (!confirm(`Remove the '${rel.replace(".md", "")}' lore type? Its `
                   + "pieces are deleted with it.")) return;
      await saveMain();
      await api(`${base}/types/${rel}`, {method: "DELETE"});
      render();
    }));

  $("#b-addtype").addEventListener("click", async () => {
    const name = prompt("Name for the new lore type (e.g. Races, Rules):");
    if (!name) return;
    try {
      await api(`${base}/types`, {method: "POST", body: {name}});
      await saveMain();
      render();
    } catch (e) { alert(e.message); }
  });

  const completeBtn = $("#b-complete");
  if (completeBtn) completeBtn.addEventListener("click", async () => {
    await saveMain();
    const log = $("#b-log");
    log.classList.remove("hidden");
    log.textContent = "starting…\n";
    $("#b-complete").disabled = true;
    try {
      await sse(`/api/scenarios/${slug}/complete`, {
        type: $("#b-type").value.trim(),
        tone: $("#b-tone").value.trim(),
        improve: $("#b-improve").checked,
        n_npcs: Number($("#b-npcs").value),
        n_locations: Number($("#b-locs").value),
        n_items: Number($("#b-items").value),
      }, {
        stage: m => { log.textContent += "· " + m.text + "\n";
                      log.scrollTop = log.scrollHeight; },
        done: m => { log.textContent += "✓ done\n"
                       + (m.events || []).map(x => "! " + x + "\n").join(""); },
        error: m => { log.textContent += "error: " + m.text + "\n"; },
      });
      setTimeout(render, 1200);
    } catch (e) {
      log.textContent += "error: " + e.message + "\n";
      $("#b-complete").disabled = false;
    }
  });
}

/* piece editor modal — shared by the builder (writes to the world) and the
   Library page (lib = {id, type}: writes to /api/library instead) */
function pieceModal(slug, rel, piece, lib = null, base = null) {
  base = base || `/api/scenarios/${slug}`;
  const kind = PIECE_KIND(rel);
  const a = (piece && piece.attrs) || {};
  const isChar = rel === "characters.md";
  const isEvent = rel === "events.md";
  const isItem = rel === "items.md";
  const isThread = rel === "threads.md";
  const check = (id, label, on) => `
    <label style="display:flex;align-items:center;gap:6px;text-transform:none">
      <input type="checkbox" id="${id}" style="width:auto" ${on ? "checked" : ""}>
      ${label}</label>`;
  openModal(`
    <h1>${piece ? "Edit" : "New"} ${esc(kind)}</h1>
    <div class="row" style="align-items:flex-end">
      <div style="flex:2"><label>Title</label>
        <input id="p-title" value="${esc(piece ? piece.title : "")}"></div>
      <div><button class="mini" id="p-seed" style="width:100%">✨ Seed from idea</button></div>
      <div><button class="mini" id="p-improve" style="width:100%"
        ${piece ? "" : "disabled"}>Improve with AI</button></div>
    </div>
    <div class="row">
      <div><label>Importance 1-5</label>
        <input id="p-imp" type="number" min="1" max="5"
          value="${esc(piece ? piece.importance : 3)}"></div>
      <div><label>Weight</label>
        <select id="p-weight">${["", "minor", "supplementary", "standard",
          "important", "critical"].map(v => `<option ${v === (a.weight || "")
          ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div><label>Aliases (comma)</label>
        <input id="p-aliases" value="${esc((piece && piece.aliases || []).join(", "))}"></div>
    </div>
    <label>Triggers (extra activation keywords, comma)</label>
    <input id="p-triggers" value="${esc(a.triggers || "")}">
    <div class="row">
      ${check("p-pinned", "Pinned (always in context)", a.pinned === "true")}
      ${check("p-hidden", "Hidden (secret lore)", a.hidden === "true")}
      ${isChar ? check("p-playable", "Playable ★", a.playable === "true") : ""}
      ${isEvent ? check("p-once", "Fires once", a.once === "true") : ""}
    </div>
    ${isChar ? `<div class="row">
      <div><label>Stats ("strength 3, agility 2")</label>
        <input id="p-stats" value="${esc(a.stats || "")}"></div>
      <div><label>Skills ("name (stat), …")</label>
        <input id="p-skills" value="${esc(a.skills || "")}"></div>
    </div>` : ""}
    ${isItem ? `<label>Rarity</label>
      <select id="p-rarity">${["", "common", "uncommon", "rare", "epic",
        "legendary"].map(v => `<option ${v === (a.rarity || "") ? "selected"
        : ""}>${v}</option>`).join("")}</select>` : ""}
    ${isThread ? `<label>Objectives (semicolon-separated)</label>
      <input id="p-objectives" value="${esc(a.objectives || "")}">` : ""}
    <label>Content</label>
    <textarea id="p-body" rows="8">${esc(piece ? piece.body : "")}</textarea>
    <div class="modal-actions">
      ${lib ? "" : '<button id="p-tolib">Save to library</button>'}
      ${piece && (!lib || lib.id)
        ? '<button id="p-delete" class="danger">Delete</button>' : ""}
      <span style="flex:1"></span>
      <button id="p-cancel">Cancel</button>
      <button class="primary" id="p-save">Save piece</button>
    </div>`);

  const collect = () => {
    const attrs = {
      weight: $("#p-weight").value,
      triggers: $("#p-triggers").value.trim(),
      pinned: $("#p-pinned").checked ? "true" : "",
      hidden: $("#p-hidden").checked ? "true" : "",
    };
    // preserve attrs the form doesn't manage
    for (const [k, v] of Object.entries(a)) {
      if (!(k in attrs) && !["playable", "once", "stats", "skills", "rarity",
                             "objectives"].includes(k)) attrs[k] = v;
    }
    if (isChar) {
      attrs.playable = $("#p-playable").checked ? "true" : "";
      attrs.stats = $("#p-stats").value.trim();
      attrs.skills = $("#p-skills").value.trim();
    }
    if (isEvent) attrs.once = $("#p-once").checked ? "true" : "";
    if (isItem) attrs.rarity = $("#p-rarity").value;
    if (isThread) attrs.objectives = $("#p-objectives").value.trim();
    return {
      title: $("#p-title").value.trim(),
      slug: piece ? piece.slug : "",
      importance: Number($("#p-imp").value) || 3,
      aliases: $("#p-aliases").value.split(",").map(s => s.trim())
        .filter(Boolean),
      attrs,
      body: $("#p-body").value.trim(),
    };
  };
  const fill = entry => {
    $("#p-title").value = entry.title || "";
    $("#p-imp").value = entry.importance || 3;
    $("#p-aliases").value = (entry.aliases || []).join(", ");
    $("#p-body").value = entry.body || "";
    const ea = entry.attrs || {};
    $("#p-weight").value = ea.weight || "";
    $("#p-triggers").value = ea.triggers || "";
    $("#p-pinned").checked = ea.pinned === "true";
    $("#p-hidden").checked = ea.hidden === "true";
    if (isChar) {
      $("#p-playable").checked = ea.playable === "true";
      $("#p-stats").value = ea.stats || "";
      $("#p-skills").value = ea.skills || "";
    }
    if (isEvent) $("#p-once").checked = ea.once === "true";
    if (isItem) $("#p-rarity").value = ea.rarity || "";
    if (isThread) $("#p-objectives").value = ea.objectives || "";
  };

  $("#p-cancel").addEventListener("click", closeModal);
  $("#p-save").addEventListener("click", async () => {
    const entry = collect();
    if (!entry.title) { alert("A piece needs a title."); return; }
    if (lib) {
      await api("/api/library", {method: "POST", body: {
        type: lib.type, entry, id: lib.id || ""}});
    } else {
      await api(`${base}/pieces/${rel}`, {method: "PUT", body: {
        entry, old_slug: piece ? piece.slug : ""}});
    }
    closeModal();
    render();
  });
  const del = $("#p-delete");
  if (del) del.addEventListener("click", async () => {
    if (!confirm(`Delete '${piece.title}'?`)) return;
    if (lib) {
      await api(`/api/library/${lib.id}`, {method: "DELETE"});
    } else {
      await api(`${base}/pieces/${rel}/${piece.slug}`,
                {method: "DELETE"});
    }
    closeModal();
    render();
  });
  const tolib = $("#p-tolib");
  if (tolib) tolib.addEventListener("click", async () => {
    if (isChar) {
      await api("/api/characters/from-entry",
                {method: "POST", body: {entry: collect()}});
    } else {
      await api("/api/library",
                {method: "POST", body: {type: kind, entry: collect()}});
    }
    tolib.textContent = "Saved to library ✓";
  });

  $("#p-seed").addEventListener("click", async () => {
    const idea = prompt("Your idea in a line (blank = let the AI decide):", "");
    if (idea === null) return;
    $("#p-seed").disabled = true;
    $("#p-seed").textContent = "✨ generating…";
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind, mode: "seed", text: idea, scenario: slug,
        improve: Boolean($("#b-improve") && $("#b-improve").checked),
      }});
      fill(out.entry);
    } catch (e) { alert(e.message); }
    $("#p-seed").disabled = false;
    $("#p-seed").textContent = "✨ Seed from idea";
  });
  $("#p-improve").addEventListener("click", async () => {
    $("#p-improve").disabled = true;
    $("#p-improve").textContent = "✨ improving…";
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind, mode: "improve", text: JSON.stringify(collect()),
        scenario: slug,
      }});
      fill(out.entry);
    } catch (e) { alert(e.message); }
    $("#p-improve").disabled = false;
    $("#p-improve").textContent = "Improve with AI";
  });
}

/* ---------- play ---------- */
let busy = false;

async function renderPlay(slug) {
  const s = await api(`/api/saves/${slug}`);
  s.companions = s.companions || [];        // never deref undefined (play head + Talk)
  view.innerHTML = `<div id="play">
    <div id="story-col">
      <div id="play-head">
        <button id="back">← Library</button>
        <div class="title">${esc(s.title)}</div>
        <div class="clock">${esc(s.clock || "")}</div>
        <button id="edit-btn" title="edit this story's characters, lore &amp; world"
          >Edit</button>
        <button id="note-btn" title="author's note — steer tone &amp; pacing"
          >Note</button>
        <button id="talk-btn" ${s.companions.length ? "" : "disabled"}
          title="${s.companions.length ? "private companion chat"
                 : "no companions yet"}">Talk</button>
      </div>
      <div id="transcript"></div>
      <div id="stageline"></div>
      <div id="eventbar"></div>
      <div id="composer">
        <div id="play-actions">
          <button id="continue">Continue</button>
          <button id="undo">Undo</button>
          <button id="retry">Retry</button>
          <button id="branch">Branch…</button>
          <button id="aids-btn" title="quick actions &amp; output cleanup rules"
            >Aids</button>
        </div>
        <div id="quick-bar"></div>
        <div id="composer-inner">
          <button id="suggest" title="let the AI draft your next action">✍</button>
          <textarea id="action" placeholder="What do you do?"></textarea>
          <button class="primary" id="send">Send</button>
        </div>
      </div>
    </div>
    ${s.rpg ? '<aside id="sheet"></aside>' : ""}
  </div>`;

  const transcript = $("#transcript");
  const stage = $("#stageline");
  const evbar = $("#eventbar");
  let swipe = {count: 1, idx: 0};      // ST-02 state for the last narrator turn

  const bodyOf = d => d.querySelector(".turn-body");
  const paint = (d, text) => {         // set a turn's text (markdown for prose)
    d._raw = text;
    const b = bodyOf(d);
    if (d.classList.contains("narrator")) b.innerHTML = renderProse(text);
    else b.textContent = text;
  };
  const addTurn = (role, text) => {
    const d = document.createElement("div");
    d.className = `turn ${role}`;
    const body = document.createElement("span");
    body.className = "turn-body";
    d.appendChild(body);
    const pen = document.createElement("button");
    pen.className = "turn-edit"; pen.textContent = "✎"; pen.title = "edit";
    pen.addEventListener("click", () => startEdit(d));   // ST-03
    d.appendChild(pen);
    paint(d, text);
    transcript.appendChild(d);
    transcript.scrollTop = transcript.scrollHeight;
    return d;
  };
  const lastNarrator = () =>
    [...transcript.children].reverse().find(d =>
      d.classList.contains("narrator"));

  // ST-03: in-place message editor
  const startEdit = d => {
    if (busy || d.querySelector(".turn-editor")) return;
    const idx = [...transcript.children].indexOf(d);
    const body = bodyOf(d);
    const ta = document.createElement("textarea");
    ta.className = "turn-editor"; ta.value = d._raw ?? body.textContent;
    const bar = document.createElement("div");
    bar.className = "turn-editbar";
    bar.innerHTML = '<button class="mini primary sv">Save</button>'
                  + '<button class="mini cx">Cancel</button>';
    body.style.display = "none";
    d.append(ta, bar); ta.focus();
    const close = () => { ta.remove(); bar.remove(); body.style.display = ""; };
    bar.querySelector(".cx").onclick = close;
    bar.querySelector(".sv").onclick = async () => {
      const text = ta.value.trim();
      try {
        await api(`/api/saves/${slug}/turns/${idx}`,
                  {method: "PUT", body: {text}});
      } catch (e) { alert(e.message); return; }
      paint(d, text); close();
    };
  };

  // ST-02: swipe control on the last narrator turn
  const renderSwipeBar = () => {
    transcript.querySelectorAll(".swipebar").forEach(b => b.remove());
    const d = lastNarrator();
    if (!d) return;
    const bar = document.createElement("div");
    bar.className = "swipebar";
    bar.innerHTML =
      `<button class="mini swl" ${swipe.idx ? "" : "disabled"}>◄</button>`
      + `<span>${swipe.idx + 1}/${swipe.count}</span>`
      + `<button class="mini swr">►</button>`;
    d.appendChild(bar);
    bar.querySelector(".swl").onclick = () => swipeMove(-1);
    bar.querySelector(".swr").onclick = () => swipeMove(1);
  };
  let swiping = false;                  // serialize ◄/► so fast clicks can't race
  const swipeMove = async dir => {
    if (busy || swiping) return;
    swiping = true;
    try {
      if (dir < 0) {
        if (swipe.idx === 0) return;
        const out = await api(`/api/saves/${slug}/swipe`,
                              {method: "POST", body: {dir: -1}});
        paint(lastNarrator(), out.text); swipe = {count: out.count, idx: out.idx};
        renderSwipeBar();
      } else if (swipe.idx + 1 < swipe.count) {
        const out = await api(`/api/saves/${slug}/swipe`,
                              {method: "POST", body: {dir: 1}});
        paint(lastNarrator(), out.text); swipe = {count: out.count, idx: out.idx};
        renderSwipeBar();
      } else {
        await swipeGen();               // past the end → generate a new one
      }
    } finally { swiping = false; }
  };
  const swipeGen = async () => {
    const d = lastNarrator();
    if (!d || busy) return;
    setBusy(true); stage.textContent = "Thinking…";
    const body = bodyOf(d); body.textContent = ""; d.classList.add("pending");
    transcript.querySelectorAll(".swipebar").forEach(b => b.remove());
    try {
      await sse(`/api/saves/${slug}/swipe-gen`, undefined, {
        stage: m => { stage.textContent = m.text; },
        chunk: m => { d.classList.remove("pending"); body.textContent += m.text;
                      transcript.scrollTop = transcript.scrollHeight; },
        done: m => { setEvents(m.events); setSheet(m.sheet || []);
                     $(".clock").textContent = m.clock || "";
                     if (m.text != null) body._settle = m.text; stage.textContent = ""; },
        error: m => { stage.textContent = "error: " + m.text; },
      });
    } catch (e) { stage.textContent = "error: " + e.message; }
    d.classList.remove("pending");
    if (body._settle && body.textContent) body.textContent = body._settle;
    paint(d, body.textContent);
    swipe = {count: swipe.count + 1, idx: swipe.count};
    setBusy(false); renderSwipeBar();
  };
  const setSheet = lines => {
    const el = $("#sheet");
    if (el) el.innerHTML =
      '<div class="sheet-title">Character</div>' + esc(lines.join("\n"));
  };
  const setEvents = events => {
    evbar.innerHTML = (events || []).map(e =>
      `<span class="evt ${e.startsWith("validator:") ? "warn" : ""}">
       ${esc(e)}</span>`).join("");
  };

  const setBusy = on => {
    busy = on;
    ["send", "continue", "undo", "retry", "branch", "suggest"].forEach(id => {
      const b = $("#" + id); if (b) b.disabled = on;
    });
    transcript.querySelectorAll(".swipebar button, .turn-edit")
      .forEach(b => b.disabled = on);
  };
  const run = async (path, body, playerText) => {
    if (busy) return;
    setBusy(true);
    stage.textContent = "Thinking…";
    evbar.innerHTML = "";
    transcript.querySelectorAll(".swipebar").forEach(b => b.remove());
    if (playerText !== undefined) addTurn("player", playerText);
    const live = addTurn("narrator", "");
    const liveBody = bodyOf(live);
    live.classList.add("pending");   // blinking caret until prose streams in
    let settled = null;              // ST-31: the regex-cleaned stored text
    try {
      await sse(path, body, {
        stage: m => { stage.textContent = m.text; },
        chunk: m => { live.classList.remove("pending");
                      liveBody.textContent += m.text;
                      transcript.scrollTop = transcript.scrollHeight; },
        done: m => { setEvents(m.events); setSheet(m.sheet || []);
                     $(".clock").textContent = m.clock || "";
                     if (m.text != null) settled = m.text;
                     stage.textContent = ""; },
        error: m => { stage.textContent = "error: " + m.text; },
      });
    } catch (e) {
      stage.textContent = "error: " + e.message;
    }
    live.classList.remove("pending");
    // ST-31: settle the raw streamed turn onto the cleaned, stored version. Only a
    // NON-EMPTY settle applies — an empty done.text must never wipe a good turn.
    if (settled && liveBody.textContent) liveBody.textContent = settled;
    if (!liveBody.textContent) live.remove();
    else paint(live, liveBody.textContent);   // ST-06: apply markdown
    swipe = {count: 1, idx: 0};                // fresh turn resets alternates
    renderSwipeBar();
    setBusy(false);
  };

  s.turns.forEach(t => addTurn(t.role, t.text));
  setSheet(s.sheet || []);
  renderSwipeBar();

  $("#suggest").addEventListener("click", async () => {
    if (busy) return;
    const b = $("#suggest"); b.disabled = true; const was = b.textContent;
    b.textContent = "…";
    try {
      const out = await api(`/api/saves/${slug}/impersonate`, {method: "POST"});
      $("#action").value = out.text; $("#action").focus();
    } catch (e) { alert(e.message); }
    b.disabled = false; b.textContent = was;
  });

  const send = async () => {
    const text = $("#action").value.trim();
    if (!text || busy) return;
    $("#action").value = "";
    await run(`/api/saves/${slug}/turn`, {text}, text);
  };
  $("#send").addEventListener("click", send);
  $("#action").addEventListener("keydown", ev => {
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(); }
  });

  // ST-30: quick-action buttons — a canned action fills the composer and sends.
  const renderQuickBar = actions => {
    const bar = $("#quick-bar");
    if (!bar) return;
    bar.innerHTML = (actions || []).map((a, i) =>
      `<button class="qa" data-i="${i}">${esc(a)}</button>`).join("");
    bar.querySelectorAll(".qa").forEach(b => b.addEventListener("click", () => {
      if (busy) return;
      $("#action").value = actions[Number(b.dataset.i)] || "";
      send();
    }));
  };
  renderQuickBar(s.quick_actions);

  $("#aids-btn").addEventListener("click", async () => {          // ST-30 + ST-31
    const aids = await api(`/api/saves/${slug}/aids`);
    openModal(`
      <h1>Play aids</h1>
      <label>Quick actions <span class="muted">(this story — one per line)</span></label>
      <textarea id="qa-list" rows="4"
        placeholder="Look around&#10;Check my inventory&#10;Wait and listen"
        >${esc((aids.quick_actions || []).join("\n"))}</textarea>
      <label>Output cleanup rules <span class="muted">(regex find &rarr; replace,
      applied to narration &amp; saved)</span></label>
      <div id="rx-rows"></div>
      <button id="rx-add" class="mini">+ rule</button>
      <div class="modal-actions">
        <button id="aids-cancel">Cancel</button>
        <button class="primary" id="aids-save">Save</button>
      </div>`);
    const rxRows = $("#rx-rows");
    const addRow = r => {
      const div = document.createElement("div");
      div.className = "rx-row row";
      div.innerHTML =
        `<input class="rx-find" placeholder="find (regex)" value="${esc(r.find || "")}">`
        + `<input class="rx-repl" placeholder="replace" value="${esc(r.replace || "")}">`
        + `<input class="rx-flags" placeholder="ims" style="max-width:4.5em" value="${esc(r.flags || "")}">`
        + `<button class="rx-del mini">✕</button>`;
      div.querySelector(".rx-del").addEventListener("click", () => div.remove());
      rxRows.appendChild(div);
    };
    (aids.regex_rules || []).forEach(addRow);
    $("#rx-add").addEventListener("click", () => addRow({}));
    $("#aids-cancel").addEventListener("click", closeModal);
    $("#aids-save").addEventListener("click", async () => {
      const quick = $("#qa-list").value.split("\n").map(t => t.trim()).filter(Boolean);
      const rules = [...rxRows.querySelectorAll(".rx-row")].map(r => ({
        find: r.querySelector(".rx-find").value,
        replace: r.querySelector(".rx-repl").value,
        flags: r.querySelector(".rx-flags").value,
      })).filter(r => r.find.trim());
      await api(`/api/saves/${slug}/aids`,
                {method: "PUT", body: {quick_actions: quick, regex_rules: rules}});
      closeModal();
      renderQuickBar((await api(`/api/saves/${slug}`)).quick_actions);
    });
  });

  $("#back").addEventListener("click", () => { location.hash = "#library"; });
  $("#continue").addEventListener("click", () => {
    if (!busy) run(`/api/saves/${slug}/continue`);
  });
  $("#undo").addEventListener("click", async () => {
    if (busy) return;
    const out = await api(`/api/saves/${slug}/undo`, {method: "POST"});
    if (out.ok) {
      while (transcript.children.length > out.turns)
        transcript.lastChild.remove();
      setSheet(out.sheet || []);
      setEvents(["undone — try a different action"]);
    }
  });
  $("#retry").addEventListener("click", async () => {
    if (busy) return;
    const turns = transcript.children;
    if (!turns.length) return;
    if (turns[turns.length - 1].classList.contains("narrator"))
      turns[turns.length - 1].remove();
    if (turns.length && turns[turns.length - 1].classList.contains("player"))
      turns[turns.length - 1].remove();
    await run(`/api/saves/${slug}/retry`);
  });
  $("#branch").addEventListener("click", async () => {
    const total = transcript.children.length;
    const n = prompt(`Branch from turn (1..${total}):`);
    if (!n) return;
    try {
      const out = await api(`/api/saves/${slug}/branch`,
                            {method: "POST", body: {turn: Number(n)}});
      if (out.warnings.length) alert(out.warnings.join("\n"));
      location.hash = `#play/${out.slug}`;
    } catch (e) { alert(e.message); }
  });
  $("#talk-btn").addEventListener("click", () => talkDrawer(slug, s.companions));
  $("#edit-btn").addEventListener("click", () => { location.hash = `#edit/${slug}`; });
  $("#note-btn").addEventListener("click", async () => {          // ST-21 author's note
    const an = await api(`/api/saves/${slug}/authors-note`);
    openModal(`
      <h1>Author's note</h1>
      <p class="muted">Standing guidance woven into the prompt — tone, pacing,
      style. Never shown to the reader.</p>
      <textarea id="an-content" rows="5"
        placeholder="e.g. Keep the tone noir and terse; end scenes on a hook."
        >${esc(an.content)}</textarea>
      <label>Placement</label>
      <div class="seg" id="an-depth">
        <button data-v="system" ${an.depth === "system" ? 'class="on"' : ""}>
          System prompt</button>
        <button data-v="tail" ${an.depth === "tail" ? 'class="on"' : ""}>
          Near the action (binds harder)</button>
      </div>
      <label>Inject every N turns</label>
      <input id="an-every" type="number" min="1" value="${an.every || 1}">
      <div class="modal-actions">
        <button id="an-cancel">Cancel</button>
        <button class="primary" id="an-save">Save</button>
      </div>`);
    let depth = an.depth;
    $("#an-depth").addEventListener("click", ev => {
      if (!ev.target.dataset.v) return;
      depth = ev.target.dataset.v;
      $("#an-depth").querySelectorAll("button").forEach(b =>
        b.classList.toggle("on", b.dataset.v === depth));
    });
    $("#an-cancel").addEventListener("click", closeModal);
    $("#an-save").addEventListener("click", async () => {
      await api(`/api/saves/${slug}/authors-note`, {method: "PUT", body: {
        content: $("#an-content").value, depth,
        every: Number($("#an-every").value) || 1}});
      closeModal();
    });
  });

  // A brand-new save generates its opening now that every control is wired — so
  // the quick-action bar / Aids / composer are all live while it streams.
  if (!s.turns.length) await run(`/api/saves/${slug}/opening`);
}

function talkDrawer(slug, companions) {
  if ($("#talk-drawer")) { $("#talk-drawer").remove(); return; }
  const d = document.createElement("div");
  d.id = "talk-drawer";
  d.innerHTML = `
    <div class="row" style="align-items:center">
      <select id="talk-who">${companions.map(c =>
        `<option>${esc(c)}</option>`).join("")}</select>
      <button id="talk-close" style="flex:0">✕</button>
    </div>
    <div id="talk-log">(This chat stays between you two — it never enters
the story transcript.)\n</div>
    <div id="talk-row">
      <input id="talk-input" placeholder="Say something…">
      <button class="primary" id="talk-send" style="flex:0">Send</button>
    </div>`;
  document.body.appendChild(d);
  const log = $("#talk-log");
  let sending = false;                  // drawer-local; the server lock guards the rest
  const send = async () => {
    const text = $("#talk-input").value.trim();
    const who = $("#talk-who").value;
    if (!text || sending) return;
    $("#talk-input").value = "";
    log.textContent += `\nYou → ${who}: ${text}\n${who}: `;
    sending = true;
    try {
      await sse(`/api/saves/${slug}/talk`, {name: who, text}, {
        chunk: m => { log.textContent += m.text;
                      log.scrollTop = log.scrollHeight; },
        error: m => { log.textContent += `[error: ${m.text}]`; },
      });
    } catch (e) { log.textContent += `[error: ${e.message}]`; }
    log.textContent += "\n";
    sending = false;
  };
  $("#talk-send").addEventListener("click", send);
  $("#talk-input").addEventListener("keydown", ev => {
    if (ev.key === "Enter") send();
  });
  $("#talk-close").addEventListener("click", () => d.remove());
}

/* ---------- characters ---------- */
let charFilter = "all";        // playable/npc sub-filter (Characters chip)
let libType = "character";     // active Library type chip

async function renderCharacters() {
  const [data, libd] = await Promise.all([
    api("/api/characters"), api("/api/library")]);
  const baseTypes = ["character", "location", "item", "faction", "thread",
                     "event"];
  const types = [...baseTypes,
                 ...libd.types.filter(t => !baseTypes.includes(t))];
  if (!types.includes(libType)) libType = "character";
  const chips = types.map(t => `<button data-v="${esc(t)}"
    ${libType === t ? 'class="on"' : ""}>${esc(t)}${
    t.endsWith("s") ? "" : "s"}</button>`).join("");
  const isChar = libType === "character";

  let cards, subFilter = "", newLabel;
  if (isChar) {
    newLabel = "+ New character";
    subFilter = `<div class="seg" id="ch-filter">
      ${["all", "playable", "npc"].map(v => `<button data-v="${v}"
        ${charFilter === v ? 'class="on"' : ""}>${v}</button>`).join("")}
    </div>`;
    const shown = data.characters.filter(c =>
      charFilter === "all" || (c.kind || "playable") === charFilter);
    cards = shown.map(c => `
      <div class="card" data-id="${esc(c.id)}">
        <div class="title">${esc(c.name)}</div>
        <div class="meta"><span class="chip ${
          (c.kind || "playable") === "playable" ? "rpg" : ""}">${
          esc(c.kind || "playable")}</span></div>
        <div class="muted">${esc(c.description || "")}</div>
        <div class="meta">${data.stats.map(s =>
          `<span class="chip">${s.slice(0, 3)} ${esc(c.stats?.[s] ?? 1)}</span>`)
          .join("")}</div>
        <div class="actions">
          <button data-act="edit">Edit</button>
          <button data-act="delete" class="danger">Delete</button>
        </div>
      </div>`).join("");
  } else {
    newLabel = `+ New ${libType}`;
    const shown = libd.pieces.filter(p => p.type === libType);
    cards = shown.map(p => `
      <div class="card" data-pid="${esc(p.id)}">
        <div class="title">${esc(p.entry.title)}</div>
        <div class="meta"><span class="chip">imp ${esc(p.entry.importance)}
          </span>${p.entry.attrs && p.entry.attrs.weight
          ? `<span class="chip">${esc(p.entry.attrs.weight)}</span>` : ""}</div>
        <div class="muted">${esc((p.entry.body || "").slice(0, 120))}</div>
        <div class="actions">
          <button data-act="edit">Edit</button>
          <button data-act="delete" class="danger">Delete</button>
        </div>
      </div>`).join("");
  }

  view.innerHTML = `<div class="page">
    <div class="page-head">
      <h1>Piece library</h1>
      <button class="primary" id="new-piece">${newLabel}</button>
    </div>
    <p class="muted">Your reusable pieces — drop any of them into a world from
    its builder ("From library…"), or send a world's piece here with
    "Save to library". <b>Playable</b> characters can be the protagonist of a
    story.</p>
    <div class="seg" id="lib-types">${chips}</div>
    ${subFilter}
    <div class="cards" style="margin-top:14px">${cards ||
      `<p class="muted">Nothing here yet.</p>`}</div>
  </div>`;

  $("#lib-types").addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    libType = ev.target.dataset.v;
    render();
  });
  const chf = $("#ch-filter");
  if (chf) chf.addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    charFilter = ev.target.dataset.v;
    render();
  });
  $("#new-piece").addEventListener("click", () => {
    if (isChar) charModal(data.stats, null);
    else pieceModal("", KIND_REL(libType), null, {id: "", type: libType});
  });
  view.querySelectorAll(".card[data-id]").forEach(card => {
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      const c = data.characters.find(x => x.id === card.dataset.id);
      if (act === "delete") {
        if (!confirm(`Delete ${c.name}? Worlds already using them keep their copy.`))
          return;
        await api(`/api/characters/${c.id}`, {method: "DELETE"});
        render();
      } else if (act === "edit" || !act) {
        charModal(data.stats, c);
      }
    });
  });
  view.querySelectorAll(".card[data-pid]").forEach(card => {
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      const p = libd.pieces.find(x => x.id === card.dataset.pid);
      if (act === "delete") {
        if (!confirm(`Delete '${p.entry.title}' from the library? Worlds `
                     + "already using it keep their copy.")) return;
        await api(`/api/library/${p.id}`, {method: "DELETE"});
        render();
      } else if (act === "edit" || !act) {
        pieceModal("", KIND_REL(p.type), p.entry, {id: p.id, type: p.type});
      }
    });
  });
}

function charModal(statNames, c) {
  const stats = statNames.map(s => `
    <div><label>${esc(s)}</label>
    <input type="number" min="-5" max="10" data-stat="${esc(s)}"
      value="${esc(c?.stats?.[s] ?? 1)}"></div>`).join("");
  openModal(`
    <h1>${c ? "Edit" : "New"} character</h1>
    <label>Kind</label>
    <div class="seg" id="ch-kind">
      <button data-v="playable" ${(c?.kind || "playable") === "playable"
        ? 'class="on"' : ""}>Playable sheet</button>
      <button data-v="npc" ${c?.kind === "npc" ? 'class="on"' : ""}>NPC</button>
    </div>
    <label>Name</label><input id="ch-name" value="${esc(c?.name || "")}">
    <label>Description</label>
    <textarea id="ch-desc" rows="3">${esc(c?.description || "")}</textarea>
    <label>Traits (comma separated)</label>
    <input id="ch-traits" value="${esc(c?.traits || "")}">
    <label>Skills — "name (stat), name (stat)"</label>
    <input id="ch-skills" value="${esc(c?.skills || "")}"
      placeholder="lockpicking (agility), old tongues (knowledge)">
    <div class="row">
      <div><label>Aliases (comma)</label>
        <input id="ch-aliases" value="${esc((c?.aliases || []).join(", "))}"></div>
      <div><label>Importance 1-5</label>
        <input id="ch-imp" type="number" min="1" max="5"
          value="${esc(c?.importance ?? 4)}"></div>
      <div><label>Weight</label>
        <select id="ch-weight">${["", "minor", "supplementary", "standard",
          "important", "critical"].map(v => `<option ${
          v === (c?.extra?.weight || "") ? "selected" : ""}>${v}</option>`)
          .join("")}</select></div>
    </div>
    <label>Triggers (extra activation keywords, comma)</label>
    <input id="ch-triggers" value="${esc(c?.extra?.triggers || "")}">
    <div class="row">
      <label style="display:flex;align-items:center;gap:6px;text-transform:none">
        <input type="checkbox" id="ch-pinned" style="width:auto"
          ${c?.extra?.pinned === "true" ? "checked" : ""}>
        Pinned (always in context)</label>
      <label style="display:flex;align-items:center;gap:6px;text-transform:none">
        <input type="checkbox" id="ch-hidden" style="width:auto"
          ${c?.extra?.hidden === "true" ? "checked" : ""}>
        Hidden (secret lore)</label>
    </div>
    <h2>Stats</h2>
    <div class="stat-grid">${stats}</div>
    <div class="modal-actions">
      <button id="ch-cancel">Cancel</button>
      <button class="primary" id="ch-save">Save</button>
    </div>`);
  let kind = c?.kind || "playable";
  $("#ch-kind").addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    kind = ev.target.dataset.v;
    $("#ch-kind").querySelectorAll("button").forEach(b =>
      b.classList.toggle("on", b.dataset.v === kind));
  });
  $("#ch-cancel").addEventListener("click", closeModal);
  $("#ch-save").addEventListener("click", async () => {
    const extra = {...(c?.extra || {})};
    extra.weight = $("#ch-weight").value;
    extra.triggers = $("#ch-triggers").value.trim();
    extra.pinned = $("#ch-pinned").checked ? "true" : "";
    extra.hidden = $("#ch-hidden").checked ? "true" : "";
    for (const k of Object.keys(extra)) if (!extra[k]) delete extra[k];
    const body = {
      id: c?.id, name: $("#ch-name").value, kind,
      description: $("#ch-desc").value, traits: $("#ch-traits").value,
      skills: $("#ch-skills").value, stats: {},
      aliases: $("#ch-aliases").value.split(",").map(s => s.trim())
        .filter(Boolean),
      importance: Number($("#ch-imp").value) || 4,
      extra,
    };
    modalCard.querySelectorAll("[data-stat]").forEach(inp => {
      body.stats[inp.dataset.stat] = Number(inp.value);
    });
    await api("/api/characters", {method: "POST", body});
    closeModal();
    render();
  });
}

/* ---------- settings ---------- */
async function renderSettings() {
  const [st, local, hosted, profs] = await Promise.all([
    api("/api/settings"), api("/api/models/local"), api("/api/models/hosted"),
    api("/api/profiles").catch(() => ({profiles: [], active: ""})),
  ]);
  const names = local.installed.map(m => m.name);
  const opt = (list, sel) => list.map(n =>
    `<option ${n === sel ? "selected" : ""}>${esc(n)}</option>`).join("");
  const localOpts = sel => opt(
    names.includes(sel) || !sel ? names : [sel, ...names], sel);
  const presetOpts = hosted.presets.map((p, i) =>
    `<option value="${i}" ${p.model === st.hosted.model ? "selected" : ""}>
     ${esc(p.label)}</option>`).join("");

  view.innerHTML = `<div class="page">
    <h1>Settings</h1>
    <div class="seg" id="mode-seg">
      <button data-v="local" ${st.mode === "local" ? 'class="on"' : ""}>
        Local (Ollama)</button>
      <button data-v="hosted" ${st.mode === "hosted" ? 'class="on"' : ""}>
        Hosted (your API key)</button>
    </div>

    <div class="setting-panel">
      <h2>Connection profiles</h2>
      <p class="muted">Save a connection (provider + model + context) under a name
      and switch between them — e.g. "fast local" vs "quality cloud".</p>
      <div class="row">
        <div style="flex:1"><label>Saved profiles</label>
          <select id="pf-list">
            <option value="">${profs.profiles.length ? "— pick —"
              : "(none saved yet)"}</option>
            ${profs.profiles.map(n => `<option ${n === profs.active
              ? "selected" : ""}>${esc(n)}</option>`).join("")}
          </select>
        </div>
        <div style="align-self:flex-end">
          <button id="pf-load">Load</button>
          <button id="pf-del" class="danger">Delete</button>
        </div>
      </div>
      <div class="row">
        <div style="flex:1"><label>Save current connection as…</label>
          <input id="pf-name" placeholder="fast local"></div>
        <div style="align-self:flex-end"><button id="pf-save">Save</button></div>
      </div>
      <span id="pf-status" class="muted"></span>
    </div>

    <div class="setting-panel" id="panel-local">
      <h2>Local models — quad brain stages</h2>
      <details class="howto">
        <summary>New to this? Install Ollama &amp; set up local models</summary>
        ${(local.howto || []).map(p => `<p>${esc(p)}</p>`).join("")}
      </details>
      ${local.error ? `<p class="muted">${esc(local.error)} — showing
        suggestions only.</p>` : ""}
      <div class="row">
        <div><label>Director (plans the turn — thinking model)</label>
          <select id="lm-director">${localOpts(st.local.director)}</select></div>
        <div><label>Writer (prose — non-thinking is fine)</label>
          <select id="lm-writer">${localOpts(st.local.writer)}</select></div>
      </div>
      <div class="row">
        <div><label>Lore-keeper (optional continuity pass)</label>
          <select id="lm-keeper">
            <option value="" ${!st.local.lorekeeper ? "selected" : ""}>(none — skip it)</option>
            ${localOpts(st.local.lorekeeper)}</select></div>
        <div><label>Context tokens</label>
          <input id="lm-ctx" type="number" step="1024"
            value="${esc(st.local.context_tokens)}"></div>
      </div>
      <p class="muted">Installed via Ollama: ${local.installed.map(m =>
        `${esc(m.name)} (${esc(m.size)})`).join(", ") || "none detected"}.
      Suggested pulls: ${local.suggestions.map(s =>
        `<b>${esc(s.name)}</b> — ${esc(s.note)}`).join("; ")}.</p>
    </div>

    <div class="setting-panel" id="panel-hosted">
      <h2>Hosted model — one model runs every stage</h2>
      <details class="howto">
        <summary>New to this? How to get running in 5 minutes</summary>
        ${hosted.howto.map(p => `<p>${esc(p)}</p>`).join("")}
      </details>
      <label>Preset</label>
      <select id="hm-preset"><option value="">(custom)</option>${presetOpts}
      </select>
      <div class="row">
        <div><label>Model id</label>
          <input id="hm-model" value="${esc(st.hosted.model)}"></div>
        <div><label>Context tokens</label>
          <input id="hm-ctx" type="number" step="1024"
            value="${esc(st.hosted.context_tokens)}"></div>
      </div>
      <label>Base URL (OpenAI-compatible)</label>
      <input id="hm-base" value="${esc(st.hosted.base_url)}">
      <label>API key ${st.hosted.key_set
        ? '<span style="color:var(--ok)">(saved — leave blank to keep)</span>'
        : ""}</label>
      <input id="hm-key" type="password" placeholder="${st.hosted.key_set
        ? "••••••••" : "paste your key"}">
      <h2>Context windows (snapshot)</h2>
      <pre class="table">${esc(hosted.hints.join("\n"))}</pre>
      <details><summary class="muted">What the big platforms actually run</summary>
        <pre class="table">${esc(hosted.platforms.join("\n"))}</pre></details>
    </div>

    <div class="setting-panel">
      <h2>Storytelling</h2>
      <label>Response length</label>
      <div class="seg" id="len-seg">
        ${["short", "medium", "long"].map(v => `<button data-v="${v}"
          ${st.generation.response_length === v ? 'class="on"' : ""}>
          ${v}</button>`).join("")}
      </div>
    </div>

    <div class="setting-panel">
      <h2>Generation controls</h2>
      <label>Start every reply with (optional)</label>
      <input id="gc-prefix" placeholder='e.g. a quote " or an action *'
        value="${esc(st.generation.start_reply_with || "")}">
      <p class="muted">Every narrator turn will begin with this literal text —
      handy to force dialogue or an action tag. Works with any model.</p>
      <label>Stop sequences (one per line)</label>
      <textarea id="gc-stop" rows="2"
        placeholder="text that ends generation, e.g.  User:">${
        esc((st.generation.stop || []).join("\n"))}</textarea>
      <div class="row">
        <div><label>Temperature</label>
          <input id="gc-temp" type="number" step="0.05" min="0" max="2"
            value="${st.generation.temperature ?? 0.9}"></div>
        <div><label>Top-p</label>
          <input id="gc-topp" type="number" step="0.05" min="0" max="1"
            value="${st.generation.top_p ?? 0.95}"></div>
        <div><label>Max tokens</label>
          <input id="gc-max" type="number" step="50" min="1"
            value="${st.generation.max_tokens ?? 2500}"></div>
      </div>
      <details><summary class="muted">Advanced samplers (blank = model default)</summary>
        <div class="row">
          <div><label>Frequency penalty</label>
            <input id="gc-freq" type="number" step="0.1" min="-2" max="2"
              value="${st.generation.frequency_penalty ?? ""}"></div>
          <div><label>Presence penalty</label>
            <input id="gc-pres" type="number" step="0.1" min="-2" max="2"
              value="${st.generation.presence_penalty ?? ""}"></div>
        </div>
        <div class="row">
          <div><label>Repetition penalty <span class="muted">(local models)</span></label>
            <input id="gc-rep" type="number" step="0.05" min="0" max="2"
              value="${st.generation.repetition_penalty ?? ""}"></div>
          <div><label>Seed <span class="muted">(fixed = reproducible)</span></label>
            <input id="gc-seed" type="number" step="1" min="0"
              value="${st.generation.seed ?? ""}"></div>
        </div>
      </details>
    </div>

    <div class="setting-panel">
      <h2>Quick actions (global)</h2>
      <p class="muted">Canned action buttons shown in every story's play bar — one
      per line. Each story can add its own from the play view (Aids).</p>
      <textarea id="qa-global" rows="3"
        placeholder="Look around&#10;Check my inventory&#10;Wait and listen"
        >${esc((st.quick_actions || []).join("\n"))}</textarea>
    </div>

    <div class="savebar">
      <button class="primary" id="save-settings">Save &amp; apply</button>
      <span id="save-status"></span>
    </div>
  </div>`;

  let mode = st.mode;
  let length = st.generation.response_length || "medium";
  const syncPanels = () => {
    $("#panel-local").classList.toggle("hidden", mode !== "local");
    $("#panel-hosted").classList.toggle("hidden", mode !== "hosted");
    $("#mode-seg").querySelectorAll("button").forEach(b =>
      b.classList.toggle("on", b.dataset.v === mode));
  };
  syncPanels();
  $("#mode-seg").addEventListener("click", ev => {
    if (ev.target.dataset.v) { mode = ev.target.dataset.v; syncPanels(); }
  });
  $("#len-seg").addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    length = ev.target.dataset.v;
    $("#len-seg").querySelectorAll("button").forEach(b =>
      b.classList.toggle("on", b.dataset.v === length));
  });
  $("#hm-preset").addEventListener("change", () => {
    const p = hosted.presets[Number($("#hm-preset").value)];
    if (!p) return;
    $("#hm-model").value = p.model;
    $("#hm-base").value = p.base_url;
    $("#hm-ctx").value = p.context;
  });
  const pfStatus = m => {
    if (!$("#pf-status")) return;
    $("#pf-status").textContent = m;
    setTimeout(() => { if ($("#pf-status")) $("#pf-status").textContent = ""; }, 3000);
  };
  $("#pf-save").addEventListener("click", async () => {
    const name = $("#pf-name").value.trim();
    if (!name) return pfStatus("enter a name first");
    try { await api("/api/profiles", {method: "POST", body: {name}}); render(); }
    catch (e) { pfStatus("error: " + e.message); }
  });
  $("#pf-load").addEventListener("click", async () => {
    const name = $("#pf-list").value;
    if (!name) return pfStatus("pick a profile");
    try {
      await api("/api/profiles/activate", {method: "POST", body: {name}});
      setBrainline(); render();
    } catch (e) { pfStatus("error: " + e.message); }
  });
  $("#pf-del").addEventListener("click", async () => {
    const name = $("#pf-list").value;
    if (!name) return pfStatus("pick a profile");
    if (!confirm(`Delete profile "${name}"?`)) return;
    try {
      await api(`/api/profiles/${encodeURIComponent(name)}`, {method: "DELETE"});
      render();
    } catch (e) { pfStatus("error: " + e.message); }
  });
  $("#save-settings").addEventListener("click", async () => {
    const body = {
      mode,
      generation: {
        response_length: length,
        start_reply_with: $("#gc-prefix").value,
        stop: $("#gc-stop").value,
        temperature: $("#gc-temp").value,
        top_p: $("#gc-topp").value,
        max_tokens: $("#gc-max").value,
        frequency_penalty: $("#gc-freq").value,
        presence_penalty: $("#gc-pres").value,
        repetition_penalty: $("#gc-rep").value,
        seed: $("#gc-seed").value,
      },
      quick_actions: $("#qa-global") ? $("#qa-global").value : "",
      local: {
        director: $("#lm-director") ? $("#lm-director").value : "",
        writer: $("#lm-writer") ? $("#lm-writer").value : "",
        lorekeeper: $("#lm-keeper") ? $("#lm-keeper").value : "",
        context_tokens: Number($("#lm-ctx").value) || 16384,
      },
      hosted: {
        model: $("#hm-model").value.trim(),
        base_url: $("#hm-base").value.trim(),
        context_tokens: Number($("#hm-ctx").value) || 131072,
        api_key: $("#hm-key").value.trim(),
      },
    };
    try {
      await api("/api/settings", {method: "PUT", body});
      $("#save-status").textContent = "Saved — applied to new turns.";
      setBrainline();
      setTimeout(() => { $("#save-status").textContent = ""; }, 3000);
    } catch (e) {
      $("#save-status").textContent = "error: " + e.message;
    }
  });
}

/* ---------- I-329: combat canvas + fiche perso ---------- */
const DKS_FIXTURE = {
  tokens: [
    {id:"pj:kael",name:"Kael",col:2,row:3,hp:12,hpMax:12,ac:16,color:"#1fda25",faction:"ally"},
    {id:"pnj:gob1",name:"Goblin 1",col:7,row:1,hp:7,hpMax:7,ac:15,color:"#ff6b6b",faction:"enemy"},
    {id:"pnj:gob2",name:"Goblin 2",col:8,row:2,hp:7,hpMax:7,ac:15,color:"#ff6b6b",faction:"enemy"},
    {id:"pnj:gob3",name:"Goblin 3",col:9,row:1,hp:7,hpMax:7,ac:15,color:"#ff6b6b",faction:"enemy"},
    {id:"pnj:gob4",name:"Goblin 4",col:7,row:4,hp:7,hpMax:7,ac:15,color:"#ff6b6b",faction:"enemy"},
    {id:"pnj:gob5",name:"Goblin 5",col:8,row:5,hp:7,hpMax:7,ac:15,color:"#ff6b6b",faction:"enemy"},
    {id:"pnj:cent1",name:"Centipede",col:10,row:3,hp:14,hpMax:14,ac:13,color:"#ff6b6b",faction:"enemy"},
    {id:"pnj:cent2",name:"Centipede 2",col:10,row:5,hp:14,hpMax:14,ac:13,color:"#ff6b6b",faction:"enemy"},
    {id:"pnj:darek",name:"Darek",col:5,row:6,hp:22,hpMax:22,ac:14,color:"#ffce6a",faction:"ally"},
    {id:"pnj:dk",name:"Death Knight",col:11,row:4,hp:28,hpMax:28,ac:15,color:"#b44aff",faction:"enemy",persistent:["pv"]},
  ],
  log: [
    {t:"move",text:"Kael moves to E3"},
    {t:"attack",text:"Goblin 1 attacks Kael: d20+4=15 vs AC16 → miss"},
    {t:"attack",text:"Kael attacks Goblin 1: d20+5=18 vs AC15 → hit, 1d8+3=7 dmg"},
    {t:"dmg",text:"Goblin 1 takes 7 damage (0/7 HP)"},
    {t:"move",text:"Death Knight advances to L4"},
  ],
  initiative: ["pj:kael","pnj:gob1","pnj:gob2","pnj:cent1","pnj:darek","pnj:gob3","pnj:dk"],
  round: 1,
};

const FICHE_FIXTURE = {
  personnage: {
    id: "kael",
    nom: "Kael",
    acquis_conversation: [
      "A accepté l'alliance avec Darek Brewmont",
      "Découvert l'entrée sud du donjon",
      "Appris que le Death Knight garde la relique",
      "Négocié le passage avec les gobelins",
    ],
    destinee: [
      {id: "j1", intention_md: "Retrouver la relique volée", rattachement: "node:donjon"},
      {id: "j2", intention_md: "Confronter le Death Knight", rattachement: "pnj:dk"},
      {id: "j3", intention_md: "Protéger Darek", rattachement: "pnj:darek"},
    ],
  },
  tensions: [
    {id: "t1", categorie: "menace", description_md: "Le Death Knight traque les intrus"},
    {id: "t2", categorie: "echeance", description_md: "La relique s'affaiblit à chaque aube"},
  ],
  ressources: [
    {id: "carte-donjon", type: "carte", fichier: "resources/carte-donjon.jpg", description_md: "Plan du donjon"},
    {id: "relique", type: "carte", fichier: "resources/relique.jpg", description_md: "Relique ancienne"},
  ],
};

let _battleGrid = null;

function renderCombatView(container) {
  const tpl = document.getElementById("tpl-combat-view");
  if (!tpl) return;
  const frag = tpl.content.cloneNode(true);
  container.appendChild(frag);
  const area = document.getElementById("battle-area");
  _battleGrid = new BattleGrid(area, {cols: 12, rows: 8, cellSize: 48});
  _battleGrid.loadTokens(DKS_FIXTURE.tokens);
  _battleGrid.onMove = (token, oldCol, oldRow) => {
    _battleGrid.addLog({t: "move", text: token.name + " moves to " + String.fromCharCode(65 + token.col) + (token.row + 1)});
    updateCombatLog();
    updateCombatInitiative();
  };
  DKS_FIXTURE.log.forEach(e => _battleGrid.addLog(e));
  updateCombatLog();
  updateCombatInitiative();
  document.getElementById("combat-round").textContent = "Round " + DKS_FIXTURE.round;
  const backBtn = document.getElementById("combat-back");
  if (backBtn) backBtn.addEventListener("click", () => {
    if (_battleGrid) { _battleGrid.destroy(); _battleGrid = null; }
    location.hash = "#library";
  });
}

function updateCombatLog() {
  const el = document.getElementById("combat-log");
  if (!el || !_battleGrid) return;
  el.innerHTML = _battleGrid.log.map(e => {
    const cls = e.t === "dmg" || e.t === "attack" ? "log-dmg" : e.t === "heal" ? "log-heal" : "log-move";
    return '<div class="log-entry ' + cls + '">' + esc(e.text) + "</div>";
  }).join("");
  el.scrollTop = el.scrollHeight;
}

function updateCombatInitiative() {
  const el = document.getElementById("combat-initiative");
  if (!el) return;
  const activeIdx = 0;
  el.innerHTML = '<div class="init-title">Initiative</div>' +
    DKS_FIXTURE.initiative.map((id, i) => {
      const t = DKS_FIXTURE.tokens.find(x => x.id === id);
      const name = t ? t.name : id;
      const active = i === activeIdx ? " active" : "";
      return '<div class="init-row' + active + '"><span class="init-num">' + (20 - i * 2) + '</span> ' + esc(name) + "</div>";
    }).join("");
}

function renderFichePerso(container, data) {
  const tpl = document.getElementById("tpl-fiche-perso");
  if (!tpl) return;
  const frag = tpl.content.cloneNode(true);
  container.appendChild(frag);
  const d = data || FICHE_FIXTURE;
  const pers = d.personnage || {};
  const nameEl = document.querySelector(".fiche-name");
  if (nameEl) nameEl.textContent = pers.nom || "Character";
  const tensionEl = document.querySelector(".fiche-tension");
  if (tensionEl && d.tensions && d.tensions.length) {
    tensionEl.innerHTML = d.tensions.map(t =>
      '<div>' + esc(t.description_md || t.id) + "</div>").join("");
  } else if (tensionEl) { tensionEl.textContent = ""; }
  const acquisEl = document.querySelector(".fiche-acquis");
  if (acquisEl) {
    acquisEl.innerHTML = (pers.acquis_conversation || []).map(a =>
      "<li>" + esc(a) + "</li>").join("") || '<li class="muted">none</li>';
  }
  const destEl = document.querySelector(".fiche-destinee");
  if (destEl) {
    destEl.innerHTML = (pers.destinee || []).map(j =>
      "<li>" + esc(j.intention_md || j.id) + "</li>").join("")
      || '<li class="muted">none</li>';
  }
  const resEl = document.querySelector(".fiche-ressources");
  if (resEl) {
    resEl.innerHTML = (d.ressources || []).map(r =>
      '<div class="fiche-ressource-card">' +
      '<div class="vignette" style="background:var(--bg)"></div>' +
      '<div class="res-label">' + esc(r.id) + "</div></div>"
    ).join("") || '<span class="muted">none</span>';
  }
}

window.DKS_FIXTURE = DKS_FIXTURE;
window.FICHE_FIXTURE = FICHE_FIXTURE;
window.renderCombatView = renderCombatView;
window.renderFichePerso = renderFichePerso;

/* ---------- brainline ---------- */
async function setBrainline() {
  try {
    const st = await api("/api/settings");
    $("#brainline").textContent = st.mode === "hosted"
      ? `hosted: ${st.hosted.model}`
      : `local: ${st.local.director} → ${st.local.writer}`;
  } catch (_e) { /* server booting */ }
}

setBrainline();
render();
