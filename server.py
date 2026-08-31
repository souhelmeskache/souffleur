"""Coderain web server (Phase 6) — the MAIN app UI.

Régime SECONDAIRE (D-267) — flexibilité locale/API ; le produit joué passe
par le chemin MCP/forfait, pas par ici.

FastAPI + a static SPA (webapp/). One process, local-first:

    .venv\\Scripts\\python.exe server.py          # http://127.0.0.1:8377

The Tkinter app (gui.py) remains as the retro easter egg; everything new lands
here first. Endpoints are thin wrappers over the same Engine/Library the CLI
and GUI use — no engine logic lives in this file.
"""
from __future__ import annotations

import contextlib
import json
import queue
import shutil
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from coderain import models as models_mod
from coderain import features
from coderain.config import (load_config, read_env, save_yaml,
                                write_env)
from coderain import templates
from coderain.engine import Engine
from coderain.generator import (PIECE_KINDS, ScenarioSpec,
                                   _split_premise_body, _write_premise_md,
                                   assist_field, complete_scenario,
                                   generate_scenario)
from coderain.llm import LLM
from coderain.memory import (Entry, Library, MemoryStore, _safe_zip_member,
                             safe_output_regex)
from coderain.profiles import (STAT_NAMES, CharacterProfiles,
                                  PieceLibrary, apply_character,
                                  apply_playable_entry, character_from_entry,
                                  entry_from_character)

# Data (saves/scenarios/config/.env) lives in the user's home dir — the repo
# root in dev, %LOCALAPPDATA%\Coderain in the frozen desktop build (see
# config._home_dir). Assets (webapp/) always come from the install/bundle dir.
from coderain.config import ROOT as DATA_ROOT  # noqa: E402
ROOT = DATA_ROOT
ASSETS = Path(__file__).resolve().parent
OLLAMA_TAGS = "http://localhost:11434/api/tags"
HOSTED_KEY_ENV = "HOSTED_API_KEY"

app = FastAPI(title="Coderain")
lib = Library(ROOT)
lib.scenarios.ensure_default()   # seed the bundled world on a fresh install (web mode)
characters = CharacterProfiles(ROOT)
pieces_lib = PieceLibrary(ROOT)

_cfg = load_config()
_engines: dict[str, Engine] = {}
# The local GPU (and most single-key plans) can't run turns in parallel —
# one generation at a time, app-wide.
_gen_lock = threading.Lock()


def _guard_slug(slug: str) -> str:
    """Reject a slug that isn't a clean id (a real slug equals slugify(slug)) — a
    boundary guard against path traversal on any endpoint that maps slug -> disk."""
    if not slug or slug != templates.slugify(slug):
        raise HTTPException(400, "invalid id")
    return slug


@contextlib.contextmanager
def _exclusive():
    """Run a save-mutating (non-streaming) op under the single generation lock,
    failing fast with 409 rather than blocking if a turn is in flight — so an
    edit/undo/delete never races a generation nor hangs on a stuck stream."""
    if not _gen_lock.acquire(blocking=False):
        raise HTTPException(409, "a turn is generating — try again in a moment")
    try:
        yield
    finally:
        _gen_lock.release()


def _engine(slug: str) -> Engine:
    _guard_slug(slug)
    if slug not in _engines:
        try:
            # First touch of this slug in the process = session open — snapshot
            # it (I-148/ESC-4); later calls stay on bare store() (see memory.py
            # SaveLibrary.open).
            store = lib.saves.open(slug)
        except FileNotFoundError:
            raise HTTPException(404, f"no such save: {slug}")
        _engines[slug] = Engine(_cfg, store)
    return _engines[slug]


def _reload_config() -> None:
    global _cfg
    try:
        new = load_config()               # a bad persisted config must not kill
    except SystemExit as e:               # the running server — keep the last good
        raise HTTPException(400, f"config not applied: {e}")
    _cfg = new
    _engines.clear()          # engines rebuild lazily against the new config


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _quick_actions_for(store: MemoryStore) -> list[str]:
    """ST-30: the global quick actions (config) followed by this save's own, deduped."""
    merged = _clean_quick_actions(_cfg.raw.get("quick_actions"))
    for a in _clean_quick_actions(store.world_state().get("quick_actions")):
        if a not in merged:
            merged.append(a)
    return merged


def _save_payload(slug: str) -> dict:
    eng = _engine(slug)
    store = eng.store
    turns = store.turns()
    return {
        "slug": slug,
        "title": store.title,
        "mode": store.mode(),
        "rpg": store.rpg_enabled(),
        "turns": turns,
        "sheet": _sheet_lines(eng),
        "companions": eng.companions(),
        "clock": store.clock_str(),
        "quick_actions": _quick_actions_for(store),
    }


def _rpg_payload(store: MemoryStore) -> dict:
    """Structured character-sheet + combat data (I-329): the same source as the
    text sheet (`_sheet_lines`/`rpg_mod.render_sheet_lines`) but as plain dicts,
    for the live character-sheet page and the combat canvas to render without
    parsing formatted text. Empty/inert shape when RPG mechanics are off."""
    rpg = store.rpg_state()
    world = store.world_state()
    if not rpg.get("enabled"):
        return {"enabled": False}
    wplayer = world.get("player") if isinstance(world.get("player"), dict) else {}
    time = world.get("time") if isinstance(world.get("time"), dict) else {}
    quests = world.get("quests") if isinstance(world.get("quests"), dict) else {}
    return {
        "enabled": True,
        "player": rpg.get("player", {}),
        "inventory": rpg.get("inventory", {}),
        "companions": rpg.get("companions", {}),
        "enemies": rpg.get("enemies", {}),
        "last_check": rpg.get("last_check"),
        "world": {
            "day": time.get("day"),
            "phase": time.get("phase"),
            "weather": time.get("weather"),
            "location": wplayer.get("location"),
            "gold": wplayer.get("gold"),
            "quests_active": [s for s, st in quests.items() if st == "active"],
        },
    }


def _sheet_lines(eng: Engine) -> list[str]:
    store = eng.store
    if not store.rpg_enabled():
        return []
    try:
        rpg_mod = features.module("rpg")
        if rpg_mod is None:
            return []
        text = rpg_mod.render_sheet_lines(store.rpg_state(),
                                          store.world_state())
        return text.splitlines() if isinstance(text, str) else list(text)
    except Exception:  # noqa: BLE001 — the sheet must never kill a request
        return []


def _stream_generation(slug: str, run):
    """Shared SSE pump: `run(eng, notes)` returns the prose iterator. Stage
    notes are flushed between chunks so the UI shows pipeline progress live."""
    eng = _engine(slug)

    def gen():
        if not _gen_lock.acquire(blocking=False):
            yield _sse({"t": "error", "text": "another turn is running"})
            return
        try:
            notes: list[str] = []
            it = run(eng, notes)
            for piece in it:
                while notes:
                    yield _sse({"t": "stage", "text": notes.pop(0)})
                if piece:
                    yield _sse({"t": "chunk", "text": piece})
            while notes:
                yield _sse({"t": "stage", "text": notes.pop(0)})
            events = eng.maybe_fold()
            # ST-31: hand back the final STORED narrator text so the client can
            # settle the streamed (raw) turn onto the regex-cleaned version.
            tail = eng.store.turns()
            final = tail[-1]["text"] if tail and tail[-1]["role"] == "narrator" else None
            yield _sse({"t": "done", "events": events,
                        "sheet": _sheet_lines(eng),
                        "clock": eng.store.clock_str(),
                        "turns": len(eng.store.turns()),
                        "text": final})
        except Exception as e:  # noqa: BLE001 — surface, never hang the stream
            yield _sse({"t": "error", "text": str(e)})
        finally:
            _gen_lock.release()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------- library ----------
