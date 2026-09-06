"""Issue #340 (découpe (d) de #316) : `tools/banc/metriques_nuit.py` voit
TOUS les combats — créature en scène (records classe `creature`, cités au
nœud courant ou dans l'enveloppe/le journal du tour) croisée avec le MEILLEUR
chemin employé n'importe quand dans la partie : `start_combat` / `attack
seul` / `jets seuls` / `prose seule`. Fixture 100% synthétique (D-109) :
jamais de matériau de campagne réel."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "metriques_nuit", REPO_ROOT / "tools" / "banc" / "metriques_nuit.py")
metriques_nuit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(metriques_nuit)


def _fabriquer_partition_factice(partition_dir: Path) -> None:
    """Une partition minimale, à la main (même esprit que
    `save_depart_test.py::_fabriquer_partition_factice`) : deux records
    classe `creature` — l'un posé au nœud `salle-gardee` (repli
    `pose_sur_nodes`, cas d'un module positionné), l'autre non posé du tout
    (`gobelin2`, cas mesuré sur banc réel #340 : la conversion P4 ne pose
    pas toujours ses créatures — seule la citation directe reste alors
    disponible)."""
    partition_dir.mkdir(parents=True, exist_ok=True)
    (partition_dir / "index.json").write_text(json.dumps({
        "nodes": [{"id": "salle-gardee", "type": "scene", "altitude": "scene"}],
        "records": [
            {"id": "gobelin", "classe": "creature",
             "transverse": False, "pose_sur_nodes": ["salle-gardee"]},
            {"id": "gobelin2", "classe": "creature", "transverse": False},
        ],
    }), encoding="utf-8")


def _fabriquer_partie(partie_dir: Path, evs: list[dict],
                      partition_dir: Path | None = None,
                      n_prose: int = 1) -> None:
    (partie_dir / "save" / "memory").mkdir(parents=True)
    for t in range(1, n_prose + 1):
        (partie_dir / f"prose-{t:02d}.md").write_text("x", encoding="utf-8")
    events_path = partie_dir / "save" / "memory" / "events.jsonl"
    events_path.write_text(
        "\n".join(json.dumps(e) for e in evs) + "\n", encoding="utf-8")
    if partition_dir is not None:
        (partie_dir / "save" / "module.json").write_text(
            json.dumps({"partition": str(partition_dir)}), encoding="utf-8")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="metriques-nuit-combats-i340-test-"))
    try:
        partition_dir = tmp / "partition-factice"
        _fabriquer_partition_factice(partition_dir)

        run_dir = tmp / "nuit-20260906"
        # partie-01 : start_combat (sous-système, jamais journalisé en vrai
        # aujourd'hui mais reconnu si présent — même réserve que
        # `compter_combats`).
        _fabriquer_partie(run_dir / "partie-01",
                          [{"turn": 1, "type": "start_combat"}])
        # partie-02 : attack seul — env.deltas.enemies (apply_envelope),
        # sans passer par le sous-système.
        _fabriquer_partie(run_dir / "partie-02", [
            {"turn": 1, "env": {"deltas": {"enemies": {"goblin": {"hp_delta": -5}}}}},
        ])
        # partie-03 : jets seuls — un `check` d'enveloppe appliqué, sans
        # jamais d'attaque (même signal que le rejeu réel du 06/09 : #340
        # ne revérifie pas la créature derrière un `check`, voir
        # `chemin_combat_tour`).
        _fabriquer_partie(run_dir / "partie-03", [
            {"turn": 1, "env": {"check": {"stat": "wisdom", "dc": 12}}},
        ])
        # partie-04 : jets seuls, par bouchage (D-275) — la fiche
        # `gobelin2` (jamais posée sur un nœud) manque un chiffre en pleine
        # résolution d'un jet : citation directe, sans attaque appliquée.
        _fabriquer_partie(run_dir / "partie-04", [
            {"turn": 1, "type": "bouchage_demande", "id": "gobelin2.ca",
             "trou": {"type": "nombre", "champ": "ca", "fiche": "gobelin2"}},
            {"turn": 1, "type": "bouchage_enregistre", "id": "gobelin2.ca",
             "trou": {"type": "nombre", "champ": "ca", "fiche": "gobelin2"},
             "valeur": "12"},
        ], partition_dir=partition_dir)
        # partie-05 : prose seule — créature en scène (nœud, repli
        # `pose_sur_nodes`) mais AUCUN appel au moteur : le pire cas, #340.
        _fabriquer_partie(run_dir / "partie-05", [
            {"turn": 1, "env": {"deltas": {"location": "salle-gardee"}}},
        ], partition_dir=partition_dir)
        # partie-06 : pas de combat du tout (aucune créature en scène, et
        # la partition n'est même pas rattachée) — ne doit apparaître nulle
        # part dans le compte.
        _fabriquer_partie(run_dir / "partie-06", [
            {"turn": 1, "env": {"deltas": {"gold_delta": 10}}},
        ])

        cv = metriques_nuit.combats_vus(run_dir)
        assert cv["total"] == 5, cv
        assert cv["par_chemin"] == {
            "start_combat": 1, "attack": 1, "jets": 2, "prose": 1}, cv
        assert cv["par_partie"] == {
            "partie-01": "start_combat", "partie-02": "attack",
            "partie-03": "jets", "partie-04": "jets", "partie-05": "prose"}, cv
        assert "partie-06" not in cv["par_partie"], cv
        assert cv["prose_seule_nommes"] == ["partie-05, tour 1"], cv
        print("1) combats_vus() : 5 combats, quatre chemins distincts "
              "(deux voies vers « jets seuls » : check et bouchage), "
              "prose seule nommée (partie, tour)")

        rapport = metriques_nuit.calculer_rapport(run_dir, "fin de nuit", 60, "non")
        assert rapport["combats_vus"] == cv, rapport
        rendu = metriques_nuit.formater_rapport_markdown(rapport)
        assert ("Combats vus (#340) : 5 (start_combat 1 · attack seul 1 · "
                "jets seuls 2 · prose seule 1)") in rendu, rendu
        assert "partie-01 : start_combat" in rendu, rendu
        assert "partie-05, tour 1" in rendu, rendu
        print("2) rapport-nuit.md porte la ligne « Combats vus » + le pire "
              "cas nommé")

        # --- unités : lire_combats_declares prime sur index.json ------------
        (partition_dir / "mapping-regles.json").write_text(json.dumps({
            "combats": {"salle-gardee": ["gobelin", {"id": "gobelin2"}]},
        }), encoding="utf-8")
        declares = metriques_nuit.creatures_par_noeud(partition_dir)
        assert declares == {"salle-gardee": ["gobelin", "gobelin2"]}, declares
        print("3) creatures_par_noeud() : la déclaration `combats` de "
              "mapping-regles.json (#316 (b)) prime sur le repli index.json")

        # --- unités : creatures_module (repli hors nœud) ---------------------
        assert metriques_nuit.creatures_module(partition_dir) == {
            "gobelin", "gobelin2"}
        assert metriques_nuit.creatures_module(None) == set()
        print("4) creatures_module() : tous les ids creature, sans "
              "distinction de nœud")

        # --- unités : lieu_par_tour, reconstitution cumulative --------------
        evs = [
            {"turn": 1, "env": {"deltas": {"location": "a"}}},
            {"turn": 2, "env": {}},
            {"turn": 3, "env": {"deltas": {"location": "b"}}},
        ]
        assert metriques_nuit.lieu_par_tour(evs, 4) == {
            1: "a", 2: "a", 3: "b", 4: "b"}, metriques_nuit.lieu_par_tour(evs, 4)
        print("5) lieu_par_tour() : nœud courant porté d'un tour au suivant "
              "tant qu'aucun `location` ne le change")

        # --- unités : chemin_combat_tour, priorité start_combat > attack > jets
        assert metriques_nuit.chemin_combat_tour(
            [{"type": "start_combat"},
             {"env": {"deltas": {"enemies": {"g": {}}}}}]) == "start_combat"
        assert metriques_nuit.chemin_combat_tour(
            [{"env": {"deltas": {"enemies": {"g": {}}}}},
             {"env": {"check": {"stat": "x"}}}]) == "attack"
        assert metriques_nuit.chemin_combat_tour(
            [{"env": {"check": {"stat": "x"}}}]) == "jets"
        assert metriques_nuit.chemin_combat_tour([{"env": {}}]) is None
        print("6) chemin_combat_tour() : priorité start_combat > attack > "
              "jets > None (aucun signal moteur)")

        print("\nALL METRIQUES_NUIT_COMBATS_I340 TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
