"""Chantier 5 (chemin MCP du régime principal, sujet 1/4) : `record_turn` et
sa chaîne d'annulation, outils MCP (jamais l'Engine nu).

Mesuré avant d'écrire ce test (Grep `tests/`, voir le corps de la PR) :
`tests/undo_test.py` couvre `Engine.undo_last` à nu, sans passer par
`mcp_server` ; `tests/test-corrections-dispositif-v2.py` et
`tests/test-ecarts-actes-d419.py` rejouent la LOGIQUE de `retry_turn`/
`undo_last` mais appellent `Engine.apply_envelope`/`Engine.undo_last`
directement, jamais `mcp_server.record_turn`/`mcp_server.undo_last`/
`mcp_server.retry_turn`. Aucun test existant n'appelle ces trois outils MCP
eux-mêmes — ce fichier comble ce trou.

100 % synthétique (D-109), hors ligne (aucun modèle, `engine.llm` jamais
sollicité : on ne lit/n'écrit que par `apply_envelope`/`record_turn`/
`undo_last`/`retry_turn`).

Couvre :
  1. `record_turn` écrit l'action puis la narration (ordre), rend `turns`
     (compte exact) et `fold_due` (False, sous le seuil) ; il réarme le
     signal R1 — `paquet_narrateur` sans nouvelle mécanique, sans
     `sans_mecanique=True`, est refusé juste après (R1 nommé).
  2. `retry_turn()`/`undo_last()` sur un store vide : refus nommé
     (`{"error": ...}`) / `{"undone": False}` — rien à défaire.
  3. `undo_last` défait le DERNIER tour, mécanique comprise : les PV
     reviennent à l'état d'AVANT ce tour, jamais plus loin (un tour
     antérieur, déjà clos, reste intact) — never-deux-tours.
  4. `retry_turn` défait narration + action du dernier tour, restaure la
     mécanique, et rend l'action pour renarration ; même garantie
     never-deux-tours.
  5. Après `undo_last`/`retry_turn`, le signal R1 est réarmé à zéro : un
     `paquet_narrateur` sans mécanique fraîche est de nouveau refusé.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


TMP = Path(tempfile.gettempdir()) / "se_mcp_record_undo_retry_chantier5"
if TMP.exists():
    shutil.rmtree(TMP)

try:
    lib = Library(TMP / "app")
    slug = lib.saves.create("Chantier5-1", premise="Un couloir de pierre.",
                            mode="rpg")
    store = lib.store(slug)
    assert store.mode() == "rpg" and store.rpg_enabled()

    rpg = store.rpg_state()
    rpg.setdefault("player", {})["hp"] = 20
    rpg["player"]["hp_max"] = 20
    store.set_rpg_state(rpg)

    # --- câblage régime PRINCIPAL (même geste que load_save, coderain/mcp/
    # save_installation.py:60-94 — sans save_lock, hors du vrai saves_root) --
    mcp_server._store = store
    mcp_server._slug = slug
    mcp_server._load_rpg()
    mcp_server._cfg = load_config()
    mcp_server._engine = Engine(mcp_server._cfg, store)
    mcp_server._engine.trinity = None
    mcp_server._completed_turn = None
    mcp_server._pending_log_mark = None
    mcp_server._last_applied_events = None
    mcp_server._arm_turn()

    tool_names = {t.name for t in __import__("asyncio").run(
        mcp_server.mcp.list_tools())}
    for outil in ("record_turn", "undo_last", "retry_turn"):
        assert outil in tool_names, f"{outil} absent du serveur MCP"
    section("0) record_turn/undo_last/retry_turn existent comme outils MCP")

    # --- 2) rien à défaire sur un store vide -------------------------------
    r_retry_vide = mcp_server.retry_turn()
    assert r_retry_vide.get("error"), r_retry_vide
    section("2a) retry_turn() sur store vide : refus nommé "
           f"({r_retry_vide['error']!r})")

    r_undo_vide = mcp_server.undo_last()
    assert r_undo_vide["undone"] is False, r_undo_vide
    assert r_undo_vide["mechanics_restored"] is False, r_undo_vide
    section("2b) undo_last() sur store vide : {'undone': False}")

    # --- 1) record_turn : ordre, compte, fold_due, réarmement R1 -----------
    section("1a) R1 : record_turn refusé tant qu'aucune mécanique n'est "
           "résolue ni sans_mecanique déclaré — inchangé, revérifié ici "
           "pour situer le signal AVANT le premier tour")
    try:
        mcp_server.paquet_narrateur("Angle : tension.", "J'avance.")
        raise AssertionError("R1 aurait dû refuser (aucune mécanique)")
    except ValueError as exc:
        assert "R1" in str(exc), str(exc)

    events1 = mcp_server.apply_envelope(
        json.dumps({"v": 1, "deltas": {"hp_delta": -3}}), rpg_on=True)
    assert any("hp" in e for e in events1), events1
    assert mcp_server._last_applied_events is not None
    section("  mécanique résolue (apply_envelope, hp -3) : signal R1 posé")

    r1 = mcp_server.record_turn("J'avance dans le couloir.",
                                "Le couloir s'ouvre sur une salle froide.")
    assert r1["turns"] == 2, r1
    assert r1["fold_due"] is False, r1
    hist = store.turns()
    assert hist[0] == {"role": "player", "text": "J'avance dans le couloir."}
    assert hist[1]["role"] == "narrator" and "froide" in hist[1]["text"]
    section(f"1b) record_turn({{action, narration}}) -> {r1} ; ordre "
           "action puis narration respecté")

    assert mcp_server._last_applied_events is None, \
        "record_turn doit réarmer le signal R1 (remis à None)"
    try:
        mcp_server.paquet_narrateur("Angle : calme.", "J'observe.")
        raise AssertionError(
            "R1 aurait dû refuser juste après record_turn (pas de mécanique "
            "fraîche depuis)")
    except ValueError as exc:
        assert "R1" in str(exc), str(exc)
    section("1c) record_turn réarme le signal R1 : paquet_narrateur "
           "suivant sans mécanique est refusé (R1 nommé)")

    hp_apres_tour1 = store.rpg_state()["player"]["hp"]
    assert hp_apres_tour1 == 17, hp_apres_tour1

    # --- un second tour, mécanique + narration, pour mesurer le --------
    # --- never-deux-tours d'undo_last sur un tour ANTÉRIEUR déjà clos ---
    mcp_server.apply_envelope(
        json.dumps({"v": 1, "deltas": {"hp_delta": -3}}), rpg_on=True)
    r2 = mcp_server.record_turn("Je pousse la porte suivante.",
                                "La porte grince et s'ouvre lentement.")
    assert r2["turns"] == 4, r2
    hp_apres_tour2 = store.rpg_state()["player"]["hp"]
    assert hp_apres_tour2 == 14, hp_apres_tour2
    section(f"  deux tours enregistrés (turns=4), PV 20 -> {hp_apres_tour1} "
           f"-> {hp_apres_tour2}")

    # --- 3) undo_last : défait SEULEMENT le dernier tour -------------------
    r_undo = mcp_server.undo_last()
    assert r_undo["undone"] is True, r_undo
    assert r_undo["mechanics_restored"] is True, r_undo
    assert r_undo["turns_before"] == 4 and r_undo["turns_after"] == 2, r_undo
    hp_apres_undo = store.rpg_state()["player"]["hp"]
    assert hp_apres_undo == hp_apres_tour1 == 17, \
        (f"undo_last doit restaurer l'état D'AVANT le DERNIER tour "
         f"(17), jamais au-delà (20) -> {hp_apres_undo}")
    assert len(store.turns()) == 2, store.turns()
    section(f"3) undo_last() -> {r_undo} ; PV restaurés à {hp_apres_undo} "
           "(le tour antérieur, déjà clos, reste intact — never-deux-tours)")

    assert mcp_server._last_applied_events is None, \
        "undo_last doit réarmer le signal R1"
    try:
        mcp_server.paquet_narrateur("Angle : prudence.", "J'observe encore.")
        raise AssertionError("R1 aurait dû refuser après undo_last")
    except ValueError as exc:
        assert "R1" in str(exc), str(exc)
    section("5a) undo_last réarme le signal R1 à zéro")

    # --- 4) retry_turn : défait narration+action, restaure la mécanique, --
    # --- rend l'action pour renarration -------------------------------------
    mcp_server.apply_envelope(
        json.dumps({"v": 1, "deltas": {"hp_delta": -5}}), rpg_on=True)
    r3 = mcp_server.record_turn("J'affronte l'ombre.",
                                "L'ombre frappe avant que vous ne réagissiez.")
    assert r3["turns"] == 4, r3
    hp_avant_retry = store.rpg_state()["player"]["hp"]
    assert hp_avant_retry == 12, hp_avant_retry

    r_retry = mcp_server.retry_turn()
    assert r_retry["action"] == "J'affronte l'ombre.", r_retry
    assert r_retry["mechanics_restored"] is True, r_retry
    assert r_retry["turns"] == 2, r_retry
    hp_apres_retry = store.rpg_state()["player"]["hp"]
    assert hp_apres_retry == hp_apres_tour1 == 17, \
        (f"retry_turn doit restaurer l'état d'avant CE tour (17), jamais "
         f"au-delà -> {hp_apres_retry}")
    assert len(store.turns()) == 2, store.turns()
    section(f"4) retry_turn() -> {r_retry!r} ; action rendue pour "
           f"renarration, mécanique restaurée à {hp_apres_retry} "
           "(never-deux-tours)")

    assert mcp_server._last_applied_events is None, \
        "retry_turn doit réarmer le signal R1"
    try:
        mcp_server.paquet_narrateur("Angle : hésitation.", "J'hésite.")
        raise AssertionError("R1 aurait dû refuser après retry_turn")
    except ValueError as exc:
        assert "R1" in str(exc), str(exc)
    section("5b) retry_turn réarme le signal R1 à zéro")

    print(f"\nOK test-mcp-record-undo-retry-chantier5 — {len(FAIT)} "
         "sections vertes")
finally:
    mcp_server._engine = None
    mcp_server._store = None
    mcp_server._slug = ""
    mcp_server._last_applied_events = None
    mcp_server._completed_turn = None
    mcp_server._pending_log_mark = None
    shutil.rmtree(TMP, ignore_errors=True)
