"""Coderain CLI.

Régime SECONDAIRE (D-267) — flexibilité locale/API ; le produit joué passe
par le chemin MCP/forfait, pas par ici.

Usage:
    py play.py

Storage is three layers: global rule files in `instructions/` (shared by all
saves), reusable worlds in `scenarios/`, and playthroughs in `saves/`.

Commands during play:
    /new         start a new save (pick or create a scenario)
    /load        list and load an existing save
    /scenarios   list / create reusable worlds
    /gen         auto-generate a scenario (type/tone/summary + counts)
    /duplicate   copy the current save into a new one
    /branch N    fork the story at turn N (state + memory as of that turn)
    /rename NEW  rename the current save
    /delete      delete a save (pick from a list)
    /export PATH zip the current save to PATH (backup / share)
    /import PATH load a save zip into a new save
    /rpg on|off  toggle the RPG mechanics module for this save
    /sheet       show your character sheet (RPG on)
    /talk NAME   private side-chat with a companion (blank line to exit)
    /resetrules  restore the global writer/memory/rpg rules to app defaults
    /profile     show the active model profile
    /retry       regenerate the last narration
    /undo        remove the last exchange (no regeneration)
    /quit        exit
Anything else is your action in the story.
"""
from __future__ import annotations

import os
import sys

# Windows consoles often default to cp1252, which can't print the arrows/dots in
# event strings ("time → Day 2") or model prose — reconfigure instead of crashing.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — cosmetic; never block the CLI on this
            pass

from coderain.features import pro_module
rpg_mod = pro_module("rpg")  # None on a free install
from coderain.config import ROOT, load_config
from coderain.engine import Engine
from coderain.memory import Library


def _stream(engine_iter):
    for piece in engine_iter:
        sys.stdout.write(piece)
        sys.stdout.flush()
    print("\n")


def _stage(msg):
    """Progress marker for the Trinity Brain's stages (no-op noise when single-brain)."""
    print(f"· {msg}...")


def pick_scenario(lib: Library) -> str:
    scens = lib.scenarios.list()
    print("\nScenarios (reusable worlds):")
    for i, s in enumerate(scens, 1):
        print(f"  [{i}] {s['title']}  ({s['slug']})")
    print("  [c] create a new scenario")
    ans = input("Pick a scenario> ").strip().lower()
    if ans == "c" or not ans:
        return create_scenario(lib)
    if ans.isdigit() and 1 <= int(ans) <= len(scens):
        return scens[int(ans) - 1]["slug"]
    return create_scenario(lib)


def create_scenario(lib: Library) -> str:
    print("\n--- New scenario (a reusable world) ---")
    title = input("Title: ").strip() or "Untitled World"
    print("Premise / scenario. Blank for a default dark-fantasy opening.")
    from coderain.templates import DEFAULT_PREMISE
    premise = input("Premise: ").strip() or DEFAULT_PREMISE
    world = input("World bible (optional, one line, blank to skip): ").strip()
    intro = input("Introduction — the first message every story opens with "
                  "(optional, blank to skip): ").strip()
    slug = lib.scenarios.create(title, premise, world=world,
                                introduction=intro)
    print(f"Created scenario '{title}' ({slug}).")
    return slug


def new_save(lib: Library, cfg=None) -> str:
    scen = pick_scenario(lib)
    scen_title = next((s["title"] for s in lib.scenarios.list()
                       if s["slug"] == scen), scen)
    title = input(f"Save name [{scen_title}]: ").strip() or scen_title
    mode = "rpg" if input(
        "Story mode — [s]imple (fast, pure narrative) or [r]pg campaign "
        "(stats, dice, quests)? [s]: ").strip().lower().startswith("r") \
        else "simple"
    slug = lib.saves.create(title, scen, mode=mode,
                            rpg_cfg=cfg.rpg if cfg else None)
    print(f"Created save '{title}' ({slug}, {mode} mode).")
    return slug


def choose_save(lib: Library, cfg=None) -> str:
    saves = lib.saves.list()
    if saves:
        print("\nSaves:")
        for i, s in enumerate(saves, 1):
            scen = f"  ← {s['scenario']}" if s.get("scenario") else ""
            print(f"  [{i}] {s['title']}  ({s['slug']}){scen}")
    print("\nType a number to load, or press Enter to start a new save.")
    ans = input("> ").strip()
    if ans.isdigit() and 1 <= int(ans) <= len(saves):
        return saves[int(ans) - 1]["slug"]
    return new_save(lib, cfg)


def _open(lib: Library, cfg, slug: str):
    store = lib.saves.open(slug)  # session-open snapshot (I-148/ESC-4)
    engine = Engine(cfg, store)
    print(f"\n>>> {store.title}"
          f"{'  [RPG]' if store.rpg_enabled() else ''}\n")
    return store, engine


