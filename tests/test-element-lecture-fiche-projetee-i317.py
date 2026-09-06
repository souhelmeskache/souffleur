"""Issue #317 — découpe (a) de #316. Mesuré au banc (nuit 06/09, partie 02) :
la projection (`coderain/converter/projection.py::project_into_save`) écrit
le bloc de stats d'un record (`ca`, `pv`, `attaque_bonus`, `degats`...) en
JSON dans le CORPS de l'entrée `characters.md` — seul `importance` vit dans
ses attrs pour une créature. `mcp_server._attack_fiche` ne lisait que
`e.attrs` : une créature entièrement connue du module se bouchait quand même
(6 bouchages mesurés sur une créature dont CA/attaque_bonus/degats étaient
déjà écrits — nom et chiffres fictifs ici, D-109).

`_creature_stats` (mcp_server.py) est le chemin de lecture UNIQUE d'une
fiche non-joueur, partagé par `attack` et `start_combat` (I-463 : « en un
seul lieu ») — voir `tests/test-start-combat-membre-slug-i317.py` pour le
second appelant.

Couvre :
  A. `attack(player -> <créature projetée>)` résout sans bouchage (le bloc
     JSON du corps porte tous les champs requis) ;
  B. repli sur le record de module (`get_record`) quand l'entrée
     `characters.md` n'existe PAS du tout.

Fixtures 100% synthétiques (D-109) : chiffres repris de l'Issue #317
(ca=10, pv=26, attaque_bonus=+3, degats="4 (1d6+1)"), nom et slug fictifs.

Verdicts mécaniques (D-134), moule I-382.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.element_mold import ElementMold, present

from coderain.memory import Entry, Library

import mcp_server

root = os.path.join(tempfile.gettempdir(), "se_lecture_fiche_projetee_i317")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create(
    "LectureFicheProjetee", mode="rpg",
    premise="Banc synthétique I-317, D-109 — aucun matériau réel.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

# ---- fixtures : une arme pour le joueur, une créature PROJETÉE (bloc JSON
# dans le corps, comme le fait vraiment converter/projection.py) ------------
store.upsert_entry("items.md", Entry(
    title="Épée factice", slug="epee-factice", importance=2,
    attrs={"degats": "1d8+3", "stat": "strength", "status": "held by you"},
    body="Objet synthétique de test."))

CREATURE_SLUG = "reflet-ensanglante-banc"
CREATURE_STATS = {"nom": "Reflet ensanglanté (banc)", "ca": 10, "pv": 26,
                  "vitesse": "30 ft.", "attaque_bonus": 3,
                  "degats": "4 (1d6+1)", "immunites_degats": "poison"}
# Même écriture que projection.py:101/104 : body = JSON des stats, attrs =
# {"importance": "4"} SEUL (rec["meta"].get("classe") == "creature").
store.upsert_entry("characters.md", Entry(
    title=str(CREATURE_STATS["nom"]), slug=CREATURE_SLUG, importance=4,
    attrs={"importance": "4"},
    body=json.dumps(CREATURE_STATS, ensure_ascii=False, indent=1)))

mcp_server._engine = None
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None
mcp_server._saves_root = lib.saves.dir(slug).parent


def _set_player(*, seed=7, hp=20):
    rpg = store.rpg_state()
    p = rpg.setdefault("player", {})
    p["stats"] = {"strength": 3, "agility": 2}
    p["level"] = 5
    p["hp"], p["hp_max"] = hp, max(hp, 20)
    p["conditions"] = []
    p["death_saves"] = {"successes": 0, "failures": 0}
    rpg["inventory"] = {"epee-factice": {"qty": 1, "equipped": True}}
    rpg["enemies"] = {}
    rpg["provisoire"] = {}
    rpg["seed"], rpg["rolls"] = seed, 0
    store.set_rpg_state(rpg)
    return rpg


with ElementMold("lecture-fiche-projetee-i317", budget_seconds=10.0) as mold:
    # ---- A. le bloc JSON projeté se lit tel quel, aucun bouchage requis ---
    _set_player(seed=7)
    fiche = mcp_server._attack_fiche(store, CREATURE_SLUG)
    mold.check(
        "A1-fiche-lue-depuis-le-corps-json",
        fiche.get("ac") == 10 and fiche.get("attack_bonus") == 3
        and fiche.get("damage") == "4 (1d6+1)" and fiche.get("hp_max") == 26
        and "provisoire_ids" not in fiche,
        f"_attack_fiche({CREATURE_SLUG!r}) -> {fiche!r}")

    _set_player(seed=7)
    avant = dict(store.rpg_state().get("provisoire") or {})
    touche = mcp_server.attack(attacker="player", target=CREATURE_SLUG)
    apres = store.rpg_state().get("provisoire") or {}
    mold.check(
        "A2-attack-sans-bouchage",
        "error" not in touche and "provisoire" not in touche
        and apres == avant,
        f"attack(player -> {CREATURE_SLUG}) -> {touche!r} ; "
        f"provisoire avant={avant!r} après={apres!r}")

    # ---- B. repli get_record() atteint quand l'entrée characters.md
    # n'existe PAS du tout — record brut écrit directement dans une
    # partition (aucune projection ici, pour que characters.md l'ignore).
    partition_dir = Path(root) / "partition-fallback"
    (partition_dir / "records").mkdir(parents=True)
    record_slug = "ombre-hors-fiche-banc"
    (partition_dir / "records" / f"{record_slug}.md").write_text(
        '---\n{"id": "%s", "classe": "creature"}\n---\n'
        '{"nom": "Ombre hors fiche (banc)", "ca": 12, "pv": 15, '
        '"attaque_bonus": 2, "degats": "1d4+1"}' % record_slug,
        encoding="utf-8")
    (lib.saves.dir(slug) / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")

    assert not any(e.slug == record_slug for e in store.entries("characters.md")), (
        "fixture invalide : l'entrée ne doit PAS exister sur characters.md")

    fiche_repli = mcp_server._attack_fiche(store, record_slug)
    mold.check(
        "B1-repli-get-record-quand-entree-absente",
        fiche_repli.get("ac") == 12 and fiche_repli.get("attack_bonus") == 2
        and fiche_repli.get("hp_max") == 15
        and fiche_repli.get("damage") == "1d4+1",
        f"_attack_fiche({record_slug!r}) (repli get_record) -> {fiche_repli!r}")

    (lib.saves.dir(slug) / "module.json").unlink()
    inconnu = mcp_server._attack_fiche(store, "personne-hors-fiche-banc")
    mold.check(
        "B2-refus-quand-ni-fiche-ni-record",
        present(str(inconnu.get("error", "")), "unknown combatant"),
        f"_attack_fiche(slug inconnu) -> {inconnu!r}")

assert mold.report(), "test-element-lecture-fiche-projetee-i317: au moins un verdict a échoué"
print("test-element-lecture-fiche-projetee-i317: OK — bloc de stats projeté "
      "lu sans bouchage, repli get_record() atteint quand l'entrée manque")