@app.get("/api/saves")
def list_saves():
    return {"saves": lib.saves.list(), "scenarios": lib.scenarios.list(),
            "characters": characters.list()}


@app.post("/api/saves")
def create_save(body: dict):
    title = str(body.get("title", "")).strip() or "Untitled"
    scenario = str(body.get("scenario", "")).strip()
    mode = body.get("mode") if body.get("mode") in ("simple", "rpg") \
        else "simple"
    premise = str(body.get("premise", "")).strip()
    start_time = body.get("start_time") if isinstance(
        body.get("start_time"), dict) else None
    slug = lib.saves.create(title, scenario, mode=mode, premise=premise,
                            rpg_cfg=_cfg.rpg, start_time=start_time)
    cid = str(body.get("character", "")).strip()
    if cid:
        char = characters.get(cid)
        if char:
            apply_character(lib.saves.store(slug), char)
    # Play as one of the WORLD's playable characters (piece slug): the files
    # were just copied from the scenario, so resolve it in the save itself.
    pslug = str(body.get("playable", "")).strip()
    if pslug:
        store = lib.saves.store(slug)
        entry = next((e for e in store.entries("characters.md")
                      if e.slug == pslug), None)
        if entry is not None:
            apply_playable_entry(store, entry)
    return {"slug": slug}


@app.get("/api/saves/{slug}")
def get_save(slug: str):
    return _save_payload(slug)


@app.delete("/api/saves/{slug}")
def delete_save(slug: str):
    _guard_slug(slug)
    with _exclusive():                       # don't rmtree files under a live turn
        _engines.pop(slug, None)
        if not lib.saves.delete(slug):
            raise HTTPException(404, f"no such save: {slug}")
    return {"ok": True}


@app.post("/api/saves/{slug}/branch")
def branch_save(slug: str, body: dict):
    try:
        n = int(body.get("turn", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "turn must be a number")
    total = len(_engine(slug).store.turns())
    if not 1 <= n <= total:
        raise HTTPException(400, f"turn must be 1..{total}")
    with _exclusive():                       # copy a consistent transcript snapshot
        new_slug, warnings = lib.saves.branch(slug, n, _cfg.rpg)
    return {"slug": new_slug, "warnings": warnings}


# ---------- play ----------
def _reset_swipes(slug: str) -> None:
    eng = _engines.get(slug)
    if eng is not None:
        eng._swipes = None      # a genuine new/edited turn invalidates alternates


@app.post("/api/saves/{slug}/opening")
def opening(slug: str):
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.opening(on_stage=notes.append))


@app.post("/api/saves/{slug}/turn")
def turn(slug: str, body: dict):
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "empty action")
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.turn(text, on_stage=notes.append))


@app.put("/api/saves/{slug}/turns/{i}")
def edit_turn(slug: str, i: int, body: dict):
    """In-place message edit (ST-03)."""
    eng = _engine(slug)
    with _exclusive():                       # don't rewrite the transcript mid-turn
        if not eng.store.update_turn(i, str(body.get("text", ""))):
            raise HTTPException(400, f"no turn at index {i}")
        eng._swipes = None
    return {"ok": True}


@app.post("/api/saves/{slug}/impersonate")
def impersonate(slug: str):
    """Draft the player's next action (ST-04). Returns text; stores nothing."""
    eng = _engine(slug)
    with _exclusive():
        return {"text": eng.impersonate()}


@app.post("/api/saves/{slug}/swipe")
def swipe_browse(slug: str, body: dict):
    """Browse cached narrator alternates without generating (ST-02)."""
    eng = _engine(slug)
    direction = 1 if int(body.get("dir", 1)) >= 0 else -1
    with _exclusive():                       # rewrites the tail turn — not mid-gen
        out = eng.swipe_browse(direction)
    if out is None:
        raise HTTPException(400, "nothing to swipe")
    return out


@app.post("/api/saves/{slug}/swipe-gen")
def swipe_gen(slug: str):
    """Generate a NEW narrator alternate and select it (ST-02)."""
    return _stream_generation(
        slug, lambda eng, notes: eng.swipe_generate(on_stage=notes.append))


@app.post("/api/saves/{slug}/undo")
def undo(slug: str):
    eng = _engine(slug)
    with _exclusive():
        ok = eng.undo_last()
        eng._swipes = None
    return {"ok": ok, "turns": len(eng.store.turns()),
            "sheet": _sheet_lines(eng)}


@app.post("/api/saves/{slug}/retry")
def retry(slug: str):
    eng = _engine(slug)
    turns = eng.store.turns()
    if not (turns and turns[-1]["role"] in ("narrator", "player")):
        raise HTTPException(400, "nothing to retry yet")

    def run(e, notes):
        # The destructive rollback runs UNDER the generation lock (inside the
        # stream) so it can't truncate the transcript of an in-flight turn.
        t = e.store.turns()
        if t and t[-1]["role"] == "narrator" and len(t) >= 2:
            last_player = t[-2]["text"]
            e.store.drop_last_turns(2)
        elif t and t[-1]["role"] == "player":
            last_player = t[-1]["text"]
            e.store.drop_last_turns(1)
        else:
            return iter(())               # nothing to retry (raced away)
        e.restore_pre_turn_rpg()
        e._swipes = None
        return e.turn(last_player, on_stage=notes.append)

    return _stream_generation(slug, run)


@app.post("/api/saves/{slug}/continue")
def continue_story(slug: str):
    """Extend the prose with no player action (the 'Continue' button)."""
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.continue_story(on_stage=notes.append))


@app.post("/api/saves/{slug}/talk")
def talk(slug: str, body: dict):
    name = str(body.get("name", "")).strip()
    text = str(body.get("text", "")).strip()
    if not name or not text:
        raise HTTPException(400, "need a companion name and a message")
    return _stream_generation(
        slug, lambda eng, notes: eng.companion_chat(name, text))


# ---------- scenarios (FictionLab shape: name + premise + introduction) ----
_BASE_PIECE_FILES = ["characters.md", "locations.md", "items.md",
                     "factions.md", "threads.md", "events.md"]


def _scen_store(slug: str) -> MemoryStore:
    _guard_slug(slug)
    scen_dir = lib.scenarios.dir(slug)
    if not (scen_dir / "scenario.json").exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    # scenario_dir = itself so custom lore types (scenario.json) resolve
    return MemoryStore(scen_dir, None, scen_dir)


def _piece_files(store: MemoryStore) -> list[str]:
    return _BASE_PIECE_FILES + [f for f in store.custom_files()
                                if f not in _BASE_PIECE_FILES]


