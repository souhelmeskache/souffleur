"""P-VAL validation bout-en-bout : preuve que l'enchaînement tient.
100% synthétique (D-109) sauf cas (b) qui charge partition-pconv3 réelle.
4 cas :
  (a) partition-pval minimale (1 node + 1 record + 1 tension + 1 ressource
      + 1 personnage rattaché) VERT
  (b) partition-pconv3 réelle + Vahn synthétique VERT
  (c) dangling croisé (personnage → tension inexistante) ⇒ ValueError nommé
  (d) load_partition (mcp_server module_index) expose personnages (lecture pure)
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

from coderain.converter import validate_form, validate_fidelity
from coderain.converter.aval import load_partition
from coderain.converter.emit import write_partition
from coderain.converter.schemas import (Aventure, Manifest, Node, Partition,
                                         Personnage, Record, Ressource,
                                         RollTable, Secret, Tension)

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
    return Node(nid, "scene", nid.upper(), body, "scene",
                anchors=anchors or [(0, 10)])


# (a) partition-pval minimale : 1 node + 1 record + 1 tension + 1 ressource
#     + 1 personnage rattaché, validate_form 10 sections VERT ---------------
section("(a) partition-pval minimale : toutes primitives, validate_form VERT")
tmp_a = Path(tempfile.mkdtemp(prefix="pval-min-"))
try:
    part = Partition(manifest())
    n1 = Node("scene-origine", "scene", "SCENE-ORIGINE",
              "La forêt d'Weathercote. Un Goblin Warrior patrouille.",
              "scene", anchors=[(0, 50)],
              charniere_sortie={"ouvre_vers_md": "La suite est ouverte.",
                                "prerequis_etat": "quete acceptee"})
    part.nodes.append(n1)
    part.records.append(Record(
        "goblin-warrior", "creature", "Goblin Warrior",
        {"nom": "Goblin Warrior", "ca": 15, "pv": 7,
         "vitesse": "30 ft", "attaque_bonus": "+4", "degats": "1d6+2",
         "ancre_srd": "goblin-warrior"},
        [(0, 20)]))
    part.tables.append(RollTable(
        "table-rencontre", "1d6",
        [{"plage_debut": 1, "plage_fin": 3,
          "resultat_md": "Goblin Warrior"},
         {"plage_debut": 4, "plage_fin": 6,
          "resultat_md": "Kobolds"}],
        [(0, 10)]))
    part.secrets.append(Secret(
        "secret-pieux", "Le pieu de l'arbre rouge est la clé.",
        "secret", ["scene-origine"],
        {"declencheur": "inspection", "node_cible": "scene-origine"},
        "Révéler brise l'immersion", [(0, 15)]))
    part.tensions.append(Tension(
        "tension-menace", "menace",
        "Le chevalier noir traque les héros.",
        "scene-origine", [(0, 20)]))
    part.ressources.append(Ressource(
        "carte-1", "carte", [(0, 10)],
        node_id="scene-origine", page=100,
        fichier="resources/carte-1.jpg",
        description_md="Carte de la forêt"))
    part.resources = part.ressources
    part.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête acceptée",
          "declencheur": {"type": "etat", "valeur": "quete acceptee"},
          "perturbations": [{"condition_etat": "abandon",
                             "issue": "abandonnee",
                             "porteur_cible_id": "scene-origine"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    part.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-origine",
             "intention_md": "Ancien soldat de la guerre d'Weathercote.",
             "rattachement": "scene-origine"},
            {"id": "jalon-dette",
             "intention_md": "Porteur d'une dette envers un mort.",
             "rattachement": "tension-menace"},
        ]))
    write_partition(part, tmp_a)
    (tmp_a / "directeur.md").write_text("# Brief\nSans secret.\n",
                                        encoding="utf-8")
    errs = validate_form.validate_form(part, tmp_a)
    assert errs == [], f"(a) attendu VERT mais {errs}"
    idx = json.loads((tmp_a / "index.json").read_text(encoding="utf-8"))
    assert len(idx["nodes"]) == 1
    assert len(idx["records"]) == 1
    assert len(idx["tables"]) == 1
    assert len(idx["secrets"]) == 1
    assert len(idx["tensions"]) == 1
    assert len(idx["resources"]) == 1
    assert len(idx["personnages"]) == 1
    assert idx["personnages"][0]["id"] == "vahn"
    assert idx["personnages"][0]["nom"] == "Vahn"
    assert idx["personnages"][0]["nb_jalons"] == 2
    print(f"  VERT : 1/1/1/1/1/1/1 (node/record/table/secret/tension/ressource/personnage)")
finally:
    shutil.rmtree(tmp_a, ignore_errors=True)

# (b) partition-pconv3 réelle + Vahn synthétique VERT -----------------------
section("(b) partition-pconv3 reelle + Vahn synthetique VERT")
PCONV3 = Path(r"C:\Users\souhe\coderain\corpus-modules"
              r"\death-knights-squire\partition-pconv3")
if PCONV3.exists():
    import hashlib
    from datetime import datetime, timezone

    texte = Path(r"C:\Users\souhe\coderain\corpus-modules"
                 r"\death-knights-squire\extraction"
                 r"\source-pconv0-p10-98.txt").read_text(encoding="utf-8")
    manifest_obj = Manifest(
        titre="Death Knight's Squire", corpus_source="5e",
        corpus_cible="5e", structures=["S1", "S2"],
        hash_source=hashlib.sha256(texte.encode("utf-8")).hexdigest(),
        date_conversion=datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        version_convertisseur="0.4.0+gamebook-local")
    part_b = Partition(manifest_obj)
    for f in sorted((PCONV3 / "nodes").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        body = m.group(2).strip()
        part_b.nodes.append(Node(
            nid=fm["id"], type_=fm["type"], titre=fm.get("titre", ""),
            corps_md=body, altitude=fm["altitude"],
            liens=fm.get("liens", []), anchors=fm["anchors"],
            charniere_sortie=fm.get("charniere_sortie"),
            objectif_md=fm.get("objectif_md", ""),
            debouches=fm.get("debouches"),
            heritage=fm.get("heritage")))
    for f in sorted((PCONV3 / "records").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        body = json.loads(m.group(2).strip()) \
            if m.group(2).strip().startswith("{") else {}
        part_b.records.append(Record(
            rid=fm["id"], classe=fm["classe"], nom=fm["nom"],
            stats_5e=body, anchors=fm["anchors"],
            tags=fm.get("tags"), transverse=fm.get("transverse"),
            fonctions_aval=fm.get("fonctions_aval")))
    for f in sorted((PCONV3 / "tables").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        entrees = []
        for line in m.group(2).splitlines():
            em = re.match(r"^-\s+(\d+)-(\d+):\s+(.*)$", line.strip())
            if em:
                entrees.append({"plage_debut": int(em.group(1)),
                                "plage_fin": int(em.group(2)),
                                "resultat_md": em.group(3)})
        if entrees:
            part_b.tables.append(RollTable(
                tid=fm["id"], de=fm["de"], entrees=entrees,
                anchors=fm.get("anchors", [[0, 10]])))
    for f in sorted((PCONV3 / "secrets").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        part_b.secrets.append(Secret(
            sid=fm["id"], contenu_md=m.group(2).strip(),
            statut=fm["statut"], porteurs=fm.get("porteurs", []),
            revelation=fm["revelation"],
            consequence_si_brule=fm.get("consequence_si_brule", ""),
            anchors=fm["anchors"]))
    for f in sorted((PCONV3 / "tensions").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        part_b.tensions.append(Tension(
            tid=fm["id"], categorie=fm["categorie"],
            description_md=m.group(2).strip(),
            node_id=fm["node_id"], anchors=fm["anchors"]))
    for f in sorted((PCONV3 / "resources").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        part_b.ressources.append(Ressource(
            rid=fm["id"], type_ressource=fm["type"],
            anchors=fm.get("anchors", [[0, 10]]),
            node_id=fm.get("node_id"), page=fm.get("page"),
            fichier=fm.get("fichier"),
            description_md=m.group(2).strip()))
    part_b.resources = part_b.ressources
    av_text = (PCONV3 / "aventure.md").read_text(encoding="utf-8") \
        if (PCONV3 / "aventure.md").exists() else ""
    m_av = re.search(r"---\n(.*?)\n---", av_text, re.S)
    if m_av:
        fm_av = json.loads(m_av.group(1))
        charniere = (fm_av.get("charniere_md", "")
                     if "charniere_md" in fm_av
                     else av_text.split("## Charnière de sortie")[-1].strip()
                     if "## Charnière" in av_text else "")
        part_b.aventure = Aventure(
            fm_av.get("trajectoire", []),
            fm_av.get("conditions", []), charniere)
    tension_ids = [t.id for t in part_b.tensions]
    node_ids_list = [n.id for n in part_b.nodes]
    assert len(tension_ids) >= 1, f"tensions {len(tension_ids)} < 1"
    assert len(node_ids_list) >= 1, f"nodes {len(node_ids_list)} < 1"
    part_b.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-origine",
             "intention_md": "Ancien soldat ayant survécu à la guerre "
                             "d'Weathercote.",
             "rattachement": tension_ids[0]},
            {"id": "jalon-dette",
             "intention_md": "Porteur d'une dette envers un mort.",
             "rattachement": node_ids_list[0]},
        ]))
    tmp_b = Path(tempfile.mkdtemp(prefix="pval-reel-"))
    try:
        write_partition(part_b, tmp_b)
        (tmp_b / "directeur.md").write_text("# Brief\nSans secret.\n",
                                            encoding="utf-8")
        errs_b = validate_form.validate_form(part_b, tmp_b)
        assert errs_b == [], f"(b) attendu VERT mais {errs_b}"
        idx_b = json.loads((tmp_b / "index.json").read_text(
            encoding="utf-8"))
        assert len(idx_b["nodes"]) == 361
        assert len(idx_b["records"]) == 35
        assert len(idx_b["tables"]) == 5
        assert len(idx_b["secrets"]) == 4
        assert len(idx_b["tensions"]) == 9
        assert len(idx_b["resources"]) == 19
        assert len(idx_b["personnages"]) == 1
        assert idx_b["personnages"][0]["id"] == "vahn"
        assert idx_b["personnages"][0]["nom"] == "Vahn"
        assert idx_b["personnages"][0]["nb_jalons"] == 2
        from coderain.converter import s1_local
        scan = s1_local.scan_gamebook(texte)
        units = scan["units"]
        coverage = validate_fidelity.coverage_report(units, [], len(texte))
        assert not coverage["gaps"], f"(b) fidelity gaps: {coverage['gaps']}"
        assert not coverage["overlaps"], \
            f"(b) fidelity overlaps: {coverage['overlaps']}"
        print(f"  VERT : 361/35/5/4/9/19/1 + fidelity gaps=0 overlaps=0")
    finally:
        shutil.rmtree(tmp_b, ignore_errors=True)
else:
    print("  SKIP partition reelle : dossier absent (CI)")

# (c) dangling croisé : personnage → tension inexistante ⇒ ValueError nommé --
section("(c) dangling croise : personnage -> tension inexistante => ValueError")
tmp_c = Path(tempfile.mkdtemp(prefix="pval-dang-"))
try:
    part_c = Partition(manifest())
    part_c.nodes.append(node("scene-1"))
    part_c.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-1",
             "intention_md": "Origine lointaine.",
             "rattachement": "tension-inexistante"},
            {"id": "jalon-2",
             "intention_md": "Dette non tenue."},
        ]))
    try:
        write_partition(part_c, tmp_c)
        raise AssertionError("(c) dangling rattachement accepte a l'emission")
    except ValueError as e:
        assert "tension-inexistante" in str(e), e
        assert "vahn" in str(e), e
        print(f"  ValueError OK : {e}")
    errs_c = validate_form.validate_form(part_c)
    assert any("rattachement" in e and "tension-inexistante" in e
               for e in errs_c), errs_c
finally:
    shutil.rmtree(tmp_c, ignore_errors=True)

# (d) load_partition (module_index) expose personnages (lecture pure) --------
section("(d) load_partition expose personnages via module_index (lecture pure)")
tmp_d = Path(tempfile.mkdtemp(prefix="pval-load-"))
try:
    part_d = Partition(manifest())
    part_d.nodes.append(node("scene-1", "Contenu.", [(0, 10)]))
    part_d.nodes.append(node("scene-2", "Autre contenu.", [(10, 20)]))
    part_d.nodes[-1].liens.append(
        {"cible_id": "scene-1", "condition_textuelle": "retour"})
    part_d.tensions.append(Tension(
        "tension-1", "menace", "Menace imminente.",
        "scene-1", [(0, 5)]))
    part_d.ressources.append(Ressource(
        "carte-1", "carte", [(0, 5)],
        node_id="scene-1", page=100,
        fichier="resources/carte-1.jpg"))
    part_d.resources = part_d.ressources
    part_d.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Trajectoire par défaut",
          "declencheur": {"type": "etat", "valeur": "debut"},
          "perturbations": [{"condition_etat": "abandon",
                             "issue": "abandonnee",
                             "porteur_cible_id": "scene-1"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    part_d.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-1",
             "intention_md": "Ancien soldat.",
             "rattachement": "scene-1"},
            {"id": "jalon-2",
             "intention_md": "Porteur d'une dette.",
             "rattachement": "tension-1"},
        ]))
    write_partition(part_d, tmp_d)
    idx_d = load_partition(tmp_d)
    assert "personnages" in idx_d, \
        f"(d) personnages absent de l'index : {sorted(idx_d.keys())}"
    assert len(idx_d["personnages"]) == 1
    assert idx_d["personnages"][0]["id"] == "vahn"
    assert idx_d["personnages"][0]["nom"] == "Vahn"
    assert idx_d["personnages"][0]["nb_jalons"] == 2
    assert idx_d["personnages"][0]["acquis_conversation"] == []
    print(f"  load_partition OK : personnages[0] = "
          f"{idx_d['personnages'][0]}")
finally:
    shutil.rmtree(tmp_d, ignore_errors=True)

print(f"\nOK test-pval-bout-en-bout — {len(FAIT)} sections vertes")
