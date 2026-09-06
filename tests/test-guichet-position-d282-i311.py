"""D-282 (Issue #311) : LA GARDE de position — un delta `location` n'est
accepté que s'il est un id de `nodes[]` de la partition chargée OU un id de
`records[]` classe `lieu` ; jamais du texte libre. Mesure déclenchante :
`bench/nuit-20260906/partie-04` a dérivé 120 tours sur des slugs de prose
(aucun `para-*`) sans qu'aucune garde ne le refuse — reproduit ici sur une
partition SYNTHÉTIQUE (D-109 : zéro matériau de campagne réel).

Couvre le point 5 de l'Issue #311 :
  (a) `location` = id de nœud -> accepté ; = slug libre -> refusé, tracé
      (`events.jsonl`, `type: position_refusee`), frontière posée
      (`rpg.frontiere`) ; = id de record lieu -> accepté.
  (b) rejeu d'un premier événement hors partition (analogue synthétique de
      la partie 04) : refusé, frontière posée au tour 1.
  (c) rejeu d'une chaîne de nœuds VALIDES (analogue synthétique de la
      partie 02) jusqu'au nœud terminal : `noeud_atteint` (banc,
      `tools/banc/detecter_fin.py`) = le dernier nœud franchi, `fin_module`
      inchangé.
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
from coderain.converter.schemas import Manifest, Node, Partition, Record
from coderain.engine import Engine
from coderain.memory import Library
from coderain import validator as validator_mod

_spec = importlib.util.spec_from_file_location(
    "detecter_fin", ROOT / "tools" / "banc" / "detecter_fin.py")
detecter_fin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detecter_fin)


def _manifest():
    return Manifest(titre="module factice D-282", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="2" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


def _lien(cible_id: str) -> dict:
    return {"cible_id": cible_id, "condition_textuelle": ""}


def _build_chain_partition() -> Partition:
    """para-01 -> para-02 -> para-03 -> para-terminal (liens: [] +
    charniere_sortie) + un lieu enregistré `vieux-pont` (classe lieu, D-282
    règle 1 : accepté au même titre qu'un nœud)."""
    p = Partition(_manifest())
    p.nodes.append(Node("para-01", "scene", "Le seuil",
                        "Vous êtes devant une porte close.", "scene",
                        liens=[_lien("para-02")], anchors=[(0, 10)]))
    p.nodes.append(Node("para-02", "scene", "Le couloir",
                        "Un couloir humide s'enfonce dans le noir.", "scene",
                        liens=[_lien("para-03")], anchors=[(0, 10)]))
    p.nodes.append(Node("para-03", "scene", "La salle basse",
                        "Une salle voûtée, l'air y est plus frais.", "scene",
                        liens=[_lien("para-terminal")], anchors=[(0, 10)]))
    p.nodes.append(Node("para-terminal", "scene", "La sortie",
                        "Le jour filtre enfin par une fissure.", "scene",
                        liens=[], anchors=[(0, 10)],
                        charniere_sortie={
                            "ouvre_vers_md": "Le héros sort du donjon.",
                            "prerequis_etat": "etat: node para-terminal atteint"}))
    p.records.append(Record(
        "vieux-pont", "lieu", "Le vieux pont",
        {"description_md": "Un pont de pierre effondré à moitié."},
        anchors=[(0, 10)]))
    p.aventure = None
    return p


def _save_with_partition(root: Path, partition_dir: Path, titre: str,
                         location: str = "para-01") -> tuple:
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon oublié, version factice.")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    store = lib.store(slug)
    state = store.world_state()
    state.setdefault("player", {})["location"] = location
    store.set_world_state(state)
    return lib, slug, store


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="d282-guichet-test-"))
    try:
        partition_dir = tmp / "partition"
        write_partition(_build_chain_partition(), partition_dir)

        cfg = load_config()
        cfg.generation["trinity_brain"] = False

        # --- (a) validate() : node id / lieu record id / slug libre --------
        lib_a, slug_a, store_a = _save_with_partition(
            tmp / "app-a", partition_dir, "Garde — validate", "para-01")
        stats = []
        clean, rejected = validator_mod.validate(
            {"v": 1, "deltas": {"location": "para-02"}}, store_a, stats=stats)
        assert clean["deltas"]["location"] == "para-02", clean
        assert rejected == [], rejected
        print("a1) location = id de nœud -> accepté")

        clean, rejected = validator_mod.validate(
            {"v": 1, "deltas": {"location": "vieux-pont"}}, store_a, stats=stats)
        assert clean["deltas"]["location"] == "vieux-pont", clean
        assert rejected == [], rejected
        print("a2) location = id de record classe lieu -> accepté")

        slug_libre = "l-entree-de-la-grotte-accroupi-guettant-l-obscurite"
        clean, rejected = validator_mod.validate(
            {"v": 1, "deltas": {"location": slug_libre}}, store_a, stats=stats)
        assert "location" not in clean.get("deltas", {}), clean
        assert len(rejected) == 1 and rejected[0]["delta"] == "location", rejected
        print("a3) location = slug de prose libre -> refusé (texte libre)")

        # --- (a bis) monde sans partition -> refus explicite ----------------
        lib_np = Library(tmp / "app-sans-partition")
        slug_np = lib_np.create_story("Sans partition", "Monde vide (#281).")
        store_np = lib_np.store(slug_np)
        clean, rejected = validator_mod.validate(
            {"v": 1, "deltas": {"location": "nimporte-quoi"}}, store_np, stats=stats)
        assert "location" not in clean.get("deltas", {}), clean
        assert rejected and rejected[0]["delta"] == "location", rejected
        print("a4) aucune partition chargée -> refus explicite (#281)")

        # --- (b) rejeu du 1er événement hors partition (partie 04) ----------
        lib_b, slug_b, store_b = _save_with_partition(
            tmp / "app-b", partition_dir, "Frontière — partie 04", "para-01")
        eng_b = Engine(cfg, store_b)
        events = eng_b.apply_envelope(
            {"v": 1, "deltas": {"location": slug_libre}}, rpg_on=False,
            log_turn=1)
        assert any("position refusée" in e for e in events), events
        state_b = store_b.world_state()
        frontiere = state_b.get("rpg", {}).get("frontiere")
        assert frontiere == {"tour": 1, "valeur_tentee": slug_libre}, frontiere
        assert validator_mod.current_location(state_b) == "para-01", state_b
        log = [json.loads(l) for l in
              (store_b.dir / "memory" / "events.jsonl").read_text(
                  encoding="utf-8").splitlines() if l.strip()]
        refus_log = [r for r in log if r.get("type") == "position_refusee"]
        assert len(refus_log) == 1, log
        assert refus_log[0]["valeur_tentee"] == slug_libre, refus_log
        assert refus_log[0]["turn"] == 1, refus_log
        print("b) 1er `location` hors partition -> refusé, frontière posée "
             "au tour 1, tracé events.jsonl (type: position_refusee)")

        # --- (c) rejeu d'une chaîne de nœuds valides (partie 02) ------------
        lib_c, slug_c, store_c = _save_with_partition(
            tmp / "app-c", partition_dir, "Chaîne valide — partie 02", "para-01")
        eng_c = Engine(cfg, store_c)
        for i, cible in enumerate(("para-02", "para-03", "para-terminal"), 1):
            events = eng_c.apply_envelope(
                {"v": 1, "deltas": {"location": cible}}, rpg_on=False,
                log_turn=i)
            assert any(f"location → {cible}" in e for e in events), events
        state_c = store_c.world_state()
        assert not state_c.get("rpg", {}).get("frontiere"), state_c
        assert validator_mod.current_location(state_c) == "para-terminal", state_c

        r = detecter_fin.evaluer(store_c.dir)
        assert r == {"fin": "fin_module", "noeud": "para-terminal"}, r
        print("c) chaîne de nœuds VALIDES jusqu'au terminal -> fin_module "
             "inchangé, noeud_atteint = dernier nœud franchi (para-terminal)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL D-282 GUICHET POSITION (#311) TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
