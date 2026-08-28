"""I-033 borne à deux murs — fenêtres conversation d'accord (D-219 §4).
100% synthétique (D-109) sauf section 7 (partition-pconv3 réelle).

I-370a : la tension liée est obligatoire SEULEMENT pour F3 (dimension
lien_tension) — F1/F2/F4 la portent en option, conformément à D-219 §4.
La garde suit la spec, pas l'inverse.

8 sections + validate_form :
  1. F1 origine → vert (fenêtre valide SANS tension, rattachement existant)
  2. F2 posture → vert (fenêtre valide SANS tension — cas réel, ex-contournement I-370a)
  3. F3 lien_tension → vert (tension liée, requise)
  4. F4 enjeu → vert (tension optionnelle, ici présente)
  5. Spoiler refusé — fenêtre négociable cite un secret → erreur
  6. Dangling refusé — rattachement inexistant → erreur
  7. F3 sans tension → refusé (borne à deux murs (a), I-370a)
  8. partition-pconv3 intégrée — 4 fenêtres vertes + validate_form vert
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
from coderain.converter.schemas import (Manifest, Node, Partition, Tension,
                                         Secret, Fenetre, Aventure, Ressource)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e", corpus_cible="5e",
                    structures=["S1", "S2"], hash_source="0" * 64,
                    date_conversion="2026-08-27T00:00:00+00:00",
                    version_convertisseur="test")


def node(nid="scene-1", body="Contenu de scene.", anchors=None):
    return Node(nid, "scene", nid.upper(), body, "scene", anchors=anchors or [(0, 10)])


def partition_base():
    """Partition minimale avec nodes, tensions, secret, ressource pour tester les fenêtres."""
    p = Partition(manifest())
    p.nodes.append(node("scene-origine", "La forêt s'étend.", [(0, 10)]))
    p.nodes.append(node("scene-chateau", "Le château en ruine.", [(10, 20)]))
    p.nodes[-1].liens.append({"cible_id": "scene-origine", "condition_textuelle": "retour"})
    p.tensions.append(Tension("tension-menace-1", "menace", "Une menace rode",
                              "scene-origine", [(0, 5)]))
    p.tensions.append(Tension("tension-choix-1", "choix", "Dire ou mentir",
                              "scene-chateau", [(10, 15)]))
    p.tensions.append(Tension("tension-cout-1", "cout", "Un prix à payer",
                              "scene-chateau", [(12, 18)]))
    p.secrets.append(Secret("secret-dette", "Le mort doit être vengé", "secret",
                            ["scene-origine"],
                            {"declencheur": "jalon-dette", "node_cible": "scene-chateau"},
                            "Révélation brise le lien", [(5, 10)]))
    p.ressources.append(Ressource("carte-redtree", "carte", [(0, 5)],
                                  node_id="scene-origine", page=100,
                                  fichier="resources/carte-redtree.jpg"))
    p.resources = p.ressources
    p.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête acceptée",
          "declencheur": {"type": "etat", "valeur": "quete acceptee"},
          "perturbations": [{"condition_etat": "abandon", "issue": "abandonnee",
                             "porteur_cible_id": "scene-origine"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    return p


# 1 -- F1 origine → vert ---------------------------------------------------
section("F1 origine : fenetre valide SANS tension, rattachement existant")
tmp = Path(tempfile.mkdtemp(prefix="i033-f1-"))
try:
    part = partition_base()
    part.fenetres.append(Fenetre(
        "f1-origine", "origine", "Ancien soldat",
        "Vous avez survécu à la guerre d'Weathercote.",
        ["Soldat vétéran", "Recrue inexpérimentée", "Déserteur repentis"],
        negociable=True,
        rattachement="scene-origine"))
    write_partition(part, tmp)
    assert (tmp / "fenetres" / "f1-origine.md").exists()
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["fenetres"]) == 1
    assert idx["fenetres"][0]["dimension"] == "origine"
    assert "tension_id" not in idx["fenetres"][0]
    (tmp / "directeur.md").write_text("# Brief\nSans secret.\n", encoding="utf-8")
    errs = validate_form.validate_form(part, tmp)
    assert errs == [], f"F1 VERT attendu mais {errs}"
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 2 -- F2 posture → vert ---------------------------------------------------
section("F2 posture : fenetre valide SANS tension — cas réel (I-370a)")
tmp = Path(tempfile.mkdtemp(prefix="i033-f2-"))
try:
    part = partition_base()
    part.fenetres.append(Fenetre(
        "f2-posture", "posture", "Posture sociale",
        "Votre position dans la hiérarchie sociale.",
        ["Noble discret", "Roturier ambitieux"],
        negociable=True,
        rattachement="scene-chateau"))
    write_partition(part, tmp)
    assert (tmp / "fenetres" / "f2-posture.md").exists()
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert idx["fenetres"][0]["dimension"] == "posture"
    assert "tension_id" not in idx["fenetres"][0]
    errs = validate_form.validate_form(part)
    assert errs == [], f"F2 VERT attendu mais {errs}"
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 3 -- F3 lien_tension → vert ----------------------------------------------
section("F3 lien_tension : fenetre valide avec tension menace")
tmp = Path(tempfile.mkdtemp(prefix="i033-f3-"))
try:
    part = partition_base()
    part.fenetres.append(Fenetre(
        "f3-lien", "lien_tension", "Lien à la dette",
        "Vous portez une dette envers un mort.",
        ["Vengeur silencieux", "Gardien du souvenir"],
        negociable=False,
        non_negociable_msg="La dette existe, le mort est réel.",
        tension_id="tension-menace-1",
        rattachement="tension-menace-1"))
    write_partition(part, tmp)
    assert (tmp / "fenetres" / "f3-lien.md").exists()
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert idx["fenetres"][0]["dimension"] == "lien_tension"
    assert idx["fenetres"][0]["negociable"] is False
    errs = validate_form.validate_form(part)
    assert errs == [], f"F3 VERT attendu mais {errs}"
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 4 -- F4 enjeu → vert -----------------------------------------------------
section("F4 enjeu : fenetre valide avec tension cout et ressource")
tmp = Path(tempfile.mkdtemp(prefix="i033-f4-"))
try:
    part = partition_base()
    part.fenetres.append(Fenetre(
        "f4-enjeu", "enjeu", "Gardien du pieu",
        "Vous êtes le gardien du pieu de l'arbre rouge.",
        ["Gardien par serment", "Gardien par héritage"],
        negociable=True,
        tension_id="tension-cout-1",
        rattachement="carte-redtree"))
    write_partition(part, tmp)
    assert (tmp / "fenetres" / "f4-enjeu.md").exists()
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert idx["fenetres"][0]["dimension"] == "enjeu"
    assert idx["fenetres"][0]["rattachement"] == "carte-redtree"
    errs = validate_form.validate_form(part)
    assert errs == [], f"F4 VERT attendu mais {errs}"
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 5 -- Spoiler refusé : fenêtre négociable cite un secret ------------------
section("spoiler refuse : fenetre negociable cite un secret")
part = partition_base()
part.fenetres.append(Fenetre(
    "f1-spoiler", "origine", "Origine maudite",
    "Vous connaissez le secret-dette qui hante ces lieux.",
    ["Option A", "Option B"],
    negociable=True,
    tension_id="tension-menace-1",
    rattachement="scene-origine"))
errs = validate_form.validate_form(part)
assert any("secret-dette" in e and "spoiler" in e for e in errs), \
    f"attendu erreur spoiler dans {errs}"
# emit refuse aussi
tmp = Path(tempfile.mkdtemp(prefix="i033-spoiler-"))
try:
    try:
        write_partition(part, tmp)
        raise AssertionError("emit a accepte une fenetre qui cite un secret")
    except ValueError as e:
        assert "secret-dette" in str(e), e
        assert "spoiler" in str(e), e
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 6 -- Dangling refusé : rattachement inexistant ---------------------------
section("dangling refuse : rattachement vers id inexistant")
part = partition_base()
part.fenetres.append(Fenetre(
    "f1-dangling", "origine", "Origine perdue",
    "Votre origine se trouve dans un lieu oublié.",
    ["Option A"],
    negociable=True,
    tension_id="tension-menace-1",
    rattachement="node-inexistant-xyz"))
errs = validate_form.validate_form(part)
assert any("node-inexistant-xyz" in e and "dangling" in e for e in errs), \
    f"attendu erreur dangling dans {errs}"
# emit refuse aussi
tmp = Path(tempfile.mkdtemp(prefix="i033-dangling-"))
try:
    try:
        write_partition(part, tmp)
        raise AssertionError("emit a accepte une fenetre avec rattachement dangling")
    except ValueError as e:
        assert "node-inexistant-xyz" in str(e), e
        assert "dangling" in str(e), e
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 7 -- F3 sans tension → refusé ---------------------------------------------
section("F3 sans tension refuse : borne a deux murs (a) exige tension pour lien_tension")
part = partition_base()
part.fenetres.append(Fenetre(
    "f3-sans-tension", "lien_tension", "Lien à la dette",
    "Vous portez une dette envers un mort.",
    ["Vengeur silencieux", "Gardien du souvenir"],
    negociable=False,
    non_negociable_msg="La dette existe, le mort est réel.",
    rattachement="scene-origine"))
errs = validate_form.validate_form(part)
assert any("f3-sans-tension" in e and "tension_id" in e for e in errs), \
    f"attendu erreur tension_id manquant pour F3 dans {errs}"

# 8 -- partition-pconv3 intégrée : 4 fenêtres vertes + validate_form -------
section("partition-pconv3 integree : 4 fenetres vertes + validate_form vert")
part_dir = corpus_dir() / "death-knights-squire" / "partition-pconv3"
if part_dir.exists():
    import hashlib
    from datetime import datetime, timezone
    idx_pconv3 = json.loads((part_dir / "index.json").read_text(encoding="utf-8"))
    # construire une partition minimale depuis partition-pconv3
    texte = (corpus_dir() / "death-knights-squire" / "extraction" / "source-pconv0-p10-98.txt").read_text(encoding="utf-8")
    manifest_obj = Manifest(titre="Death Knight's Squire", corpus_source="5e", corpus_cible="5e",
                            structures=["S1", "S2"], hash_source=hashlib.sha256(texte.encode("utf-8")).hexdigest(),
                            date_conversion=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            version_convertisseur="0.4.0+gamebook-local")
    part_test = Partition(manifest_obj)
    # recharger nodes
    for f in (part_dir / "nodes").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        body = m.group(2).strip()
        part_test.nodes.append(Node(nid=fm["id"], type_=fm["type"], titre=fm.get("titre",""),
                                     corps_md=body, altitude=fm["altitude"], liens=fm.get("liens",[]),
                                     anchors=fm["anchors"], charniere_sortie=fm.get("charniere_sortie"),
                                     objectif_md=fm.get("objectif_md",""), debouches=fm.get("debouches"),
                                     heritage=fm.get("heritage")))
    # recharger tensions
    for f in (part_dir / "tensions").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        body = m.group(2).strip()
        part_test.tensions.append(Tension(tid=fm["id"], categorie=fm["categorie"],
                                           description_md=body, node_id=fm["node_id"],
                                           anchors=fm["anchors"]))
    # recharger records
    from coderain.converter.schemas import Record
    for f in (part_dir / "records").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        body = json.loads(m.group(2).strip()) if m.group(2).strip().startswith("{") else {}
        part_test.records.append(Record(rid=fm["id"], classe=fm["classe"], nom=fm["nom"],
                                         stats_5e=body, anchors=fm["anchors"], tags=fm.get("tags"),
                                         transverse=fm.get("transverse"), fonctions_aval=fm.get("fonctions_aval")))
    # recharger ressources
    for f in (part_dir / "resources").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        part_test.ressources.append(Ressource(rid=fm["id"], type_ressource=fm["type"],
                                               anchors=fm.get("anchors", [(0,0)]),
                                               node_id=fm.get("node_id"),
                                               page=fm.get("page"),
                                               fichier=fm.get("fichier")))
    part_test.resources = part_test.ressources
    # recharger aventure
    av_text = (part_dir / "aventure.md").read_text(encoding="utf-8") if (part_dir / "aventure.md").exists() else ""
    m_av = re.search(r"---\n(.*?)\n---", av_text, re.S)
    if m_av:
        fm_av = json.loads(m_av.group(1))
        part_test.aventure = Aventure(fm_av.get("trajectoire", []), fm_av.get("conditions", []),
                                       av_text.split("## Charnière de sortie")[-1].strip() if "## Charnière" in av_text else "")
    else:
        part_test.aventure = Aventure([], [], "")
    # ajouter 4 fenêtres canoniques rattachées aux ids existants
    tension_ids = [t.id for t in part_test.tensions]
    node_ids_list = [n.id for n in part_test.nodes]
    ressource_ids = [r.id for r in part_test.ressources]
    assert len(tension_ids) >= 4, f"tensions {len(tension_ids)} < 4"
    assert len(node_ids_list) >= 1, f"nodes {len(node_ids_list)} < 1"
    # F1 origine — sans tension (D-219 §4 : tension optionnelle hors F3)
    part_test.fenetres.append(Fenetre("f1-origine", "origine", "Ancien soldat",
                                       "Vous avez survécu à la guerre.",
                                       ["Vétéran", "Recrue"],
                                       negociable=True,
                                       rattachement=node_ids_list[0]))
    # F2 posture — sans tension, cas réel (I-370a, ex-contournement)
    part_test.fenetres.append(Fenetre("f2-posture", "posture", "Position sociale",
                                       "Votre place dans la hiérarchie.",
                                       ["Noble", "Roturier"],
                                       negociable=True,
                                       rattachement=node_ids_list[0]))
    # F3 lien_tension
    part_test.fenetres.append(Fenetre("f3-lien", "lien_tension", "Lien à la menace",
                                       "Vous portez une marque.",
                                       ["Gardien", "Héritier"],
                                       negociable=False,
                                       non_negociable_msg="La marque est réelle.",
                                       tension_id=tension_ids[0],
                                       rattachement=tension_ids[0]))
    # F4 enjeu
    ratt_f4 = ressource_ids[0] if ressource_ids else tension_ids[2]
    part_test.fenetres.append(Fenetre("f4-enjeu", "enjeu", "Gardien du pieu",
                                       "Vous gardez un objet sacré.",
                                       ["Par serment", "Par héritage"],
                                       negociable=True,
                                       tension_id=tension_ids[2],
                                       rattachement=ratt_f4))
    # emission + validate_form
    tmp = Path(tempfile.mkdtemp(prefix="i033-pconv3-"))
    try:
        write_partition(part_test, tmp)
        assert (tmp / "fenetres").exists()
        idx2 = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
        assert len(idx2["fenetres"]) == 4, f"fenetres {len(idx2['fenetres'])} != 4"
        dims = {f["dimension"] for f in idx2["fenetres"]}
        assert dims == {"origine", "posture", "lien_tension", "enjeu"}, f"dims {dims}"
        errs = validate_form.validate_form(part_test)
        assert errs == [], f"partition-pconv3 4 fenetres VERT attendu mais {errs}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
else:
    print("SKIP partition-pconv3 : dossier absent (CI)")

print(f"\nOK test-borne-deux-murs-i033 — {len(FAIT)}/8 sections vertes")
assert len(FAIT) >= 7, f"attendu au moins 7 sections, got {len(FAIT)}"
