"""Local web screen for the coderain MCP bridge (meta-rpg MRPG-I-144).

Why this exists
---------------
The player must not read the Claude Code terminal: tool results are printed there,
and some of them are the campaign's secrets (event rules, "Secrets you know").
The previous workaround hid every secret-touching call inside subagents. That works
(a subagent is a black box) but subagents are capped at a five-minute prompt-cache
TTL, so a player who thinks for six minutes pays the full context again, every turn.

Giving the player a browser window removes the reason to hide anything: the terminal
can print whatever it likes because nobody is looking at it. The narrator moves back
into the main conversation, which has the one-hour cache.

The browser holds no API key and calls no model. It is a screen and a keyboard, wired
to Claude Code through the MCP process — which is already a long-lived Python program
and can simply open a socket.

Protocol (all local, 127.0.0.1 only)
    GET  /                 the page (re-read from disk on every request, so the
                           HTML can be edited without restarting Claude Code)
    GET  /poll?since=N     {messages, panel, status, seq} — the page polls this
    POST /say              {"text": ...} — the player's input, queued for ui_wait
    GET  /health           {"ok": true}
"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
HTML_FILE = ROOT / "webui.html"
PORT_FILE = ROOT / ".turn" / "ui_port"

_lock = threading.Lock()
_messages: list[dict] = []
_panel: str = ""
_sheet: str = ""                # full character sheet (multi-line, right rail)
_status: str = "idle"          # idle | waiting | thinking
_title: str = "Table de jeu"
_gauge: dict = {}              # fed by the status line: context window usage
_inbox: "queue.Queue[str]" = queue.Queue()
_pending: int = 0               # messages queued while nobody waits


def _pending_inc():
    global _pending
    with _lock:
        _pending += 1

_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_port: int | None = None


# ── state helpers (called from the MCP tools) ────────────────────

def _append(role: str, text: str) -> int:
    with _lock:
        seq = len(_messages) + 1
        _messages.append({"id": seq, "role": role, "text": text})
        return seq


def say(text: str, role: str = "mj") -> int:
    """Push a message onto the player's screen."""
    global _status
    seq = _append(role, text)
    with _lock:
        _status = "idle"
    return seq


def set_panel(text: str) -> None:
    global _panel
    with _lock:
        _panel = text or ""


def set_sheet(text: str) -> None:
    global _sheet
    with _lock:
        _sheet = text or ""


def set_title(text: str) -> None:
    global _title
    with _lock:
        _title = text or "Table de jeu"


def set_status(value: str) -> None:
    global _status
    with _lock:
        _status = value


def wait(timeout_seconds: float) -> dict:
    """Block until the player submits something, or until timeout.

    Returns {"status": "input", "text": ...} or {"status": "timeout"}.
    Input typed while nobody was waiting is queued, never lost.
    """
    global _status, _pending
    with _lock:
        _status = "waiting"
    try:
        text = _inbox.get(timeout=max(1.0, float(timeout_seconds)))
    except queue.Empty:
        return {"status": "timeout"}
    with _lock:
        _pending = 0
        _status = "thinking"
    return {"status": "input", "text": text}


def set_gauge(data: dict) -> None:
    """Context-window usage, pushed by the Claude Code status line.

    The MCP process cannot see the conversation it serves, so this is the only
    honest source: Claude Code hands `context_window.used_percentage` to the
    status line script, which forwards it here. Without it the player would have
    to watch the terminal to know when to start a fresh conversation — which is
    exactly what the browser screen exists to avoid.
    """
    global _gauge
    with _lock:
        _gauge = dict(data or {})


def snapshot(since: int = 0) -> dict:
    with _lock:
        return {
            "messages": [m for m in _messages if m["id"] > since],
            "seq": len(_messages),
            "panel": _panel,
            "sheet": _sheet,
            "status": _status,
            "pending": _pending > 0,
            "title": _title,
            "gauge": dict(_gauge),
        }


def reset() -> None:
    """Clear the transcript (new session on the same server)."""
    global _messages, _panel, _status
    with _lock:
        _messages = []
        _panel = ""
        _status = "idle"
    while not _inbox.empty():
        try:
            _inbox.get_nowait()
        except queue.Empty:
            break


