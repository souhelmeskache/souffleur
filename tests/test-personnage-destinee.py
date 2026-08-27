"""I-341/D-219/D-220 : Personnage + Destinée (séquence canonique).
100% synthétique (D-109) : aucun matériau de module réel.
Couvre : Personnage (id kebab, nom, acquis_conversation, destinee jalons flous),
rattachement vers node/tension/ressource, garde zéro-dangling,
D-129/D-135 (passé/intention seuls, jamais futur/événement),
émission personnages/ + index, validate_form, bout-en-bout VERT.
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
from coderain.converter.schemas import (Manifest, Node, Partition, Personnage,
                                         Ressource, Tension)

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


# 1 -- Personnage : création vide (2 jalons flous sans rattachement) --------
section("personnage : creation vide, 2 jalons flous sans rattachement")
p = Personnage("vahn", "Vahn",
               destinee=[{"id": "jalon-1", "intention_md": "Ancien soldat ayant survécu à une guerre oubliée."},
                         {"id": "jalon-2", "intention_md": "Porteur d'une dette envers un mort."}])
assert p.id == "vahn"
assert p.nom == "Vahn"
assert p.acquis_conversation == []
assert len(p.destinee) == 2
assert p.destinee[0]["rattachement"] is None
assert p.destinee[1]["rattachement"] is None
# moins de 2 jalons => rejet
try:
    Personnage("bad", "Bad", destinee=[{"id": "j1", "intention_md": "Seul."}])
    raise AssertionError("1 seul jalon accepte")
except ValueError:
    pass
# nom vide => rejet
try:
    Personnage("bad2", "", destinee=[{"id": "j1", "intention_md": "A."},
                                      {"id": "j2", "intention_md": "B."}])
    raise AssertionError("nom vide accepte")
except ValueError:
    pass
# id non kebab => rejet
try:
    Personnage("BadId", "X", destinee=[{"id": "j1", "intention_md": "A."},
                                        {"id": "j2", "intention_md": "B."}])
    raise AssertionError("id non kebab accepte")
except ValueError:
    pass
# intention_md vide => rejet
try:
    Personnage("bad3", "X", destinee=[{"id": "j1", "intention_md": ""},
                                       {"id": "j2", "intention_md": "B."}])
    raise AssertionError("intention vide accepte")
except ValueError:
    pass

# 2 -- Rattachement valide vers node/tension/ressource -----------------------
section("personnage : rattachement valide vers node/tension/ressource")
tmp = Path(tempfile.mkdtemp(prefix="i341-ratt-"))
try:
    part = Partition(manifest())
    part.nodes.append(node("scene-1", "La forêt s'étend.", [(0, 10)]))
    part.nodes.append(node("scene-2", "Le château en ruine.", [(10, 20)]))
    part.nodes[-1].liens.append({"cible_id": "scene-1", "condition_textuelle": "retour"})
    part.tensions.append(Tension("tension-menace-1", "menace", "Une menace rode",
                                 "scene-1", [(0, 5)]))
    part.ressources.append(Ressource("carte-1", "carte", [(0, 5)],
                                     node_id="scene-1", page=100,
                                     fichier="resources/carte-1.jpg"))
    part.resources = part.ressources
    from coderain.converter.schemas import Aventure
    part.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête acceptée",
          "declencheur": {"type": "etat", "valeur": "quete acceptee"},
          "perturbations": [{"condition_etat": "abandon", "issue": "abandonnee",
                             "porteur_cible_id": "scene-1"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    part.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-origine", "intention_md": "Ancien soldat de la guerre d'Weathercote.",
             "rattachement": "scene-1"},
            {"id": "jalon-dette", "intention_md": "Porteur du pieu de l'arbre rouge.",
             "rattachement": "tension-menace-1"},
            {"id": "jalon-carte", "intention_md": "Gardien de la carte tilepage.",
             "rattachement": "carte-1"},
        ]))
    write_partition(part, tmp)
    assert (tmp / "personnages" / "vahn.md").exists()
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["personnages"]) == 1
    assert idx["personnages"][0]["id"] == "vahn"
    assert idx["personnages"][0]["nb_jalons"] == 3
    # le fichier front matter porte la destinée
    txt = (tmp / "personnages" / "vahn.md").read_text(encoding="utf-8")
    assert "jalon-origine" in txt
    assert "scene-1" in txt
    # validate_form vert
    (tmp / "directeur.md").write_text("# Brief\nSans secret.\n", encoding="utf-8")
    errs = validate_form.validate_form(part, tmp)
    assert errs == [], f"attendu VERT mais {errs}"
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 3 -- Dangling rattachement => ValueError nommé -----------------------------
section("personnage : dangling rattachement => ValueError nomme")
tmp = Path(tempfile.mkdtemp(prefix="i341-dang-"))
try:
    part = Partition(manifest())
    part.nodes.append(node("scene-1"))
    part.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-1", "intention_md": "Origine lointaine.",
             "rattachement": "node-inexistant"},
            {"id": "jalon-2", "intention_md": "Dette non tenue."},
        ]))
    try:
        write_partition(part, tmp)
        raise AssertionError("dangling rattachement accepte a l'emission")
    except ValueError as e:
        assert "node-inexistant" in str(e), e
        assert "vahn" in str(e), e
    # validate_form detecte aussi le dangling (sans passer par emit)
    errs = validate_form.validate_form(part)
    assert any("rattachement" in e and "node-inexistant" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 4 -- Jalons au futur/événement => rejet D-129 ------------------------------
section("personnage : jalons au futur/evenement => rejet D-129")
for marqueur in ("fera", "quand il", "va", "deviendra", "il arrivera"):
    try:
        Personnage("bad", "Bad",
                   destinee=[{"id": "j1", "intention_md": f"Un jour il {marqueur} grand."},
                             {"id": "j2", "intention_md": "Passé simple."}])
        raise AssertionError(f"marqueur futur {marqueur!r} accepte")
    except ValueError as e:
        assert "D-129" in str(e) or marqueur in str(e), e
# passé/intention OK
p_ok = Personnage("ok", "Ok",
                  destinee=[{"id": "j1", "intention_md": "Ancien soldat."},
                            {"id": "j2", "intention_md": "Veut retrouver la paix."}])
assert len(p_ok.destinee) == 2

# 5 -- Bout-en-bout : partition avec personnage synthétique VERT -------------
section("bout-en-bout : partition avec personnage synthetique VERT")
tmp = Path(tempfile.mkdtemp(prefix="i341-boutenbout-"))
try:
    part = Partition(manifest())
    part.nodes.append(Node("scene-1", "scene", "SCENE 1", "La forêt de Weathercote.",
                           "scene", anchors=[(0, 30)]))
    part.nodes.append(Node("scene-2", "scene", "SCENE 2", "Le château en ruine.",
                           "scene", anchors=[(30, 60)]))
    part.nodes[-1].liens.append({"cible_id": "scene-1", "condition_textuelle": "retour"})
    part.tensions.append(Tension("tension-menace", "menace", "Menace du chevalier",
                                 "scene-1", [(0, 10)]))
    part.tensions.append(Tension("tension-choix", "choix", "Dire ou mentir",
                                 "scene-2", [(30, 40)]))
    from coderain.converter.schemas import Aventure
    part.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête acceptée",
          "declencheur": {"type": "etat", "valeur": "quete acceptee"},
          "perturbations": [{"condition_etat": "abandon", "issue": "abandonnee",
                             "porteur_cible_id": "scene-1"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    part.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-origine", "intention_md": "Ancien soldat de la guerre d'Weathercote.",
             "rattachement": "scene-1"},
            {"id": "jalon-dette", "intention_md": "Porteur d'une dette envers un mort.",
             "rattachement": "tension-menace"},
        ]))
    write_partition(part, tmp)
    (tmp / "directeur.md").write_text("# Brief\nSans secret.\n", encoding="utf-8")
    errs = validate_form.validate_form(part, tmp)
    assert errs == [], f"partition VERT attendue mais {errs}"
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["personnages"]) == 1
    assert idx["personnages"][0]["nom"] == "Vahn"
    # duplicate id detection inclut personnages
    part_dup = Partition(manifest())
    part_dup.nodes.append(node("scene-1"))
    part_dup.personnages.append(Personnage("dup", "Dup",
        destinee=[{"id": "j1", "intention_md": "A."}, {"id": "j2", "intention_md": "B."}]))
    from coderain.converter.schemas import Secret
    part_dup.secrets.append(Secret("dup", "y", "secret", [],
                                    {"declencheur": "x", "node_cible": "scene-1"}, "", [(0, 5)]))
    errs = validate_form.validate_form(part_dup)
    assert any("duplicate" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 6 -- Partition réelle poste : personnage synthétique Vahn ------------------
section("partition reelle poste : Vahn synthetique dans partition-pconv3")
part_dir = Path(r"C:\Users\souhe\coderain\corpus-modules\death-knights-squire\partition-pconv3")
if part_dir.exists():
    import re
    idx = json.loads((part_dir / "index.json").read_text(encoding="utf-8"))
    # à ce stade 0 personnages — la partition-pconv3 n'en porte pas encore
    assert len(idx.get("personnages", [])) == 0, f"personnages {len(idx.get('personnages', []))} != 0"
    # construction d'un personnage synthétique Vahn rattaché aux tensions existantes
    from coderain.converter.schemas import Manifest as Mf, Partition as Pt, Personnage as Pp, Record as Rec
    import hashlib
    from datetime import datetime, timezone
    texte = Path(r"C:\Users\souhe\coderain\corpus-modules\death-knights-squire\extraction\source-pconv0-p10-98.txt").read_text(encoding="utf-8")
    manifest_obj = Mf(titre="Death Knight's Squire", corpus_source="5e", corpus_cible="5e",
                      structures=["S1", "S2"], hash_source=hashlib.sha256(texte.encode("utf-8")).hexdigest(),
                      date_conversion=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      version_convertisseur="0.4.0+gamebook-local")
    part_test = Pt(manifest_obj)
    # recharger nodes et tensions depuis la partition existante
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
    # charger aventure depuis la partition existante
    from coderain.converter.schemas import Aventure as Av
    av_text = (part_dir / "aventure.md").read_text(encoding="utf-8") if (part_dir / "aventure.md").exists() else ""
    m_av = re.search(r"---\n(.*?)\n---", av_text, re.S)
    if m_av:
        fm_av = json.loads(m_av.group(1))
        part_test.aventure = Av(fm_av.get("trajectoire", []), fm_av.get("conditions", []),
                                fm_av.get("charniere_md", "") if "charniere_md" in fm_av else
                                av_text.split("## Charnière de sortie")[-1].strip() if "## Charnière" in av_text else "")
    else:
        part_test.aventure = Av([], [], "")
    # charger records pour les porteur_cible_id des evenements
    for f in (part_dir / "records").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        body = json.loads(m.group(2).strip()) if m.group(2).strip().startswith("{") else {}
        part_test.records.append(Rec(rid=fm["id"], classe=fm["classe"], nom=fm["nom"],
                                      stats_5e=body, anchors=fm["anchors"], tags=fm.get("tags"),
                                      transverse=fm.get("transverse"), fonctions_aval=fm.get("fonctions_aval")))
    # ajouter Vahn avec 2 jalons flous rattachés à des ids existants
    tension_ids = [t.id for t in part_test.tensions]
    node_ids_list = [n.id for n in part_test.nodes]
    assert len(tension_ids) >= 1, f"tensions {len(tension_ids)} < 1"
    assert len(node_ids_list) >= 1, f"nodes {len(node_ids_list)} < 1"
    part_test.personnages.append(Pp(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-origine", "intention_md": "Ancien soldat ayant survécu à la guerre d'Weathercote.",
             "rattachement": tension_ids[0]},
            {"id": "jalon-dette", "intention_md": "Porteur d'une dette envers un mort.",
             "rattachement": node_ids_list[0]},
        ]))
    # émission dans un tmp pour vérifier VERT
    tmp = Path(tempfile.mkdtemp(prefix="i341-reel-"))
    try:
        write_partition(part_test, tmp)
        assert (tmp / "personnages" / "vahn.md").exists()
        idx2 = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
        assert len(idx2["personnages"]) == 1
        assert idx2["personnages"][0]["nom"] == "Vahn"
        assert idx2["personnages"][0]["nb_jalons"] == 2
        errs = validate_form.validate_form(part_test)
        assert errs == [], f"Vahn VERT attendu mais {errs}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
else:
    print("SKIP partition reelle : dossier absent (CI)")

print(f"\nOK test-personnage-destinee — {len(FAIT)} sections vertes")
