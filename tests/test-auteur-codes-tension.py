"""D-218 contrat traversant : codes de tension (6) — enum, validator, emit, intégrée.
100% synthétique (D-109) sauf section 6 (partition-pconv3 réelle).
6 sections :
  1. TENSION_CODES enum — 6 valeurs canoniques
  2. Validator vert — tensions valides passent
  3. Validator rouge — catégorie hors codes ⇒ tension_code_invalide
  4. Emit garde — catégorie invalide ⇒ ValueError non silencieuse
  5. Code valide accepté + undefined refusé
  6. partition-pconv3 intégrée — 9 tensions réelles toutes valides
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

from coderain.converter import validate_form
from coderain.converter.emit import write_partition
from coderain.converter.schemas import (Manifest, Node, Partition, Tension,
                                         TENSION_CODES, TENSION_CATEGORIES,
                                         Aventure)

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


def partition_min():
    p = Partition(manifest())
    p.nodes.append(node("scene-1", "La forêt s'étend.", [(0, 10)]))
    p.nodes.append(node("scene-2", "Le château.", [(10, 20)]))
    p.nodes[-1].liens.append({"cible_id": "scene-1", "condition_textuelle": "retour"})
    p.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête acceptée",
          "declencheur": {"type": "etat", "valeur": "quete acceptee"},
          "perturbations": [{"condition_etat": "abandon", "issue": "abandonnee",
                             "porteur_cible_id": "scene-1"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie ouverte")
    return p


# 1 -- TENSION_CODES enum : 6 valeurs canoniques D-218 --------------------
section("TENSION_CODES enum : 6 valeurs canoniques D-218")
assert TENSION_CODES == ("menace", "horloge", "echeance", "cout", "choix", "revelation"), \
    f"TENSION_CODES = {TENSION_CODES}"
assert TENSION_CODES is TENSION_CATEGORIES, "TENSION_CODES alias de TENSION_CATEGORIES"
assert len(TENSION_CODES) == 6
for code in ("menace", "horloge", "echeance", "cout", "choix", "revelation"):
    assert code in TENSION_CODES, f"{code} absent de TENSION_CODES"

# 2 -- Validator vert : tensions valides passent ---------------------------
section("validator vert : tensions valides passent")
tmp = Path(tempfile.mkdtemp(prefix="d218-vert-"))
try:
    part = partition_min()
    part.tensions.append(Tension("t-menace", "menace", "Une menace rode",
                                 "scene-1", [(0, 5)]))
    part.tensions.append(Tension("t-horloge", "horloge", "Le temps presse",
                                 "scene-1", [(0, 5)]))
    part.tensions.append(Tension("t-echeance", "echeance", "Échéance du rituel",
                                 "scene-2", [(10, 15)]))
    part.tensions.append(Tension("t-cout", "cout", "Un prix à payer",
                                 "scene-2", [(10, 15)]))
    part.tensions.append(Tension("t-choix", "choix", "Dire ou mentir",
                                 "scene-1", [(3, 8)]))
    part.tensions.append(Tension("t-revelation", "revelation", "Secret révélé",
                                 "scene-2", [(12, 18)]))
    (tmp / "directeur.md").write_text("# Brief\nSans secret.\n", encoding="utf-8")
    errs = validate_form.validate_form(part, tmp)
    assert errs == [], f"attendu VERT mais {errs}"
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 3 -- Validator rouge : catégorie hors codes ⇒ tension_code_invalide ------
section("validator rouge : categorie hors codes => tension_code_invalide")
part = partition_min()
t_bad = Tension.__new__(Tension)
t_bad.id = "t-fake"
t_bad.categorie = "emotion"
t_bad.description_md = "Ressenti intense"
t_bad.node_id = "scene-1"
t_bad.anchors = [(0, 5)]
part.tensions.append(t_bad)
errs = validate_form.validate_form(part)
assert any("tension_code_invalide" in e for e in errs), \
    f"attendu tension_code_invalide dans {errs}"
assert any("emotion" in e for e in errs), f"attendu 'emotion' dans {errs}"

# 4 -- Emit garde : catégorie invalide ⇒ ValueError non silencieuse --------
section("emit garde : categorie invalide => ValueError non silencieuse")
tmp = Path(tempfile.mkdtemp(prefix="d218-emit-"))
try:
    part = partition_min()
    t_bad2 = Tension.__new__(Tension)
    t_bad2.id = "t-undefined-cat"
    t_bad2.categorie = "undefined"
    t_bad2.description_md = "Catégorie non définie"
    t_bad2.node_id = "scene-1"
    t_bad2.anchors = [(0, 5)]
    part.tensions.append(t_bad2)
    try:
        write_partition(part, tmp)
        raise AssertionError("emit a accepte une tension avec categorie 'undefined'")
    except ValueError as e:
        assert "tension_code_invalide" in str(e), e
        assert "undefined" in str(e), e
        assert "D-218" in str(e), e
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 5 -- Code valide accepté + undefined refusé ------------------------------
section("code valide accepte + undefined refuse")
tmp = Path(tempfile.mkdtemp(prefix="d218-accept-"))
try:
    part = partition_min()
    part.tensions.append(Tension("t-ok", "menace", "Menace valide",
                                 "scene-1", [(0, 5)]))
    write_partition(part, tmp)
    assert (tmp / "tensions" / "t-ok.md").exists()
    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    assert len(idx["tensions"]) == 1
    assert idx["tensions"][0]["categorie"] == "menace"
finally:
    shutil.rmtree(tmp, ignore_errors=True)
# undefined → rejeté par le constructeur Tension
for bad in ("undefined", None, "", "emotion", "peur"):
    try:
        if bad is None:
            t = Tension.__new__(Tension)
            t.id = "t-none"
            t.categorie = bad
            t.description_md = "X"
            t.node_id = "scene-1"
            t.anchors = [(0, 5)]
            part_x = partition_min()
            part_x.tensions.append(t)
            errs = validate_form.validate_form(part_x)
            assert any("tension_code_invalide" in e for e in errs), f"None: {errs}"
        else:
            Tension("t-bad", bad, "Desc", "scene-1", [(0, 5)])
            raise AssertionError(f"categorie {bad!r} acceptee")
    except ValueError:
        pass

# 6 -- partition-pconv3 intégrée : 9 tensions réelles toutes valides -------
section("partition-pconv3 integree : 9 tensions reelles toutes valides")
part_dir = Path(r"C:\Users\souhe\coderain\corpus-modules\death-knights-squire\partition-pconv3")
if part_dir.exists():
    idx = json.loads((part_dir / "index.json").read_text(encoding="utf-8"))
    assert len(idx["tensions"]) == 9, f"tensions {len(idx['tensions'])} != 9"
    for t_entry in idx["tensions"]:
        assert t_entry["categorie"] in TENSION_CODES, \
            f"tension {t_entry['id']}: categorie {t_entry['categorie']!r} hors codes"
    # recharger et valider
    from coderain.converter.schemas import Manifest as Mf, Partition as Pt, Record as Rec
    import hashlib
    from datetime import datetime, timezone
    texte = Path(r"C:\Users\souhe\coderain\corpus-modules\death-knights-squire\extraction\source-pconv0-p10-98.txt").read_text(encoding="utf-8")
    manifest_obj = Mf(titre="Death Knight's Squire", corpus_source="5e", corpus_cible="5e",
                      structures=["S1", "S2"], hash_source=hashlib.sha256(texte.encode("utf-8")).hexdigest(),
                      date_conversion=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      version_convertisseur="0.4.0+gamebook-local")
    part_test = Pt(manifest_obj)
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
    av_text = (part_dir / "aventure.md").read_text(encoding="utf-8") if (part_dir / "aventure.md").exists() else ""
    m_av = re.search(r"---\n(.*?)\n---", av_text, re.S)
    if m_av:
        fm_av = json.loads(m_av.group(1))
        part_test.aventure = Aventure(fm_av.get("trajectoire", []), fm_av.get("conditions", []),
                                       fm_av.get("charniere_md", "") if "charniere_md" in fm_av else
                                       av_text.split("## Charnière de sortie")[-1].strip() if "## Charnière" in av_text else "")
    else:
        part_test.aventure = Aventure([], [], "")
    # validate_form vert sur partition-pconv3 + 9 tensions
    errs = validate_form.validate_form(part_test)
    assert errs == [], f"partition-pconv3 VERT attendu mais {errs}"
    # emit vert
    tmp = Path(tempfile.mkdtemp(prefix="d218-pconv3-"))
    try:
        write_partition(part_test, tmp)
        idx2 = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
        assert len(idx2["tensions"]) == 9
        cats = {t["categorie"] for t in idx2["tensions"]}
        assert cats <= set(TENSION_CODES), f"categories hors codes : {cats - set(TENSION_CODES)}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
else:
    print("SKIP partition-pconv3 : dossier absent (CI)")

print(f"\nOK test-auteur-codes-tension — {len(FAIT)}/6 sections vertes")
assert len(FAIT) == 6, f"attendu 6 sections, got {len(FAIT)}"