# ── HTTP ─────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # never pollute the MCP streams
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path)
        if path.path in ("/", "/index.html"):
            try:
                html = HTML_FILE.read_bytes()
            except OSError as e:
                self._send(500, f"webui.html illisible: {e}".encode("utf-8"),
                           "text/plain; charset=utf-8")
                return
            self._send(200, html, "text/html; charset=utf-8")
        elif path.path == "/poll":
            q = parse_qs(path.query)
            try:
                since = int((q.get("since") or ["0"])[0])
            except ValueError:
                since = 0
            self._json(snapshot(since))
        elif path.path == "/health":
            self._json({"ok": True, "port": _port})
        elif path.path == "/conv-b/state":
            self._json(conv_b_state())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path)
        if path.path == "/gauge":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                set_gauge(json.loads(self.rfile.read(length) or b"{}"))
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 400)
                return
            self._json({"ok": True})
            return
        if path.path == "/conv-b/start":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                pdata = payload.get("partition", {})
                nom = payload.get("nom", "Vahn")
                result = conv_b_start(pdata, nom)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 400)
                return
            self._json(result)
            return
        if path.path == "/conv-b/choice":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                text = (payload.get("text") or "").strip()
                result = conv_b_submit(text)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 400)
                return
            self._json(result)
            return
        if path.path != "/say":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            text = (payload.get("text") or "").strip()
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 400)
            return
        if not text:
            self._json({"error": "empty"}, 400)
            return
        seq = _append("joueur", text)
        _pending_inc()
        _inbox.put(text)
        self._json({"ok": True, "id": seq})


def start(port: int = 8787) -> dict:
    """Start the screen server (idempotent). Binds loopback only."""
    global _server, _thread, _port
    if _server is not None:
        return {"url": f"http://127.0.0.1:{_port}", "port": _port,
                "already_running": True}
    last_err = None
    for candidate in range(port, port + 10):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", candidate), _Handler)
        except OSError as e:
            last_err = e
            continue
        srv.daemon_threads = True
        _server = srv
        _port = candidate
        _thread = threading.Thread(target=srv.serve_forever, daemon=True,
                                   name="coderain-webui")
        _thread.start()
        # The status line script runs in a separate process and has to find us.
        try:
            PORT_FILE.parent.mkdir(exist_ok=True)
            PORT_FILE.write_text(str(candidate), encoding="utf-8")
        except OSError:
            pass
        return {"url": f"http://127.0.0.1:{candidate}", "port": candidate,
                "already_running": False}
    return {"error": f"aucun port libre entre {port} et {port + 9}: {last_err}"}


def stop() -> dict:
    global _server, _thread, _port
    if _server is None:
        return {"stopped": False, "reason": "pas de serveur en cours"}
    _server.shutdown()
    _server.server_close()
    _server = None
    _thread = None
    old, _port = _port, None
    return {"stopped": True, "port": old}


def is_running() -> bool:
    return _server is not None


# ── Conversation B — 4 fenêtres jouables (D-219 §Spécification) ──

class _FenetreOption:
    __slots__ = ("texte", "negotiable", "acquis", "jalon")

    def __init__(self, texte: str, negotiable: bool, acquis: str, jalon: dict):
        self.texte = texte
        self.negotiable = negotiable
        self.acquis = acquis
        self.jalon = jalon