def main():
    cfg = load_config()
    lib = Library(ROOT)
    lib.scenarios.ensure_default()

    print("=" * 60)
    print(f"Coderain v0.3  |  profile: {cfg.profile.name}  "
          f"|  model: {cfg.profile.model}")
    print("=" * 60)
    if lib.outdated_rules:
        print(f"Note: your edited rule file(s) {', '.join(lib.outdated_rules)} differ "
              "from this version's defaults. /resetrules to restore the defaults.")

    slug = choose_save(lib, cfg)
    store, engine = _open(lib, cfg, slug)

    if not store.has_turns():
        print("(setting the scene...)\n")
        try:
            _stream(engine.opening())
        except Exception as e:  # noqa: BLE001
            print(f"\n[error talking to the model: {e}]")
            print("Check config.yaml profile + your .env API key, then /retry.")

    while True:
        try:
            action = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not action:
            continue

        cmd = action.lower()
        parts = action.split(None, 1)
        word = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if cmd in ("/quit", "/exit", "/q"):
            print("Saved. Bye.")
            break
        if cmd == "/profile":
            print(f"profile={cfg.profile.name} model={cfg.profile.model} "
                  f"base_url={cfg.profile.base_url} ctx={cfg.profile.context_tokens}")
            continue
        if cmd == "/new":
            slug = new_save(lib, cfg)
            store, engine = _open(lib, cfg, slug)
            print("(setting the scene...)\n")
            _stream(engine.opening())
            continue
        if cmd in ("/load", "/saves"):
            slug = choose_save(lib, cfg)
            store, engine = _open(lib, cfg, slug)
            if not store.has_turns():
                print("(setting the scene...)\n")
                _stream(engine.opening())
            continue
        if cmd == "/scenarios":
            scens = lib.scenarios.list()
            for i, s in enumerate(scens, 1):
                print(f"  [{i}] {s['title']}  ({s['slug']})  {s['description']}")
            ans = input("[c]reate new, [d]elete one, or Enter to close: "
                        ).strip().lower()
            if ans == "c":
                create_scenario(lib)
            elif ans == "d" and scens:
                which = input("Delete which number? ").strip()
                if which.isdigit() and 1 <= int(which) <= len(scens):
                    victim = scens[int(which) - 1]
                    if input(f"Delete '{victim['title']}'? Existing saves keep their "
                             f"copied world. [y/N]: ").strip().lower() == "y":
                        lib.scenarios.delete(victim["slug"])
                        print("Deleted.")
            continue
        if cmd == "/gen":
            from coderain.generator import ScenarioSpec, generate_scenario
            print("\n--- Auto-generate a scenario (blank = let the AI decide) ---")
            stype = input("Type of scenario: ").strip()
            tone = input("Tone: ").strip()
            premise = input("Premise: ").strip()
            improve = input("Run the prompt through the detailer/improver "
                            "first? [y/N]: ").strip().lower().startswith("y")

            def _count(label):
                raw = input(f"How many {label}? [5]: ").strip()
                return int(raw) if raw.isdigit() else 5
            n_npcs, n_locs = _count("NPCs"), _count("locations")
            n_items = _count("items")
            detail = input("Detail — [r]ich (one call per entity, slow) or "
                           "[f]ast (batched)? [r]: ").strip().lower()
            spec = ScenarioSpec(type=stype, tone=tone, premise=premise,
                                n_npcs=n_npcs, n_locations=n_locs, n_items=n_items,
                                detail="fast" if detail.startswith("f") else "rich",
                                improve=improve)
            print("(generating — several model calls, please wait)")
            try:
                new_slug = generate_scenario(
                    lib, engine.llm, spec, on_stage=lambda s: print(f"  · {s}"))
                for w in generate_scenario.last_warnings:
                    print(f"  ! {w}")
                gtitle = next((sc["title"] for sc in lib.scenarios.list()
                               if sc["slug"] == new_slug), new_slug)
                print(f"Created scenario '{gtitle}' ({new_slug}). "
                      f"Use /new to start a save from it.")
            except Exception as e:  # noqa: BLE001
                print(f"[generation failed: {e}]")
            continue
        if cmd == "/duplicate":
            new_slug = lib.saves.duplicate(slug)
            print(f"Duplicated to '{lib.saves.meta(new_slug)['title']}' ({new_slug}). "
                  f"Use /load to switch to it.")
            continue
        if word == "/branch":
            total = len(store.turns())
            n = arg
            if not n.isdigit():
                n = input(f"Branch from turn (1..{total}): ").strip()
            if not n.isdigit() or not (1 <= int(n) <= total):
                print(f"Usage: /branch N  (1..{total})")
                continue
            new_slug, warns = lib.saves.branch(slug, int(n), cfg.rpg)
            for w in warns:
                print(f"  ! {w}")
            print(f"Branched to '{lib.saves.meta(new_slug)['title']}' "
                  f"({new_slug}). Use /load to switch to it.")
            continue
        if cmd.startswith("/rename"):
            new_title = action[len("/rename"):].strip()
            if not new_title:
                new_title = input("New name: ").strip()
            if new_title and lib.saves.rename(slug, new_title):
                store = lib.saves.store(slug)  # refresh title
                print(f"Renamed to '{new_title}'.")
            continue
        if cmd == "/delete":
            saves = lib.saves.list()
            for i, s in enumerate(saves, 1):
                print(f"  [{i}] {s['title']}  ({s['slug']})"
                      f"{'  <- current' if s['slug'] == slug else ''}")
            ans = input("Delete which number (blank to cancel)? ").strip()
            if ans.isdigit() and 1 <= int(ans) <= len(saves):
                victim = saves[int(ans) - 1]["slug"]
                if input(f"Really delete '{saves[int(ans)-1]['title']}'? [y/N]: "
                         ).strip().lower() == "y":
                    lib.saves.delete(victim)
                    print("Deleted.")
                    if victim == slug:
                        slug = choose_save(lib, cfg)
                        store, engine = _open(lib, cfg, slug)
            continue
        if cmd.startswith("/export"):
            path = action[len("/export"):].strip() or f"{slug}.zip"
            arc = lib.saves.export(slug, path)
            print(f"Exported to {os.path.abspath(arc)}")
            continue
        if cmd.startswith("/import"):
            path = action[len("/import"):].strip() or input("Zip path: ").strip()
            if path:
                new_slug = lib.saves.import_(path)
                print(f"Imported as '{lib.saves.meta(new_slug)['title']}' "
                      f"({new_slug}). Use /load to open it.")
            continue
        if word == "/rpg":
            sub = arg.lower()
            state = store.rpg_state()
            if sub in ("on", "off"):
                state["enabled"] = (sub == "on")
                store.set_rpg_state(state)
            print(f"RPG mechanics: {'ON' if store.rpg_enabled() else 'OFF'}"
                  + ("" if sub in ("on", "off") else "  (use /rpg on|off)"))
            continue
        if cmd == "/sheet":
            clock = store.clock_str()
            loc = store.world_state().get("player", {}).get("location", "")
            if clock or loc:
                print("  |  ".join(x for x in (clock, loc and f"at {loc}") if x))
            if store.rpg_enabled():
                print(rpg_mod.render_sheet(store.rpg_state())
                      if rpg_mod is not None
                      else "(Coderain Pro required for the sheet)")
            else:
                print("RPG mechanics are off for this save (/rpg on to enable).")
            continue
        if word == "/talk":
            who = arg
            if not who:
                comps = engine.companions()
                if not comps:
                    print("No companions yet (mark one with `companion: true` "
                          "in characters.md, or let the story recruit one).")
                    continue
                print("Companions: " + ", ".join(comps))
                who = input("Talk to: ").strip()
            if not who:
                continue
            print(f"(private side-chat with {who} — blank line to return "
                  "to the story)")
            while True:
                try:
                    line = input(f"[you → {who}] ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line or line.lower() in ("/back", "/quit"):
                    break
                print(f"[{who}] ", end="", flush=True)
                _stream(engine.companion_chat(who, line))
                print()
            continue
        if cmd == "/resetrules":
            reset = lib.reset_all_rules()
            print("Restored global rule masters to this version's defaults: "
                  + ", ".join(reset))
            print("(Per-save rule overrides, if any, were left untouched.)")
            continue
        if cmd == "/undo":
            if engine.undo_last():
                print("(undone — the last exchange was removed)\n")
            else:
                print("Nothing to undo yet.")
            continue
        if cmd == "/retry":
            turns = store.turns()
            if turns and turns[-1]["role"] == "narrator" and len(turns) >= 2:
                last = turns[-2]["text"]
                store.drop_last_turns(2)
            elif turns and turns[-1]["role"] == "player":
                last = turns[-1]["text"]
                store.drop_last_turns(1)
            else:
                print("Nothing to retry yet.")
                continue
            engine.restore_pre_turn_rpg()  # roll back the retried turn's mechanics
            print("(retrying...)\n")
            _stream(engine.turn(last, on_stage=_stage))
            for event in engine.maybe_fold():
                print(f"· {event}")
            continue

        print()
        try:
            _stream(engine.turn(action, on_stage=_stage))
            for event in engine.maybe_fold():
                print(f"· {event}")
            lib.saves.touch(slug)
        except Exception as e:  # noqa: BLE001
            print(f"\n[error talking to the model: {e}]")


if __name__ == "__main__":
    main()
