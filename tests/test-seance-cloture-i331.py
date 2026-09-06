"""F0.3 (Issue #331) : le record `seance` écrit à la clôture (`fin_module` ->
raison="terminal", `frontiere` -> raison="frontiere") + la section « Reprise
de séance » du paquet, servie SEULEMENT au premier tour qui suit une
clôture — jamais par lecture de prose, toujours sur l'état/l'assembleur
(C0.3). Partition SYNTHÉTIQUE de 3 nœuds (D-109 : zéro matériau de campagne
réel), save synthétique.

Couvre les 4 cas de la fixture de l'Issue #331 :
  (A) clôture terminale (nœud `scene-fin`, liens: [] + charnière) -> record
      `seance` complet (5 champs), raison="terminal".
  (B) clôture frontière (`rpg.frontiere` posé par la garde du guichet) ->
      record raison="frontiere", drapeau NON consommé à la clôture.
  (C) partie sans clôture -> aucun record écrit, aucune section « Reprise »
      dans le paquet, quel que soit le tour.
  (D) reprise après clôture frontière -> au premier tour suivant : section
      « Reprise de séance » citant nœud + raison + en_suspens, drapeau
      `rpg.frontiere` CONSOMMÉ ; la partie continue jusqu'au terminal ->
      DEUXIÈME record `seance`, numero=2, tour_debut enchaîné sur le
      tour_fin de la première.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.config import load_config
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition
from coderain.engine import Engine
from coderain.memory import Library
from coderain import assembleur_position
from coderain import validator as validator_mod

_spec = importlib.util.spec_from_file_location(
    "cloturer_seance", ROOT / "tools" / "banc" / "cloturer_seance.py")
cloturer_seance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cloturer_seance)


def _manifest():
    return Manifest(titre="module factice F0.3", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="3" * 64,
                    date_conversion="2026-09-06T00:00:00+00:00",
                    version_convertisseur="test")


def _lien(cible_id: str) -> dict:
    return {"cible_id": cible_id, "condition_textuelle": ""}


def _build_partition() -> Partition:
    """3 nœuds : scene-a -> scene-b -> scene-fin (terminal, liens: [] +
    charniere_sortie). Chacun porte un `objectif_md` (altitude scenario) —
    la matière mécanique lue par `en_suspens`."""
    p = Partition(_manifest())
    p.nodes.append(Node("scene-a", "scene", "L'entrée factice",
                        "Corps factice de scene-a.", "scenario",
                        liens=[_lien("scene-b")], anchors=[(0, 10)],
                        objectif_md="Trouver l'indice"))
    p.nodes.append(Node("scene-b", "scene", "Le passage factice",
                        "Corps factice de scene-b.", "scenario",
                        liens=[_lien("scene-fin")], anchors=[(0, 10)],
                        objectif_md="Confronter le gardien"))
    p.nodes.append(Node("scene-fin", "scene", "La sortie factice",
                        "Corps factice de scene-fin.", "scenario",
                        liens=[], anchors=[(0, 10)],
                        objectif_md="Sceller le pacte final",
                        charniere_sortie={
                            "ouvre_vers_md": "Le héros sort du donjon factice.",
                            "prerequis_etat": "etat: node scene-fin atteint"}))
    p.aventure = None
    return p


def _save(root: Path, partition_dir: Path, titre: str, location: str):
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon factice pour F0.3.")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    store = lib.store(slug)
    state = store.world_state()
    state.setdefault("player", {})["location"] = location
    store.set_world_state(state)
    return lib, slug, store


def _round(store, texte: str) -> None:
    """Un échange transcript (player + narrator) — même convention de
    comptage que `Engine.apply_envelope`/`location_refusal_events`
    (`len(store.turns())`, D-282/#311) : jamais une resélection séparée."""
    store.append_turn("player", f"j'avance ({texte})")
    store.append_turn("narrator", f"la scène répond ({texte})")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="seance-cloture-test-"))
    try:
        partition_dir = tmp / "partition"
        write_partition(_build_partition(), partition_dir)
        cfg = load_config()
        cfg.generation["trinity_brain"] = False

        # --- (A) clôture terminale ------------------------------------------
        lib_a, slug_a, store_a = _save(
            tmp / "app-a", partition_dir, "Clôture terminale", "scene-a")
        eng_a = Engine(cfg, store_a)
        for cible in ("scene-b", "scene-fin"):
            _round(store_a, cible)
            events = eng_a.apply_envelope(
                {"v": 1, "deltas": {"location": cible}}, rpg_on=False)
            assert any(f"location → {cible}" in e for e in events), events
        assert len(store_a.turns()) == 4, store_a.turns()

        record = cloturer_seance.cloturer(store_a.dir)
        assert record == {
            "numero": 1, "tour_debut": 1, "tour_fin": 4,
            "raison": "terminal", "dernier_noeud_franchi": "scene-fin",
            "en_suspens": ["visée non résolue : Sceller le pacte final"],
        }, record
        state_a = store_a.world_state()
        assert state_a["seances"] == [record], state_a
        print("A) clôture terminale (scene-fin) -> record seance complet "
             "(5 champs), raison=terminal")

        # idempotence : un second appel (le banc relit l'état à chaque tour)
        # ne duplique rien.
        assert cloturer_seance.cloturer(store_a.dir) is None
        assert store_a.world_state()["seances"] == [record]
        print("A bis) appel répété sur une séance déjà close -> aucun "
             "doublon (idempotence)")

        # --- (C) partie sans clôture -----------------------------------------
        lib_c, slug_c, store_c = _save(
            tmp / "app-c", partition_dir, "Sans clôture", "scene-a")
        _round(store_c, "premier tour")
        assert cloturer_seance.cloturer(store_c.dir) is None
        state_c = store_c.world_state()
        assert "seances" not in state_c or not state_c["seances"], state_c
        assert assembleur_position._reprise_section(
            store_c, len(store_c.turns())) is None
        messages_c = assembleur_position.assemble(
            partition_dir, store_c, state_c, [], "je continue")
        assert "Reprise de séance" not in messages_c[0]["content"], messages_c
        print("C) partie sans clôture -> aucun record, aucune section "
             "« Reprise » dans le paquet")

        # --- (B) clôture frontière + (D) reprise -> deuxième séance ----------
        lib_b, slug_b, store_b = _save(
            tmp / "app-b", partition_dir, "Frontière puis reprise", "scene-a")
        eng_b = Engine(cfg, store_b)
        _round(store_b, "franchissement scene-a")
        eng_b.apply_envelope(
            {"v": 1, "deltas": {"location": "scene-a"}}, rpg_on=False)
        _round(store_b, "hors partition")
        slug_libre = "un-slug-de-prose-hors-partition"
        events = eng_b.apply_envelope(
            {"v": 1, "deltas": {"location": slug_libre}}, rpg_on=False)
        assert any("position refusée" in e for e in events), events
        assert len(store_b.turns()) == 4, store_b.turns()

        record_b = cloturer_seance.cloturer(store_b.dir)
        assert record_b == {
            "numero": 1, "tour_debut": 1, "tour_fin": 4,
            "raison": "frontiere", "dernier_noeud_franchi": "scene-a",
            "en_suspens": ["visée non résolue : Trouver l'indice",
                          "débouché ouvert : scene-b"],
        }, record_b
        state_b = store_b.world_state()
        assert state_b["rpg"]["frontiere"], state_b   # PAS consommé encore
        print("B) clôture frontière (scene-a, débouché scene-b encore "
             "ouvert) -> record seance raison=frontiere, drapeau NON "
             "consommé à la clôture (D-282 règle 2)")

        # Reprise : le premier tour qui suit (tour_courant = tour_fin + 1).
        store_b.append_turn("player", "je reprends la partie")
        tour_reprise = len(store_b.turns())
        assert tour_reprise == 5, tour_reprise
        reprise = assembleur_position._reprise_section(store_b, tour_reprise)
        assert reprise is not None
        assert "n°1" in reprise.text and "frontiere" in reprise.text \
            and "scene-a" in reprise.text \
            and "débouché ouvert : scene-b" in reprise.text, reprise.text

        state_b_avant = store_b.world_state()
        messages_b = assembleur_position.assemble(
            partition_dir, store_b, state_b_avant, [], "je continue")
        paquet = messages_b[0]["content"]
        assert "Reprise de séance" in paquet, paquet
        assert "scene-a" in paquet and "frontiere" in paquet, paquet
        state_b_apres = store_b.world_state()
        assert not state_b_apres.get("rpg", {}).get("frontiere"), state_b_apres
        print("D) reprise au tour suivant -> section « Reprise de séance » "
             "dans le paquet du Director, `rpg.frontiere` CONSOMMÉ à "
             "l'ouverture de la séance suivante — jamais avant")

        store_b.append_turn("narrator", "la partie reprend")
        eng_b.apply_envelope(
            {"v": 1, "deltas": {"location": "scene-b"}}, rpg_on=False)
        _round(store_b, "vers la fin")
        eng_b.apply_envelope(
            {"v": 1, "deltas": {"location": "scene-fin"}}, rpg_on=False)
        assert len(store_b.turns()) == 8, store_b.turns()

        record_b2 = cloturer_seance.cloturer(store_b.dir)
        assert record_b2 == {
            "numero": 2, "tour_debut": 5, "tour_fin": 8,
            "raison": "terminal", "dernier_noeud_franchi": "scene-fin",
            "en_suspens": ["visée non résolue : Sceller le pacte final"],
        }, record_b2
        assert store_b.world_state()["seances"] == [record_b, record_b2]
        print("D bis) partie relancée jusqu'au terminal -> DEUXIÈME record "
             "seance, numero=2, tour_debut enchaîné sur le tour_fin de la "
             "première")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL SEANCE CLOTURE (#331) TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
