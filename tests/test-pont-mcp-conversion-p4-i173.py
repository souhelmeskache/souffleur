"""Issue #173 : variant pont-MCP de la conversion P4 — segmentation/buckets/
sémantique jugés par la session, zéro appel API.

Fixture 100% SYNTHÉTIQUE (D-109) : specimen S1+S2 fabriqué pour ce test,
calqué sur celui de converter_test.py (même forme, texte différent) —
aucun matériau de campagne réel.

Couvre :
  1. p4_convert_step(answers=[]) rend le prompt de segmentation ("due":true),
     n'écrit rien.
  2. une fois la réponse de segmentation fournie, rend le prompt de
     bucketing ; puis celui de la conversion sémantique (par lot) — chaque
     appel REJOUE les réponses déjà connues (le seul appel manquant est
     redemandé, jamais les précédents).
  3. la dernière réponse fournie -> "due": false, la Partition est écrite sur
     disque (manifest + node), verdict VERT.
  4. zéro appel réseau : openai.OpenAI est empoisonné (lève si instancié) —
     toute la séquence tourne jusqu'au bout sans jamais l'atteindre, la
     preuve que convert_module n'a vu que le shim.
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

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


# --------------------------------------------------------- fixture ----------
S1 = "## 1. Arrivee\nVous approchez du village fabrique. Si vous entrez, allez en 2.\n\n"
S2 = "## Place du village\nUn Garde fabrique surveille le puits.\n\n"
SOURCE = S1 + S2
A, B = len(S1), len(SOURCE)

SEG_ANSWER = json.dumps({"units": [
    {"id": "u-arrivee", "structure": "S1", "start": 0, "end": A,
     "titre": "Arrivee",
     "renvois": [{"condition": "si entrez", "cible": "2"}]},
    {"id": "u-place", "structure": "S2", "start": A, "end": B,
     "titre": "Place du village"},
]})

BUCKETS_ANSWER = json.dumps({"buckets": [
    {"id": "u-arrivee", "bucket": "consulte-a-froid", "detail": []},
    {"id": "u-place", "bucket": "mixte", "detail": []},
]})

RECORD_STATS = {"THAC0": "18", "CA": "8", "HD": "1",
                "vitesse": "9 m", "degats": "1d4"}

SEMANTIC_ANSWER = json.dumps({"units": [
    {"uid": "u-arrivee",
     "nodes": [{"id": "arrivee", "type": "chapitre", "titre": "Arrivee",
               "altitude": "scenario", "corps_md": SOURCE[0:A],
               "objectif_md": "entrer dans le village fabrique",
               "liens": [{"cible_id": "place",
                          "condition_textuelle": "si entrez"}],
               "debouches": [
                   {"id": "vers-place", "cible_id": "place",
                    "condition_textuelle": "si entrez"}],
               "anchors": [[0, A]]}],
     "evenements": [{"id": "ev-arrivee", "rubrique": "trajectoire",
                     "altitude": "adventure",
                     "description_md": "le village fabrique continue sans le heros",
                     "declencheur": {"type": "etat",
                                     "valeur": "arrivee quittee"},
                     "once": True,
                     "consequences": ["la place se verrouille"],
                     "perturbations": [{
                         "condition_etat": "heros blesse avant l'entree",
                         "issue": "abandonnee"}],
                     "anchors": [[0, A]]}]},
    {"uid": "u-place",
     "nodes": [{"id": "place", "type": "section", "titre": "Place du village",
               "altitude": "scene", "corps_md": SOURCE[A:B],
               "liens": [],
               "charniere_sortie": {
                   "ouvre_vers_md": "la suite est ouverte",
                   "prerequis_etat": "etat: garde-puits neutralise"},
               "anchors": [[A, B]]}],
     "records": [{"id": "garde-puits", "classe": "creature", "nom": "Garde",
                 "ruleset": "2e", "stats_source": RECORD_STATS,
                 "anchors": [[A, B]]}]},
]})

OUT = Path(tempfile.gettempdir()) / "se_pont_mcp_conversion_p4_i173"
if OUT.exists():
    shutil.rmtree(OUT)
PARTITION_DIR = OUT / "partition"

# ---------------------------------------------- section 4 (anti-réseau) -----
section("0) openai.OpenAI empoisonné : lève si jamais instancié")
import openai


class _NetworkAttempted(AssertionError):
    pass


def _poisoned_init(self, *a, **k):
    raise _NetworkAttempted(
        "openai.OpenAI() instancié — la séquence pont-MCP a touché le réseau")


_real_init = openai.OpenAI.__init__
openai.OpenAI.__init__ = _poisoned_init

try:
    # ------------------------------------------------- section 1 ------------
    section("1) answers=[] -> due segmentation, rien d'écrit")
    out1 = mcp_server.p4_convert_step(
        SOURCE, titre="Specimen I-173", structures=["S1", "S2"],
        corpus_source="2e", target_version="2014",
        out_dir=str(PARTITION_DIR), answers=[])
    assert out1["due"] is True, out1
    assert "You segment" in out1["instruction"], out1
    assert SOURCE in out1["payload"] or SOURCE.strip() in out1["payload"]
    assert not PARTITION_DIR.exists()

    # ------------------------------------------------- section 2 ------------
    section("2) réponse segmentation fournie -> due buckets (rejoue la seg)")
    out2 = mcp_server.p4_convert_step(
        SOURCE, titre="Specimen I-173", structures=["S1", "S2"],
        corpus_source="2e", target_version="2014",
        out_dir=str(PARTITION_DIR), answers=[SEG_ANSWER])
    assert out2["due"] is True, out2
    assert "You classify" in out2["instruction"], out2
    assert "u-arrivee" in out2["payload"] and "u-place" in out2["payload"]
    assert not PARTITION_DIR.exists()

    section("2b) réponse buckets fournie -> due sémantique (par lot)")
    out2b = mcp_server.p4_convert_step(
        SOURCE, titre="Specimen I-173", structures=["S1", "S2"],
        corpus_source="2e", target_version="2014",
        out_dir=str(PARTITION_DIR),
        answers=[SEG_ANSWER, BUCKETS_ANSWER])
    assert out2b["due"] is True, out2b
    assert "SEVERAL units" in out2b["instruction"], out2b
    assert "u-arrivee" in out2b["payload"] and "u-place" in out2b["payload"]
    assert not PARTITION_DIR.exists()

    # ------------------------------------------------- section 3 ------------
    section("3) réponse sémantique fournie -> due false, Partition écrite VERT")
    out3 = mcp_server.p4_convert_step(
        SOURCE, titre="Specimen I-173", structures=["S1", "S2"],
        corpus_source="2e", target_version="2014",
        out_dir=str(PARTITION_DIR),
        answers=[SEG_ANSWER, BUCKETS_ANSWER, SEMANTIC_ANSWER])
    assert out3["due"] is False, out3
    assert out3["report"]["verdict"] == "VERT", out3["report"]
    assert out3["nodes"] == 2, out3
    assert out3["records"] == 1, out3
    assert PARTITION_DIR.exists()
    manifest = json.loads((PARTITION_DIR / "manifest.json").read_text(
        encoding="utf-8"))
    assert manifest["titre"] == "Specimen I-173", manifest
    assert (PARTITION_DIR / "nodes" / "arrivee.md").exists()
    assert (PARTITION_DIR / "records" / "garde-puits.md").exists()
finally:
    openai.OpenAI.__init__ = _real_init

print("\nALL PONT MCP CONVERSION P4 (#173) CHECKS PASSED: " + ", ".join(FAIT))