class ConversationB:
    """4 fenêtres jouables F1→F4 (D-219 §Spécification, I-341/D-220).

    F1 origine / F2 posture sociale / F3 lien tension centrale / F4 enjeu personnel.
    Chaque fenêtre : 3 options négociables + 1 non-négociable rare.
    Le joueur choisit ou reformule. Garde zéro-spoiler (5 règles D-219).
    Produit un record Personnage (acquis_conversation + destinée ≥2 jalons rattachés).
    """

    NUM_WINDOWS = 4
    WINDOW_NAMES = ("origine", "posture_sociale", "lien_tension", "enjeu_personnel")

    def __init__(self, partition_data: dict, nom: str = "Vahn"):
        self._partition = partition_data
        self._nom = nom
        self._idx = 0
        self._acquis: list[str] = []
        self._jalons: list[dict] = []
        self._options: list[_FenetreOption] = []
        self._done = False
        self._last_prose = ""
        self._secrets_ids = {s["id"] for s in partition_data.get("secrets", [])}
        self._build_window()

    def _nodes(self) -> list[dict]:
        return self._partition.get("nodes", [])

    def _tensions(self) -> list[dict]:
        return self._partition.get("tensions", [])

    def _resources(self) -> list[dict]:
        return self._partition.get("resources", [])

    def _scene_origine(self) -> dict | None:
        for n in self._nodes():
            if n["id"] == "scene-origine":
                return n
        for n in self._nodes():
            if n.get("type") == "scene":
                return n
        return None

    def _scene_origine_id(self) -> str:
        s = self._scene_origine()
        return s["id"] if s else "scene-origine"

    def _tension_by_cat(self, cat: str) -> dict | None:
        for t in self._tensions():
            if t.get("categorie") == cat:
                return t
        return None

    def _build_window(self):
        if self._idx >= self.NUM_WINDOWS:
            self._done = True
            self._options = []
            return
        builders = (self._build_f1, self._build_f2,
                    self._build_f3, self._build_f4)
        builders[self._idx]()

    def _build_f1(self):
        sid = self._scene_origine_id()
        self._options = [
            _FenetreOption(
                "Ancien soldat ayant survécu à une guerre oubliée, "
                "tu portes encore les cicatrices des campagnes passées.",
                True, "soldat-survivant",
                {"id": "jalon-origine",
                 "intention_md": "Ancien soldat ayant survécu à une guerre oubliée.",
                 "rattachement": sid}),
            _FenetreOption(
                "Vagabond sans maître, tu erres depuis les ruines "
                "d'un foyer que tu ne reverras pas.",
                True, "vagabond",
                {"id": "jalon-origine",
                 "intention_md": "Vagabond sans maître ni attache.",
                 "rattachement": sid}),
            _FenetreOption(
                "Fils de paysan endetté, tu as fui pour échapper "
                "aux créanciers et à la misère.",
                True, "paysan-fugitif",
                {"id": "jalon-origine",
                 "intention_md": "Fils de paysan endetté ayant fui son domaine.",
                 "rattachement": sid}),
            _FenetreOption(
                "Porteur d'une dette envers un mort — tu lui as promis "
                "de finir ce qu'il a commencé.",
                False, "dette-envers-un-mort",
                {"id": "jalon-dette",
                 "intention_md": "Porteur d'une dette envers un mort.",
                 "rattachement": sid}),
        ]

    def _build_f2(self):
        self._options = [
            _FenetreOption(
                "Tu te méfies des autorités — les seigneurs et "
                "leurs promesses creuses ne t'abusent plus.",
                True, "mefiance-autorite",
                {"id": "jalon-posture",
                 "intention_md": "Méfiant envers les autorités établies."}),
            _FenetreOption(
                "Tu cherches la rédemption — une faute ancienne "
                "que tu veux racheter avant la fin.",
                True, "redemption",
                {"id": "jalon-posture",
                 "intention_md": "En quête de rédemption pour une faute ancienne."}),
            _FenetreOption(
                "Tu protèges les tiens — ceux qui ne peuvent "
                "se défendre eux-mêmes.",
                True, "protecteur",
                {"id": "jalon-posture",
                 "intention_md": "Protecteur de ceux qui ne peuvent se défendre."}),
            _FenetreOption(
                "Tu portes le pieu de l'arbre rouge — marque "
                "des anciens combattants, serment de sang.",
                False, "pieu-arbre-rouge",
                {"id": "jalon-marque",
                 "intention_md": "Porteur du pieu de l'arbre rouge, marque des anciens combattants."}),
        ]

    def _build_f3(self):
        menace = self._tension_by_cat("menace")
        choix = self._tension_by_cat("choix")
        cout = self._tension_by_cat("cout")
        menace_id = menace["id"] if menace else "tension-menace"
        choix_id = choix["id"] if choix else "tension-choix"
        cout_id = cout["id"] if cout else "tension-cout"
        self._options = [
            _FenetreOption(
                "Une menace rôde dans les terres sauvages — "
                "tu l'as déjà croisée du regard.",
                True, "menace-rode",
                {"id": "jalon-tension-1",
                 "intention_md": "Confronté à une menace rôdant dans les terres sauvages.",
                 "rattachement": menace_id}),
            _FenetreOption(
                "Un choix ancien te hante — dire la vérité ou mentir, "
                "la balance pèse encore.",
                True, "choix-ancien",
                {"id": "jalon-tension-2",
                 "intention_md": "Hanté par un choix ancien entre vérité et mensonge.",
                 "rattachement": choix_id}),
            _FenetreOption(
                "Un coût personnel t'a marqué — ce que tu as perdu "
                "ne se remplacera pas.",
                True, "cout-personnel",
                {"id": "jalon-tension-3",
                 "intention_md": "Marqué par un coût personnel irréversible.",
                 "rattachement": cout_id}),
            _FenetreOption(
                "La menace des gobelins pèse sur la région — "
                "tu ne peux l'ignorer.",
                False, "menace-goblins",
                {"id": "jalon-tension-goblins",
                 "intention_md": "Confronté à la menace des gobelins pesant sur la région.",
                 "rattachement": menace_id}),
        ]

    def _build_f4(self):
        resources = self._resources()
        res_id = resources[0]["id"] if resources else "carte-1"
        sid = self._scene_origine_id()
        self._options = [
            _FenetreOption(
                "Retrouver la paix intérieure — laisser les fantômes "
                "du passé se reposer enfin.",
                True, "paix-interieure",
                {"id": "jalon-enjeu",
                 "intention_md": "En quête de paix intérieure, laisser les fantômes se reposer.",
                 "rattachement": sid}),
            _FenetreOption(
                "Honorer la promesse faite au mort — finir "
                "ce qu'il n'a pas pu achever.",
                True, "honorer-promesse",
                {"id": "jalon-enjeu",
                 "intention_md": "Honorer la promesse faite à un mort.",
                 "rattachement": sid}),
            _FenetreOption(
                "Construire un foyer — avoir un lieu à soi, enfin.",
                True, "construire-foyer",
                {"id": "jalon-enjeu",
                 "intention_md": "Construire un foyer, avoir un lieu à soi.",
                 "rattachement": res_id}),
            _FenetreOption(
                "Protéger la carte tilepage — un héritage qui ne doit "
                "pas tomber en mauvaises mains.",
                False, "protecteur-carte",
                {"id": "jalon-enjeu-carte",
                 "intention_md": "Protecteur de la carte tilepage, héritage à préserver.",
                 "rattachement": res_id}),
        ]

    @property
    def current_window(self) -> str:
        if self._idx >= self.NUM_WINDOWS:
            return "done"
        return self.WINDOW_NAMES[self._idx]

    @property
    def is_done(self) -> bool:
        return self._done

    def start(self) -> dict:
        self._idx = 0
        self._acquis = []
        self._jalons = []
        self._done = False
        self._build_window()
        return self._current_state()

    def _window_title(self) -> str:
        titles = {
            0: f"**Origine** — D'où viens-tu, {self._nom} ?",
            1: "**Posture** — Comment te tiens-tu dans ce monde ?",
            2: "**Fardeau** — Qu'est-ce qui pèse sur tes épaules ?",
            3: "**Enjeu** — Que cherches-tu, au fond ?",
        }
        return titles.get(self._idx, "")

    def _options_prose(self) -> str:
        lines = []
        for opt in self._options:
            lines.append(f"*{opt.texte}*")
        lines.append("\nChoisis, ou reformule à ta manière.")
        return "\n\n".join(lines)

    def _closing_prose(self) -> str:
        return (f"La toile de ton destin est tissée, {self._nom}. "
                f"Que l'aventure commence.")

    def _current_state(self) -> dict:
        if self._done:
            prose = self._closing_prose()
            self._guard_check(prose)
            self._last_prose = prose
            return {"done": True, "prose": prose,
                    "acquis": list(self._acquis),
                    "jalons": list(self._jalons)}
        title = self._window_title()
        opts = self._options_prose()
        full = f"{title}\n\n{opts}"
        self._guard_check(full)
        self._last_prose = full
        return {
            "done": False,
            "window": self.current_window,
            "window_number": self._idx + 1,
            "prose": full,
            "options": [{"numero": i + 1, "texte": o.texte}
                        for i, o in enumerate(self._options)],
            "acquis": list(self._acquis),
            "jalons": list(self._jalons),
        }

    def submit(self, player_text: str) -> dict:
        if self._done:
            return {"error": "conversation terminee", "done": True}
        player_text = player_text.strip()
        if not player_text:
            return {"error": "texte vide", "done": False}
        choice_idx = self._parse_choice(player_text)
        if choice_idx is not None:
            opt = self._options[choice_idx]
            self._accept_option(opt)
        else:
            rejection = self._check_reformulation(player_text)
            if rejection:
                return {"error": rejection,
                        "error_type": "non-negotiable-contredit",
                        "done": False, "prose": self._last_prose,
                        "window": self.current_window}
            self._accept_reformulation(player_text)
        self._idx += 1
        self._build_window()
        return self._current_state()

    def _parse_choice(self, text: str) -> int | None:
        t = text.strip().lower()
        mapping = {"1": 0, "un": 0, "2": 1, "deux": 1,
                   "3": 2, "trois": 2, "4": 3, "quatre": 3}
        return mapping.get(t)

    def _accept_option(self, opt: _FenetreOption):
        self._acquis.append(opt.acquis)
        self._jalons.append(dict(opt.jalon))

    def _accept_reformulation(self, text: str):
        neg_opts = [o for o in self._options if o.negotiable]
        self._acquis.append(f"reformulation-{self._idx}")
        if neg_opts:
            jalon = dict(neg_opts[0].jalon)
            jalon["intention_md"] = text
            self._jalons.append(jalon)
        else:
            self._jalons.append({"id": f"jalon-reformulation-{self._idx}",
                                 "intention_md": text})

    def _check_reformulation(self, text: str) -> str | None:
        non_neg = next((o for o in self._options if not o.negotiable), None)
        if non_neg is None:
            return None
        text_lower = text.lower()
        non_neg_words = [w for w in non_neg.texte.lower().split()
                         if len(w) > 4]
        if len(non_neg_words) < 2:
            return None
        has_key = sum(1 for w in non_neg_words[:5] if w in text_lower) >= 2
        negation_markers = ("pas", "jamais", "non", "refuse", "contre",
                            "nullement", "aucun")
        has_neg = any(m in text_lower for m in negation_markers)
        if has_key and has_neg:
            return (f"reformulation contredit l'element non-negociable "
                    f"'{non_neg.acquis}' — fondamental pour ce personnage")
        return None

    def _guard_check(self, text: str) -> None:
        violations = self.guard_output(text)
        if violations:
            raise ValueError(
                f"GARDE ZERO-SPOILER VIOLEE: {violations}")

    def guard_output(self, text: str) -> list[str]:
        violations: list[str] = []
        text_lower = text.lower()
        for sid in self._secrets_ids:
            if sid.lower() in text_lower:
                violations.append(f"secret-cite: {sid}")
        for marker in ("négociable", "non-négociable",
                       "negociable", "non-negociable"):
            if marker in text_lower:
                violations.append(f"marqueur-visible: {marker}")
        for n in self._nodes():
            nid = n["id"]
            if nid in text:
                violations.append(f"id-node-cite: {nid}")
        for t in self._tensions():
            tid = t["id"]
            if tid in text:
                violations.append(f"id-tension-cite: {tid}")
        for r in self._resources():
            rid = r["id"]
            if rid in text:
                violations.append(f"id-ressource-cite: {rid}")
        return violations

    def personnage(self, pid: str | None = None,
                   nom: str | None = None) -> dict:
        if not self._done:
            raise ValueError("conversation non terminee — "
                             "4 fenêtres requises")
        return {
            "id": pid or self._nom.lower(),
            "nom": nom or self._nom,
            "acquis_conversation": list(self._acquis),
            "destinee": [dict(j) for j in self._jalons],
        }


def conv_b_start(partition_data: dict, nom: str = "Vahn") -> dict:
    global _conv_b
    _conv_b = ConversationB(partition_data, nom)
    state = _conv_b.start()
    say(state["prose"], role="mj")
    return state


def conv_b_submit(player_text: str) -> dict:
    global _conv_b
    if _conv_b is None:
        return {"error": "conversation non initialisee"}
    result = _conv_b.submit(player_text)
    if "error" not in result:
        say(result.get("prose", ""), role="mj")
    return result


def conv_b_state() -> dict:
    if _conv_b is None:
        return {"error": "conversation non initialisee"}
    return _conv_b._current_state()


def conv_b_personnage(pid: str | None = None,
                      nom: str | None = None) -> dict:
    if _conv_b is None:
        return {"error": "conversation non initialisee"}
    return _conv_b.personnage(pid, nom)


_conv_b: ConversationB | None = None
