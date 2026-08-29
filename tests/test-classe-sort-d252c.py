"""D-252.3 (Issue #63) : classe de record `sort` — sorts inédits des
appendices de campagne. 100% synthétique (D-109) : sorts inventés, aucun
matériau de campagne réel."""
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
from coderain.converter.aval import get_record
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="0" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


def sort(stats_extra=None, **kw):
    stats = {"niveau": 3, "ecole": "evocation",
             "temps_incantation": "1 action", "portee": "36 mètres",
             "composantes": "V, S, M (une pincée de suie)",
             "duree": "instantanée",
             "effet_md": "Un jet de flammes imaginaire inflige 6d6 dégâts.",
             "listes_de_classes": ["magicien", "ensorceleur"]}
    stats.update(stats_extra or {})
    return Record(kw.get("rid", "flamme-torsadee"), "sort",
                  kw.get("nom", "Flamme torsadée"), stats, [(1, 40)],
                  tags=kw.get("tags"))


# 1 -- un sort inédit complet charge et valide -----------------------------
section("sort complet : charge et valide (niveau/ecole/composantes bornés)")
r = sort()
assert r.classe == "sort"
assert r.stats_5e["niveau"] == 3
assert r.stats_5e["ecole"] == "evocation"

# 2 -- niveau hors bornes refusé --------------------------------------------
section("niveau hors bornes [0-9] refusé avec message")
for bad in (-1, 10, "3", True, 3.5):
    try:
        sort({"niveau": bad})
        raise AssertionError(f"niveau invalide accepté: {bad!r}")
    except ValueError as e:
        assert "niveau" in str(e), e

# 3 -- ecole hors bornes refusée --------------------------------------------
section("ecole hors énum SRD refusée avec message")
try:
    sort({"ecole": "conjuration"})   # pas dans la nomenclature du poste
    raise AssertionError("ecole invalide acceptée")
except ValueError as e:
    assert "ecole" in str(e), e

# 4 -- composantes sans V/S/M refusées --------------------------------------
section("composantes doit citer au moins une composante V/S/M")
try:
    sort({"composantes": "aucune"})
    raise AssertionError("composantes invalides acceptées")
except ValueError as e:
    assert "composantes" in str(e), e

# 5 -- listes_de_classes vide refusée ---------------------------------------
section("listes_de_classes non vide requise")
try:
    sort({"listes_de_classes": []})
    raise AssertionError("listes_de_classes vide acceptée")
except ValueError as e:
    assert "listes_de_classes" in str(e), e

# 6 -- concentration/rituel : booléens seulement ----------------------------
section("concentration/rituel typés booléen")
r = sort({"concentration": True, "rituel": False})
assert r.stats_5e["concentration"] is True
try:
    sort({"concentration": "oui"})
    raise AssertionError("concentration non-booléenne acceptée")
except ValueError as e:
    assert "concentration" in str(e), e

# 7 -- champ requis manquant refusé (présence, annexe_a) --------------------
section("champ requis absent refusé (required_fields §6 annexe A)")
try:
    Record("sort-incomplet", "sort", "Sort incomplet",
           {"niveau": 1, "ecole": "abjuration"}, [(1, 5)])
    raise AssertionError("sort incomplet accepté")
except ValueError as e:
    assert "missing" in str(e), e

# 8 -- sorts_connus réservé creature/pnj ------------------------------------
section("sorts_connus réservé aux classes lanceuses creature/pnj")
try:
    Record("porte-x", "objet", "Porte", {"description_md": "x",
                                          "sorts_connus": ["flamme-torsadee"]},
           [(1, 2)])
    raise AssertionError("sorts_connus accepté hors creature/pnj")
except ValueError as e:
    assert "creature/pnj" in str(e), e

pnj_lanceur = Record(
    "sorcier-exemple", "pnj", "Sorcier d'exemple",
    {"role": "antagoniste mineur", "description_md": "Lance des sorts.",
     "sorts_connus": ["flamme-torsadee"]}, [(50, 90)])
assert pnj_lanceur.sorts_connus == ["flamme-torsadee"]

# 9 -- garde zéro-dangling : PNJ lanceur résout le sort par id --------------
section("garde zéro-dangling : PNJ lanceur cite un sort existant → vert")
tmp = Path(tempfile.mkdtemp(prefix="sort-d252c-"))
try:
    p = Partition(manifest())
    p.nodes.append(Node("repaire", "scene", "REPAIRE",
                        "Sorcier d'exemple garde ce repaire imaginaire.",
                        "scene", anchors=[(1, 60)]))
    p.records.append(sort())
    p.records.append(pnj_lanceur)
    write_partition(p, tmp)   # ne doit pas lever

    errs = validate_form.validate_form(p)
    assert not [e for e in errs if "sorts_connus" in e], errs
    assert not [e for e in errs if "orphan" in e], errs

    rec = get_record(tmp, "sorcier-exemple")
    assert rec["meta"]["sorts_connus"] == ["flamme-torsadee"]

    # 10 -- garde zéro-dangling : sort inconnu refusé à l'émission ----------
    section("garde zéro-dangling : sort inconnu refusé à l'émission")
    p2 = Partition(manifest())
    p2.nodes.append(Node("repaire2", "scene", "REPAIRE2", "Texte.",
                        "scene", anchors=[(1, 10)]))
    p2.records.append(Record(
        "sorcier-orphelin", "pnj", "Sorcier orphelin",
        {"role": "figurant", "description_md": "x",
         "sorts_connus": ["sort-inexistant"]}, [(1, 5)]))
    try:
        write_partition(p2, tmp)
        raise AssertionError("sorts_connus dangling accepté à l'émission")
    except ValueError as e:
        assert "sort-inexistant" in str(e), e

    errs2 = validate_form.validate_form(p2)
    assert any("sort-inexistant" in e for e in errs2), errs2
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\nOK test-classe-sort-d252c — {len(FAIT)} sections vertes")