def _entry_dict(e: Entry) -> dict:
    return {"title": e.title, "slug": e.slug, "aliases": e.aliases,
            "importance": e.importance, "attrs": e.attrs, "body": e.body}


def _entry_from_dict(d: dict) -> Entry:
    from coderain.templates import slugify
    title = str(d.get("title", "")).strip()
    slug = slugify(str(d.get("slug", "")).strip() or title)
    if not title or not slug:
        raise HTTPException(400, "a piece needs at least a title")
    try:
        imp = max(1, min(5, int(d.get("importance", 3))))
    except (TypeError, ValueError):
        imp = 3
    raw_attrs = d.get("attrs")
    attrs = {str(k): str(v) for k, v in raw_attrs.items()
             if str(v).strip()} if isinstance(raw_attrs, dict) else {}
    raw_aliases = d.get("aliases")
    aliases = [str(a).strip() for a in raw_aliases
               if str(a).strip()] if isinstance(raw_aliases, list) else []
    return Entry(title=title, slug=slug, aliases=aliases, importance=imp,
                 attrs=attrs, body=str(d.get("body", "")).strip())


def _scenario_context(store: MemoryStore) -> str:
    """What the per-field AI assists see: the premise (and tone lives in it)."""
    return _split_premise_body(store.read("premise.md"))


@app.post("/api/scenarios")
def create_scenario(body: dict):
    """Create a world — a builder shell (empty premise is fine; the builder
    fills it) or a complete manual one with premise + introduction."""
    title = str(body.get("title", "")).strip() or "Untitled World"
    premise = str(body.get("premise", "")).strip()
    slug = lib.scenarios.create(
        title, premise,
        world=str(body.get("world", "")).strip(),
        description=str(body.get("description", "")).strip() or premise[:140],
        introduction=str(body.get("introduction", "")).strip())
    return {"slug": slug}


@app.get("/api/scenarios/{slug}/full")
def scenario_full(slug: str):
    store = _scen_store(slug)
    meta = json.loads((lib.scenarios.dir(slug) / "scenario.json")
                      .read_text(encoding="utf-8"))
    world = "\n".join(ln for ln in store.read("world-bible.md").splitlines()
                      if not ln.startswith("# ")).strip()
    files = _piece_files(store)
    return {
        "slug": slug,
        "title": meta.get("title", slug),
        "description": meta.get("description", ""),
        "premise": _split_premise_body(store.read("premise.md")),
        "introduction": store.opening_override(),
        "world": world,
        "pieces": {rel: [_entry_dict(e) for e in store.entries(rel)]
                   for rel in files},
    }


@app.put("/api/scenarios/{slug}/main")
def scenario_main(slug: str, body: dict):
    store = _scen_store(slug)
    premise = str(body.get("premise", "")).strip()
    intro = str(body.get("introduction", "")).strip()
    _write_premise_md(store, premise, intro)
    world = str(body.get("world", "")).strip()
    store.write("world-bible.md", "# World bible\n\n"
                + (world + "\n" if world else ""))
    lib.scenarios.update_meta(
        slug, title=str(body.get("title", "")).strip(),
        description=str(body.get("description", "")).strip())
    return {"ok": True}


@app.put("/api/scenarios/{slug}/pieces/{rel}")
def scenario_piece_put(slug: str, rel: str, body: dict):
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    entry = _entry_from_dict(body.get("entry") or {})
    store.upsert_entry(rel, entry)
    old = str(body.get("old_slug", "")).strip()
    if old and old != entry.slug:
        store.remove_entry(rel, old)          # slug rename cleans the old one
    return {"ok": True, "slug": entry.slug}


@app.delete("/api/scenarios/{slug}/pieces/{rel}/{pslug}")
def scenario_piece_delete(slug: str, rel: str, pslug: str):
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    if not store.remove_entry(rel, pslug):
        raise HTTPException(404, f"no such piece: {pslug}")
    return {"ok": True}


def _declare_custom_type(slug: str, name: str) -> str:
    """Declare (and seed) a custom lore type on a scenario. Returns the
    filename; raises HTTPException on bad names / missing scenario."""
    _guard_slug(slug)
    import re as _re
    base = str(name).strip().removesuffix(".md")
    if not _re.search(r"[A-Za-z0-9]", base):
        raise HTTPException(400, f"not a usable lore file name: {name!r}")
    from coderain.memory import _RESERVED_MD
    fname = templates.slugify(base) + ".md"
    if fname in _RESERVED_MD or fname in _BASE_PIECE_FILES:
        raise HTTPException(400, f"'{fname}' is a built-in file")
    scen_dir = lib.scenarios.dir(slug)
    meta_path = scen_dir / "scenario.json"
    if not meta_path.exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.setdefault("custom_files", [])
    if fname not in declared:
        declared.append(fname)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    f = scen_dir / fname
    if not f.exists():
        label = fname.removesuffix(".md").replace("-", " ").title()
        f.write_text(f"# {label}\n\n{label} — custom lore registry.\n",
                     encoding="utf-8")
    return fname


@app.post("/api/scenarios/{slug}/types")
def scenario_add_type(slug: str, body: dict):
    """Declare a custom lore type on a scenario (scenario.json custom_files)."""
    return {"file": _declare_custom_type(slug, str(body.get("name", "")))}


@app.delete("/api/scenarios/{slug}/types/{fname}")
def scenario_delete_type(slug: str, fname: str):
    """Remove a CUSTOM lore type: the declaration AND the file (its pieces go
    with it — the UI confirms first). Built-ins are never deletable."""
    _guard_slug(slug)
    if fname in _BASE_PIECE_FILES or not fname.endswith(".md") \
            or "/" in fname or "\\" in fname:
        raise HTTPException(400, f"'{fname}' is not a removable lore type")
    scen_dir = lib.scenarios.dir(slug)
    meta_path = scen_dir / "scenario.json"
    if not meta_path.exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.get("custom_files") or []
    if fname not in declared:
        raise HTTPException(404, f"'{fname}' is not declared on this world")
    meta["custom_files"] = [f for f in declared if f != fname]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        (scen_dir / fname).unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


@app.get("/api/scenarios/{slug}/pieces/{rel}/export")
def scenario_section_export(slug: str, rel: str):
    """Download one section of a world as its raw Markdown file."""
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    path = lib.scenarios.dir(slug) / rel
    if not path.exists():
        raise HTTPException(404, f"{rel} has no content yet")
    return FileResponse(path, filename=f"{slug}-{rel}",
                        media_type="text/markdown")


# ---------- per-save world editing (same builder UI, live save files) --------
# A save owns its OWN copies of the world files (they diverge from the scenario
# as the story evolves). These mirror the scenario builder endpoints but read
# and write the loaded save, so the player can edit characters/locations/etc.
# mid-play. The engine reads the Markdown fresh each turn, so edits go live.
def _save_store(slug: str) -> MemoryStore:
    _guard_slug(slug)
    try:
        return lib.saves.store(slug)
    except FileNotFoundError:
        raise HTTPException(404, f"no such save: {slug}")


