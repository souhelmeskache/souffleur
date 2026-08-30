"""Test d'élément — BOUCLAGE : écrire la production Auteur (declaration_rendu)
dans scenario-auteur.json (Issue #187, dernier maillon du chemin AUTEUR).

Brique visée : `coderain.converter.rendu_auteur.node_id_par_scene` +
`coderain.converter.rendu_auteur.ecrire_rendu_auteur` (mapping scène ->
node_id depuis une partition convertie, câblage via
`ecrivain_module.vers_scenario_auteur`, fusion non destructive dans
`scenario-auteur.json`, lu ensuite par `coderain/converter/cli.py` §
scenario-auteur.json et posé par `Node.attach_scenario`). Voir
tests/fixtures/element_mold.py pour la doctrine du moule et
README-moule-test-element.md pour le gabarit.

Fixtures d'états (100% synthétique, D-109/D-206 — aucun matériau réel) :
  1. declaration_rendu (2 scènes) + partition convertie (nodes aux titres
     correspondants) -> scenario-auteur.json porte scenarios[].rendu_md sur
     les bons node_id ; ré-application (`Node.attach_scenario`, même
     lecture que cli.py) -> Node.rendu_md peuplé, round-trip
     write_partition/get_node.
  2. node ayant déjà une entrée objectif_md -> rendu_md ajouté à la MÊME
     entrée, objectif_md intact.
  3. scène sans node correspondant -> signalée, aucune entrée créée.
  4. idempotence : seconde écriture identique à la première.

Verdicts mécaniques (D-134) : égalité de chaîne, présence/absence, égalité
de fichier après double écriture.
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

from tests.fixtures.element_mold import ElementMold, present
from coderain.converter.emit import write_partition
from coderain.converter.aval import get_node
from coderain.converter.rendu_auteur import ecrire_rendu_auteur
from coderain.converter.schemas import Manifest, Node, Partition


def _manifest():
    return Manifest(titre="module factice boucle rendu_md auteur",
                    corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="7" * 64,
                    date_conversion="2026-08-30T00:00:00+00:00",
                    version_convertisseur="test")


DECLARATION_RENDU = (
    {"scene": "Scène -- la veillée des braises",
     "rendu_md": "registre feutré ; joue les silences, ne révèle rien"},
    {"scene": "Scène -- le passage du gué",
     "rendu_md": "registre urgent ; presse le rythme, laisse peu de répit"},
    {"scene": "Scène -- introuvable",
     "rendu_md": "registre mystérieux ; entretiens le doute"},
)


with ElementMold("rendu_md-boucle-auteur-i187", budget_seconds=5.0) as mold:
    tmp = Path(tempfile.mkdtemp(prefix="rendu-md-boucle-i187-"))
    try:
        # ---- partition convertie : deux scènes, titres correspondants ----
        node_veillee = Node("sc-veillee", "section",
                            "Scène -- la veillée des braises",
                            "Autour du feu.", "scene", anchors=[(0, 10)])
        node_gue = Node("sc-gue", "section", "Scène -- le passage du gué",
                        "L'eau presse.", "scene", anchors=[(10, 20)])
        node_avec_objectif = Node("sc-veillee-obj", "chapitre",
                                  "Scène -- la veillée des braises (bis)",
                                  "Autour du feu bis.", "scene",
                                  anchors=[(20, 30)])
        node_avec_objectif.attach_scenario("tenir la veillée jusqu'au bout")
        partition = Partition(_manifest())
        partition.nodes.extend([node_veillee, node_gue])

        chemin = tmp / "scenario-auteur.json"

        # ---- 1. mapping + écriture -> scenario-auteur.json bien peuplé ----
        res1 = ecrire_rendu_auteur(DECLARATION_RENDU, partition, [chemin])
        data1 = json.loads(chemin.read_text(encoding="utf-8"))
        by_id = {s["node_id"]: s for s in data1["scenarios"]}
        mold.check(
            "1-scenario-auteur-peuple-sur-les-bons-nodes",
            by_id.get("sc-veillee", {}).get("rendu_md")
            == "registre feutré ; joue les silences, ne révèle rien"
            and by_id.get("sc-gue", {}).get("rendu_md")
            == "registre urgent ; presse le rythme, laisse peu de répit",
            f"data1={data1!r}")

        # ---- round-trip : cli.py relit et pose via attach_scenario --------
        node_veillee.attach_scenario(
            rendu_md=by_id["sc-veillee"]["rendu_md"])
        write_partition(partition, tmp)
        loaded = get_node(tmp, "sc-veillee")
        mold.check(
            "1b-round-trip-write-partition-get-node",
            present(loaded["meta"].get("rendu_md", ""),
                   "registre feutré"),
            f"loaded={loaded!r}")

        # ---- 2. node avec objectif_md déjà posé : fusion non destructive --
        partition2 = Partition(_manifest())
        partition2.nodes.append(node_avec_objectif)
        decl2 = ({"scene": "Scène -- la veillée des braises (bis)",
                 "rendu_md": "registre chaleureux ; installe le confort"},)
        chemin2 = tmp / "scenario-auteur-2.json"
        # une entrée objectif_md pré-existante pour ce node_id
        chemin2.write_text(json.dumps(
            {"scenarios": [{"node_id": "sc-veillee-obj",
                           "objectif_md": "tenir la veillée jusqu'au bout"}]},
            ensure_ascii=False), encoding="utf-8")
        ecrire_rendu_auteur(decl2, partition2, [chemin2])
        data2 = json.loads(chemin2.read_text(encoding="utf-8"))
        entry2 = next(s for s in data2["scenarios"]
                     if s["node_id"] == "sc-veillee-obj")
        mold.check(
            "2-fusion-non-destructive-objectif-md-intact",
            entry2.get("objectif_md") == "tenir la veillée jusqu'au bout"
            and entry2.get("rendu_md")
            == "registre chaleureux ; installe le confort",
            f"entry2={entry2!r}")

        # ---- 3. scène sans node correspondant -> signalée, pas d'entrée --
        mold.check(
            "3-scene-sans-node-signalee",
            any("introuvable" in a for a in res1["avertissements"])
            and not any(e["node_id"] == "" for e in res1["entrees"])
            and len(res1["entrees"]) == 2,
            f"avertissements={res1['avertissements']!r} "
            f"entrees={res1['entrees']!r}")

        # ---- 4. idempotence : seconde écriture identique à la première ---
        avant = chemin.read_text(encoding="utf-8")
        ecrire_rendu_auteur(DECLARATION_RENDU, partition, [chemin])
        apres = chemin.read_text(encoding="utf-8")
        mold.check("4-idempotence-double-ecriture", avant == apres,
                  f"avant={avant!r} apres={apres!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

assert mold.report(), ("test-element-rendu-md-boucle-i187: au moins un "
                       "verdict a échoué")
print("test-element-rendu-md-boucle-i187: OK — Issue #187, "
     "4 verdicts mécaniques + coût borné")
