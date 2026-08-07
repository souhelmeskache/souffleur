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
_status: str = "idle"          # idle | waiting | thinking
_title: str = "Table de jeu"
_gauge: dict = {}              # fed by the status line: context window usage
_inbox: "queue.Queue[str]" = queue.Queue()

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
    global _status
    with _lock:
        _status = "waiting"
    try:
        text = _inbox.get(timeout=max(1.0, float(timeout_seconds)))
    except queue.Empty:
        return {"status": "timeout"}
    with _lock:
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
            "status": _status,
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
