"""CI job integration: bout-en-bout OFFLINE sur la fixture synthétique.

Chaîne éprouvée : segmenter (route S1 déterministe, zéro LLM et zéro secret)
-> émettre la partition -> vérifier verdict, couverture exacte, comptages.
La fixture est 100% fabriquée : le module source réel vit hors dépôt et n'est
pas licencié pour redistribution.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from coderain.converter.cli import cmd_convert            # noqa: E402
from coderain.converter.emit import read_manifest          # noqa: E402
from coderain.converter import validate_fidelity           # noqa: E402
from coderain.converter.s1_local import segment_s1         # noqa: E402


def main() -> int:
    src = ROOT / "tests" / "fixtures" / "module-fixture-s1.txt"
    text = src.read_text(encoding="utf-8")
    out = Path(tempfile.mkdtemp(prefix="ci_boutenbout_"))
    try:
        # 1) conversion complete hors-ligne (route S1, llm=None)
        res = cmd_convert(src, out, titre="Fixture CI", mode="s1", llm=None)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if res["verdict"] != "VERT":
            print(f"ECHEC: verdict attendu VERT, obtenu {res['verdict']}")
            return 1

        # 2) manifest: hash de la source consigne
        manifest = read_manifest(out)
        attendu = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if manifest.get("hash_source") != attendu:
            print("ECHEC: hash_source du manifest ne correspond pas a la fixture")
            return 1

        # 3) comptages via le miroir machine (index.json)
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        if len(index["nodes"]) != 4:
            print(f"ECHEC: 4 nodes attendus, obtenu {len(index['nodes'])}")
            return 1
        fichiers_nodes = len(list((out / "nodes").glob("*.md")))
        if fichiers_nodes != 4:
            print(f"ECHEC: 4 fichiers nodes attendus, obtenu {fichiers_nodes}")
            return 1

        # 4) renvois convertis en liens types
        liens = 0
        for f in (out / "nodes").glob("*.md"):
            liens += f.read_text(encoding="utf-8").count('"cible_id"')
        if liens < 4:
            print(f"ECHEC: au moins 4 liens attendus, obtenu {liens}")
            return 1

        # 5) couverture exacte de la source par la segmentation
        couv = validate_fidelity.coverage_report(
            segment_s1(text), [], len(text))
        if couv["gaps"] or couv["overlaps"]:
            print(f"ECHEC: couverture non exacte: {couv}")
            return 1

        print(f"OK bout-en-bout hors-ligne: 4 nodes, {liens} liens, "
              f"verdict {res['verdict']}")
        return 0
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
