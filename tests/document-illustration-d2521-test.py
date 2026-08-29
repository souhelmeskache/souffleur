"""D-252.1 : documents et illustrations montrables (extension Ressource).
100% synthétique (D-109) : aucun matériau de module réel.

Couvre : typologie fine (carte, document, illustration), sous_type
obligatoire pour document/illustration, porteur_ou_emplacement (zéro
dangling), condition_remise_secret_id (référence Secret), état de remise
TRACÉ (non_remis -> remis, unidirectionnel), et une partition synthétique
bout-en-bout VERT avec un document typé complet et une illustration.
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

from coderain.converter import validate_form
from coderain.converter.emit import write_partition
from coderain.converter.schemas import (
    Manifest, Node, Partition, Record, Ressource, Secret,
    RESSOURCE_TYPES, set_etat_ressource,
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


def secret(sid="secret-taverne", node_cible="scene-1"):
    return Secret(sid, "Le tavernier ment.", "secret", [],
                 {"declencheur": "fouille", "node_cible": node_cible},
                 "le tavernier se sauve", [(0, 5)])


# 1 -- RESSOURCE_TYPES étendu, document/illustration acceptés -----------------
section("RESSOURCE_TYPES etendu : carte, document, illustration")
assert RESSOURCE_TYPES == ("carte", "document", "illustration"), RESSOURCE_TYPES

# 2 -- document : sous_type obligatoire, champs propres ----------------------
section("document : sous_type obligatoire + champs D-252.1")
d = Ressource("lettre-menace", "document", [(0, 10)], node_id="scene-1",
             sous_type="lettre", porteur_ou_emplacement="scene-1",
             fonction_md="Révèle le nom du commanditaire.",
             description_md="Verbatim de la lettre.")
assert d.sous_type == "lettre"
assert d.porteur_ou_emplacement == "scene-1"
assert d.fonction_md == "Révèle le nom du commanditaire."
assert d.etat == "non_remis"
assert d.condition_remise_secret_id is None
# refus : document sans sous_type
try:
    Ressource("doc-sans-soustype", "document", [(0, 10)], node_id="scene-1")
    raise AssertionError("document sans sous_type accepte")
except ValueError as e:
    assert "sous_type" in str(e), e

# 3 -- illustration : mêmes champs, sous_type libre ---------------------------
section("illustration : sous_type libre, memes champs")
il = Ressource("illu-revelation-1", "illustration", [(0, 10)], node_id="scene-1",
              sous_type="scene", fonction_md="Déclenche la scène de révélation.")
assert il.sous_type == "scene"
try:
    Ressource("illu-sans-soustype", "illustration", [(0, 10)], node_id="scene-1")
    raise AssertionError("illustration sans sous_type accepte")
except ValueError:
    pass

# 4 -- carte : régime inchangé, sous_type non exigé ---------------------------
section("carte : regime D-217 inchange, sous_type non exige")
c = Ressource("carte-t1", "carte", [(0, 10)], node_id="scene-1",
             fichier="resources/carte-t1.jpg")
assert c.sous_type == ""

# 5 -- condition_remise_secret_id : forme id kebab à la construction ----------
section("condition_remise_secret_id : forme id + resolution en aval")
d2 = Ressource("lettre-conditionnee", "document", [(0, 10)], node_id="scene-1",
              sous_type="lettre", condition_remise_secret_id="secret-taverne")
assert d2.condition_remise_secret_id == "secret-taverne"
try:
    Ressource("lettre-badid", "document", [(0, 10)], node_id="scene-1",
             sous_type="lettre", condition_remise_secret_id="BadId")
    raise AssertionError("condition_remise_secret_id non kebab acceptee")
except ValueError:
    pass

# 6 -- état de remise : transition unidirectionnelle, tracée ------------------
section("etat de remise : non_remis -> remis, jamais retour arriere")
r_etat = Ressource("note-1", "document", [(0, 10)], node_id="scene-1", sous_type="note")
assert r_etat.etat == "non_remis"
assert set_etat_ressource(r_etat, "remis") is True
assert r_etat.etat == "remis"
# retour en arrière refusé
assert set_etat_ressource(r_etat, "non_remis") is False
assert r_etat.etat == "remis"
# état inconnu refusé
assert set_etat_ressource(r_etat, "perdu") is False
# construction directe avec etat invalide refusée
try:
    Ressource("note-bad-etat", "document", [(0, 10)], node_id="scene-1",
             sous_type="note", etat="perdu")
    raise AssertionError("etat invalide accepte a la construction")
except ValueError:
    pass

# 7 -- valideur de forme : les quatre refus listés au contrat ------------------
section("valideur de forme : porteur_ou_emplacement dangling")
tmp = Path(tempfile.mkdtemp(prefix="d2521-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1"))
    r_dangling = Ressource("lettre-dangling", "document", [(0, 5)], node_id="scene-1",
                           sous_type="lettre", porteur_ou_emplacement="nulle-part")
    p.ressources.append(r_dangling)
    p.resources = p.ressources
    errs = validate_form.validate_form(p, tmp)
    assert any("porteur_ou_emplacement" in e and "nulle-part" in e for e in errs), errs
    # garde symétrique côté emit (raise)
    try:
        write_partition(p, tmp)
        raise AssertionError("porteur_ou_emplacement dangling accepte a l'emission")
    except ValueError as e:
        assert "porteur_ou_emplacement" in str(e), e
finally:
    shutil.rmtree(tmp, ignore_errors=True)

section("valideur de forme : condition_remise_secret_id inconnu")
tmp = Path(tempfile.mkdtemp(prefix="d2521-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1"))
    r_bad_secret = Ressource("lettre-secret-inconnu", "document", [(0, 5)], node_id="scene-1",
                             sous_type="lettre", condition_remise_secret_id="secret-fantome")
    p.ressources.append(r_bad_secret)
    p.resources = p.ressources
    errs = validate_form.validate_form(p, tmp)
    assert any("condition_remise_secret_id" in e and "secret-fantome" in e
              for e in errs), errs
    try:
        write_partition(p, tmp)
        raise AssertionError("condition_remise_secret_id inconnu accepte a l'emission")
    except ValueError as e:
        assert "condition_remise_secret_id" in str(e), e
finally:
    shutil.rmtree(tmp, ignore_errors=True)

section("valideur de forme : document sans sous_type (construction refusee en amont)")
# la garde vit à la construction (schemas.Ressource) ; validate_form la
# re-checke aussi via une ressource factice pour couvrir la ligne §9 seule.
class FakeDocSansSousType:
    id = "fake-doc"
    type_ressource = "document"
    node_id = "scene-1"
    page = None
    fichier = ""
    anchors = [(0, 5)]
    sous_type = ""
    porteur_ou_emplacement = None
    fonction_md = ""
    condition_remise_secret_id = None
    etat = "non_remis"


tmp = Path(tempfile.mkdtemp(prefix="d2521-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1"))
    p.ressources.append(FakeDocSansSousType())  # type: ignore
    p.resources = p.ressources
    errs = validate_form.validate_form(p, tmp)
    assert any("sous_type obligatoire" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 8 -- bout-en-bout : partition avec document + illustration typés, VERT ------
section("bout-en-bout : document typé + illustration, partition VERT")
tmp = Path(tempfile.mkdtemp(prefix="d2521-boutenbout-"))
try:
    p = Partition(manifest())
    p.nodes.append(Node("scene-1", "scene", "SCENE 1", "La taverne s'anime.",
                        "scene", anchors=[(0, 30)]))
    p.nodes.append(Node("scene-2", "scene", "SCENE 2", "Le repaire secret.",
                        "scene", anchors=[(30, 60)]))
    p.nodes[-1].liens.append({"cible_id": "scene-1", "condition_textuelle": "retour"})
    from coderain.converter.schemas import Aventure
    p.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Enquete lancee",
          "declencheur": {"type": "etat", "valeur": "enquete lancee"},
          "perturbations": [{"condition_etat": "abandon", "issue": "abandonnee",
                              "porteur_cible_id": "scene-1"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    p.secrets.append(secret("secret-taverne", "scene-1"))
    # document typé complet : sous_type, porteur, fonction, condition liée à un Secret
    p.ressources.append(Ressource(
        "lettre-menace", "document", [(10, 20)], node_id="scene-1",
        sous_type="lettre", porteur_ou_emplacement="scene-1",
        fonction_md="Révèle le nom du commanditaire au joueur.",
        condition_remise_secret_id="secret-taverne",
        description_md="Verbatim : « Tu paieras pour ce que tu sais. »"))
    # illustration
    p.ressources.append(Ressource(
        "illu-repaire", "illustration", [(30, 40)], node_id="scene-2",
        sous_type="lieu", fonction_md="Pose visuellement le repaire secret.",
        description_md="Le repaire, vu depuis l'entrée."))
    p.resources = p.ressources
    write_partition(p, tmp)
    (tmp / "directeur.md").write_text("# Brief\nContenu sans secret.\n", encoding="utf-8")
    errs = validate_form.validate_form(p, tmp)
    assert errs == [], f"partition VERT attendue mais {errs}"
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["resources"]) == 2
    types = {r["type"] for r in idx["resources"]}
    assert types == {"document", "illustration"}, types
    for r in idx["resources"]:
        assert r["etat"] == "non_remis", r
    # front matter porte bien les champs D-252.1
    txt = (tmp / "resources" / "lettre-menace.md").read_text(encoding="utf-8")
    assert '"sous_type": "lettre"' in txt, txt
    assert '"porteur_ou_emplacement": "scene-1"' in txt, txt
    assert '"condition_remise_secret_id": "secret-taverne"' in txt, txt
    assert '"etat": "non_remis"' in txt, txt
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\nOK document-illustration-d2521-test — {len(FAIT)} sections vertes")