def _declare_type_in(base_dir: Path, meta_name: str, name: str) -> str:
    """Declare (+seed) a custom lore type by writing its file and adding it to
    the target's `custom_files` (scenario.json OR a save's meta.json)."""
    import re as _re
    base = str(name).strip().removesuffix(".md")
    if not _re.search(r"[A-Za-z0-9]", base):
        raise HTTPException(400, f"not a usable lore file name: {name!r}")
    from coderain.memory import _RESERVED_MD
    fname = templates.slugify(base) + ".md"
    if fname in _RESERVED_MD or fname in _BASE_PIECE_FILES:
        raise HTTPException(400, f"'{fname}' is a built-in file")
    meta_path = base_dir / meta_name
    if not meta_path.exists():
        raise HTTPException(404, "no such target")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.setdefault("custom_files", [])
    if fname not in declared:
        declared.append(fname)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    f = base_dir / fname
    if not f.exists():
        label = fname.removesuffix(".md").replace("-", " ").title()
        f.write_text(f"# {label}\n\n{label} — custom lore registry.\n",
                     encoding="utf-8")
    return fname


def _delete_type_in(base_dir: Path, meta_name: str, fname: str) -> dict:
    if fname in _BASE_PIECE_FILES or not fname.endswith(".md") \
            or "/" in fname or "\\" in fname:
        raise HTTPException(400, f"'{fname}' is not a removable lore type")
    meta_path = base_dir / meta_name
    if not meta_path.exists():
        raise HTTPException(404, "no such target")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.get("custom_files") or []
    if fname not in declared:
        raise HTTPException(404, f"'{fname}' is not declared here")
    meta["custom_files"] = [f for f in declared if f != fname]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        (base_dir / fname).unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


@app.get("/api/saves/{slug}/world/full")
def save_world_full(slug: str):
    store = _save_store(slug)
    meta = lib.saves.meta(slug)
    world = "\n".join(ln for ln in store.read("world-bible.md").splitlines()
                      if not ln.startswith("# ")).strip()
    files = _piece_files(store)
    return {
        "slug": slug,
        "title": meta.get("title", slug),
        "description": "",
        "premise": _split_premise_body(store.read("premise.md")),
        "introduction": store.opening_override(),
        "world": world,
        "pieces": {rel: [_entry_dict(e) for e in store.entries(rel)]
                   for rel in files},
    }


@app.get("/api/saves/{slug}/authors-note")
def get_authors_note(slug: str):
    store = _save_store(slug)
    an = store.world_state().get("authors_note")
    an = an if isinstance(an, dict) else {}
    depth = an.get("depth") if an.get("depth") in ("system", "tail") else "system"
    try:
        every = max(1, int(an.get("every", 1)))
    except (TypeError, ValueError):
        every = 1
    return {"content": store.custom_instructions(), "depth": depth, "every": every}


@app.put("/api/saves/{slug}/authors-note")
def put_authors_note(slug: str, body: dict):
    """ST-21: the per-save author's note — content + placement (depth/frequency)."""
    store = _save_store(slug)
    content = str(body.get("content", "") or "")
    depth = body.get("depth") if body.get("depth") in ("system", "tail") else "system"
    try:
        every = max(1, int(body.get("every", 1)))
    except (TypeError, ValueError):
        every = 1
    with _exclusive():                           # don't race a live turn's state write
        # custom_instructions() reads the body BELOW the first `---`; keep whatever
        # header sits above it (the template's, or the user's own) instead of nuking it.
        existing = store.read("custom-instructions.md")
        head = existing.split("---", 1)[0] if "---" in existing \
            else "# Custom instructions (this save)\n\n"
        store.write("custom-instructions.md", head + "---\n" + content)
        state = store.world_state()
        state["authors_note"] = {"depth": depth, "every": every}
        store.set_world_state(state)
    return {"ok": True}


# ---------- Tier 4 play aids: quick actions (ST-30) + regex rules (ST-31) ----------
def _clean_quick_actions(raw) -> list[str]:
    if isinstance(raw, str):
        raw = raw.split("\n")
    if not isinstance(raw, list):
        return []
    return [s.strip() for s in raw if isinstance(s, str) and s.strip()][:20]


