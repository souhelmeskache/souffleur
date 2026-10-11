"""Chantier 5 (chemin MCP du régime principal, sujet 2/4) : le repliement
(fold) côté pont MCP — `fold_due`/`fold_apply`.

Mesuré avant d'écrire ce test (Grep `tests/`) : AUCUN test existant
n'appelle `mcp_server.fold_due`/`mcp_server.fold_apply` — la logique de
repliement elle-même (`Summarizer.maybe_fold`) est couverte ailleurs
(`phase2_test.py`, `wave2_test.py`, `trinity_test.py`, ...) mais toujours en
pilotant directement `Engine`/`Summarizer`, jamais le pont MCP qui relève le
seul appel modèle du fold (voir le docstring de `fold_due`). Ce fichier
comble ce trou précis.

100 % synthétique (D-109), hors ligne : `_ShimLLM`/`_NeedLLM` (définis dans
`mcp_server.py` pour ces deux outils) servent des réponses PRÉPARÉES, zéro
appel modèle réel.

Couvre :
  1. `fold_due()` rend `{"due": False}` sous le seuil (12 tours, config par
     défaut `medium_fold_after: 12`/`medium_fold_size: 5`, `config.yaml`) et
     `{"due": True, "instruction", "payload"}` dès le seuil franchi (13
     tours) — `instruction` porte `SCENE_INSTRUCTION`
     (`coderain/summarizer.py`) verbatim, `payload` porte les tours
     (`"TURNS:"`). Rien n'est écrit par cet appel (compte de scènes
     inchangé, tours inchangés).
  2. `fold_apply(summary_json)` applique UN chunk (5 tours) et rend
     `"next"` non nul quand le compte de tours en attend un second
     (20 tours : 20-5=15 > 12) ; un second `fold_apply` applique le second
     chunk et rend `"next": null` une fois le compte retombé sous le seuil
     (20-10=10) — la boucle `fold_due -> fold_apply` s'arrête exactement
     là, jamais avant.
  3. Un `fold_apply` mal formé (réponse sans JSON exploitable, deux tours
     de retry `emit_json_ex` épuisés) est refusé SANS RIEN ÉCRIRE — mesuré
     précisément (voir le corps de la PR) : aucune scène n'est créée, le
     compte de tours repliés (`folded_turns`) reste inchangé, et l'appel
     rend `"next"` non nul (un nouveau tour est redemandé) plutôt que de
     planter — la panne se rattrape, elle ne casse jamais la boucle. Un
     `fold_apply` bien formé juste après avance normalement.
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
from coderain.summarizer import SCENE_INSTRUCTION

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def n_scenes(store):
    return len(store.entries("memory/scenes.md"))


TMP = Path(tempfile.gettempdir()) / "se_mcp_repliement_pont_chantier5"
if TMP.exists():
    shutil.rmtree(TMP)

try:
    lib = Library(TMP / "app")
    slug = lib.saves.create("Chantier5-2", premise="Une veille silencieuse.")
    store = lib.store(slug)

    mcp_server._store = store
    mcp_server._slug = slug
    mcp_server._cfg = load_config()
    mcp_server._engine = Engine(mcp_server._cfg, store)
    mcp_server._engine.trinity = None       # neutralisé, même geste que load_save
    mcp_server._completed_turn = None
    mcp_server._pending_log_mark = None
    mcp_server._last_applied_events = None
    mcp_server._arm_turn()

    tool_names = {t.name for t in __import__("asyncio").run(
        mcp_server.mcp.list_tools())}
    for outil in ("fold_due", "fold_apply"):
        assert outil in tool_names, f"{outil} absent du serveur MCP"
    section("0) fold_due/fold_apply existent comme outils MCP")

    medium_after = mcp_server._engine.summarizer.medium_after
    medium_size = mcp_server._engine.summarizer.medium_size
    assert medium_after == 12 and medium_size == 5, \
        (medium_after, medium_size)  # config.yaml par défaut — hypothèse du test

    # --- 1a) sous le seuil (12 tours) : fold_due() -> due False -----------
    for _ in range(6):
        mcp_server.record_turn("J'avance.", "Le couloir continue.")
    assert len(store.turns()) == 12, store.turns()
    r_sous_seuil = mcp_server.fold_due()
    assert r_sous_seuil == {"due": False, "events": []}, r_sous_seuil
    assert n_scenes(store) == 0, "fold_due ne doit RIEN écrire"
    section(f"1a) 12 tours (seuil) : fold_due() -> {r_sous_seuil}")

    # --- 1b) dès le seuil franchi (13 tours) : fold_due() -> due True -----
    mcp_server.record_turn("", "Une porte grince au loin.")  # +1 tour (13)
    assert len(store.turns()) == 13, store.turns()
    r_seuil = mcp_server.fold_due()
    assert r_seuil["due"] is True, r_seuil
    assert SCENE_INSTRUCTION.strip() in r_seuil["instruction"], \
        r_seuil["instruction"][:200]
    assert "TURNS:" in r_seuil["payload"], r_seuil["payload"][:200]
    assert n_scenes(store) == 0 and len(store.turns()) == 13, \
        "fold_due (probe) ne doit RIEN écrire, même due=True"
    section("1b) 13 tours (seuil franchi) : fold_due() -> due=True, "
           "instruction=SCENE_INSTRUCTION verbatim, payload porte TURNS: "
           "— rien écrit (scènes=0, tours=13 inchangés)")

    # --- préparer le scénario à deux chunks : 20 tours au total -----------
    while len(store.turns()) < 20:
        mcp_server.record_turn("", "Rien ne bouge.")
    assert len(store.turns()) == 20, store.turns()
    section("  préparatifs : 20 tours au total (20-0=20 > 12 ; après un "
           "premier chunk de 5, 20-5=15 > 12 — un second chunk sera dû)")

    # --- 2a) premier fold_apply : un chunk appliqué, next NON nul ---------
    r1 = mcp_server.fold_apply(json.dumps({
        "scene_summary": "Un couloir de pierre, traversé sans incident."}))
    assert r1["scenes"] == 1 and r1["scenes_added"] == 1, r1
    assert n_scenes(store) == 1, n_scenes(store)
    assert r1["next"] is not None, \
        f"20-5=15 > 12 : un second chunk devrait être dû -> {r1}"
    assert "instruction" in r1["next"] and "payload" in r1["next"], r1["next"]
    assert len(store.turns()) == 20, \
        "le fold ne touche jamais le transcript — seulement les tours FOLDÉS"
    section(f"2a) fold_apply (1er chunk) -> scenes=1, next NON nul "
           f"({sorted(r1['next'].keys())})")

    # --- 2b) second fold_apply : second chunk appliqué, next NUL ----------
    r2 = mcp_server.fold_apply(json.dumps({
        "scene_summary": "Le silence se prolonge, rien ne se produit."}))
    assert r2["scenes"] == 2 and r2["scenes_added"] == 1, r2
    assert n_scenes(store) == 2, n_scenes(store)
    assert r2["next"] is None, \
        f"20-10=10, sous le seuil : la boucle doit s'arrêter ici -> {r2}"
    section(f"2b) fold_apply (2e chunk) -> scenes=2, next NUL — la boucle "
           "fold_due -> fold_apply s'arrête exactement quand next est nul")

    # --- 3) fold_apply mal formé : refusé, rien écrit -----------------------
    # Un nouveau fold doit être dû (20-10=10 pas encore ; on repasse le
    # seuil : +3 tours -> 23-10=13 > 12).
    for _ in range(3):
        mcp_server.record_turn("", "Encore un instant de silence.")
    assert len(store.turns()) == 23, store.turns()
    scenes_avant = n_scenes(store)
    folded_avant = store.state().get("folded_turns")
    assert mcp_server.fold_due()["due"] is True

    # Une réponse sans JSON exploitable : le premier essai échoue à
    # extraire un objet, `emit_json_ex` relance une seconde fois
    # (retry=1 par défaut) — le second essai trouve le shim à sec et lève
    # `_NeedLLM`, que `_run_fold` convertit en un nouveau `"next"`, jamais
    # une écriture partielle.
    r_mal = mcp_server.fold_apply("ceci n'a pas la forme d'un objet JSON")
    assert r_mal["scenes_added"] == 0, r_mal
    assert n_scenes(store) == scenes_avant, \
        "un fold_apply mal formé ne doit créer aucune scène"
    assert store.state().get("folded_turns") == folded_avant, \
        "un fold_apply mal formé ne doit pas avancer le compte de tours repliés"
    assert r_mal["next"] is not None, \
        f"un nouveau tour doit être redemandé plutôt qu'un échec muet -> {r_mal}"
    section(f"3a) fold_apply(réponse sans JSON) -> rien écrit "
           f"(scenes_added={r_mal['scenes_added']}, folded_turns="
           f"{store.state().get('folded_turns')}), next redemandé")

    # --- bien formé juste après : la boucle se rattrape normalement -------
    r_bon = mcp_server.fold_apply(json.dumps({
        "scene_summary": "Le silence retombe, rien d'autre ne se produit."}))
    assert r_bon["scenes_added"] == 1, r_bon
    assert n_scenes(store) == scenes_avant + 1, n_scenes(store)
    section(f"3b) fold_apply bien formé juste après -> avance normalement "
           f"(scenes={n_scenes(store)})")

    print(f"\nOK test-mcp-repliement-pont-chantier5 — {len(FAIT)} "
         "sections vertes")
finally:
    mcp_server._engine = None
    mcp_server._store = None
    mcp_server._slug = ""
    mcp_server._last_applied_events = None
    mcp_server._completed_turn = None
    mcp_server._pending_log_mark = None
    shutil.rmtree(TMP, ignore_errors=True)
