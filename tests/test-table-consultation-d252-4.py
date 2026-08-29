"""D-252.4 : mode consultation des tables — clé de consultation sans dé,
interrogeable par le documentaliste (MRPG-D-252 point 4).

100% synthétique (D-109) : aucun matériau de campagne réel — fixture prix
par marchandise.

Formes livrées :
- RollTable mode consultation/aleatoire (coderain/converter/schemas.py:356)
- rendu markdown + front matter mode-aware (coderain/converter/emit.py:10,74)
- lecture ciblée consulter_table() / roll_table() garde de mode
  (coderain/converter/aval.py)
- construction LLM mode-aware (coderain/converter/semantic.py:100)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter import aval
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, RollTable

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="0" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


# 1 -- rétrocompat : table aleatoire existante inchangée -----------------------
section("table aleatoire : comportement inchange (retrocompat)")
t = RollTable("table-tresor", "1d6",
             [{"plage_debut": 1, "plage_fin": 1, "resultat_md": "piece d'or"},
              {"plage_debut": 2, "plage_fin": 6, "resultat_md": "rien du tout"}],
             [(0, 10)])
assert t.mode == "aleatoire"
assert t.de == "1d6"

# 2 -- table consultation : cle de consultation sans de -------------------------
section("table consultation : cle sans de, prix par marchandise")
t_cons = RollTable("table-prix-marchandises", "",
                   [{"cle": "sel", "resultat_md": "2 po la livre"},
                    {"cle": "epices", "resultat_md": "15 po la livre"},
                    {"cle": "soie", "resultat_md": "40 po la livre"}],
                   [(0, 20)], mode="consultation")
assert t_cons.mode == "consultation"
assert t_cons.de is None
assert len(t_cons.entrees) == 3

# 3 -- refus du valideur : consultation avec de ---------------------------------
section("refus : table consultation avec de")
try:
    RollTable("bad-cons-de", "1d20",
             [{"cle": "sel", "resultat_md": "2 po"}],
             [(0, 5)], mode="consultation")
    raise AssertionError("consultation avec de acceptee")
except ValueError as e:
    assert "dé" in str(e) or "de" in str(e).lower(), e

# 4 -- refus du valideur : aleatoire sans de -------------------------------------
section("refus : table aleatoire sans de")
try:
    RollTable("bad-aleat-sans-de", "",
             [{"plage_debut": 1, "plage_fin": 6, "resultat_md": "rien"}],
             [(0, 5)], mode="aleatoire")
    raise AssertionError("aleatoire sans de acceptee")
except ValueError:
    pass

# 5 -- refus du valideur : cles dupliquees ---------------------------------------
section("refus : cles de consultation dupliquees")
try:
    RollTable("bad-dup-cle", "",
             [{"cle": "sel", "resultat_md": "2 po"},
              {"cle": "sel", "resultat_md": "3 po"}],
             [(0, 5)], mode="consultation")
    raise AssertionError("cles dupliquees acceptees")
except ValueError as e:
    assert "dupliqu" in str(e), e

# 6 -- refus du valideur : cle vide ----------------------------------------------
section("refus : cle de consultation vide")
try:
    RollTable("bad-cle-vide", "",
             [{"cle": "  ", "resultat_md": "2 po"}],
             [(0, 5)], mode="consultation")
    raise AssertionError("cle vide acceptee")
except ValueError as e:
    assert "vide" in str(e), e

# 7 -- mode invalide --------------------------------------------------------------
section("refus : mode inconnu")
try:
    RollTable("bad-mode", "1d6",
             [{"plage_debut": 1, "plage_fin": 6, "resultat_md": "x"}],
             [(0, 5)], mode="au-hasard")
    raise AssertionError("mode inconnu accepte")
except ValueError:
    pass

# 8 -- bout en bout : emission + lecture ciblee (documentaliste) ----------------
section("bout en bout : emission puis consulter_table")
tmp = Path(tempfile.mkdtemp(prefix="d252-4-cons-"))
try:
    p = Partition(manifest())
    p.nodes.append(Node("scene-marche", "scene", "MARCHE",
                        "Le marche vend sel, epices et soie.", "scene",
                        anchors=[(0, 30)]))
    p.nodes[-1].liens = []
    p.tables.append(t_cons)
    p.tables.append(t)   # table aleatoire coexiste, mode par defaut inchange
    write_partition(p, tmp)

    # lecture ciblee : cle connue rend la bonne entree
    res = aval.consulter_table(tmp, "table-prix-marchandises", "epices")
    assert res["resultat_md"] == "15 po la livre", res

    # cle inconnue : echec explicite, jamais une invention
    try:
        aval.consulter_table(tmp, "table-prix-marchandises", "or")
        raise AssertionError("cle inconnue acceptee")
    except aval.TableConsultationError as e:
        assert "or" in str(e), e

    # table aleatoire existante : roll_table toujours fonctionnel
    r = aval.roll_table(tmp, "table-tresor", die_result=3)
    assert r["resultat"]["resultat_md"] == "rien du tout", r

    # garde de mode : roll_table refuse sur une table consultation
    try:
        aval.roll_table(tmp, "table-prix-marchandises")
        raise AssertionError("roll_table sur table consultation acceptee")
    except aval.TableConsultationError:
        pass

    # garde de mode : consulter_table refuse sur une table aleatoire
    try:
        aval.consulter_table(tmp, "table-tresor", "1")
        raise AssertionError("consulter_table sur table aleatoire acceptee")
    except aval.TableConsultationError:
        pass
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\nOK test-table-consultation-d252-4 — {len(FAIT)} sections vertes")
