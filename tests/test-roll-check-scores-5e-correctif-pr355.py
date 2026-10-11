"""Correctif revue PR #355 (chantier 7a, D&D réel) : `roll_check`
(`coderain/mcp/jets_combat.py`) lisait la fiche sans passer par le réglage
de vocabulaire — `base = int(actor_stats[stat_key])`. Sur une save au
vocabulaire 5e exact, une Force de 16 ajoutait donc +16 au d20 au lieu du
modificateur 5e (+3) : l'outil principal du Director aurait joué n'importe
quel jet de caractéristique complètement faux.

Couvre, de bout en bout (`mcp_server.load_save`, JAMAIS `_rpg_cfg` posé à la
main — la revue le demandait explicitement) :

  1. `load_save` règle `_rpg_cfg["stats"]` sur les six noms 5e exacts quand
     la fiche les porte (fixture `guerrier-5e`, chantier 7a).
  2. `roll_check` sur le JOUEUR déduit le modificateur par la règle 5e
     (`(score-10)//2`), même fonction que `derived_combat`
     (`rpg.ability_mod`/`rpg.scores_mode`).
  3. `roll_check` sur un PNJ (`characters.md`, `stats:` attr) traite le MÊME
     vocabulaire 5e de la MÊME façon — choix mesuré (voir le corps de la
     PR) : le réglage `rpg.stats` est celui de la SAVE (une seule partie,
     un seul vocabulaire), jamais par-personnage ; un `stats:` écrit à la
     main sur `characters.md` suit donc la même règle que la fiche jouée.
  4. une valeur provisoire posée par bouchage (D-275) GARDE sa sémantique
     actuelle : c'est déjà un modificateur final (choisi par le juge
     humain), jamais reconverti par `ability_mod` même en vocabulaire 5e —
     sinon un bouchage "4" deviendrait un modificateur -3.
  5. une save au vocabulaire GÉNÉRIQUE (hors D&D) n'est pas affectée :
     `roll_check` continue de lire un modificateur déjà calculé.

Fixtures 100% synthétiques (D-109), hors ligne.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.memory import Entry, Library

import mcp_server

_spec = importlib.util.spec_from_file_location(
    "personnage_banc_fix355", ROOT / "bench" / "fixtures" / "personnage-banc.py")
personnage_banc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(personnage_banc)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


TMP = Path(tempfile.gettempdir()) / "se_roll_check_scores_5e_correctif_pr355"
if TMP.exists():
    shutil.rmtree(TMP)

try:
    lib = Library(TMP / "app")
    saves_root = TMP / "app" / "saves"

    # ======================================================================
    # 1) save 5e réelle, chargée par load_save (jamais _rpg_cfg à la main)
    # ======================================================================
    slug = lib.saves.create(
        "Correctif355-5e", mode="rpg",
        premise="Correctif revue PR 355, D-109 — aucun matériau réel.")
    save_dir = saves_root / slug
    res = personnage_banc.install(save_dir, profil="guerrier-5e")
    assert res["status"] == "installed", res

    mcp_server._store = None
    mcp_server._engine = None
    mcp_server._slug = ""
    mcp_server._last_applied_events = None
    mcp_server._lib = lib
    mcp_server._saves_root = saves_root

    out = mcp_server.load_save(slug)
    assert "error" not in out, out
    assert set(mcp_server._rpg_cfg["stats"]) == {
        "strength", "dexterity", "constitution",
        "intelligence", "wisdom", "charisma"}, mcp_server._rpg_cfg
    section(f"1) load_save règle rpg.stats sur les six noms 5e exacts "
            f"(fiche 'guerrier-5e') -> {out['stats']!r}")

    # ======================================================================
    # 2) roll_check(joueur) : score 5e -> modificateur (score-10)//2
    # ======================================================================
    r1 = mcp_server.roll_check(stat="strength", dc=10)
    assert "error" not in r1, r1
    assert r1["mod"] == 3, r1   # Force 16 -> (16-10)//2 = 3, jamais +16
    section(f"2) roll_check(player, strength=16) -> mod={r1['mod']} "
            f"((16-10)//2=3, jamais le score brut +16) -> {r1!r}")

    # ======================================================================
    # 3) roll_check(PNJ) dans la MÊME save : même vocabulaire, même règle
    # ======================================================================
    store = mcp_server._require_store()
    store.upsert_entry("characters.md", Entry(
        title="Garde 5e (banc)", slug="garde-5e-banc", importance=2,
        attrs={"stats": "strength 14, dexterity 12"},
        body="PNJ synthétique de test (D-109) — stats 5e écrites à la main."))
    r2 = mcp_server.roll_check(stat="strength", dc=10, actor="garde-5e-banc")
    assert "error" not in r2, r2
    assert r2["mod"] == 2, r2   # Force 14 -> (14-10)//2 = 2
    section(f"3) roll_check(PNJ 'garde-5e-banc', strength=14) -> "
            f"mod={r2['mod']} — même réglage de save que le joueur "
            f"(un vocabulaire par PARTIE, jamais par personnage) -> {r2!r}")

    # ======================================================================
    # 4) bouchage D-275 : la valeur provisoire reste un modificateur BRUT
    # ======================================================================
    trou = {"type": "nombre", "champ": "intuition", "fiche": "player",
            "contexte": "le joueur sent un piège, la stat manque sur sa "
                        "fiche 5e"}
    dossier = mcp_server.demander_bouchage(dict(trou))
    assert "error" not in dossier, dossier
    enreg = mcp_server.enregistrer_bouchage(
        dossier["id"], "4",
        "Modificateur de rang moyen, aligné sur le niveau 1 — D-109.")
    assert "error" not in enreg, enreg
    r3 = mcp_server.roll_check(stat="intuition", dc=10)
    assert "error" not in r3, r3
    # Si le bouchage était reconverti en score ability_mod(4) vaudrait -3 :
    # la sémantique D-275 (déjà un modificateur) exige mod == 4, jamais -3.
    assert r3["mod"] == 4 and r3.get("provisoire") is True, r3
    section(f"4) roll_check(stat provisoire D-275 'intuition'=4) -> "
            f"mod={r3['mod']} BRUT, jamais reconverti par ability_mod "
            f"(qui donnerait -3) -> {r3!r}")

    # ======================================================================
    # 5) save au vocabulaire GÉNÉRIQUE (hors D&D) : comportement inchangé
    # ======================================================================
    slug_g = lib.saves.create(
        "Correctif355-generique", mode="rpg",
        premise="Correctif revue PR 355, vocabulaire générique, D-109.")
    save_dir_g = saves_root / slug_g
    res_g = personnage_banc.install(save_dir_g, profil="guerrier")
    assert res_g["status"] == "installed", res_g

    mcp_server._store = None
    mcp_server._slug = ""
    out_g = mcp_server.load_save(slug_g)
    assert "error" not in out_g, out_g
    assert "strength" in mcp_server._rpg_cfg["stats"] \
        and "dexterity" not in mcp_server._rpg_cfg["stats"], mcp_server._rpg_cfg

    r4 = mcp_server.roll_check(stat="strength", dc=10)
    assert "error" not in r4, r4
    assert r4["mod"] == 3, r4   # profil 'guerrier' générique : strength=3,
                                # DÉJÀ un modificateur, lu tel quel
    section(f"5) save au vocabulaire générique : roll_check(player, "
            f"strength) -> mod={r4['mod']} BRUT, comportement du socle "
            f"inchangé -> {r4!r}")

    print(f"\nOK test-roll-check-scores-5e-correctif-pr355 — "
         f"{len(FAIT)} sections vertes")
finally:
    mcp_server._engine = None
    mcp_server._store = None
    mcp_server._slug = ""
    mcp_server._last_applied_events = None
    shutil.rmtree(TMP, ignore_errors=True)