def _clean_regex_rules(raw) -> list[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for r in raw:
        if not isinstance(r, dict):
            continue
        find = r.get("find")
        # a non-string or ReDoS-prone pattern is dropped on save (import re-checks
        # at exec time too, since import bypasses this cleaning layer).
        if not isinstance(find, str) or not safe_output_regex(find):
            continue
        out.append({"find": find, "replace": str(r.get("replace", ""))[:1000],
                    "flags": "".join(c for c in str(r.get("flags", "")).lower()
                                     if c in "ims")})
        if len(out) >= 30:
            break
    return out


@app.get("/api/saves/{slug}/rpg")
def get_rpg(slug: str):
    """I-329: structured sheet + combat data for character-sheet.html and
    combat-canvas.js — see `_rpg_payload`."""
    return _rpg_payload(_save_store(slug))


@app.get("/api/saves/{slug}/aids")
def get_aids(slug: str):
    ws = _save_store(slug).world_state()
    return {"quick_actions": _clean_quick_actions(ws.get("quick_actions")),
            "regex_rules": _clean_regex_rules(ws.get("regex_rules"))}


@app.put("/api/saves/{slug}/aids")
def put_aids(slug: str, body: dict):
    """ST-30 per-save quick actions + ST-31 persistent output regex rules."""
    store = _save_store(slug)
    qa = _clean_quick_actions(body.get("quick_actions"))
    rules = _clean_regex_rules(body.get("regex_rules"))
    with _exclusive():                           # don't race a live turn's state write
        state = store.world_state()
        state["quick_actions"] = qa
        state["regex_rules"] = rules
        store.set_world_state(state)
    return {"ok": True}


@app.put("/api/saves/{slug}/world/main")
def save_world_main(slug: str, body: dict):
    store = _save_store(slug)
    premise = str(body.get("premise", "")).strip()
    world = str(body.get("world", "")).strip()
    title = str(body.get("title", "")).strip()
    with _exclusive():                           # don't race a live turn's state write
        # Preserve the opening unless the caller sends one: a live save's intro is
        # already in the transcript, and the builder hides that field for saves.
        intro = str(body.get("introduction", store.opening_override())).strip()
        _write_premise_md(store, premise, intro)
        store.write("world-bible.md", "# World bible\n\n"
                    + (world + "\n" if world else ""))
        if title:
            lib.saves.rename(slug, title)
    return {"ok": True}


@app.put("/api/saves/{slug}/world/pieces/{rel}")
def save_world_piece_put(slug: str, rel: str, body: dict):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    entry = _entry_from_dict(body.get("entry") or {})
    old = str(body.get("old_slug", "")).strip()
    with _exclusive():                           # don't race a live turn's state write
        store.upsert_entry(rel, entry)
        if old and old != entry.slug:
            store.remove_entry(rel, old)
    return {"ok": True, "slug": entry.slug}


@app.delete("/api/saves/{slug}/world/pieces/{rel}/{pslug}")
def save_world_piece_delete(slug: str, rel: str, pslug: str):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    with _exclusive():                           # don't race a live turn's state write
        if not store.remove_entry(rel, pslug):
            raise HTTPException(404, f"no such piece: {pslug}")
    return {"ok": True}


@app.post("/api/saves/{slug}/world/types")
def save_world_add_type(slug: str, body: dict):
    _save_store(slug)                          # 404 guard
    with _exclusive():                           # meta.json write vs. a live turn
        return {"file": _declare_type_in(lib.saves.dir(slug), "meta.json",
                                         str(body.get("name", "")))}


@app.delete("/api/saves/{slug}/world/types/{fname}")
def save_world_delete_type(slug: str, fname: str):
    _save_store(slug)
    with _exclusive():                           # meta.json write vs. a live turn
        return _delete_type_in(lib.saves.dir(slug), "meta.json", fname)


@app.get("/api/saves/{slug}/world/pieces/{rel}/export")
def save_world_section_export(slug: str, rel: str):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    path = lib.saves.dir(slug) / rel
    if not path.exists():
        raise HTTPException(404, f"{rel} has no content yet")
    return FileResponse(path, filename=f"{slug}-{rel}",
                        media_type="text/markdown")


@app.post("/api/saves/{slug}/world/from-library")
def save_world_insert_character(slug: str, body: dict):
    char = characters.get(str(body.get("id", "")).strip())
    if char is None:
        raise HTTPException(404, "no such character")
    store = _save_store(slug)
    entry = entry_from_character(char)
    with _exclusive():                           # don't race a live turn's state write
        store.upsert_entry("characters.md", entry)
    return {"ok": True, "slug": entry.slug}


@app.post("/api/saves/{slug}/world/from-piece-library")
def save_world_insert_piece(slug: str, body: dict):
    rec = pieces_lib.get(str(body.get("id", "")).strip())
    if rec is None:
        raise HTTPException(404, "no such library piece")
    entry = pieces_lib.entry(rec["id"])
    rel = _kind_to_rel(rec.get("type", ""))
    store = _save_store(slug)
    with _exclusive():                           # don't race a live turn's state write
        if rel not in _piece_files(store):
            _declare_type_in(lib.saves.dir(slug), "meta.json", rel.removesuffix(".md"))
            store = _save_store(slug)
        store.upsert_entry(rel, entry)
    return {"ok": True, "rel": rel, "slug": entry.slug}


@app.get("/api/scenarios/{slug}/playable")
def scenario_playable(slug: str):
    """The world's playable characters (`playable: true` in characters.md) —
    what the new-story dialog offers as 'Play as'."""
    store = _scen_store(slug)
    out = [{"slug": e.slug, "title": e.title,
            "blurb": e.body.strip().splitlines()[0][:120]
            if e.body.strip() else ""}
           for e in store.entries("characters.md")
           if str(e.attrs.get("playable", "")).strip().lower()
           in ("true", "yes", "1", "on")]
    return {"playable": out}


@app.post("/api/assist")
def assist(body: dict):
    """Per-field AI assist for the builder: seed a section from a one-line
    idea, or improve existing content. Piece kinds return a full entry."""
    kind = str(body.get("kind", "")).strip().lower()
    mode = str(body.get("mode", "seed")).strip().lower()
    text = str(body.get("text", ""))
    improve = bool(body.get("improve", False))
    context = ""
    scen = str(body.get("scenario", "")).strip()
    if scen and lib.scenarios.exists(scen):
        context = _scenario_context(_scen_store(scen))
    if not _gen_lock.acquire(blocking=False):
        raise HTTPException(409, "another generation is running")
    try:
        llm = LLM(_cfg.profile, _cfg.generation)
        result, err = assist_field(llm, kind, mode, text, context=context,
                                   improve=improve)
    finally:
        _gen_lock.release()
    if err:
        raise HTTPException(502, err)
    if isinstance(result, Entry):
        return {"entry": _entry_dict(result)}
    return {"text": result}


@app.post("/api/scenarios/{slug}/complete")
def scenario_complete(slug: str, body: dict):
    """'Generate the rest with AI' (SSE): fill only what's missing, keep
    everything the user wrote."""
    _guard_slug(slug)                            # every sibling scenario endpoint guards
    def _n(key, default=5):
        try:
            return max(0, min(20, int(body.get(key, default))))
        except (TypeError, ValueError):
            return default
    spec = ScenarioSpec(
        type=str(body.get("type", "")).strip(),
        tone=str(body.get("tone", "")).strip(),
        premise=str(body.get("premise", "")).strip(),
        n_npcs=_n("n_npcs"), n_locations=_n("n_locations"),
        n_items=_n("n_items"),
        detail="fast" if body.get("detail") == "fast" else "rich",
        improve=bool(body.get("improve", False)))

    def gen():
        if not _gen_lock.acquire(blocking=False):
            yield _sse({"t": "error", "text": "another generation is running"})
            return
        try:
            q: queue.Queue = queue.Queue()
            result: dict = {}

            def worker():
                try:
                    llm = LLM(_cfg.profile, _cfg.generation)
                    result["warnings"] = complete_scenario(
                        lib, llm, slug, spec, on_stage=lambda s: q.put(s))
                except Exception as e:  # noqa: BLE001
                    result["error"] = str(e)
                q.put(None)

            threading.Thread(target=worker, daemon=True).start()
            while True:
                msg = q.get()
                if msg is None:
                    break
                yield _sse({"t": "stage", "text": msg})
            if "error" in result:
                yield _sse({"t": "error", "text": result["error"]})
            else:
                yield _sse({"t": "done", "slug": slug,
                            "events": result.get("warnings", [])})
        finally:
            _gen_lock.release()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.delete("/api/scenarios/{slug}")
def delete_scenario(slug: str):
    _guard_slug(slug)
    if not lib.scenarios.delete(slug):
        raise HTTPException(404, f"no such scenario: {slug}")
    return {"ok": True}


@app.post("/api/scenarios/generate")
def generate_scenario_ep(body: dict):
    """AI world generation (SSE). Streams every stage note; `improve: true`
    runs the user's prompt through the detailer/improver first."""
    def _n(key, default=5):
        try:
            return max(0, min(20, int(body.get(key, default))))
        except (TypeError, ValueError):
            return default
    spec = ScenarioSpec(
        type=str(body.get("type", "")).strip(),
        tone=str(body.get("tone", "")).strip(),
        premise=str(body.get("premise", "")).strip(),
        n_npcs=_n("n_npcs"), n_locations=_n("n_locations"),
        n_items=_n("n_items"),
        detail="fast" if body.get("detail") == "fast" else "rich",
        improve=bool(body.get("improve", False)))

    def gen():
        if not _gen_lock.acquire(blocking=False):
            yield _sse({"t": "error", "text": "another generation is running"})
            return
        try:
            q: queue.Queue = queue.Queue()
            result: dict = {}

            def worker():
                try:
                    llm = LLM(_cfg.profile, _cfg.generation)
                    result["slug"] = generate_scenario(
                        lib, llm, spec, on_stage=lambda s: q.put(s))
                    result["warnings"] = list(generate_scenario.last_warnings)
                except Exception as e:  # noqa: BLE001
                    result["error"] = str(e)
                q.put(None)

            threading.Thread(target=worker, daemon=True).start()
            while True:
                msg = q.get()
                if msg is None:
                    break
                yield _sse({"t": "stage", "text": msg})
            if "error" in result:
                yield _sse({"t": "error", "text": result["error"]})
            else:
                scen = next((s for s in lib.scenarios.list()
                             if s["slug"] == result["slug"]), {})
                yield _sse({"t": "done", "slug": result["slug"],
                            "title": scen.get("title", result["slug"]),
                            "events": result.get("warnings", [])})
        finally:
            _gen_lock.release()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------- library <-> scenario character exchange ----------
@app.post("/api/scenarios/{slug}/from-library")
def scenario_insert_character(slug: str, body: dict):
    """Drop a saved library character into a world as a characters.md piece
    (playable sheets land with `playable: true`)."""
    char = characters.get(str(body.get("id", "")).strip())
    if char is None:
        raise HTTPException(404, "no such character")
    store = _scen_store(slug)
    entry = entry_from_character(char)
    store.upsert_entry("characters.md", entry)
    return {"ok": True, "slug": entry.slug}


@app.post("/api/characters/from-entry")
def character_save_entry(body: dict):
    """Save a scenario piece back into the character library."""
    entry = _entry_from_dict(body.get("entry") or {})
    return characters.save(character_from_entry(entry))


# ---------- generic piece library (locations/items/factions/…) ----------
def _kind_to_rel(kind: str) -> str:
    info = PIECE_KINDS.get(kind)
    return info[3] if info else templates.slugify(kind) + ".md"


@app.get("/api/library")
def list_library(type: str = ""):
    return {"pieces": pieces_lib.list(type), "types": pieces_lib.types()}


@app.post("/api/library")
def save_library_piece(body: dict):
    try:
        return pieces_lib.save(str(body.get("type", "")),
                               body.get("entry") or {},
                               pid=str(body.get("id", "")).strip())
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/library/{pid}")
def delete_library_piece(pid: str):
    if not pieces_lib.delete(pid):
        raise HTTPException(404, "no such library piece")
    return {"ok": True}


@app.post("/api/scenarios/{slug}/from-piece-library")
def scenario_insert_piece(slug: str, body: dict):
    """Drop a library piece into a world — its type's registry file; a custom
    type the world doesn't have yet is declared on the fly."""
    rec = pieces_lib.get(str(body.get("id", "")).strip())
    if rec is None:
        raise HTTPException(404, "no such library piece")
    entry = pieces_lib.entry(rec["id"])
    rel = _kind_to_rel(rec.get("type", ""))
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        _declare_custom_type(slug, rel.removesuffix(".md"))
        store = _scen_store(slug)          # re-read the declaration
    store.upsert_entry(rel, entry)
    return {"ok": True, "rel": rel, "slug": entry.slug}


# ---------- exports ----------
_EXPORT_DIR = Path(tempfile.gettempdir()) / "coderain-exports"


@app.get("/api/saves/{slug}/export")
def export_save(slug: str):
    _guard_slug(slug)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path = lib.saves.export(slug, _EXPORT_DIR / f"save-{slug}.zip")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, filename=f"save-{slug}.zip",
                        media_type="application/zip")


