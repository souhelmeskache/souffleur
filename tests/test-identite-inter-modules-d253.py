"""D-253.2 (Issue #72) : identité inter-modules — garde de résolution.

100% synthétique (D-109) : deux mini-partitions factices partageant un PNJ
récurrent, aucun matériau de module réel. Couvre le contrat de
coderain/converter/validate_inter_module.py::cross_module_report :
  1. référence inter-modules conforme (même slug, module différent) résout
     — la garde intra-module seule la verrait dangling, celle-ci non ;
  2. référence vers un slug absent de TOUS les modules fournis -> échec
     explicite (liste "orphelines") ;
  3. deux slugs distincts portant le même nom d'usage déclaré -> signalement
     (liste "slugs_suspects"), jamais un refus.
Voir docs/identite-inter-modules-d253.md pour la convention consignée.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter.schemas import Manifest, Node, Partition, Record
from coderain.converter.validate_inter_module import cross_module_report

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest(titre):
    return Manifest(titre=titre, corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="0" * 64,
                    date_conversion="2026-08-26T00:00:00+00:00",
                    version_convertisseur="test")


# module A : définit le PNJ récurrent sous son slug canonique --------------
manifest_a = manifest("Module A")
node_a1 = Node("scene-a1", "scene", "SCENE A1",
               "Le garde Huygens surveille le pont-levis.", "scene",
               anchors=[(0, 10)])
record_huygens = Record("garde-huygens", "pnj", "Huygens",
                        {"role": "garde", "description_md": "Garde du pont."},
                        anchors=[(0, 10)])
partition_a = Partition(manifest_a)
partition_a.nodes = [node_a1]
partition_a.records = [record_huygens]


def module_b(heritage_porte, records_extra=None):
    """Module B factice : un node d'altitude scenario dont heritage.porte
    cite `heritage_porte` — id censé résoudre inter-modules (D-253.2)."""
    m = manifest("Module B")
    node_b1 = Node("scenario-b1", "scene", "SCENARIO B1",
                   "Retour au pont, Huygens s'en souvient.", "scenario",
                   anchors=[(0, 10)],
                   heritage=[{"fait_md": "Le garde reconnaît le héros.",
                              "ancre_source": [0, 5],
                              "porte": [heritage_porte]}])
    p = Partition(m)
    p.nodes = [node_b1]
    p.records = list(records_extra or [])
    return p


# 1 -- référence inter-modules conforme : résout via l'union ----------------
section("heritage.porte vers un slug défini dans un AUTRE module : résout")
partition_b = module_b("garde-huygens")
rapport = cross_module_report([partition_a, partition_b])
assert rapport["orphelines"] == [], rapport["orphelines"]
assert rapport["slugs_suspects"] == [], rapport["slugs_suspects"]

# avec une seule partition (B isolée), la même référence est bien dangling
# côté garde intra-module — la garde inter-modules ajoute l'étage, elle ne
# remplace rien (contrat : « la garde intra-module reste inchangée »)
from coderain.converter.validate_form import scenario_report
intra_seul = scenario_report(partition_b)
assert any("garde-huygens" in e for e in intra_seul["erreurs"]), (
    "attendu : heritage.porte dangling en isolation intra-module", intra_seul)

# 2 -- référence orpheline : slug absent de TOUS les modules fournis --------
section("heritage.porte vers un slug absent partout : échec explicite")
partition_b_orpheline = module_b("porte-fantome")
rapport2 = cross_module_report([partition_a, partition_b_orpheline])
assert len(rapport2["orphelines"]) == 1, rapport2["orphelines"]
assert "porte-fantome" in rapport2["orphelines"][0]
assert "Module B" in rapport2["orphelines"][0]
assert rapport2["slugs_suspects"] == []

# 3 -- slugs suspects : même nom d'usage, deux slugs distincts --------------
section("deux slugs distincts partageant le même nom d'usage : signalement")
capitaine_huygens = Record("capitaine-huygens", "pnj", "Huygens",
                           {"role": "capitaine", "description_md":
                            "Capitaine du fort, même nom que le garde."},
                           anchors=[(0, 10)])
partition_b_doublon = module_b("garde-huygens", records_extra=[capitaine_huygens])
rapport3 = cross_module_report([partition_a, partition_b_doublon])
assert rapport3["orphelines"] == [], rapport3["orphelines"]  # signalement seul, pas un échec
assert len(rapport3["slugs_suspects"]) == 1, rapport3["slugs_suspects"]
suspect = rapport3["slugs_suspects"][0]
assert "garde-huygens" in suspect and "capitaine-huygens" in suspect, suspect
assert "huygens" in suspect

# 4 -- pas de faux positif : deux entités différentes, noms différents ------
section("noms d'usage distincts : pas de signalement")
autre = Record("aubergiste-morna", "pnj", "Morna",
               {"role": "aubergiste", "description_md": "Tient l'auberge."},
               anchors=[(0, 10)])
partition_b_ok = module_b("garde-huygens", records_extra=[autre])
rapport4 = cross_module_report([partition_a, partition_b_ok])
assert rapport4["orphelines"] == []
assert rapport4["slugs_suspects"] == []

print(f"\nOK test-identite-inter-modules-d253 — {len(FAIT)} sections vertes")
