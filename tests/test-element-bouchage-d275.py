"""Test d'élément — l'organe de bouchage (D-275, Issue #253, moule I-382).

Briques visées : `coderain.bouchage` (logique pure), les outils MCP
`demander_bouchage`/`enregistrer_bouchage`, et la lecture de
`rpg.provisoire` par `attack`, `player_combat`/`derived_combat` et
`roll_check` — APRÈS la fiche, AVANT le refus.

Le trou constaté : un PETIT trou de règle (un nombre absent d'une fiche
convertie) arrêtait la partie, puisque `attack` refuse plutôt que d'inventer
(D-274 §1) et que le Director n'a pas le droit de fabriquer le nombre. Le
bouchage le rend jouable : dossier préparé sans réseau, valeur jugée par un
sous-agent du harnais, valeur enregistrée PROVISOIRE et tracée — jamais
versée à une fiche, un record ou une règle du moteur.

Fixtures 100 % synthétiques (D-109/D-206, aucun matériau de campagne réel) :
une épée factice, une « ombre sans CA » factice, une table de repli factice.
Dés déterministes (seed + nonce), mêmes graines sondées que
`tests/test-element-attaque-i463.py`.

Verdicts mécaniques (D-134) : égalité de valeurs, présence de sous-chaîne,
comparaison d'états sérialisés — jamais une lecture de qualité.
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

from coderain import bouchage as organe
from coderain.memory import Entry, Library

import mcp_server

root = os.path.join(tempfile.gettempdir(), "se_element_bouchage_d275")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create(
    "ElementBouchage", mode="rpg",
    premise="Banc synthétique D-275, D-109/D-206 — aucun matériau réel.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

store.upsert_entry("items.md", Entry(
    title="Épée factice", slug="epee-factice", importance=2,
    attrs={"degats": "1d8+3", "stat": "strength", "status": "held by you"},
    body="Objet synthétique de test."))
# La cible du banc : PV, bonus d'attaque et dés écrits, CA ABSENTE — le trou.
store.upsert_entry("characters.md", Entry(
    title="Ombre sans CA", slug="ombre-sans-ca", importance=2,
    attrs={"pv": "9", "attaque_bonus": "+4", "degats": "1d6+2"},
    body="Créature synthétique de test, volontairement incomplète."))

mcp_server._engine = None          # régime dégradé, comme test-element-attaque
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None


def _set_player(*, seed=7):
    """Remet le save dans son état de fixture (rolls à 0, aucun ennemi)."""
    rpg = store.rpg_state()
    p = rpg.setdefault("player", {})
    p["stats"] = {"strength": 3, "agility": 2}
    p["level"], p["hp"], p["hp_max"] = 5, 20, 20
    p["conditions"] = []
    rpg["inventory"] = {"epee-factice": {"qty": 1, "equipped": True}}
    rpg["enemies"] = {}
    rpg["seed"], rpg["rolls"] = seed, 0
    store.set_rpg_state(rpg)


def _evenements() -> list[dict]:
    out = []
    for ligne in store.read("memory/events.jsonl").splitlines():
        try:
            out.append(json.loads(ligne))
        except ValueError:
            pass
    return out


TROU_CA = {"type": "nombre", "champ": "ca", "fiche": "ombre-sans-ca",
           "contexte": "le joueur frappe l'ombre à l'épée, sa CA manque"}

with ElementMold("bouchage-d275", budget_seconds=15.0) as mold:
    # ---- A. l'état d'avant : le nombre absent est un refus ----------------
    _set_player()
    refus = mcp_server.attack(attacker="player", target="ombre-sans-ca")
    mold.check(
        "A1-refus-avant-bouchage",
        present(str(refus.get("error", "")), "missing ca")
        and store.rpg_state().get("rolls") == 0,
        f"attack sans CA -> {refus!r} (aucun dé consommé)")

    # ---- B. la garde : ce qui n'est PAS un petit trou ---------------------
    deja = mcp_server.demander_bouchage(
        {"type": "nombre", "champ": "pv", "fiche": "ombre-sans-ca",
         "contexte": "combien de PV a l'ombre ?"})
    mold.check(
        "B1-refus-champ-deja-present",
        present(str(deja.get("error", "")), "déjà écrit"),
        f"demander_bouchage sur un champ écrit -> {deja!r}")

    portee = mcp_server.demander_bouchage(
        {"type": "regle", "champ": "riposte-du-garde", "fiche": None,
         "modifie": "fiche",
         "contexte": "le garde riposterait en modifiant sa propre fiche"})
    mold.check(
        "B2-refus-portee-declaree-interdite",
        present(str(portee.get("error", "")), "hors D-275"),
        f"demander_bouchage de portée interdite -> {portee!r}")

    informe = mcp_server.demander_bouchage(
        {"type": "sortilege", "champ": "ca", "contexte": "?"})
    mold.check(
        "B3-refus-type-inconnu",
        present(str(informe.get("error", "")), "unknown trou type"),
        f"demander_bouchage de type inconnu -> {informe!r}")

    # ---- C. le dossier, sans table de repli -------------------------------
    dossier = mcp_server.demander_bouchage(dict(TROU_CA))
    attendus = {"id", "trou", "scene", "repli", "regles", "consigne"}
    mold.check(
        "C1-dossier-bien-forme",
        set(dossier) == attendus and dossier["id"] == "ombre-sans-ca.ca"
        and dossier["consigne"] == organe.CONSIGNE,
        f"dossier -> {sorted(dossier)!r}, id={dossier.get('id')!r}")
    mold.check(
        "C2-repli-vide-sans-fichier",
        dossier["repli"] == [],
        f"repli sans repli.md -> {dossier['repli']!r}")
    mold.check(
        "C3-scene-mecanique-sans-prose",
        set(dossier["scene"]) == {"tour", "lieu", "temps", "joueur",
                                  "ennemis", "dernier_jet"}
        and dossier["scene"]["joueur"]["hp"] == 20,
        f"scene -> {dossier['scene']!r}")
    mold.check(
        "C4-regles-du-vocabulaire-ferme",
        any(r["slug"] == "combat.attack.legacy" for r in dossier["regles"]),
        f"regles -> {[r['slug'] for r in dossier['regles']]!r}")

    # ---- D. le dossier, AVEC la table de repli livrée avec la partition ---
    store.upsert_entry("repli.md", Entry(
        title="CA de l'ombre", slug="ombre-sans-ca-ca", importance=2,
        attrs={"valeur": "13", "source": "table de repli factice, D-206"},
        body="Entrée synthétique de test."))
    store.upsert_entry("repli.md", Entry(
        title="Entrée sans valeur", slug="ombre-sans-ca-vitesse",
        importance=2, attrs={"source": "table de repli factice"},
        body="Entrée synthétique sans champ valeur — jamais servie."))
    dossier2 = mcp_server.demander_bouchage(dict(TROU_CA))
    repli = dossier2["repli"]
    mold.check(
        "D1-repli-lu-du-save",
        len(repli) == 1 and repli[0]["slug"] == "ombre-sans-ca-ca"
        and repli[0]["valeur"] == "13"
        and present(repli[0]["source"], "table de repli"),
        f"repli avec repli.md -> {repli!r}")

    # ---- E. enregistrer : la trace commence au dossier --------------------
    orphelin = mcp_server.enregistrer_bouchage(
        "fantome.ca", "13", "aucun dossier n'a été préparé")
    mold.check(
        "E1-refus-sans-dossier",
        present(str(orphelin.get("error", "")), "no bouchage dossier"),
        f"enregistrer sans dossier -> {orphelin!r}")

    avant_state = json.loads(store.read("state.json"))
    avant_chars = store.read("characters.md")
    avant_items = store.read("items.md")
    enreg = mcp_server.enregistrer_bouchage(
        dossier2["id"], "13",
        "Créature de corvée sans armure ; CA 13 aligne l'ombre sur les "
        "créatures de son rang dans la table de repli.")
    prov = store.rpg_state().get("provisoire") or {}
    entree = prov.get("ombre-sans-ca.ca") or {}
    mold.check(
        "E2-entree-provisoire-tracee",
        set(entree) == {"trou", "valeur", "justification", "tour", "scene"}
        and entree["valeur"] == "13"
        and entree["trou"]["champ"] == "ca"
        and present(entree["justification"], "table de repli"),
        f"rpg.provisoire['ombre-sans-ca.ca'] -> {entree!r}")
    mold.check(
        "E3-compteur-de-scenario",
        prov.get(organe.CLE_COMPTEUR) == 1 and enreg.get("nb_scenario") == 1
        and enreg.get("seuil") == organe.SEUIL_SCENARIO,
        f"nb_scenario -> {prov.get(organe.CLE_COMPTEUR)!r}, retour {enreg!r}")

    apres_state = json.loads(store.read("state.json"))
    (apres_state.get("rpg") or {}).pop("provisoire", None)
    mold.check(
        "E4-aucune-ecriture-hors-provisoire",
        apres_state == avant_state
        and store.read("characters.md") == avant_chars
        and store.read("items.md") == avant_items,
        "state.json hors rpg.provisoire, characters.md et items.md "
        "inchangés par l'enregistrement")

    # ---- F. la valeur provisoire s'applique, et le retour le DIT ----------
    _set_player(seed=7)
    touche = mcp_server.attack(attacker="player", target="ombre-sans-ca")
    mold.check(
        "F1-attack-applique-la-valeur-provisoire",
        touche.get("target_ac") == 13 and touche.get("hit") is True
        and touche.get("roll") == 19,
        f"attack après bouchage -> {touche!r}")
    mold.check(
        "F2-retour-marque-provisoire",
        touche.get("provisoire") is True
        and touche.get("provisoire_ids") == ["ombre-sans-ca.ca"],
        f"marquage -> provisoire={touche.get('provisoire')!r}, "
        f"ids={touche.get('provisoire_ids')!r}")

    fiche_relue = [e for e in store.entries("characters.md")
                   if e.slug == "ombre-sans-ca"][0]
    mold.check(
        "F3-fiche-jamais-modifiee",
        "ca" not in {k.strip().lower() for k in fiche_relue.attrs},
        f"characters.md/ombre-sans-ca -> {fiche_relue.attrs!r}")

    encore = mcp_server.demander_bouchage(dict(TROU_CA))
    mold.check(
        "F4-un-trou-ne-se-demande-pas-deux-fois",
        present(str(encore.get("error", "")), "déjà bouché"),
        f"demander_bouchage sur un trou bouché -> {encore!r}")

    # ---- G. events.jsonl porte les DEUX événements ------------------------
    types = [r.get("type") for r in _evenements()]
    mold.check(
        "G1-deux-evenements-journalises",
        types.count("bouchage_demande") == 2
        and types.count("bouchage_enregistre") == 1,
        f"types journalisés -> {types!r}")
    mold.check(
        "G2-evenements-hors-rejeu",
        all("env" not in r for r in _evenements()
            if str(r.get("type", "")).startswith("bouchage_")),
        "aucun événement de bouchage ne porte d'enveloppe (replay_records "
        "les ignore)")

    # ---- H. roll_check et la dérivation lisent aussi le provisoire --------
    trou_stat = {"type": "nombre", "champ": "clairvoyance", "fiche": "player",
                 "contexte": "le joueur sonde l'obscurité, la stat manque"}
    d_stat = mcp_server.demander_bouchage(dict(trou_stat))
    mcp_server.enregistrer_bouchage(
        d_stat["id"], "4", "Stat de rang 5 alignée sur les autres de la fiche.")
    _set_player(seed=7)
    jet = mcp_server.roll_check(stat="clairvoyance", dc=10)
    mold.check(
        "H1-roll-check-applique-et-marque",
        jet.get("mod") == 4 and jet.get("provisoire") is True
        and jet.get("provisoire_ids") == ["player.clairvoyance"],
        f"roll_check sur stat provisoire -> {jet!r}")

    derive = mcp_server._load_rpg().player_combat(store)
    mold.check(
        "H2-derivation-marque-le-provisoire",
        derive.get("provisoire") is True
        and derive.get("provisoire_ids") == ["player.clairvoyance"]
        and derive.get("ac") == 12,
        f"player_combat -> {derive!r}")
    mold.check(
        "H3-stat-provisoire-hors-de-la-fiche",
        "clairvoyance" not in (store.rpg_state().get("player") or {})
                              .get("stats", {}),
        f"rpg.player.stats -> "
        f"{(store.rpg_state().get('player') or {}).get('stats')!r}")

    # ---- I. le seuil : au-delà de 3, on répare l'amont --------------------
    troisieme = {"type": "regle", "champ": "portee-du-souffle", "fiche": None,
                 "contexte": "la portée du souffle n'est écrite nulle part"}
    d3 = mcp_server.demander_bouchage(dict(troisieme))
    mcp_server.enregistrer_bouchage(
        d3["id"], "3 cases en cône", "Portée standard d'un souffle de ce rang.")
    mold.check(
        "I1-trois-bouchages-comptes",
        organe.nb_scenario(store.rpg_state()) == organe.SEUIL_SCENARIO,
        f"nb_scenario -> {organe.nb_scenario(store.rpg_state())!r}")

    quatrieme = mcp_server.demander_bouchage(
        {"type": "nombre", "champ": "ca", "fiche": "player",
         "contexte": "un quatrième trou dans le même scénario"})
    mold.check(
        "I2-refus-au-dela-du-seuil",
        present(str(quatrieme.get("error", "")),
                f"seuil D-275 atteint ({organe.SEUIL_SCENARIO})")
        and present(str(quatrieme.get("error", "")), "réparer l'amont"),
        f"demander_bouchage au-delà du seuil -> {quatrieme!r}")

assert mold.report(), "test-element-bouchage-d275: au moins un verdict a échoué"
print("test-element-bouchage-d275: OK — moule I-382, dossier sans réseau, "
      "valeur provisoire tracée, lue par attack/roll_check avant le refus "
      "(D-275)")
