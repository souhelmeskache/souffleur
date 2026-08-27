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
  const STEP = 16;                       // column width / row height (px)
  let cols, drops;

  function paintBase() {
    // Lay down an OPAQUE background first so painted and never-painted regions
    // are byte-identical — otherwise the canvas alpha caps below 255 and the
    // rain band reads as a faint grey rectangle against the page.
    ctx.fillStyle = "#03060a";               // == --bg, fully opaque
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    cols = Math.ceil(canvas.width / STEP);
    drops = Array.from({length: cols}, () =>
      Math.floor(Math.random() * -50));  // stagger the start of each column
    paintBase();
  }
  resize();
  window.addEventListener("resize", resize);

  function draw() {
    // Opaque-background wash → the classic fading trail. Colour == --bg and the
    // alpha is high enough that faded glyphs actually reach the background
    // instead of lingering as a grey-green haze (measured: prior 0.16 left the
    // band at rgb 2,8,14 vs the 3,6,10 page — a visible rectangle).
    ctx.fillStyle = "rgba(3, 6, 10, 0.30)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.font = STEP + "px monospace";
    for (let i = 0; i < drops.length; i++) {
      const g = GLYPHS[(Math.random() * GLYPHS.length) | 0];
      const y = drops[i] * STEP;
      // lead glyph brighter, the rest dim green — reads as depth
      ctx.fillStyle = Math.random() > 0.94
        ? "rgba(120, 255, 140, 0.85)" : "rgba(31, 218, 37, 0.5)";
      ctx.fillText(g, i * STEP, y);
      if (y > canvas.height && Math.random() > 0.975) drops[i] = 0;
      drops[i]++;
    }
  }

  let last = 0;
  const FRAME_MS = 55;                    // ~18 fps — calm, not seizure-y
  function loop(ts) {
    if (ts - last >= FRAME_MS) { draw(); last = ts; }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();

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
