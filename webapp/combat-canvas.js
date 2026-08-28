/* combat-canvas.js — I-329: wires the tactical canvas (BattleGrid, matrix.js)
   to the REAL engine state instead of a fixture. The engine (coderain/modules/
   rpg.py) tracks HP pools per combatant (rpg.player / rpg.companions /
   rpg.enemies) but no grid position and no rolled initiative — those are a
   presentation concern, so this module lays tokens out deterministically and
   derives a stable turn order (player, then companions, then enemies) rather
   than inventing mechanics the engine doesn't have.

   Depends on `BattleGrid` (matrix.js, loaded first in index.html). Talks to
   the server via GET /api/saves/{slug}/rpg (server.py `_rpg_payload`), which
   mirrors the exact same source as the live text sheet
   (`rpg_mod.render_sheet_lines`): store.rpg_state() + store.world_state(). */

const RpgCombat = {
  /* Turn a /api/saves/{slug}/rpg payload into {tokens, initiative} ready for
     BattleGrid.loadTokens(). Pure function — no DOM, easy to unit-test. */
  fromPayload(payload, opts = {}) {
    const cols = opts.cols || 12;
    const rows = opts.rows || 8;
    const tokens = [];
    const initiative = [];

    if (!payload || !payload.enabled) return {tokens, initiative};

    const p = payload.player || {};
    tokens.push({
      id: "player", name: "You",
      col: 1, row: Math.floor(rows / 2),
      hp: p.hp ?? 0, hpMax: p.hp_max ?? p.hp ?? 1,
      color: "#1fda25", faction: "ally",
    });
    initiative.push("player");

    const companions = payload.companions || {};
    Object.keys(companions).forEach((slug, i) => {
      // Companion HP isn't tracked per-slug (only trust/mood/disposition) —
      // shown present with no HP bar rather than a fabricated pool.
      tokens.push({
        id: "companion:" + slug, name: slug,
        col: 1, row: Math.min(rows - 1, Math.floor(rows / 2) + 1 + i),
        hp: 1, hpMax: 1, color: "#ffce6a", faction: "ally",
      });
      initiative.push("companion:" + slug);
    });

    const enemies = payload.enemies || {};
    const enemySlugs = Object.keys(enemies);
    enemySlugs.forEach((slug, i) => {
      const e = enemies[slug] || {};
      tokens.push({
        id: "enemy:" + slug, name: slug,
        col: Math.min(cols - 1, cols - 2),
        row: i % rows,
        hp: e.hp ?? 0, hpMax: e.hp_max ?? e.hp ?? 1,
        color: "#ff6b6b", faction: "enemy",
      });
      initiative.push("enemy:" + slug);
    });

    return {tokens, initiative};
  },
};

/* LiveCombat — mounts a BattleGrid against a real save and keeps HP/roster in
   sync by polling the sheet endpoint (same cadence class as webui.py's /poll:
   cheap, local, no push channel needed for a local-first app). */
class LiveCombat {
  constructor(container, opts = {}) {
    this.container = typeof container === "string"
      ? document.querySelector(container) : container;
    this.slug = opts.slug;
    this.fetcher = opts.fetcher || (slug =>
      fetch(`/api/saves/${slug}/rpg`).then(r => r.json()));
    this.pollMs = opts.pollMs || 4000;
    this.onLog = opts.onLog || null;
    this.grid = new BattleGrid(this.container, {
      cellSize: opts.cellSize || 48, cols: opts.cols || 12, rows: opts.rows || 8,
    });
    this.initiative = [];
    this._timer = null;
    this.grid.onMove = (token, oldCol, oldRow) => {
      if (this.onLog) {
        this.onLog({t: "move", text: token.name + " moves"});
      }
    };
  }

  async refresh() {
    const payload = await this.fetcher(this.slug);
    const {tokens, initiative} = RpgCombat.fromPayload(payload,
      {cols: this.grid.cols, rows: this.grid.rows});
    // Preserve any drag the player just made: only positions/HP of tokens
    // already on the grid get updated in place, new ones are appended.
    const existing = new Map(this.grid.tokens.map(t => [t.id, t]));
    this.grid.loadTokens(tokens.map(t => {
      const prev = existing.get(t.id);
      return prev ? {...t, col: prev.col, row: prev.row} : t;
    }));
    this.initiative = initiative;
    return payload;
  }

  start() {
    this.refresh();
    this._timer = setInterval(() => this.refresh(), this.pollMs);
  }

  destroy() {
    if (this._timer) clearInterval(this._timer);
    this.grid.destroy();
  }
}

window.RpgCombat = RpgCombat;
window.LiveCombat = LiveCombat;
