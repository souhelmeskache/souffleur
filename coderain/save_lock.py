"""save_lock.py — verrou de save côté pont MCP (I-188, Issue #115).

Le constat qui motive ce module : `.mcp.json` lance `mcp_server.py` comme
processus stdio enfant de chaque session Claude Code. Une session ouverte
est un moteur vivant — `load_save` construit un `_store`/`_engine` en
global, capable d'écrire dans le save à tout instant (turns, événements,
undo). Si une deuxième session charge le même save, elle écrasait jusqu'ici
la première EN SILENCE puis continuait à écrire depuis un état déjà
périmé : pas un conflit qui échoue bruyamment, une divergence qui
s'installe.

Ce module pose un fichier de lock `<save>/.lock.json` à l'ouverture
(`acquire`), le retire à la fermeture propre du pont (`release`, appelé par
les handlers `atexit`/signal de `mcp_server.py`), et détecte un verrou
orphelin — processus qui le tenait tué sans fermeture propre — pour le
réclamer automatiquement plutôt que bloquer un save à jamais
(`held_by_other_live_process` renvoie None dès que le pid enregistré n'est
plus vivant).

Zéro dépendance externe (pas de psutil, absent de requirements.txt) : la
vivacité d'un pid se teste avec les moyens du bord — POSIX `os.kill(pid, 0)`,
Windows `OpenProcess` via `ctypes` (le repo tourne aussi bien sous l'un que
sous l'autre, voir `coderain/config.py`)."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

LOCK_NAME = ".lock.json"


def _pid_alive(pid: int) -> bool:
    """True if a process with this pid currently exists on this machine.
    Best-effort: any ambiguous case (permission denied, platform quirk)
    reads as 'alive' — the safe direction, since the cost of a false
    'alive' is a lock the owning session can still release, while a false
    'dead' would let a second session silently stomp a live one."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                      False, pid)
        if not handle:
            return False
        try:
            # A handle can still be opened for a process that has already
            # exited — e.g. the parent that spawned it (subprocess.Popen)
            # keeps its own handle alive until garbage-collected, and
            # OpenProcess happily hands out a second one to that same
            # kernel object. The exit code is what actually tells "alive"
            # apart from "terminated, not yet fully torn down".
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True  # query failed: assume alive, safe direction
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else
    return True


def _lock_path(save_dir: Path) -> Path:
    return Path(save_dir) / LOCK_NAME


def read(save_dir: Path) -> dict | None:
    """Return the lock file's content if one sits at `save_dir`, else None.
    Never raises: a corrupt/partial lock file (e.g. a crash mid-write) reads
    as 'no usable lock' — same effect as an orphan, both are reclaimable."""
    path = _lock_path(save_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def held_by_other_live_process(save_dir: Path) -> dict | None:
    """None if the save is free to load: no lock, a corrupt lock, an orphan
    lock (its pid is dead), or a lock this very process already holds.
    Otherwise the live lock's content, for the caller to report."""
    lock = read(save_dir)
    if lock is None:
        return None
    pid = lock.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        return None  # orphan: the process that held it is gone
    if pid == os.getpid():
        return None  # this same process re-loading its own save
    return lock


def acquire(save_dir: Path, slug: str) -> dict:
    """Write this process's lock, silently reclaiming any orphan lock found.
    Caller is expected to have checked `held_by_other_live_process` first —
    this does not re-check, it commits."""
    lock = {"pid": os.getpid(), "host": socket.gethostname(),
            "slug": slug, "opened": time.time()}
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    _lock_path(save_dir).write_text(json.dumps(lock, indent=2),
                                    encoding="utf-8")
    return lock


def release(save_dir: Path, slug: str | None = None) -> None:
    """Remove this process's own lock — never someone else's: a pid/slug
    mismatch means either this process moved on already (switched save) or
    another process now legitimately owns the lock (it reclaimed an orphan
    left by this one), and releasing would flip a held lock back to free out
    from under it. Best-effort: a failure here must never block shutdown."""
    path = _lock_path(save_dir)
    lock = read(save_dir)
    if lock is None:
        return
    if lock.get("pid") != os.getpid():
        return
    if slug is not None and lock.get("slug") != slug:
        return
    try:
        path.unlink()
    except OSError:
        pass