def _stash_upload(file: UploadFile) -> Path:
    """Persist a multipart upload to a temp .zip so the library import_ helpers
    (which take a path) can read it. The file keeps its original name inside a
    unique dir so the import's derived slug reads well (the 'save-'/'world-'
    export prefix is stripped). Caller removes the dir's parent."""
    name = (file.filename or "").strip()
    if not name.lower().endswith(".zip"):
        raise HTTPException(400, "expected a .zip export")
    stem = Path(name).stem
    for pfx in ("save-", "world-", "user-"):
        if stem.startswith(pfx):
            stem = stem[len(pfx):]
    stem = "".join(c for c in stem if c.isalnum() or c in "-_ ") or "import"
    holder = _EXPORT_DIR / f"in-{uuid.uuid4().hex}"
    holder.mkdir(parents=True, exist_ok=True)
    dest = holder / f"{stem}.zip"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return dest


@app.post("/api/saves-import")
def import_save(file: UploadFile = File(...)):
    path = _stash_upload(file)
    try:
        slug = lib.saves.import_(path)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    return {"ok": True, "slug": slug}


@app.post("/api/cards-import")
def import_card(file: UploadFile = File(...)):
    """Import a SillyTavern/Tavern character card (PNG/JSON/charx) as a new World
    (ST-01): scenario→premise, first_mes→introduction, the character→a piece (+
    the reusable Pieces library), embedded lorebook→lore pieces."""
    from coderain import cards as cards_mod
    _MAX_UPLOAD = 32 * 1024 * 1024                        # 32 MB compressed ceiling
    raw = file.file.read(_MAX_UPLOAD + 1)
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(413, "card file too large (max 32 MB)")
    try:
        card = cards_mod.parse_card(raw, file.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))

    name = card["name"]
    sub = lambda t: cards_mod.substitute_macros(t, name)     # noqa: E731
    premise = sub(card["scenario"]) or sub(card["description"]) \
        or f"A story featuring {name}."
    intro = sub(card["first_mes"])
    desc_short = sub(card["description"])[:140]
    slug = lib.scenarios.create(name, premise, description=desc_short,
                                introduction=intro)
    store = _scen_store(slug)

    # The card's character → a characters.md piece (NPC).
    body = sub(card["description"])
    if card["personality"]:
        body += f"\n\n**Personality:** {sub(card['personality'])}"
    if card["mes_example"]:
        body += f"\n\n**Example dialogue:**\n{sub(card['mes_example'])}"
    store.upsert_entry("characters.md", Entry(
        title=name, slug=templates.slugify(name), aliases=[], importance=4,
        attrs={}, body=body.strip()))

    # Embedded lorebook → pieces in a declared custom 'lore' file.
    if card["lore"]:
        _declare_type_in(lib.scenarios.dir(slug), "scenario.json", "lore")
        store = _scen_store(slug)
        for e in card["lore"]:
            # Resolve {{char}}/{{user}} at import like every other card field, so
            # only intentional ST-20 macros survive to assemble time (no raw
            # {{char}} leak, and {{user}} matches the other fields).
            title = sub(e["title"])
            keys = [sub(k) for k in e["keys"]]
            store.upsert_entry("lore.md", Entry(
                title=title, slug=templates.slugify(title),
                aliases=keys, importance=3,
                attrs={"triggers": ", ".join(keys)} if keys else {},
                body=sub(e["content"])))

    # Also drop the character into the reusable Pieces library.
    try:
        characters.save({"name": name, "kind": "npc",
                         "description": sub(card["description"])})
    except Exception:  # noqa: BLE001 — library add is best-effort
        pass
    return {"ok": True, "slug": slug,
            "counts": {"lore": len(card["lore"]),
                       "greetings": len(card["alternate_greetings"])}}


@app.post("/api/scenarios-import")
def import_scenario(file: UploadFile = File(...)):
    path = _stash_upload(file)
    try:
        slug = lib.scenarios.import_(path)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    return {"ok": True, "slug": slug}


