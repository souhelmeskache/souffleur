"""F1.4 (Issue #342) — mesure des prérequis de débouché sur les nœuds
scénario : `coderain/converter/mesure_f14.py`. Partition SYNTHÉTIQUE (D-109 :
zéro matériau réel versionné) — 2 nœuds 'scenario', débouchés avec/sans
prérequis, un `ouvre_vers_md`, une négation, un corps de nœud scénario
portant un motif d'axe HORLOGE, un nœud 'scene' pour vérifier l'agrégat.

Vérifie ligne à ligne le rapport attendu (build_report) + que le rendu
Markdown (render_md) ne porte AUCUN texte de corps de node, seulement des
comptes et des ids.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter.emit import write_partition
from coderain.converter.mesure_f14 import build_report, render_md
from coderain.converter.schemas import Manifest, Node, Partition

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def _manifest():
    return Manifest(titre="module factice F1.4", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="f" * 64,
                    date_conversion="2026-09-06T00:00:00+00:00",
                    version_convertisseur="test")


CORPS_SCEN_1 = ("Vous frappez à la porte close du donjon. Le froid mord "
                "avant que le garde ne réponde.")
CORPS_SCEN_2 = "Le couloir s'ouvre sur une salle vide, poussiéreuse."


def _build_partition() -> Partition:
    p = Partition(_manifest())
    n1 = Node("para-1", "section", "#1", CORPS_SCEN_1, "scenario",
             anchors=[(0, len(CORPS_SCEN_1))])
    n1.attach_scenario(
        objectif_md="Franchir la porte du donjon.",
        debouches=[
            {"id": "porte-forcee", "cible_id": "para-2",
             "prerequis_etat": []},
            {"id": "porte-crochetee", "cible_id": "para-2",
             "prerequis_etat": [
                 {"type": "flag", "nom": "possede-crochets"}]},
            {"id": "porte-gardee", "ouvre_vers_md": "un affrontement",
             "prerequis_etat": [
                 {"type": "non",
                  "atome": {"type": "entite_vivante", "id": "garde-1"}}]},
        ])
    n2 = Node("para-2", "section", "#2", CORPS_SCEN_2, "scenario",
             anchors=[(0, len(CORPS_SCEN_2))])
    n2.attach_scenario(
        objectif_md="",  # I-111 : objectif_md absent, mesuré tel quel
        debouches=[
            {"id": "salle-sortie", "cible_id": "para-1",
             "prerequis_etat": []},
        ])
    n3 = Node("para-3", "section", "#3", "Une salle sans issue narrée.",
             "scene", anchors=[(0, 10)])
    p.nodes.extend([n1, n2, n3])
    p.aventure = None
    return p


TMP = Path(tempfile.mkdtemp(prefix="f14-"))
PDIR = TMP / "partition"
write_partition(_build_partition(), PDIR)
(PDIR / "directeur.md").write_text("## Brief\n\nReste tendu.\n",
                                   encoding="utf-8")

section("1) build_report — comptes par nœud scénario")
report = build_report(PDIR)
assert report["noeuds_scenario"] == 2
assert report["noeuds_scenario_sans_objectif"] == ["para-2"]
assert report["noeuds_scene"] == 1

scen_by_id = {s["id"]: s for s in report["scenarios"]}
p1 = scen_by_id["para-1"]
assert p1["objectif_md_present"] is True
assert p1["debouches_total"] == 3
assert p1["debouches_sans_prerequis"] == ["porte-forcee"]
deb_by_id = {d["id"]: d for d in p1["debouches"]}
assert deb_by_id["porte-forcee"]["n_prerequis"] == 0
assert deb_by_id["porte-forcee"]["cible"] == {"kind": "cible_id",
                                              "value": "para-2"}
assert deb_by_id["porte-crochetee"]["types_prerequis"] == ["flag"]
assert deb_by_id["porte-crochetee"]["negations"] == 0
assert deb_by_id["porte-gardee"]["cible"] == {"kind": "ouvre_vers_md"}
assert deb_by_id["porte-gardee"]["types_prerequis"] == ["entite_vivante"]
assert deb_by_id["porte-gardee"]["negations"] == 1

p2 = scen_by_id["para-2"]
assert p2["objectif_md_present"] is False
assert p2["debouches_total"] == 1
assert p2["debouches_sans_prerequis"] == ["salle-sortie"]
print("  OK : para-1 (3 débouchés, 1 sans prérequis, 1 négation, "
     "1 ouvre_vers_md) et para-2 (objectif_md absent) mesurés ligne à ligne")

section("2) totaux scénario/scène")
tot = report["totaux_scenario"]
assert tot["debouches_total"] == 4
assert tot["debouches_sans_prerequis"] == 2
assert tot["debouches_avec_prerequis"] == 2
assert tot["types_prerequis"] == {"entite_vivante": 1, "flag": 1,
                                  "quete_etat": 0}
assert tot["negations"] == 1
assert tot["cible_id"] == 3
assert tot["ouvre_vers_md"] == 1

scene_tot = report["totaux_scene"]
assert scene_tot["debouches_total"] == 0  # un node 'scene' ne porte pas
                                          # de debouches (attach_scenario
                                          # exige altitude 'scenario')
print("  OK : totaux scénario (4 débouchés, 2 sans prérequis, types "
     "{entite_vivante:1, flag:1}) et agrégat scène (0 débouché) exacts")

section("3) signaux d'axe — horloge détectée sur para-1, pas sur para-2")
sig = report["signaux_axe"]
assert sig["horloge"]["occurrences"] >= 1
assert sig["horloge"]["noeuds"] == ["para-1"]
assert sig["lieu"]["occurrences"] == 0
assert sig["lieu"]["noeuds"] == []
print("  OK : motif horloge ('avant que') détecté sur para-1 seul, "
     "aucun signal lieu")

section("4) render_md — chiffres et ids seuls, jamais le corps du node")
md = render_md(report, partition_slug="partition-f14-synthetique",
               date="2026-09-06")
assert "para-1" in md and "para-2" in md
assert "porte-gardee" in md
for corps in (CORPS_SCEN_1, CORPS_SCEN_2, "Franchir la porte du donjon."):
    assert corps not in md, f"fuite de texte de module dans le rendu: {corps!r}"
print("  OK : le Markdown cite les ids mais aucun corps_md/objectif_md")

print("\nALL F1.4 (#342) CHECKS PASSED: " + ", ".join(FAIT))
