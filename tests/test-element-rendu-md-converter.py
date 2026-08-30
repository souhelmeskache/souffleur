"""Test d'élément — EXTRACTION : le converter peuple rendu_md (Issue #182).

Brique visée : `coderain.converter.s1_local.node_for_unit` (caractérisation
du tiers sans directive) + `coderain.converter.schemas.Node.attach_scenario`
(véhicule commun rendu_md — contrat de champ `scenario-auteur.json` §
`scenarios[].rendu_md`, lu par cli.py à côté d'`objectif_md`). Voir
tests/fixtures/element_mold.py pour la doctrine du moule et
README-moule-test-element.md pour le gabarit.

Fixtures d'états (100% synthétique, D-109/D-206 — aucun matériau réel) :
  1. source portant une directive de rendu explicite (véhicule commun) —
     rendu_md peuplé sur le bon node, survit à write_partition/get_node.
  2. source tierce sans ton identifiable (aucun lexique de registre
     reconnu) — rendu_md vide + avertissement signalé, jamais un ton
     inventé (D-102/I-111).
  3. source tierce avec un ton identifiable (lexique de tension) —
     rendu_md peuplé par caractérisation, aucune directive fournie.
  4. une directive posant une séquence d'événements imposée — refusée par
     la garde anti-rail du socle (D-065, héritée, non dupliquée ici).

Verdicts mécaniques (D-134) : présence/égalité de substring, ValueError
levée avec le bon marqueur, survie à la sérialisation.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.element_mold import ElementMold, present
from coderain.converter import s1_local
from coderain.converter.aval import get_node
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Unit


def _manifest():
    return Manifest(titre="module factice rendu_md converter",
                    corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="4" * 64,
                    date_conversion="2026-08-30T00:00:00+00:00",
                    version_convertisseur="test")


with ElementMold("converter-rendu_md", budget_seconds=5.0) as mold:

    # ---- 1. directive explicite (véhicule commun, attach_scenario) --------
    node1 = Node("sc-explicite", "chapitre", "Chapitre I",
                "Vous entrez dans la salle du trone.", "scene",
                anchors=[(0, 10)])
    DIRECTIVE = "registre solennel ; fais peser le poids du protocole"
    node1.attach_scenario("atteindre le trone", rendu_md=DIRECTIVE)
    tmp = Path(tempfile.mkdtemp(prefix="rendu-md-converter-"))
    try:
        p = Partition(_manifest())
        p.nodes.append(node1)
        write_partition(p, tmp)
        loaded = get_node(tmp, "sc-explicite")
        mold.check(
            "1-directive-explicite-peuplee",
            present(loaded["meta"].get("rendu_md", ""), DIRECTIVE)
            and loaded["meta"]["rendu_md"] == DIRECTIVE,
            "rendu_md survit à write_partition/get_node : "
            f"{loaded['meta'].get('rendu_md')!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 2. tiers sans ton identifiable : vide + avertissement ------------
    NEUTRE = "Vous notez le numero sur le registre du batiment."
    unit_neutre = Unit("para-1", "S1", 0, len(NEUTRE), titre="#1")
    node2, warn2 = s1_local.node_for_unit(unit_neutre, NEUTRE, {})
    mold.check(
        "2-tiers-sans-ton-vide",
        node2.rendu_md == "" and warn2 is not None
        and "ton non identifiable" in warn2,
        f"rendu_md={node2.rendu_md!r} avertissement={warn2!r}")

    # ---- 3. tiers avec ton identifiable : caractérisé, pas inventé --------
    TENDU = "Le gobelin grogne, arme au poing, pret a attaquer."
    unit_tendu = Unit("para-2", "S1", 0, len(TENDU), titre="#2")
    node3, warn3 = s1_local.node_for_unit(unit_tendu, TENDU, {})
    mold.check(
        "3-tiers-ton-tendu-caracterise",
        node3.rendu_md != "" and warn3 is None
        and "tendu" in node3.rendu_md,
        f"rendu_md={node3.rendu_md!r}")

    # ---- 4. directive posant une séquence : refusée par le socle ----------
    try:
        Node("sc-sequence", "scene", "X", "b", "scene", anchors=[(0, 1)],
            rendu_md="le joueur fait X puis Y")
        seq_refusee, detail = False, "aucune exception levée"
    except ValueError as e:
        seq_refusee, detail = "D-065" in str(e), str(e)
    mold.check("4-sequence-refusee-par-socle", seq_refusee, detail)

assert mold.report(), ("test-element-rendu-md-converter: au moins un "
                       "verdict a échoué")
print("test-element-rendu-md-converter: OK — Issue #182, "
     "4 verdicts mécaniques + coût borné")