@app.post("/api/defaults-import")
def import_defaults(file: UploadFile = File(...)):
    """Restore a user-defaults.zip into the instructions dir (overwrites the
    files it contains; leaves others alone). Path-traversal guarded."""
    path = _stash_upload(file)
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if not _safe_zip_member(lib.instructions_dir, n):  # traversal+absolute
                    continue
                target = lib.instructions_dir / n
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as srcf, open(target, "wb") as outf:
                    shutil.copyfileobj(srcf, outf)
    except zipfile.BadZipFile as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
    return {"ok": True}


@app.get("/api/scenarios/{slug}/export")
def export_scenario(slug: str):
    _guard_slug(slug)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path = lib.scenarios.export(slug, _EXPORT_DIR / f"world-{slug}.zip")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, filename=f"world-{slug}.zip",
                        media_type="application/zip")


# ---------- user defaults (Library section) ----------
def _default_kind(name: str) -> str:
    return "rule" if name in templates.RULE_FILES else "skeleton"


def _defaultable(name: str) -> None:
    if name not in list(templates.RULE_FILES) + templates.USER_DEFAULTABLE:
        raise HTTPException(404, f"not a user-defaultable file: {name}")


@app.get("/api/defaults")
def list_defaults():
    out = []
    for name in list(templates.RULE_FILES) + templates.USER_DEFAULTABLE:
        kind = _default_kind(name)
        if kind == "rule":
            p = lib.instructions_dir / name
            customized = p.exists() and \
                p.read_text(encoding="utf-8") != templates.default_rule(name)
        else:
            customized = (lib.instructions_dir / "defaults" / name).exists()
        out.append({"name": name, "kind": kind, "customized": customized})
    return {"defaults": out}


@app.get("/api/defaults/{name}")
def get_default(name: str):
    _defaultable(name)
    if _default_kind(name) == "rule":
        p = lib.instructions_dir / name
        text = p.read_text(encoding="utf-8") if p.exists() \
            else templates.default_rule(name)
    else:
        text = templates.user_default(name, lib.instructions_dir)
    return {"name": name, "text": text}


@app.put("/api/defaults/{name}")
def put_default(name: str, body: dict):
    _defaultable(name)
    text = str(body.get("text", ""))
    if _default_kind(name) == "rule":
        (lib.instructions_dir / name).write_text(text, encoding="utf-8")
        lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
    else:
        d = lib.instructions_dir / "defaults"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")
    return {"ok": True}


@app.post("/api/defaults/{name}/revert")
def revert_default(name: str):
    _defaultable(name)
    if _default_kind(name) == "rule":
        (lib.instructions_dir / name).write_text(
            templates.default_rule(name), encoding="utf-8")
        lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
    else:
        try:
            (lib.instructions_dir / "defaults" / name).unlink()
        except FileNotFoundError:
            pass
    return get_default(name)


@app.get("/api/defaults-export")
def export_defaults():
    import zipfile
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    dest = _EXPORT_DIR / "user-defaults.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(lib.instructions_dir.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(lib.instructions_dir).as_posix())
    return FileResponse(dest, filename="user-defaults.zip",
                        media_type="application/zip")


# ---------- characters ----------
@app.get("/api/characters")
def list_characters():
    return {"characters": characters.list(), "stats": STAT_NAMES}


@app.post("/api/characters")
def save_character(body: dict):
    return characters.save(body if isinstance(body, dict) else {})


@app.delete("/api/characters/{cid}")
def delete_character(cid: str):
    if not characters.delete(cid):
        raise HTTPException(404, "no such character")
    return {"ok": True}


# ---------- models + settings ----------
@app.get("/api/models/local")
def local_models():
    """Installed Ollama models for the local dropdowns (live from the daemon;
    static suggestions as a fallback when it's not running)."""
    installed: list[dict] = []
    error = ""
    try:
        r = httpx.get(OLLAMA_TAGS, timeout=3)
        r.raise_for_status()
        for m in r.json().get("models", []):
            size_gb = round((m.get("size", 0) or 0) / 1e9, 1)
            installed.append({"name": m.get("name", ""),
                              "size": f"{size_gb} GB"})
    except Exception as e:  # noqa: BLE001
        error = f"Ollama not reachable ({e.__class__.__name__})"
    return {"installed": installed, "error": error,
            "howto": models_mod.LOCAL_HOWTO,
            "suggestions": [{"name": n, "kind": kind, "size": size,
                             "note": note}
                            for n, kind, size, note
                            in models_mod.LOCAL_SUGGESTIONS]}


@app.get("/api/models/hosted")
def hosted_models():
    return {"presets": models_mod.HOSTED_PRESETS,
            "hints": models_mod.context_hint_lines(),
            "platforms": models_mod.platform_comparison_lines(),
            "howto": models_mod.HOSTED_HOWTO,
            "recommended_min": models_mod.RECOMMENDED_MIN_CONTEXT}


@app.get("/api/settings")
def get_settings():
    raw = _cfg.raw
    trinity = raw.get("trinity") or {}
    local = raw.get("profiles", {}).get("local", {})
    hosted = raw.get("profiles", {}).get("hosted", {})
    return {
        "mode": "hosted" if raw.get("active_profile") == "hosted" else "local",
        "local": {
            "director": (trinity.get("director") or {}).get("model")
            or local.get("model", ""),
            # No base-model fallback: the lore-keeper is OPT-IN, so an unset
            # stage must read back as "" (the dropdown's "(none)") — otherwise
            # the UI would imply a continuity pass that isn't actually running.
            "lorekeeper": (trinity.get("lorekeeper") or {}).get("model", ""),
            "writer": (trinity.get("writer") or {}).get("model")
            or local.get("model", ""),
            "context_tokens": local.get("context_tokens", 16384),
        },
        "hosted": {
            "model": hosted.get("model", ""),
            "base_url": hosted.get("base_url", ""),
            "context_tokens": hosted.get("context_tokens", 131072),
            "key_set": bool(read_env().get(HOSTED_KEY_ENV, "")),
        },
        "generation": {
            "response_length":
                _cfg.generation.get("response_length", "medium"),
            "trinity_brain": bool(_cfg.generation.get("trinity_brain", True)),
            "start_reply_with": _cfg.generation.get("start_reply_with", ""),
            "stop": _cfg.generation.get("stop", []),
            "temperature": _cfg.generation.get("temperature", 0.9),
            "top_p": _cfg.generation.get("top_p", 0.95),
            "max_tokens": _cfg.generation.get("max_tokens", 2500),
            "frequency_penalty": _cfg.generation.get("frequency_penalty"),
            "presence_penalty": _cfg.generation.get("presence_penalty"),
            "repetition_penalty": _cfg.generation.get("repetition_penalty"),
            "seed": _cfg.generation.get("seed"),
        },
        "quick_actions": _clean_quick_actions(_cfg.raw.get("quick_actions")),
    }


