"""P-VAL extension Conversation B + destinee + Tension (I-340/I-341/D-219/D-218/D-109).
100% synthetique (D-109) sauf cas (a) qui charge partition-pconv3 reelle.
4 sections :
  (a) partition-pconv3 + Vahn synthetique (4 acquis, 3 jalons rattaches
      node/tension/ressource) validate_form VERT
  (b) garde zero-spoiler sur 9 tensions (aucun secret en clair en sortie)
  (c) garde passe/intention D-129/D-135 via D-220 : jalon futur/evenement
      => rejet nomme
  (d) branchement resources/ : carte-redtree dangling => ValueError
      + carte-redtree valide => VERT
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


# (a) partition-pconv3 reelle + Vahn (4 acquis, 3 jalons node/tension/ressource)
#     validate_form VERT -------------------------------------------------------
section("(a) partition-pconv3 reelle + Vahn 4 acquis 3 jalons VERT")
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
    part_a = Partition(manifest_obj)
    for f in sorted((PCONV3 / "nodes").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        body = m.group(2).strip()
        part_a.nodes.append(Node(
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
        part_a.records.append(Record(
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
            part_a.tables.append(RollTable(
                tid=fm["id"], de=fm["de"], entrees=entrees,
                anchors=fm.get("anchors", [[0, 10]])))
    for f in sorted((PCONV3 / "secrets").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        part_a.secrets.append(Secret(
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
        part_a.tensions.append(Tension(
            tid=fm["id"], categorie=fm["categorie"],
            description_md=m.group(2).strip(),
            node_id=fm["node_id"], anchors=fm["anchors"]))
    for f in sorted((PCONV3 / "resources").glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        part_a.ressources.append(Ressource(
            rid=fm["id"], type_ressource=fm["type"],
            anchors=fm.get("anchors", [[0, 10]]),
            node_id=fm.get("node_id"), page=fm.get("page"),
            fichier=fm.get("fichier"),
            description_md=m.group(2).strip()))
    part_a.resources = part_a.ressources
    av_text = (PCONV3 / "aventure.md").read_text(encoding="utf-8") \
        if (PCONV3 / "aventure.md").exists() else ""
    m_av = re.search(r"---\n(.*?)\n---", av_text, re.S)
    if m_av:
        fm_av = json.loads(m_av.group(1))
        charniere = (fm_av.get("charniere_md", "")
                     if "charniere_md" in fm_av
                     else av_text.split("## Charnière de sortie")[-1].strip()
                     if "## Charnière" in av_text else "")
        part_a.aventure = Aventure(
            fm_av.get("trajectoire", []),
            fm_av.get("conditions", []), charniere)
    tension_ids = [t.id for t in part_a.tensions]
    node_ids_list = [n.id for n in part_a.nodes]
    ressource_ids = [r.id for r in part_a.ressources]
    assert len(tension_ids) >= 1, f"tensions {len(tension_ids)} < 1"
    assert len(node_ids_list) >= 1, f"nodes {len(node_ids_list)} < 1"
    assert len(ressource_ids) >= 1, f"ressources {len(ressource_ids)} < 1"
    part_a.personnages.append(Personnage(
        "vahn", "Vahn",
        acquis_conversation=[
            "nom choisi par le joueur",
            "dettes envers un mort de la guerre",
            "serment de ne pas reveler le pieu",
            "alliance avec le clerc de Mistcross",
        ],
        destinee=[
            {"id": "jalon-origine",
             "intention_md": "Ancien soldat ayant survécu à la guerre "
                             "d'Weathercote.",
             "rattachement": node_ids_list[0]},
            {"id": "jalon-dette",
             "intention_md": "Porteur d'une dette envers un mort.",
             "rattachement": tension_ids[0]},
            {"id": "jalon-carte",
             "intention_md": "Gardien de la carte du donjon.",
             "rattachement": ressource_ids[0]},
        ]))
    tmp_a = Path(tempfile.mkdtemp(prefix="pval-ext-a-"))
    try:
        write_partition(part_a, tmp_a)
        (tmp_a / "directeur.md").write_text("# Brief\nSans secret.\n",
                                            encoding="utf-8")
        errs_a = validate_form.validate_form(part_a, tmp_a)
        assert errs_a == [], f"(a) attendu VERT mais {errs_a}"
        idx_a = json.loads((tmp_a / "index.json").read_text(encoding="utf-8"))
        assert len(idx_a["personnages"]) == 1
        p = idx_a["personnages"][0]
        assert p["id"] == "vahn"
        assert p["nom"] == "Vahn"
        assert p["nb_jalons"] == 3
        txt_vahn = (tmp_a / "personnages" / "vahn.md").read_text(
            encoding="utf-8")
        for acquis in ("nom choisi par le joueur",
                       "dettes envers un mort",
                       "serment de ne pas reveler",
                       "alliance avec le clerc"):
            assert acquis in txt_vahn, \
                f"(a) acquis manquant dans vahn.md : {acquis}"
        for ratt_id in (node_ids_list[0], tension_ids[0], ressource_ids[0]):
            assert ratt_id in txt_vahn, \
                f"(a) rattachement manquant dans vahn.md : {ratt_id}"
        print(f"  VERT : 361/35/5/4/9/19/1 + 4 acquis + 3 jalons "
              f"(node={node_ids_list[0]}, tension={tension_ids[0]}, "
              f"ressource={ressource_ids[0]})")
    finally:
        shutil.rmtree(tmp_a, ignore_errors=True)
else:
    print("  SKIP partition reelle : dossier absent (CI)")

# (b) garde zero-spoiler sur 9 tensions (aucun secret en clair en sortie) ------
section("(b) garde zero-spoiler : 9 tensions, aucun secret en clair")
tmp_b = Path(tempfile.mkdtemp(prefix="pval-ext-b-"))
try:
    part_b = Partition(manifest())
    nodes_b = []
    for i in range(9):
        n = node(f"scene-{i}", f"Contenu de la scene {i}.", [(i * 10, (i + 1) * 10)])
        part_b.nodes.append(n)
        nodes_b.append(n)
    part_b.nodes[-1].liens.append(
        {"cible_id": "scene-0", "condition_textuelle": "retour"})
    categories = ("menace", "horloge", "echeance", "cout", "choix",
                  "revelation", "menace", "horloge", "choix")
    for i in range(9):
        part_b.tensions.append(Tension(
            f"tension-{i}", categories[i],
            f"Description de la tension {i} — pas de secret ici.",
            f"scene-{i}", [(i * 10, i * 10 + 5)]))
    part_b.secrets.append(Secret(
        "secret-pieux", "Le pieu de l'arbre rouge est la clé de tout.",
        "secret", ["scene-0"],
        {"declencheur": "inspection", "node_cible": "scene-0"},
        "Révéler brise l'immersion", [(0, 15)]))
    part_b.ressources.append(Ressource(
        "carte-1", "carte", [(0, 10)],
        node_id="scene-0", page=100,
        fichier="resources/carte-1.jpg"))
    part_b.resources = part_b.ressources
    part_b.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête acceptée",
          "declencheur": {"type": "etat", "valeur": "quete acceptee"},
          "perturbations": [{"condition_etat": "abandon",
                             "issue": "abandonnee",
                             "porteur_cible_id": "scene-0"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    part_b.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-1",
             "intention_md": "Ancien soldat.",
             "rattachement": "scene-0"},
            {"id": "jalon-2",
             "intention_md": "Porteur d'une dette."},
        ]))
    write_partition(part_b, tmp_b)
    (tmp_b / "directeur.md").write_text("# Brief\nSans secret.\n",
                                        encoding="utf-8")
    errs_b = validate_form.validate_form(part_b, tmp_b)
    assert errs_b == [], f"(b) attendu VERT mais {errs_b}"
    secret_content = part_b.secrets[0].contenu_md.strip()
    for f in (tmp_b / "tensions").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        assert secret_content[:40] not in txt, \
            f"(b) secret leak dans tension file {f.name}"
    for f in (tmp_b / "nodes").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        assert secret_content[:40] not in txt, \
            f"(b) secret leak dans node file {f.name}"
    directeur_txt = (tmp_b / "directeur.md").read_text(encoding="utf-8")
    assert secret_content[:60] not in directeur_txt, \
        "(b) secret leak dans directeur.md"
    print(f"  VERT : 9 tensions, 1 secret, zero leak (prose + tensions "
          f"+ directeur)")
finally:
    shutil.rmtree(tmp_b, ignore_errors=True)

# (c) garde passe/intention D-129/D-135 via D-220 : jalon futur/evenement ------
section("(c) garde D-129/D-135 : jalon futur/evenement => rejet nomme")
rejete = 0
for marqueur in ("fera", "quand il", "va", "deviendra", "il arrivera",
                 "il adviendra", "ira"):
    try:
        Personnage("bad", "Bad",
                   destinee=[{"id": "j1",
                              "intention_md": f"Un jour il {marqueur} grand."},
                             {"id": "j2",
                              "intention_md": "Passé simple."}])
        raise AssertionError(f"marqueur futur {marqueur!r} accepte")
    except ValueError as e:
        assert "D-129" in str(e) or marqueur in str(e), e
        rejete += 1
p_ok = Personnage("ok", "Ok",
                  destinee=[{"id": "j1", "intention_md": "Ancien soldat."},
                            {"id": "j2",
                             "intention_md": "Veut retrouver la paix."}])
assert len(p_ok.destinee) == 2
assert rejete >= 7, f"(c) seulement {rejete} rejets sur 7 marqueurs"
print(f"  VERT : {rejete} marqueurs futur/evenement rejetes, "
      f"passe/intention OK")

# (d) branchement resources/ : carte-redtree dangling => ValueError
#     + carte-redtree valide => VERT ------------------------------------------
section("(d) branchement resources/ : carte-redtree dangling + valide")
tmp_d1 = Path(tempfile.mkdtemp(prefix="pval-ext-d1-"))
try:
    part_d1 = Partition(manifest())
    part_d1.nodes.append(node("scene-1"))
    part_d1.ressources.append(Ressource(
        "carte-redtree", "carte", [(0, 10)],
        node_id="scene-1", page=100,
        fichier="resources/carte-redtree.jpg"))
    part_d1.resources = part_d1.ressources
    part_d1.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête",
          "declencheur": {"type": "etat", "valeur": "debut"},
          "perturbations": [{"condition_etat": "abandon",
                             "issue": "abandonnee",
                             "porteur_cible_id": "scene-1"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    part_d1.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-1",
             "intention_md": "Gardien de la carte.",
             "rattachement": "carte-inexistante"},
            {"id": "jalon-2",
             "intention_md": "Porteur d'une dette."},
        ]))
    try:
        write_partition(part_d1, tmp_d1)
        raise AssertionError("(d) dangling carte-redtree accepte a l'emission")
    except ValueError as e:
        assert "carte-inexistante" in str(e), e
        assert "vahn" in str(e), e
        print(f"  ValueError OK (dangling) : {e}")
    errs_d1 = validate_form.validate_form(part_d1)
    assert any("rattachement" in e and "carte-inexistante" in e
               for e in errs_d1), errs_d1
finally:
    shutil.rmtree(tmp_d1, ignore_errors=True)

tmp_d2 = Path(tempfile.mkdtemp(prefix="pval-ext-d2-"))
try:
    part_d2 = Partition(manifest())
    n1 = Node("scene-1", "scene", "SCENE-1", "Contenu.", "scene",
              anchors=[(0, 10)],
              charniere_sortie={"ouvre_vers_md": "La suite est ouverte.",
                                "prerequis_etat": "quete acceptee"})
    part_d2.nodes.append(n1)
    part_d2.ressources.append(Ressource(
        "carte-redtree", "carte", [(0, 10)],
        node_id="scene-1", page=100,
        fichier="resources/carte-redtree.jpg",
        description_md="Carte du donjon de l'arbre rouge"))
    part_d2.resources = part_d2.ressources
    part_d2.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête",
          "declencheur": {"type": "etat", "valeur": "debut"},
          "perturbations": [{"condition_etat": "abandon",
                             "issue": "abandonnee",
                             "porteur_cible_id": "scene-1"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    part_d2.personnages.append(Personnage(
        "vahn", "Vahn",
        destinee=[
            {"id": "jalon-1",
             "intention_md": "Gardien de la carte du donjon.",
             "rattachement": "carte-redtree"},
            {"id": "jalon-2",
             "intention_md": "Porteur d'une dette envers un mort."},
        ]))
    write_partition(part_d2, tmp_d2)
    (tmp_d2 / "directeur.md").write_text("# Brief\nSans secret.\n",
                                         encoding="utf-8")
    errs_d2 = validate_form.validate_form(part_d2, tmp_d2)
    assert errs_d2 == [], f"(d) valide attendu VERT mais {errs_d2}"
    idx_d2 = json.loads((tmp_d2 / "index.json").read_text(encoding="utf-8"))
    assert len(idx_d2["resources"]) == 1
    assert idx_d2["resources"][0]["id"] == "carte-redtree"
    assert len(idx_d2["personnages"]) == 1
    assert idx_d2["personnages"][0]["id"] == "vahn"
    txt_vahn = (tmp_d2 / "personnages" / "vahn.md").read_text(
        encoding="utf-8")
    assert "carte-redtree" in txt_vahn
    print(f"  VERT : carte-redtree valide, rattachement Vahn -> "
          f"carte-redtree OK")
finally:
    shutil.rmtree(tmp_d2, ignore_errors=True)

print(f"\nOK test-pval-extension-conversation-b — {len(FAIT)} sections vertes")
