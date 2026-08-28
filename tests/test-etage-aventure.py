"""I-309 — étage Aventure du convertisseur : couverture dédiée, 100%
synthétique (D-109). Le socle (`Evenement`/`Aventure` figés par D-182,
émission `emit.write_partition`, contrôles `validate_form` §7) existe déjà
(D-178/D-182, `1d7ef6b`) et est exercé en pointillés par converter_test.py
(route LLM), pconv2_tension_test.py (construction Evenement) et
test-pval-bout-en-bout.py (partition réelle DKS, hors CI). Ce fichier
consolide en un seul endroit, sans dépendance corpus, les quatre briques de
la fiche méta 2026-08-23 :
  1. trajectoire par défaut (perturbations, garde anti-rail D-120 §5.1)
  2. conditions de monde (rubrique "condition", portée mondiale, D-119)
  3. charnière de sortie (étage OU node terminal, D-123 §6)
  4. exceptions signalées jamais improvisées (fiche §6, adventure_exceptions)
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
from coderain.converter.schemas import Aventure, Evenement, Manifest, Node, Partition

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e", corpus_cible="5e",
                    structures=["S1", "S2"], hash_source="0" * 64,
                    date_conversion="2026-08-28T00:00:00+00:00",
                    version_convertisseur="test")


def node(nid="scene-1", body="Contenu de scene.", anchors=None, charniere_sortie=None):
    return Node(nid, "scene", nid.upper(), body, "scene",
                anchors=anchors or [(0, 10)], charniere_sortie=charniere_sortie)


# 1) trajectoire par défaut : événement + perturbation avec issue valide -----
section("1) trajectoire : declencheur + perturbation issue valide -> vert")
ev = Evenement("traj-01", "Le donjon s'effondre lentement.",
               declencheur={"type": "delai", "valeur": "3 jours"},
               perturbations=[{"condition_etat": "heros intervient",
                               "issue": "abandonnee"}],
               anchors=[(0, 20)])
assert ev.rubrique == "trajectoire"
assert ev.perturbations[0]["issue"] == "abandonnee"
print(f"  OK : {ev.id} declencheur={ev.declencheur} perturbation={ev.perturbations}")

# 1bis) garde anti-rail D-120 §5.1 : issue hors {transplantee, abandonnee} refusée
section("1bis) perturbation.issue hors vocabulaire -> ValueError (anti-rail)")
try:
    Evenement("traj-bad", "x", declencheur={"type": "etat", "valeur": "y"},
              perturbations=[{"condition_etat": "z", "issue": "retardee"}],
              anchors=[(0, 5)])
    raise AssertionError("issue hors vocabulaire acceptée")
except ValueError as e:
    assert "PERTURBATION_ISSUES" not in str(e)  # message nommé, pas la constante brute
    assert "retardee" in str(e)
    print(f"  ValueError OK : {e}")

# 2) conditions de monde : rubrique "condition", sans lieu, portée mondiale --
section("2) condition de monde : rubrique condition, sans ancrage spatial")
cond = Evenement("cond-01", "Le royaume sombre dans la famine.",
                 declencheur={"type": "date", "valeur": "an 3"},
                 rubrique="condition", anchors=[(30, 50)])
assert cond.rubrique == "condition"
assert cond.perturbations == []   # une condition de monde n'a pas de porteur local
print(f"  OK : {cond.id} rubrique={cond.rubrique} (portée mondiale, D-119)")

# 3) Aventure assemble trajectoire + conditions, warnings sur formes héritées -
section("3) Aventure : trajectoire + conditions assemblées, perte signalée")
av = Aventure(
    trajectoire=[{"id": "traj-01", "description_md": "Depart de la caravane",
                  "declencheur": {"type": "etat", "valeur": "pacte scelle"},
                  "perturbations": [{"condition_etat": "embuscade",
                                     "issue": "transplantee",
                                     "porteur_cible_id": "scene-1"}],
                  "ancres_sources": [[0, 10]]},
                 {"id": "traj-02", "description_md": "Perturbation heritee sans issue",
                  "perturbations": ["une chaîne libre, forme héritée"],
                  "ancres_sources": [[10, 20]]}],
    conditions=[{"id": "cond-01", "description_md": "Hiver rigoureux",
                "declencheur": {"type": "date", "valeur": "an 1"},
                "ancres_sources": [[20, 30]]}],
    charniere_md="La caravane atteint la passe: la suite reste ouverte.")
assert len(av.trajectoire) == 2 and len(av.conditions) == 1
assert any("perturbation #1 héritée (chaîne)" in w for w in av.warnings), av.warnings
print(f"  OK : trajectoire={len(av.trajectoire)} conditions={len(av.conditions)} "
      f"warnings={len(av.warnings)}")

# 4) émission : aventure.md porte trajectoire/conditions + charnière ---------
section("4) emit.write_partition : aventure.md front matter + charnière")
tmp4 = Path(tempfile.mkdtemp(prefix="etage-aventure-emit-"))
try:
    p = Partition(manifest())
    p.nodes.append(node("scene-1", "Une caravane s'ébranle.", [(0, 10)]))
    p.nodes[-1].liens.append({"cible_id": "scene-1", "condition_textuelle": "boucle"})
    p.aventure = av
    write_partition(p, tmp4)
    text = (tmp4 / "aventure.md").read_text(encoding="utf-8")
    fm = json.loads(text.split("---\n")[1])
    assert fm["etage"] == "adventure"
    assert fm["schema_evenement"] == "fige-D-182"
    assert len(fm["trajectoire"]) == 2
    assert len(fm["conditions"]) == 1
    assert "Charnière de sortie" in text
    assert "atteint la passe" in text
    idx = json.loads((tmp4 / "index.json").read_text(encoding="utf-8"))
    assert idx["aventure"] == {"etage": "adventure", "trajectoire": 2, "conditions": 1}
    print(f"  OK : aventure.md + index.json cohérents ({fm['trajectoire'].__len__()} "
          f"trajectoire, {fm['conditions'].__len__()} condition)")
finally:
    shutil.rmtree(tmp4, ignore_errors=True)

# 5) charnière de sortie : au niveau étage OU portée par le node terminal ----
section("5) charnière de sortie : étage vide + node terminal charniere_sortie -> vert")
tmp5 = Path(tempfile.mkdtemp(prefix="etage-aventure-charniere-node-"))
try:
    p5 = Partition(manifest())
    p5.nodes.append(node(
        "scene-finale", "Le donjon est vidé.", [(0, 10)],
        charniere_sortie={"ouvre_vers_md": "La cité reste à raconter.",
                          "prerequis_etat": "donjon nettoye"}))
    p5.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Assaut final",
          "declencheur": {"type": "etat", "valeur": "assaut"},
          "perturbations": [{"condition_etat": "fuite",
                             "issue": "abandonnee"}],
          "ancres_sources": [[0, 10]]}],
        [], "")   # charnière étage VIDE — portée par le node terminal
    write_partition(p5, tmp5)
    (tmp5 / "directeur.md").write_text("# Brief\nSans secret.\n", encoding="utf-8")
    errs5 = validate_form.validate_form(p5, tmp5)
    assert errs5 == [], f"attendu vert (charnière portée par node) mais {errs5}"
    print("  OK : charnière étage vide tolérée quand un node terminal la porte")
finally:
    shutil.rmtree(tmp5, ignore_errors=True)

# 6) charnière de sortie absente partout -> rouge (D-123 §6) -----------------
section("6) charnière de sortie absente étage ET node terminal -> rouge")
tmp6 = Path(tempfile.mkdtemp(prefix="etage-aventure-charniere-absente-"))
try:
    p6 = Partition(manifest())
    p6.nodes.append(node("scene-finale", "Le donjon est vidé.", [(0, 10)]))
    p6.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Assaut final",
          "declencheur": {"type": "etat", "valeur": "assaut"},
          "perturbations": [{"condition_etat": "fuite", "issue": "abandonnee"}],
          "ancres_sources": [[0, 10]]}],
        [], "")
    write_partition(p6, tmp6)
    (tmp6 / "directeur.md").write_text("# Brief\nSans secret.\n", encoding="utf-8")
    errs6 = validate_form.validate_form(p6, tmp6)
    assert any("charnière de sortie vide" in e for e in errs6), errs6
    assert any("dernier node sans lien sortant ni charniere_sortie" in e
               for e in errs6), errs6
    print(f"  OK rouge : {[e for e in errs6 if 'charni' in e]}")
finally:
    shutil.rmtree(tmp6, ignore_errors=True)

# 7) étage aventure absent alors que des nodes existent -> rouge -------------
section("7) partition avec nodes mais sans étage aventure -> rouge")
p7 = Partition(manifest())
p7.nodes.append(node("scene-1"))
errs7 = validate_form.validate_form(p7)
assert any("étage aventure absent" in e for e in errs7), errs7
print(f"  OK rouge : {[e for e in errs7 if 'aventure absent' in e]}")

# 8) perturbation sans issue et porteur_cible_id inconnu -> rouges cumulés ---
section("8) perturbation sans issue + porteur_cible_id dangling -> deux rouges")
p8 = Partition(manifest())
p8.nodes.append(node("scene-1"))
p8.aventure = Aventure(
    [{"id": "traj-01", "description_md": "Traversée hasardeuse",
      "declencheur": {"type": "etat", "valeur": "entree"},
      "perturbations": [{"condition_etat": "echec jet",
                         "porteur_cible_id": "fantome-inconnu"}],
      "ancres_sources": [[0, 10]]}],
    [], "Sortie ouverte")
errs8 = validate_form.validate_form(p8)
assert any("perturbation sans issue valide" in e for e in errs8), errs8
assert any("porteur_cible_id inconnu fantome-inconnu" in e for e in errs8), errs8
print(f"  OK rouge : {[e for e in errs8 if 'traj-01' in e]}")

# 9) adventure_exceptions : pertes signalées, jamais improvisées (fiche §6) --
section("9) adventure_exceptions : trajectoire sans perturbations + declencheur vide")
p9 = Partition(manifest())
p9.nodes.append(node("scene-1"))
p9.aventure = Aventure(
    [{"id": "traj-01", "description_md": "Sans perturbation ni valeur",
      "declencheur": {"type": "etat", "valeur": ""},
      "ancres_sources": [[0, 10]]}],
    [], "Sortie ouverte")
excs = validate_form.adventure_exceptions(p9)
assert any("perturbations [] — aucune condition" in e for e in excs), excs
assert any("declencheur sans valeur fournie" in e for e in excs), excs
print(f"  OK : {excs}")

print(f"\nOK test-etage-aventure — {len(FAIT)} sections vertes")
