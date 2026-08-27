/* Matrix digital rain — a fixed full-screen canvas behind all content.
   Kept dim + short-trailed so story prose over it stays readable; the topbar,
   page margins, and card gutters are where it reads most. */
(function () {
  const canvas = document.createElement("canvas");
  canvas.id = "matrix-rain";
  canvas.setAttribute("aria-hidden", "true");
  Object.assign(canvas.style, {
    position: "fixed", inset: "0", zIndex: "-1", pointerEvents: "none",
  });
  document.body.prepend(canvas);
  const ctx = canvas.getContext("2d");

  const GLYPHS = "アカサタナハマヤラ0123456789CODERAIN".split("");
  const STEP = 16;
  let cols, drops;

  function paintBase() {
    ctx.fillStyle = "#03060a";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    cols = Math.ceil(canvas.width / STEP);
    drops = Array.from({length: cols}, () =>
      Math.floor(Math.random() * -50));
    paintBase();
  }
  resize();
  window.addEventListener("resize", resize);

  function draw() {
    ctx.fillStyle = "rgba(3, 6, 10, 0.30)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.font = STEP + "px monospace";
    for (let i = 0; i < drops.length; i++) {
      const g = GLYPHS[(Math.random() * GLYPHS.length) | 0];
      const y = drops[i] * STEP;
      ctx.fillStyle = Math.random() > 0.94
        ? "rgba(120, 255, 140, 0.85)" : "rgba(31, 218, 37, 0.5)";
      ctx.fillText(g, i * STEP, y);
      if (y > canvas.height && Math.random() > 0.975) drops[i] = 0;
      drops[i]++;
    }
  }

  let last = 0;
  const FRAME_MS = 55;
  function loop(ts) {
    if (ts - last >= FRAME_MS) { draw(); last = ts; }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();

/* BattleGrid — tactical combat canvas (I-329).
   Renders tokens on a grid, supports drag, HP overlay, range indicator.
   Zero external deps, 60 fps via requestAnimationFrame. */
class BattleGrid {
  constructor(container, opts = {}) {
    this.container = typeof container === "string"
      ? document.querySelector(container) : container;
    this.cellSize = opts.cellSize || 48;
    this.cols = opts.cols || 12;
    this.rows = opts.rows || 8;
    this.tokens = [];
    this.log = [];
    this.dragToken = null;
    this.dragOffset = {x: 0, y: 0};
    this.selectedToken = null;
    this.onMove = opts.onMove || null;
    this._init();
  }

  _init() {
    this.canvas = document.createElement("canvas");
    this.canvas.className = "battle-canvas";
    this.canvas.width = this.cols * this.cellSize;
    this.canvas.height = this.rows * this.cellSize;
    this.ctx = this.canvas.getContext("2d");
    this.container.appendChild(this.canvas);
    this.canvas.addEventListener("mousedown", e => this._onDown(e));
    this.canvas.addEventListener("mousemove", e => this._onMouseMove(e));
    this.canvas.addEventListener("mouseup", e => this._onUp(e));
    this.canvas.addEventListener("mouseleave", e => this._onUp(e));
    this._loop();
  }

  loadTokens(tokenList) {
    this.tokens = tokenList.map((t, i) => ({
      id: t.id || ("t" + i),
      name: t.name || "?",
      label: (t.name || "?").slice(0, 2).toUpperCase(),
      col: t.col ?? (i % this.cols),
      row: t.row ?? Math.floor(i / this.cols),
      hp: t.hp ?? 10,
      hpMax: t.hpMax ?? t.hp ?? 10,
      ac: t.ac ?? 10,
      color: t.color || (t.faction === "enemy" ? "#ff6b6b" : "#1fda25"),
      faction: t.faction || "ally",
      size: t.size || 1,
      persistent: t.persistent || [],
    }));
    this._dirty = true;
  }

  updateToken(id, patch) {
    const t = this.tokens.find(x => x.id === id);
    if (t) Object.assign(t, patch);
    this._dirty = true;
  }

  addLog(entry) {
    this.log.push(entry);
    if (this.log.length > 50) this.log.shift();
  }

  _cellAt(e) {
    const r = this.canvas.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    return {
      col: Math.floor(x / this.cellSize),
      row: Math.floor(y / this.cellSize),
      px: x, py: y,
    };
  }

  _tokenAt(col, row) {
    return this.tokens.find(t => t.col === col && t.row === row) || null;
  }

  _onDown(e) {
    const {col, row} = this._cellAt(e);
    const t = this._tokenAt(col, row);
    if (t) {
      this.dragToken = t;
      this.selectedToken = t;
      const r = this.canvas.getBoundingClientRect();
      this.dragOffset = {
        x: e.clientX - r.left - t.col * this.cellSize,
        y: e.clientY - r.top - t.row * this.cellSize,
      };
    } else {
      this.selectedToken = null;
    }
    this._dirty = true;
  }

  _onMouseMove(e) {
    if (!this.dragToken) return;
    const r = this.canvas.getBoundingClientRect();
    const px = e.clientX - r.left - this.dragOffset.x;
    const py = e.clientY - r.top - this.dragOffset.y;
    this.dragToken._dragCol = Math.floor(px / this.cellSize);
    this.dragToken._dragRow = Math.floor(py / this.cellSize);
    this._dirty = true;
  }

  _onUp(e) {
    if (!this.dragToken) return;
    const t = this.dragToken;
    if (t._dragCol != null && t._dragCol >= 0 && t._dragCol < this.cols
        && t._dragRow != null && t._dragRow >= 0 && t._dragRow < this.rows) {
      const oldCol = t.col, oldRow = t.row;
      t.col = t._dragCol;
      t.row = t._dragRow;
      if (this.onMove) this.onMove(t, oldCol, oldRow);
    }
    delete t._dragCol;
    delete t._dragRow;
    this.dragToken = null;
    this._dirty = true;
  }

  _draw() {
    const cs = this.cellSize, ctx = this.ctx;
    ctx.fillStyle = "#050d08";
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.strokeStyle = "#123f1c";
    ctx.lineWidth = 1;
    for (let c = 0; c <= this.cols; c++) {
      ctx.beginPath(); ctx.moveTo(c * cs, 0);
      ctx.lineTo(c * cs, this.rows * cs); ctx.stroke();
    }
    for (let r = 0; r <= this.rows; r++) {
      ctx.beginPath(); ctx.moveTo(0, r * cs);
      ctx.lineTo(this.cols * cs, r * cs); ctx.stroke();
    }
    if (this.selectedToken && !this.dragToken) {
      const st = this.selectedToken;
      ctx.fillStyle = "rgba(31, 218, 37, 0.08)";
      ctx.fillRect(st.col * cs, st.row * cs, cs, cs);
    }
    for (const t of this.tokens) {
      const dc = t._dragCol != null ? t._dragCol : t.col;
      const dr = t._dragRow != null ? t._dragRow : t.row;
      const cx = dc * cs + cs / 2, cy = dr * cs + cs / 2;
      const rad = cs * 0.38;
      ctx.beginPath();
      ctx.arc(cx, cy, rad, 0, Math.PI * 2);
      ctx.fillStyle = t.color + "33";
      ctx.fill();
      ctx.strokeStyle = t.color;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = t.color;
      ctx.font = "bold " + (cs * 0.28) + "px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(t.label, cx, cy);
      const bw = cs * 0.7, bh = 4;
      const bx = cx - bw / 2, by = cy + rad + 3;
      const ratio = Math.max(0, t.hp / t.hpMax);
      ctx.fillStyle = "#1a1a1a";
      ctx.fillRect(bx, by, bw, bh);
      ctx.fillStyle = ratio > 0.5 ? "#1fda25" : ratio > 0.25 ? "#ffce6a" : "#ff6b6b";
      ctx.fillRect(bx, by, bw * ratio, bh);
      ctx.fillStyle = "#6f9b7d";
      ctx.font = (cs * 0.18) + "px monospace";
      ctx.fillText(t.hp + "/" + t.hpMax, cx, by + bh + 8);
    }
  }

  _loop() {
    if (this._dirty) { this._draw(); this._dirty = false; }
    this._raf = requestAnimationFrame(() => this._loop());
  }

  destroy() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this.canvas.remove();
  }

  measureFps(frames) {
    return new Promise(resolve => {
      const times = [];
      let count = 0;
      this._dirty = true;
      const tick = ts => {
        times.push(ts);
        count++;
        this._dirty = true;
        if (count >= frames) {
          const elapsed = times[times.length - 1] - times[0];
          resolve({frames: count, elapsed, fps: (count - 1) / (elapsed / 1000)});
        } else {
          requestAnimationFrame(tick);
        }
      };
      requestAnimationFrame(tick);
    });
  }
}

window.BattleGrid = BattleGrid;

/* I-329: tactical combat canvas — grid, draggable tokens, HP overlay, range.
   Pure client-side; fixture-driven for tests, SSE-ready for live play. */
class CombatCanvas {
  constructor(el, opts = {}) {
    this.el = typeof el === "string" ? document.querySelector(el) : el;
    this.cols = opts.cols || 10; this.rows = opts.rows || 8;
    this.cell = 48; this.tokens = []; this.zones = [];
    this.log = []; this.drag = null; this.hover = null;
    this._frameCount = 0; this._fps = 0; this._fpsT = 0;
    this._init();
  }
  _init() {
    this.cv = document.createElement("canvas");
    this.cv.style.cssText = "display:block;width:100%;cursor:crosshair";
    this.el.appendChild(this.cv);
    this.logEl = document.createElement("div");
    this.logEl.className = "combat-log";
    this.el.appendChild(this.logEl);
    this.ctx = this.cv.getContext("2d");
    this._resize();
    this.cv.addEventListener("mousedown", e => this._down(e));
    this.cv.addEventListener("mousemove", e => this._move(e));
    this.cv.addEventListener("mouseup", () => this._up());
    window.addEventListener("resize", () => this._resize());
    this._loop();
  }
  _resize() {
    const w = this.el.clientWidth || 480;
    this.cell = Math.floor(w / this.cols);
    this.cv.width = this.cols * this.cell;
    this.cv.height = this.rows * this.cell;
  }
  load(data) {
    this.tokens = (data.tokens || []).map((t, i) => ({
      id: t.id || ("t" + i), name: t.name || "?",
      hp: t.hp || 0, maxHp: t.maxHp || t.hp || 1,
      col: t.col ?? (i % this.cols), row: t.row ?? Math.floor(i / this.cols),
      friendly: !!t.friendly, range: t.range || 0,
      persistent: t.persistent || [],
    }));
    this.zones = data.zones || [];
    this.log = data.log || [];
    this._renderLog();
  }
  _cell(e) {
    const r = this.cv.getBoundingClientRect();
    return {
      col: Math.floor((e.clientX - r.left) / this.cell),
      row: Math.floor((e.clientY - r.top) / this.cell),
    };
  }
  _tokenAt(c, ro) {
    return this.tokens.find(t => t.col === c && t.row === ro);
  }
  _down(e) {
    const {col, row} = this._cell(e);
    const t = this._tokenAt(col, row);
    if (t) { this.drag = {token: t, from: {col: t.col, row: t.row}}; }
  }
  _move(e) {
    const {col, row} = this._cell(e);
    if (this.drag) {
      this.drag.token.col = Math.max(0, Math.min(col, this.cols - 1));
      this.drag.token.row = Math.max(0, Math.min(row, this.rows - 1));
    }
    this.hover = this._tokenAt(col, row) || null;
  }
  _up() {
    if (this.drag) {
      const {token, from} = this.drag;
      this.log.push(`${token.name}: (${from.col},${from.row}) -> (${token.col},${token.row})`);
      this._renderLog();
      this.drag = null;
    }
  }
  _renderLog() {
    this.logEl.innerHTML = this.log.slice(-8).map(l =>
      `<div class="log-line">${l}</div>`).join("");
    this.logEl.scrollTop = this.logEl.scrollHeight;
  }
  _draw() {
    const c = this.ctx, s = this.cell;
    c.clearRect(0, 0, this.cv.width, this.cv.height);
    c.fillStyle = "#050a07"; c.fillRect(0, 0, this.cv.width, this.cv.height);
    c.strokeStyle = "#123f1c"; c.lineWidth = 1;
    for (let i = 0; i <= this.cols; i++) {
      c.beginPath(); c.moveTo(i * s, 0); c.lineTo(i * s, this.rows * s); c.stroke();
    }
    for (let i = 0; i <= this.rows; i++) {
      c.beginPath(); c.moveTo(0, i * s); c.lineTo(this.cols * s, i * s); c.stroke();
    }
    for (const z of this.zones) {
      c.fillStyle = "rgba(31,218,37,0.06)";
      c.fillRect(z.col * s, z.row * s, (z.w || 1) * s, (z.h || 1) * s);
      c.fillStyle = "#6f9b7d"; c.font = "10px monospace";
      c.fillText(z.label || z.id || "", z.col * s + 3, z.row * s + 11);
    }
    if (this.hover && this.hover.range > 0) {
      const t = this.hover;
      c.strokeStyle = "rgba(255,206,106,0.3)"; c.lineWidth = 2;
      c.beginPath();
      c.arc(t.col * s + s / 2, t.row * s + s / 2, t.range * s, 0, Math.PI * 2);
      c.stroke();
    }
    for (const t of this.tokens) this._drawToken(c, t, s);
    if (this.drag) {
      const t = this.drag.token;
      c.strokeStyle = "#ffce6a"; c.lineWidth = 2;
      c.strokeRect(t.col * s + 1, t.row * s + 1, s - 2, s - 2);
    }
    this._frameCount++;
    const now = performance.now();
    if (now - this._fpsT >= 1000) {
      this._fps = this._frameCount; this._frameCount = 0; this._fpsT = now;
    }
  }
  _drawToken(c, t, s) {
    const cx = t.col * s + s / 2, cy = t.row * s + s / 2, r = s * 0.36;
    c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2);
    c.fillStyle = t.friendly ? "rgba(255,206,106,0.85)" : "rgba(255,107,107,0.85)";
    c.fill();
    c.strokeStyle = t.persistent.includes("pv") ? "#fff" : "#000";
    c.lineWidth = t.persistent.includes("pv") ? 2 : 1; c.stroke();
    const hpR = t.hp / t.maxHp;
    c.fillStyle = "#222"; c.fillRect(t.col * s + 3, t.row * s + s - 7, s - 6, 4);
    c.fillStyle = hpR > 0.5 ? "#1fda25" : hpR > 0.25 ? "#ffce6a" : "#ff6b6b";
    c.fillRect(t.col * s + 3, t.row * s + s - 7, (s - 6) * Math.max(0, hpR), 4);
    c.fillStyle = "#fff"; c.font = `bold ${Math.floor(s * 0.22)}px monospace`;
    c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(`${t.hp}`, cx, cy);
    c.font = `${Math.floor(s * 0.16)}px sans-serif`; c.textBaseline = "top";
    c.fillText(t.name.slice(0, 8), cx, t.row * s + 2);
    c.textAlign = "start"; c.textBaseline = "alphabetic";
  }
  _loop() { this._draw(); this._raf = requestAnimationFrame(() => this._loop()); }
  stop() { cancelAnimationFrame(this._raf); }
  get fps() { return this._fps; }
  getPositions() {
    return this.tokens.map(t => ({id: t.id, col: t.col, row: t.row}));
  }
}
window.CombatCanvas = CombatCanvas;
