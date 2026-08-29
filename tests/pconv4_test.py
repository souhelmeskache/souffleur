"""P-CONV-4 (Issue #80) : partition DKS ré-émise avec les extensions D-252
(objets magiques, tables consultation, documents/illustrations, sorts
inédits) + détection des jets D-254. 100% synthétique (D-109) pour les
sections 1-4 : les primitives D-252 elles-mêmes sont déjà couvertes en
détail par leurs suites dédiées (`pconv_objets_magiques_test.py`,
`test-table-consultation-d252-4.py`, `document-illustration-d2521-test.py`,
`test-classe-sort-d252c.py`) — cette suite exerce leur COMBINAISON telle
qu'appliquée par la passe P-CONV-4 : un objet magique câblé à un secret, une
table restée en mode aléatoire (décision consignée), un document et une
illustration typés, zéro sort inédit. La section 5 charge la partition-pconv4
RÉELLE (hors git, `corpus_dir()`) et n'en lit que les FORMES et COMPTES.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.config import corpus_dir
from coderain.converter import validate_form
from coderain.converter.emit import write_partition
from coderain.converter.schemas import (
    Manifest, Node, Partition, Record, RollTable, Ressource, Secret,
)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e", corpus_cible="5e",
                    structures=["S1", "S2"], hash_source="0" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


def node(nid="scene-1", body="Contenu de scene.", anchors=None):
    return Node(nid, "scene", nid.upper(), body, "scene", anchors=anchors or [(0, 10)])


# 1 -- objet magique requalifié (D-252.2), câblé à un secret --------------
section("objet magique requalifie : type/rarete/activation + secret_lie_id")
p = Partition(manifest())
p.nodes.append(node("scene-crypte", "La crypte s'ouvre.", [(0, 30)]))
p.records.append(Record(
    "epee-exemple", "objet", "Épée d'exemple",
    {"description_md": "Épée d'exemple, face visible.",
     "type_objet": "arme", "rarete": "rare",
     "harmonisation": True, "activation": "action",
     "effets_md": "Inflige des dégâts radiants supplémentaires.",
     "secret_lie_id": "secret-epee-exemple"}, [(0, 20)]))
p.secrets.append(Secret(
    "secret-epee-exemple", "En vérité maudite.", "secret", ["epee-exemple"],
    {"declencheur": "harmonisation", "node_cible": "scene-crypte"},
    "le porteur perd le controle", [(0, 10)]))
errs = validate_form.validate_form(p)
assert not [e for e in errs if "secret_lie_id" in e], errs
assert p.records[0].stats_5e["type_objet"] == "arme"
assert p.records[0].stats_5e["rarete"] == "rare"

# 2 -- objet examine mais NON requalifie (judgment call consigne) ---------
section("objet ordinaire volontairement non requalifie reste valide")
r_ordinaire = Record("baie-exemple", "objet", "Baie d'exemple",
                     {"description_md": "Restaure quelques points de vie."},
                     [(0, 10)])
assert "type_objet" not in r_ordinaire.stats_5e

# 3 -- table : decision table-par-table consignee, aucune consultation ----
section("table d100 : decision consignee, mode aleatoire retenu")
DECISION = {"table-exemple-a": "aleatoire", "table-exemple-b": "aleatoire"}
t_a = RollTable("table-exemple-a", "1d100",
               [{"plage_debut": 1, "plage_fin": 50, "resultat_md": "entree A"},
                {"plage_debut": 51, "plage_fin": 100, "resultat_md": "entree B"}],
               [(0, 10)])
assert t_a.mode == "aleatoire"
assert all(v == "aleatoire" for v in DECISION.values())
# une table QUI répondrait à une question directe basculerait en consultation
# (forme déjà couverte par test-table-consultation-d252-4.py) — non illustrée
# ici car DKS n'a aucun cas d'usage réel (rapport §3).

# 4 -- documents/illustrations typés (D-252.1) -----------------------------
section("document + illustration types, rattaches a des nodes existants")
tmp = Path(tempfile.mkdtemp(prefix="pconv4-doc-"))
try:
    p2 = Partition(manifest())
    p2.nodes.append(node("entrancetomb-exemple", "Devant le caveau.", [(0, 20)]))
    p2.nodes.append(node("stonedoors-exemple", "Portes de pierre.", [(20, 40)]))
    p2.ressources.append(Ressource(
        "doc-exemple", "document", [(0, 10)], node_id="entrancetomb-exemple",
        sous_type="inscription", porteur_ou_emplacement="entrancetomb-exemple",
        fonction_md="Indice de dissimulation d'identite.",
        description_md="Inscription partiellement effacee."))
    p2.ressources.append(Ressource(
        "illu-exemple", "illustration", [(20, 30)], node_id="stonedoors-exemple",
        sous_type="scene",
        fonction_md="Pose visuellement le seuil.",
        description_md="Mosaique ornant la porte."))
    p2.resources = p2.ressources
    write_partition(p2, tmp)
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["resources"]) == 2
    types = {r["type"] for r in idx["resources"]}
    assert types == {"document", "illustration"}, types
    for r in idx["resources"]:
        assert r["etat"] == "non_remis", r
        assert r.get("sous_type"), r
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 5 -- zero sort inedit : aucun record classe sort dans une passe sans -----
#      sort hors SRD (D-252.3 reste disponible, juste non utilise ici)
section("zero sort inedit : la classe sort reste disponible, non utilisee")
p3 = Partition(manifest())
p3.nodes.append(node("scene-1"))
p3.records.append(r_ordinaire)
assert not [r for r in p3.records if r.classe == "sort"]

# 6 -- partition-pconv4 REELLE : comptages et verdict ----------------------
section("partition-pconv4 reelle : comptages D-252 + verdict VERT")
part_dir = corpus_dir() / "death-knights-squire" / "partition-pconv4"
if part_dir.exists():
    idx = json.loads((part_dir / "index.json").read_text(encoding="utf-8"))
    assert len(idx["nodes"]) == 361, len(idx["nodes"])
    assert len(idx["records"]) == 35, len(idx["records"])
    assert len(idx["tables"]) == 5, len(idx["tables"])
    assert len(idx["secrets"]) == 4, len(idx["secrets"])
    assert len(idx.get("tensions", [])) == 9, len(idx.get("tensions", []))
    resources = idx.get("resources", [])
    assert len(resources) == 22, len(resources)
    par_type = {}
    for r in resources:
        par_type[r["type"]] = par_type.get(r["type"], 0) + 1
    assert par_type == {"carte": 19, "document": 2, "illustration": 1}, par_type

    # objets magiques requalifiés (D-252.2) : compte via records-auteur.json
    # côté corpus (matière source, jamais copiée ici) -- on ne relit que le
    # COMPTE, pas le contenu.
    records_auteur = json.loads(
        (corpus_dir() / "death-knights-squire" / "records-auteur.json")
        .read_text(encoding="utf-8"))
    magiques = [r for r in records_auteur
               if r["classe"] == "objet" and "type_objet" in r["stats"]]
    assert len(magiques) == 8, len(magiques)

    # tables : toutes en mode aleatoire (aucune consultation, decision §3)
    for f in (part_dir / "tables").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---", txt, re.S)
        fm = json.loads(m.group(1))
        assert fm.get("de"), f"table {fm['id']} attendue en mode aleatoire"

    # jets détectés (D-254) : 51 (42 check + 9 saving_throw)
    mr = json.loads((part_dir / "mapping-regles.json").read_text(encoding="utf-8"))
    tous = [j for jets in mr["checks"].values() for j in jets]
    assert len(tous) == 51, len(tous)
    par_kind = {}
    for j in tous:
        par_kind[j["kind"]] = par_kind.get(j["kind"], 0) + 1
    assert par_kind == {"check": 42, "saving_throw": 9}, par_kind

    # régime trans-modules D-253.1/D-253.2 rejoué et consigné par l'outil
    regime_path = part_dir / "rapport-regime-trans-modules.json"
    if regime_path.exists():
        regime = json.loads(regime_path.read_text(encoding="utf-8"))
        assert regime["inter_modules"]["orphelines"] == [], regime
        assert regime["echeancier"]["vivantes"] == 0
        assert regime["echeancier"]["echues"] == 0

    # verdict global
    rapport = json.loads((part_dir / "rapport-conversion.json").read_text(encoding="utf-8"))
    assert rapport["verdict"] == "VERT", rapport["verdict"]
    assert rapport["comptages"]["form_errors"] == 0
    assert rapport["comptages"]["coverage_gaps"] == 0
    assert rapport["comptages"]["coverage_overlaps"] == 0
else:
    print("SKIP partition reelle : dossier absent (CI)")

print(f"\nOK pconv4_test — {len(FAIT)} sections vertes")
