"""P-CONV-2 : événements, secrets + inventaire de tension (D-218).
100% synthétique (D-109) : aucun matériau de module réel.
Couvre : tensions (catégories, ancrage node, garde zéro-dangling),
secrets (hidden/reveal, garde caméra D-184), événements (declencheur,
perturbations issue garde anti-rail), et bout-en-bout VERT.
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

from coderain.converter import validate_form, validate_fidelity
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record, Secret, Evenement, Aventure, Tension

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="0" * 64,
                    date_conversion="2026-08-26T00:00:00+00:00",
                    version_convertisseur="test")


def node(nid="scene-1", body="Contenu de scene.", anchors=None):
    return Node(nid, "scene", nid.upper(), body, "scene", anchors=anchors or [(0, 10)])


# 1 -- tensions : catégories D-218 --------------------------------------------
section("tensions : catégories D-218 et ancrage node")
for cat in ("menace", "horloge", "echeance", "cout", "choix", "revelation"):
    t = Tension(f"t-{cat}", cat, f"Description {cat}", "scene-1", [(0, 5)])
    assert t.categorie == cat
try:
    Tension("t-bad", "danger", "x", "scene-1", [(0, 5)])
    raise AssertionError("categorie invalide acceptee")
except ValueError:
    pass
try:
    Tension("t-noanchor", "menace", "x", "scene-1", [])
    raise AssertionError("tension sans ancre acceptee")
except ValueError:
    pass
try:
    Tension("t-nodeslug", "menace", "x", "BadNode", [(0, 5)])
    raise AssertionError("node_id non kebab accepte")
except ValueError:
    pass
try:
    Tension("t-empty", "menace", "   ", "scene-1", [(0, 5)])
    raise AssertionError("description vide acceptee")
except ValueError:
    pass

# 2 -- tensions : émission et garde zéro-dangling -----------------------------
section("tensions : emission et garde zero-dangling")
tmp = Path(tempfile.mkdtemp(prefix="pconv2-tensions-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1", "La menace rode.", [(0, 10)]))
    p.nodes.append(node("scene-2", "Choix moral.", [(10, 20)]))
    p.tensions.append(Tension("tension-menace", "menace", "Une menace rode", "scene-1", [(0, 5)]))
    p.tensions.append(Tension("tension-choix", "choix", "Deux voies", "scene-2", [(10, 15)]))
    write_partition(p, tmp)
    assert (tmp / "tensions" / "tension-menace.md").exists()
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["tensions"]) == 2
    assert {t["categorie"] for t in idx["tensions"]} == {"menace", "choix"}
    # garde zero-dangling
    p2 = Partition(manifest())
    p2.nodes.append(node("scene-1"))
    p2.tensions.append(Tension("t-dangling", "menace", "x", "nowhere", [(0, 5)]))
    try:
        write_partition(p2, tmp)
        raise AssertionError("tension vers node inconnu acceptee")
    except ValueError as e:
        assert "nowhere" in str(e), e
    # validate_form detecte dangling tension
    p3 = Partition(manifest())
    p3.nodes.append(node("scene-1"))
    p3.tensions.append(Tension("t-dang", "cout", "coute 20gp", "missing-node", [(0, 5)]))
    # inject without emit guard (contournement) pour tester validate_form
    errs = validate_form.validate_form(p3, tmp)
    assert any("tension" in e and "missing-node" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 3 -- secrets : hidden/reveal et garde caméra D-184 -------------------------
section("secrets : hidden/reveal et garde camera D-184")
tmp = Path(tempfile.mkdtemp(prefix="pconv2-secrets-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1", "Scène commune.", [(0, 10)]))
    p.nodes.append(node("reveal-node", "Lieu de revelation.", [(10, 20)]))
    # secret valide
    s = Secret("secret-1", "Le pieu tue le chevalier.", "secret", [], {"declencheur": "inspection", "node_cible": "reveal-node"}, "plus de surprise", [(5, 15)])
    p.secrets.append(s)
    # secret leak detection : contenu dans prose commune => rouge
    p2 = Partition(manifest())
    p2.nodes.append(node("scene-1", "Le pieu tue le chevalier.", [(0, 10)]))
    p2.secrets.append(Secret("secret-1", "Le pieu tue le chevalier.", "secret", [], {"declencheur": "x", "node_cible": "scene-1"}, "", [(0, 5)]))
    errs = validate_form.validate_form(p2)
    assert any("secret leak" in e for e in errs), errs
    # garde camera : secret dans directeur.md => rouge
    p3 = Partition(manifest())
    p3.nodes.append(node("scene-1", "Prose.", [(0, 10)]))
    p3.secrets.append(Secret("secret-cam", "Contenu ultra secret du pieu rougeoyant.", "secret", [], {"declencheur": "x", "node_cible": "scene-1"}, "", [(0, 5)]))
    write_partition(p3, tmp)
    # ecrire directeur contenant le secret
    (tmp / "directeur.md").write_text("BRIEF\nContenu ultra secret du pieu rougeoyant.\n", encoding="utf-8")
    errs = validate_form.validate_form(p3, tmp)
    assert any("garde caméra" in e or "D-184" in e for e in errs), errs
    # sans fuite, vert
    (tmp / "directeur.md").write_text("BRIEF\nRien de secret ici.\n", encoding="utf-8")
    errs = validate_form.validate_form(p3, tmp)
    assert not any("D-184" in e for e in errs), errs
    # dangling revelation
    p4 = Partition(manifest())
    p4.nodes.append(node("scene-1"))
    p4.secrets.append(Secret("secret-bad", "x", "secret", [], {"declencheur": "x", "node_cible": "nowhere"}, "", [(0, 5)]))
    errs = validate_form.validate_form(p4)
    assert any("dangling revelation" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 4 -- evenements : declencheur, perturbations, garde anti-rail ---------------
section("evenements : declencheur, perturbations, garde anti-rail")
e = Evenement("traj-01", "Quête acceptee", declencheur={"type": "etat", "valeur": "quete acceptee"}, perturbations=[{"condition_etat": "abandon", "issue": "abandonnee"}], anchors=[(0, 5)])
assert e.declencheur["type"] == "etat"
try:
    Evenement("bad", "x", declencheur={"type": "mauvais", "valeur": ""}, anchors=[(0, 5)])
    raise AssertionError("declencheur type invalide accepte")
except ValueError:
    pass
try:
    Evenement("bad2", "", declencheur={"type": "etat", "valeur": ""}, anchors=[(0, 5)])
    raise AssertionError("description vide acceptee")
except ValueError:
    pass
# perturbation sans issue => construite mais validate_form la signale rouge
e2 = Evenement("traj-02", "Traversee foret", declencheur={"type": "etat", "valeur": "entree foret"}, perturbations=[{"condition_etat": "echec jet"}], anchors=[(5, 10)])
assert e2.perturbations[0].get("issue") is None
tmp = Path(tempfile.mkdtemp(prefix="pconv2-events-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1"))
    p.aventure = Aventure([{"id": "traj-02", "description_md": "Traversee foret", "declencheur": {"type": "etat", "valeur": "entree foret"}, "perturbations": [{"condition_etat": "echec jet"}], "ancres_sources": [[5, 10]]}], [], "charniere")
    errs = validate_form.validate_form(p)
    assert any("perturbation sans issue" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 5 -- bout-en-bout : partition avec tensions/secrets/events VERT ------------
section("bout-en-bout : partition avec tensions/secrets/events VERT")
tmp = Path(tempfile.mkdtemp(prefix="pconv2-boutenbout-"))
try:
    p = Partition(manifest())
    p.nodes.append(Node("scene-1", "scene", "SCENE 1", "La forêt de Weathercote s'étend.", "scene", anchors=[(0, 30)]))
    p.nodes.append(Node("reveal-node", "scene", "REVEAL", "Le pieu rougeoyant.", "scene", anchors=[(30, 60)]))
    p.nodes[-1].liens.append({"cible_id": "scene-1", "condition_textuelle": "retour"})
    # aventure avec trajectoire valide (avec issues)
    p.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quete acceptee", "declencheur": {"type": "etat", "valeur": "quete acceptee"}, "perturbations": [{"condition_etat": "abandon", "issue": "abandonnee", "porteur_cible_id": "scene-1"}], "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    # secret valide
    p.secrets.append(Secret("secret-1", "Le pieu tue.", "secret", [], {"declencheur": "inspection", "node_cible": "reveal-node"}, "", [(5, 15)]))
    # tensions valides
    p.tensions.append(Tension("tension-menace-1", "menace", "Menace du chevalier", "scene-1", [(0, 10)]))
    p.tensions.append(Tension("tension-cout-1", "cout", "20 gp de péage", "scene-1", [(10, 20)]))
    p.tensions.append(Tension("tension-choix-1", "choix", "Dire ou mentir", "reveal-node", [(30, 40)]))
    write_partition(p, tmp)
    # directeur sans fuite
    (tmp / "directeur.md").write_text("# Brief\nContenu sans secret.\n", encoding="utf-8")
    errs = validate_form.validate_form(p, tmp)
    assert errs == [], f"partition VERT attendue mais {errs}"
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["tensions"]) == 3
    assert len(idx["secrets"]) == 1
    assert idx["aventure"]["trajectoire"] == 1
    # duplicate id detection inclut tensions
    p_dup = Partition(manifest())
    p_dup.nodes.append(node("scene-1"))
    p_dup.tensions.append(Tension("dup", "menace", "x", "scene-1", [(0, 5)]))
    p_dup.secrets.append(Secret("dup", "y", "secret", [], {"declencheur": "x", "node_cible": "scene-1"}, "", [(0, 5)]))
    errs = validate_form.validate_form(p_dup)
    assert any("duplicate" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 6 -- semantic : parsing tensions depuis LLM --------------------------------
section("semantic : parsing tensions depuis sortie LLM")
from coderain.converter.semantic import _validate

# reuse dummy tables
class DummyTables:
    def convert_stats(self, raw): return dict(raw)

unit_fake = type("U", (), {"uid": "u-1"})()
obj = {"tensions": [{"id": "tension-test", "categorie": "menace", "description_md": "Une menace.", "node_id": "scene-1", "anchors": [[0, 5]]}]}
out = _validate(obj, unit_fake, DummyTables())
assert len(out["tensions"]) == 1
assert out["tensions"][0].categorie == "menace"
# mauvaise categorie => exception signalée
obj2 = {"tensions": [{"id": "t-bad", "categorie": "unknown", "description_md": "x", "node_id": "scene-1", "anchors": [[0, 5]]}]}
out2 = _validate(obj2, unit_fake, DummyTables())
assert any("tension" in e for e in out2["exceptions"]), out2["exceptions"]

print(f"\nOK pconv2_tension_test — {len(FAIT)} sections vertes")
