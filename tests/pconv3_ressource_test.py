"""P-CONV-3 : cartes + primitive Ressource générique (D-216 §2, D-217).
100% synthétique (D-109) : aucun matériau de module réel.
Couvre : Ressource (type carte, ancrage node_id/page, kebab, anchors),
émission et garde zéro-dangling, fichier poste uniquement, duplicate ids,
bout-en-bout VERT avec 19 ressources synthétiques simulant p99-117.
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

from coderain.config import corpus_dir
from coderain.converter import validate_form
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record, Ressource

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e", corpus_cible="5e",
                    structures=["S1", "S2"], hash_source="0" * 64,
                    date_conversion="2026-08-26T00:00:00+00:00",
                    version_convertisseur="test")


def node(nid="scene-1", body="Contenu de scene.", anchors=None):
    return Node(nid, "scene", nid.upper(), body, "scene", anchors=anchors or [(0, 10)])


# 1 -- Ressource : type carte, id kebab, ancrage node_id/page ----------------
section("ressource : type carte, id kebab, ancrage node_id/page")
r = Ressource("carte-tilepage-1", "carte", [(0, 10)], node_id="scene-1", page=100, fichier="resources/carte-tilepage-1.jpg")
assert r.type_ressource == "carte"
assert r.node_id == "scene-1"
assert r.page == 100
assert r.fichier == "resources/carte-tilepage-1.jpg"
# type invalide
try:
    Ressource("carte-bad", "image", [(0, 5)], node_id="scene-1")
    raise AssertionError("type invalide accepte")
except ValueError:
    pass
# id non kebab
try:
    Ressource("BadId", "carte", [(0, 5)], node_id="scene-1")
    raise AssertionError("id non kebab accepte")
except ValueError:
    pass
# node_id non kebab
try:
    Ressource("carte-bad", "carte", [(0, 5)], node_id="BadNode")
    raise AssertionError("node_id non kebab accepte")
except ValueError:
    pass
# sans ancrage
try:
    Ressource("carte-bad", "carte", [(0, 5)])
    raise AssertionError("sans ancrage accepte")
except ValueError:
    pass
try:
    Ressource("carte-bad", "carte", [], node_id="scene-1")
    raise AssertionError("sans ancre accepte")
except ValueError:
    pass
try:
    Ressource("carte-bad", "carte", [(0, 5)], node_id="scene-1", page=0)
    raise AssertionError("page 0 accepte")
except ValueError:
    pass
# page seule (cas couverture / hand-drawn) OK sans node_id
r2 = Ressource("carte-maps-booklet", "carte", [(0, 5)], page=99, fichier="resources/carte-maps-booklet.jpg")
assert r2.page == 99 and r2.node_id is None

# 2 -- ressources : émission et garde zéro-dangling ---------------------------
section("ressources : emission et garde zero-dangling")
tmp = Path(tempfile.mkdtemp(prefix="pconv3-ress-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1", "Scène 1.", [(0, 10)]))
    p.nodes.append(node("tilepage-1", "TILEPAGE 1", [(10, 20)]))
    p.ressources.append(Ressource("carte-tilepage-1", "carte", [(0, 5)], node_id="tilepage-1", page=100, fichier="resources/carte-tilepage-1.jpg"))
    p.ressources.append(Ressource("carte-maps-booklet", "carte", [(5, 10)], page=99, fichier="resources/carte-maps-booklet.jpg"))
    p.resources = p.ressources
    write_partition(p, tmp)
    assert (tmp / "resources" / "carte-tilepage-1.md").exists()
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["resources"]) == 2
    assert {r["type"] for r in idx["resources"]} == {"carte"}
    # garde zero-dangling : node_id inconnu
    p2 = Partition(manifest())
    p2.nodes.append(node("scene-1"))
    p2.ressources.append(Ressource("carte-bad", "carte", [(0, 5)], node_id="nowhere", fichier="x.jpg"))
    p2.resources = p2.ressources
    try:
        write_partition(p2, tmp)
        raise AssertionError("ressource vers node inconnu acceptee")
    except ValueError as e:
        assert "nowhere" in str(e), e
    # validate_form detecte dangling ressource
    p3 = Partition(manifest())
    p3.nodes.append(node("scene-1"))
    p3.ressources.append(Ressource("carte-dang", "carte", [(0, 5)], node_id="missing-node", fichier="x.jpg"))
    p3.resources = p3.ressources
    errs = validate_form.validate_form(p3, tmp)
    assert any("ressource" in e and "missing-node" in e for e in errs), errs
    # ressource sans ancre
    p4 = Partition(manifest())
    p4.nodes.append(node("scene-1"))
    # construction directe contourne garde : on injecte objet factice
    class FakeR:
        id = "carte-fake"
        type_ressource = "carte"
        node_id = "scene-1"
        page = None
        fichier = "resources/x.jpg"
        anchors = []
    p4.ressources.append(FakeR())  # type: ignore
    p4.resources = p4.ressources
    errs = validate_form.validate_form(p4, tmp)
    assert any("sans ancre" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 3 -- ressources : fichier poste uniquement (D-217) --------------------------
section("ressources : fichier poste uniquement (D-217)")
tmp = Path(tempfile.mkdtemp(prefix="pconv3-fich-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1"))
    p.ressources.append(Ressource("carte-t1", "carte", [(0, 5)], node_id="scene-1", fichier="resources/carte-t1.jpg"))
    p.ressources.append(Ressource("carte-t2", "carte", [(0, 5)], node_id="scene-1", fichier="resources/carte-t2.jpg"))
    p.resources = p.ressources
    write_partition(p, tmp)
    # chaque ressource md porte son fichier
    for fid in ("carte-t1", "carte-t2"):
        txt = (tmp / "resources" / f"{fid}.md").read_text(encoding="utf-8")
        assert "resources/carte-t" in txt, txt
        assert '"type": "carte"' in txt or '"type":' in txt
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    for r in idx["resources"]:
        assert r["fichier"].startswith("resources/"), r
        assert r["fichier"].endswith(".jpg")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 4 -- ressources : 19 cartes (composition inventaire-cartes.json) ------------
section("ressources : 19 cartes TILEPAGE/SUBMAP (inventaire)")
CARTES_19 = [
    ("carte-maps-booklet", None, 99),
    ("carte-tilepage-1", "tilepage-1", 100),
    ("carte-tilepage-2", "tilepage-2", 101),
    ("carte-tilepage-3", "tilepage-3", 102),
    ("carte-tilepage-4", "tilepage-4", 103),
    ("carte-tilepage-5", "tilepage-5", 104),
    ("carte-tilepage-6", "tilepage-6", 105),
    ("carte-tilepage-7", "tilepage-7", 106),
    ("carte-tilepage-8", "tilepage-8", 107),
    ("carte-tilepage-9", "tilepage-9", 108),
    ("carte-tilepage-10", "tilepage-10", 109),
    ("carte-tilepage-11", "tilepage-11", 110),
    ("carte-tilepage-12", "tilepage-12", 111),
    ("carte-submap-1", "submap-1", 112),
    ("carte-submap-2", "submap-2", 113),
    ("carte-submap-3", "submap-3", 114),
    ("carte-submap-4", "submap-4", 115),
    ("carte-submap-5", "submap-5", 116),
    ("carte-hand-drawn-map", None, 117),
]
tmp = Path(tempfile.mkdtemp(prefix="pconv3-19-"))
try:
    p = Partition(manifest())
    # créer les 17 nodes pointeurs
    for nid in [c[1] for c in CARTES_19 if c[1]]:
        p.nodes.append(node(nid, f"Contenu {nid}", [(0, 10)]))
    p.nodes.append(node("scene-1", "Scene commune", [(0, 10)]))
    for rid, nid, pg in CARTES_19:
        p.ressources.append(Ressource(rid, "carte", [(0, 5)], node_id=nid, page=pg, fichier=f"resources/{rid}.jpg"))
    p.resources = p.ressources
    write_partition(p, tmp)
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["resources"]) == 19, idx["resources"]
    # 17 rattachées à un node, 2 page-only
    avec_node = [r for r in idx["resources"] if r.get("node_id")]
    sans_node = [r for r in idx["resources"] if not r.get("node_id")]
    assert len(avec_node) == 17, f"avec_node {len(avec_node)}"
    assert len(sans_node) == 2, f"sans_node {len(sans_node)}"
    pages = sorted(r["page"] for r in idx["resources"])
    assert pages == list(range(99, 118)), pages
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 5 -- bout-en-bout : partition avec ressources VERT ---------------------------
section("bout-en-bout : partition avec ressources VERT")
tmp = Path(tempfile.mkdtemp(prefix="pconv3-boutenbout-"))
try:
    p = Partition(manifest())
    p.nodes.append(Node("scene-1", "scene", "SCENE 1", "La forêt s'étend.", "scene", anchors=[(0, 30)]))
    p.nodes.append(Node("tilepage-1", "scene", "TILEPAGE 1", "Find tilepage 1.", "scene", anchors=[(30, 60)]))
    p.nodes.append(Node("submap-1", "scene", "SUBMAP 1", "Find submap 1.", "scene", anchors=[(60, 90)]))
    p.nodes[-1].liens.append({"cible_id": "scene-1", "condition_textuelle": "retour"})
    # aventure minimale
    from coderain.converter.schemas import Aventure
    p.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quete acceptee", "declencheur": {"type": "etat", "valeur": "quete acceptee"}, "perturbations": [{"condition_etat": "abandon", "issue": "abandonnee", "porteur_cible_id": "scene-1"}], "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    # ressources
    p.ressources.append(Ressource("carte-tilepage-1", "carte", [(30, 40)], node_id="tilepage-1", page=100, fichier="resources/carte-tilepage-1.jpg"))
    p.ressources.append(Ressource("carte-submap-1", "carte", [(60, 70)], node_id="submap-1", page=112, fichier="resources/carte-submap-1.jpg"))
    p.ressources.append(Ressource("carte-maps-booklet", "carte", [(0, 10)], page=99, fichier="resources/carte-maps-booklet.jpg"))
    p.resources = p.ressources
    write_partition(p, tmp)
    (tmp / "directeur.md").write_text("# Brief\nContenu sans secret.\n", encoding="utf-8")
    errs = validate_form.validate_form(p, tmp)
    assert errs == [], f"partition VERT attendue mais {errs}"
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["resources"]) == 3
    assert len(idx["nodes"]) == 3
    # duplicate id detection inclut ressources
    p_dup = Partition(manifest())
    p_dup.nodes.append(node("scene-1"))
    p_dup.ressources.append(Ressource("dup", "carte", [(0, 5)], node_id="scene-1", fichier="resources/dup.jpg"))
    p_dup.resources = p_dup.ressources
    p_dup.secrets.append(__import__("coderain.converter.schemas", fromlist=["Secret"]).Secret("dup", "y", "secret", [], {"declencheur": "x", "node_cible": "scene-1"}, "", [(0, 5)]))
    errs = validate_form.validate_form(p_dup)
    assert any("duplicate" in e for e in errs), errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 6 -- partition réelle poste : 19 ressources et VERT -------------------------
section("partition reelle poste : pconv3 VERT, 19 ressources, index")
import json as _js
part_dir = corpus_dir() / "death-knights-squire" / "partition-pconv3"
if part_dir.exists():
    idx = _js.loads((part_dir / "index.json").read_text(encoding="utf-8"))
    assert len(idx.get("resources", [])) == 19, f"resources {len(idx.get('resources', []))} != 19"
    pages = sorted(r["page"] for r in idx["resources"])
    assert pages == list(range(99, 118)), f"pages {pages}"
    # validate_form sur partition réelle
    from coderain.converter.schemas import Manifest, Partition, Node, Record, RollTable, Secret, Tension, Ressource, Aventure
    import hashlib
    from datetime import datetime, timezone
    texte = (corpus_dir() / "death-knights-squire" / "extraction" / "source-pconv0-p10-98.txt").read_text(encoding="utf-8")
    manifest_obj = Manifest(titre="Death Knight's Squire", corpus_source="5e", corpus_cible="5e",
                        structures=["S1", "S2"], hash_source=hashlib.sha256(texte.encode("utf-8")).hexdigest(),
                        date_conversion=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        version_convertisseur="0.4.0+gamebook-local")
    part = Partition(manifest_obj)
    for f in (part_dir / "nodes").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        import re, json as js
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = js.loads(m.group(1))
        body = m.group(2).strip()
        part.nodes.append(Node(nid=fm["id"], type_=fm["type"], titre=fm.get("titre",""), corps_md=body, altitude=fm["altitude"], liens=fm.get("liens",[]), anchors=fm["anchors"], charniere_sortie=fm.get("charniere_sortie"), objectif_md=fm.get("objectif_md",""), debouches=fm.get("debouches"), heritage=fm.get("heritage")))
    for f in (part_dir / "records").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        import re, json as js
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = js.loads(m.group(1))
        body = js.loads(m.group(2).strip()) if m.group(2).strip().startswith("{") else {}
        part.records.append(Record(rid=fm["id"], classe=fm["classe"], nom=fm["nom"], stats_5e=body, anchors=fm["anchors"], tags=fm.get("tags"), transverse=fm.get("transverse"), fonctions_aval=fm.get("fonctions_aval")))
    for f in (part_dir / "resources").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        import re, json as js
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = js.loads(m.group(1))
        body = m.group(2).strip()
        part.ressources.append(Ressource(rid=fm["id"], type_ressource=fm["type"], anchors=fm["anchors"], node_id=fm.get("node_id"), page=fm.get("page"), fichier=fm.get("fichier"), description_md=body))
    part.resources = part.ressources
    # charger aventure minimal pour validation non-bloquante
    av_text = (part_dir / "aventure.md").read_text(encoding="utf-8") if (part_dir / "aventure.md").exists() else ""
    m = re.search(r"---\n(.*?)\n---", av_text, re.S)
    if m:
        fm = js.loads(m.group(1))
        part.aventure = Aventure(fm.get("trajectoire",[]), fm.get("conditions",[]), fm.get("charniere_md","") if "charniere_md" in fm else av_text.split("## Charnière de sortie")[-1].strip() if "## Charnière" in av_text else "")
    else:
        part.aventure = Aventure([], [], "")
    errs = validate_form.validate_form(part, part_dir)
    assert errs == [], f"partition-pconv3 VERT attendue mais {errs}"
    # fichiers JPEG présents (poste uniquement)
    res_dir = corpus_dir() / "death-knights-squire" / "resources"
    assert res_dir.exists()
    jpgs = list(res_dir.glob("*.jpg"))
    assert len(jpgs) == 19, f"resources JPEG {len(jpgs)} != 19"
    total = sum(p.stat().st_size for p in jpgs)
    assert total > 1_000_000, f"total JPEG trop petit {total}"
else:
    print("SKIP partition reelle : dossier absent (CI)")

print(f"\nOK pconv3_ressource_test — {len(FAIT)} sections vertes")
