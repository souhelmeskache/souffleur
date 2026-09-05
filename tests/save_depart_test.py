"""Test d'élément — `tools/banc/save-depart.py` (Issue #275/I-465, module
installé #281).

100% synthétique (D-109) : une Library jetable dans un dossier temporaire,
JAMAIS `saves/` réel, et une Partition synthétique à la main (jamais de vrai
matériau de campagne) — manifest.json + un node + un record + un
directeur.md, juste assez pour exercer `converter/install.py` (jamais
réécrit) et `converter/projection.py::derive` (jamais réécrit).

Simule la situation réelle — une save déjà installée depuis cette partition
(scénario + module.json, comme le ferait un vrai module converti) — puis
vérifie que la save de DÉPART fabriquée à partir de ce même scénario est bien
au tour 0, personnage installé, ET porte le module (`module.json`,
lieux/PNJ projetés, brief P4) plutôt que de jouer un monde vide (#281).

Verdicts mécaniques (D-134) : égalité/présence de champs sur disque, jamais
une lecture de qualité.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.memory import Library, MemoryStore  # noqa: E402
from coderain.converter.install import install  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "save_depart", ROOT / "tools" / "banc" / "save-depart.py")
save_depart = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(save_depart)

ROOT_TMP = os.path.join(tempfile.gettempdir(), "test_save_depart_i465")


def _fabriquer_partition_factice(partition_dir: Path) -> None:
    """Une Partition 100% synthétique (D-109) — juste assez pour
    `install.install`/`projection.derive` : manifest, un node (locations), un
    record (characters), un brief de direction (custom-instructions)."""
    (partition_dir / "nodes").mkdir(parents=True, exist_ok=True)
    (partition_dir / "records").mkdir(parents=True, exist_ok=True)
    manifest = {"titre": "Module Factice de Banc", "corpus_source": "2e",
                "corpus_cible": "5e", "structures": ["S1"],
                "hash_source": "abc123def456", "date_conversion": "2026-09-01",
                "version_convertisseur": "test-i281"}
    (partition_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    (partition_dir / "nodes" / "entree.md").write_text(
        '---\n{"id": "entree", "titre": "Entree du manoir", '
        '"altitude": "scene"}\n---\n'
        "Une porte de chene s'ouvre sur un hall poussiereux.\n",
        encoding="utf-8")
    (partition_dir / "records" / "garde.md").write_text(
        '---\n{"id": "garde", "nom": "Garde factice", "classe": "creature"}\n'
        '---\n{"ca": 12, "pv": 9}',
        encoding="utf-8")
    (partition_dir / "directeur.md").write_text(
        "# BRIEF DE DIRECTION — Module Factice de Banc\n\n"
        "Consigne de test 100% synthétique (D-109), Issue #281.\n",
        encoding="utf-8")


def main() -> int:
    if os.path.exists(ROOT_TMP):
        shutil.rmtree(ROOT_TMP)
    try:
        lib_root = Path(ROOT_TMP) / "lib"
        lib = Library(lib_root)
        partition_dir = Path(ROOT_TMP) / "partition-factice"
        _fabriquer_partition_factice(partition_dir)

        # --- save déjà installée depuis cette partition (simule le réel) ----
        res_install = install(partition_dir, lib_root)
        played_slug = res_install["save_slug"]
        played_dir = lib.saves.dir(played_slug)
        assert (played_dir / "module.json").exists(), \
            "install() doit poser module.json"
        # simule des tours joués (jamais 0) : la save réelle n'est jamais au
        # gabarit vierge de transcript.md.
        (played_dir / "transcript.md").write_text(
            (played_dir / "transcript.md").read_text(encoding="utf-8")
            + "\n<!--@player-->\n> On avance.\n"
              "<!--@narrator-->\nLa porte grince.\n",
            encoding="utf-8")
        played_store = MemoryStore(played_dir)
        assert len(played_store.turns()) > 0, "la save jouée doit avoir des tours"

        # --- 1. fabrication de la save de départ depuis ce scénario ---------
        depart_slug = "banc-depart-le-manoir-factice"
        res = save_depart.fabriquer(depart_slug, from_save=played_slug,
                                    root=lib_root)
        assert res["status"] == "created", res
        depart_dir = Path(res["save_dir"])
        assert depart_dir.exists(), depart_dir
        print("1/8 fabrication depuis une save jouée existante : ok")

        # --- 2. tour 0, jamais celui de la save jouée -----------------------
        depart_store = MemoryStore(depart_dir)
        assert len(depart_store.turns()) == 0, depart_store.turns()
        print("2/8 save de départ au tour 0 : ok")

        # --- 3. personnage installé (fixture #257) --------------------------
        rpg = depart_store.rpg_state()
        assert rpg["player"]["stats"]["strength"] == 3, rpg["player"]["stats"]
        assert rpg["inventory"], "inventaire vide — fixture non appliquée"
        print("3/8 fixture personnage appliquée (arme + armure) : ok")

        # --- 4. module installé (#281) : module.json, lieux, PNJ, brief -----
        module_ptr = json.loads((depart_dir / "module.json").read_text(
            encoding="utf-8"))
        assert Path(module_ptr["partition"]).resolve() == partition_dir.resolve(), module_ptr
        assert module_ptr["titre"] == "Module Factice de Banc", module_ptr
        assert len(depart_store.entries("locations.md")) >= 1, \
            "locations.md doit porter le node de la partition"
        assert len(depart_store.entries("characters.md")) >= 1, \
            "characters.md doit porter le record de la partition"
        ci = (depart_dir / "custom-instructions.md").read_text(encoding="utf-8")
        assert "P4-BRIEF-START" in ci, "brief de direction P4 absent"
        print("4/8 module installé : module.json + lieux + PNJ + brief P4 : ok")

        # --- 5. refus d'écraser sans --force --------------------------------
        res2 = save_depart.fabriquer(depart_slug, from_save=played_slug,
                                     root=lib_root)
        assert res2["status"] == "refused", res2
        assert "existe déjà" in res2["message"], res2
        print("5/8 refus d'écraser sans --force : ok")

        # --- 6. --force reconstruit à neuf, module toujours présent ---------
        res3 = save_depart.fabriquer(depart_slug, from_save=played_slug,
                                     root=lib_root, force=True)
        assert res3["status"] == "created", res3
        assert (Path(res3["save_dir"]) / "module.json").exists()
        print("6/8 --force reconstruit à neuf, module réinstallé : ok")

        # --- 7. verifier() détecte une save NON au tour 0 -------------------
        v = save_depart.verifier(played_dir)
        assert v["status"] == "refused", v
        print("7/8 verifier() refuse une save non fraîche (tour > 0) : ok")

        # --- 8. REFUS nommé : from_save SANS module (monde vide, #281) ------
        scen_nu = lib.scenarios.create(
            "Scenario nu", premise="Aucune partition associée — D-109.")
        from coderain import templates
        nu_slug = "save-nue-sans-module"
        nu_dir = lib.saves.dir(nu_slug)
        templates.new_save(nu_dir, lib.scenarios.dir(scen_nu), nu_slug,
                           scen_nu, rpg_enabled=True, mode="rpg",
                           instructions_dir=lib.instructions_dir)
        assert not (nu_dir / "module.json").exists()
        res_nu = save_depart.fabriquer("banc-depart-nu", from_save=nu_slug,
                                       root=lib_root)
        assert res_nu["status"] == "refused", res_nu
        assert "module" in res_nu["message"].lower(), res_nu
        assert not (lib.saves.dir("banc-depart-nu")).exists(), \
            "aucune save ne doit être laissée sur REFUS"
        print("8/8 REFUS nommé si from-save n'a pas de module (monde vide) : ok")

        print("\nALL SAVE_DEPART TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(ROOT_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