@app.put("/api/settings")
def put_settings(body: dict):
    raw = _cfg.raw
    mode = body.get("mode") if body.get("mode") in ("local", "hosted") \
        else "local"
    if "quick_actions" in body:                 # ST-30 global quick actions
        raw["quick_actions"] = _clean_quick_actions(body.get("quick_actions"))
    gen = body.get("generation") or {}
    raw.setdefault("generation", {})
    if gen.get("response_length") in ("short", "medium", "long"):
        raw["generation"]["response_length"] = gen["response_length"]
    if "trinity_brain" in gen:
        raw["generation"]["trinity_brain"] = bool(gen["trinity_brain"])
    # ST-22 persistent reply prefix (literal; every generated turn starts with it)
    if "start_reply_with" in gen:
        raw["generation"]["start_reply_with"] = str(gen["start_reply_with"] or "")[:300]
    # ST-24 custom stop sequences (accepts a list or newline-separated string)
    if "stop" in gen:
        stop = gen["stop"]
        if isinstance(stop, str):
            stop = stop.split("\n")
        raw["generation"]["stop"] = ([s.strip() for s in stop
                                      if isinstance(s, str) and s.strip()][:8]
                                     if isinstance(stop, list) else [])
    # ST-26 core samplers (always set; clamped to sane ranges)
    for key, lo, hi, cast in (("temperature", 0.0, 2.0, float),
                              ("top_p", 0.0, 1.0, float),
                              ("max_tokens", 1, 100000, int)):
        if key in gen and gen[key] not in (None, ""):
            try:
                raw["generation"][key] = max(lo, min(hi, cast(gen[key])))
            except (TypeError, ValueError):
                pass
    # ST-26 opt-in samplers: set within range, or clear (None/"") -> provider default
    for key, lo, hi, cast in (("frequency_penalty", -2.0, 2.0, float),
                              ("presence_penalty", -2.0, 2.0, float),
                              ("repetition_penalty", 0.0, 2.0, float),
                              ("seed", 0, 2**31 - 1, int)):
        if key in gen:
            if gen[key] in (None, ""):
                raw["generation"].pop(key, None)
            else:
                try:
                    raw["generation"][key] = max(lo, min(hi, cast(gen[key])))
                except (TypeError, ValueError):
                    pass

    if mode == "local":
        loc = body.get("local") or {}
        profile = raw.setdefault("profiles", {}).setdefault("local", {})
        profile.setdefault("base_url", "http://localhost:11434/v1")
        profile.setdefault("api_key_env", "OLLAMA_API_KEY")
        try:
            profile["context_tokens"] = max(
                models_mod.MIN_CONTEXT_TOKENS,
                int(loc.get("context_tokens",
                            profile.get("context_tokens", 16384))))
        except (TypeError, ValueError):
            pass
        director = str(loc.get("director", "")).strip()
        writer = str(loc.get("writer", "")).strip()
        keeper = str(loc.get("lorekeeper", "")).strip()
        if director:
            profile["model"] = director
        trinity = {}
        for stage, model in (("director", director), ("lorekeeper", keeper),
                             ("writer", writer)):
            if model:
                trinity[stage] = {"profile": "local", "model": model}
        # Choosing a lore-keeper model is what TURNS THE PASS ON — "(none)"
        # leaves the stage absent, so trinity.lore_llm_pass stays False.
        if keeper:
            trinity["lorekeeper"]["llm_pass"] = True
        if trinity:
            raw["trinity"] = trinity
        else:
            raw.pop("trinity", None)
        raw["active_profile"] = "local"
    else:
        ho = body.get("hosted") or {}
        model = str(ho.get("model", "")).strip()
        base_url = str(ho.get("base_url", "")).strip()
        if not model or not base_url:
            raise HTTPException(400, "hosted mode needs a model and base URL")
        try:
            ctx = max(models_mod.MIN_CONTEXT_TOKENS,
                      int(ho.get("context_tokens", 131072)))
        except (TypeError, ValueError):
            ctx = 131072
        raw.setdefault("profiles", {})["hosted"] = {
            "base_url": base_url, "model": model,
            "api_key_env": HOSTED_KEY_ENV, "context_tokens": ctx,
        }
        key = str(ho.get("api_key", "")).strip()
        if key:
            write_env({HOSTED_KEY_ENV: key})
        # One big dual-mode model serves every stage — drop the local pins.
        raw.pop("trinity", None)
        raw["active_profile"] = "hosted"

    save_yaml(raw)
    _reload_config()
    return get_settings()


# ---------- ST-25 connection profiles (named connection bundles) ----------
def _profiles_saved() -> dict:
    p = _cfg.raw.get("connection_profiles")
    return p if isinstance(p, dict) else {}


@app.get("/api/profiles")
def list_profiles():
    saved = _profiles_saved()
    active = _cfg.raw.get("active_profile_name", "")
    return {"profiles": sorted(saved.keys()),
            "active": active if active in saved else ""}   # never a dangling pointer


@app.post("/api/profiles")
def save_profile(body: dict):
    """Snapshot the CURRENT active connection under a name."""
    name = str(body.get("name", "")).strip()
    if not name or "/" in name or "\\" in name or len(name) > 60:
        raise HTTPException(400, "profile name must be 1-60 chars with no slashes")
    raw = _cfg.raw
    kind = raw.get("active_profile", "local")
    src = (raw.get("profiles") or {}).get(kind, {})
    # Never snapshot an empty connection: a profile without base_url/model would
    # persist a config that crashes load_config on the next boot.
    if not (src.get("base_url") and src.get("model")):
        raise HTTPException(400, "the active connection has no model/URL to save yet")
    saved = raw.setdefault("connection_profiles", {})
    saved[name] = {"kind": kind, **{k: src[k] for k in
                   ("base_url", "model", "api_key_env", "context_tokens")
                   if k in src}}
    raw["active_profile_name"] = name
    save_yaml(raw)
    _reload_config()
    return list_profiles()


@app.post("/api/profiles/activate")
def activate_profile(body: dict):
    name = str(body.get("name", "")).strip()
    saved = _profiles_saved().get(name)
    if not isinstance(saved, dict):
        raise HTTPException(404, f"no such profile: {name}")
    raw = _cfg.raw
    kind = saved.get("kind", "local")
    raw.setdefault("profiles", {})[kind] = {k: v for k, v in saved.items()
                                            if k != "kind"}
    raw["active_profile"] = kind
    raw["active_profile_name"] = name
    save_yaml(raw)
    _reload_config()
    return get_settings()


@app.delete("/api/profiles/{name}")
def delete_profile(name: str):
    raw = _cfg.raw
    if isinstance(raw.get("connection_profiles"), dict):
        raw["connection_profiles"].pop(name, None)
        if raw.get("active_profile_name") == name:
            raw["active_profile_name"] = ""
        save_yaml(raw)
        _reload_config()
    return list_profiles()


# ---------- static SPA ----------
@app.get("/")
def index():
    return FileResponse(ASSETS / "webapp" / "index.html")


app.mount("/", StaticFiles(directory=ASSETS / "webapp"), name="webapp")


if __name__ == "__main__":
    import os
    _port = int((os.environ.get("CODERAIN_PORT") or "8377").strip() or "8377")
    uvicorn.run(app, host="127.0.0.1", port=_port)
