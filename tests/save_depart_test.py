"""Test d'élément — `tools/banc/save-depart.py` (Issue #275, I-465).

100% synthétique (D-109) : une Library jetable dans un dossier temporaire,
JAMAIS `saves/` réel. Simule la situation réelle — une save JOUÉE existante
(scénario enregistré, quelques tours écrits dans transcript.md) — puis
vérifie que la save de DÉPART fabriquée à partir de ce même scénario est
bien au tour 0, personnage installé, jamais un recopiage de la save jouée.

Verdicts mécaniques (D-134) : égalité/présence de champs sur disque, jamais
une lecture de qualité.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.memory import Library, MemoryStore  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "save_depart", ROOT / "tools" / "banc" / "save-depart.py")
save_depart = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(save_depart)

ROOT_TMP = os.path.join(tempfile.gettempdir(), "test_save_depart_i465")


def main() -> int:
    if os.path.exists(ROOT_TMP):
        shutil.rmtree(ROOT_TMP)
    try:
        lib_root = Path(ROOT_TMP) / "lib"
        lib = Library(lib_root)

        # --- scénario + save JOUÉE (quelques tours) — simule le réel --------
        scen_slug = lib.scenarios.create(
            "Module factice de banc", premise="Une aile oubliée d'un manoir.",
            description="Scénario 100% synthétique — Issue #275, D-109.")
        played_slug = "beyond-le-manoir-factice"
        played_dir = lib.saves.dir(played_slug)
        from coderain import templates
        templates.new_save(played_dir, lib.scenarios.dir(scen_slug),
                           played_slug, scen_slug, rpg_enabled=True,
                           mode="rpg", instructions_dir=lib.instructions_dir)
        played_store = MemoryStore(played_dir, lib.instructions_dir,
                                   lib.scenarios.dir(scen_slug))
        played_store.append_event_log({"turn": 0, "env": {}})
        # simule des tours joués (jamais 0) : la save réelle n'est jamais au
        # gabarit vierge de transcript.md.
        (played_dir / "transcript.md").write_text(
            (played_dir / "transcript.md").read_text(encoding="utf-8")
            + "\n<!--@player-->\n> On avance.\n"
              "<!--@narrator-->\nLa porte grince.\n",
            encoding="utf-8")
        assert len(played_store.turns()) > 0, "la save jouée doit avoir des tours"

        # --- 1. fabrication de la save de départ depuis ce scénario ---------
        depart_slug = "banc-depart-le-manoir-factice"
        res = save_depart.fabriquer(depart_slug, from_save=played_slug,
                                    root=lib_root)
        assert res["status"] == "created", res
        depart_dir = Path(res["save_dir"])
        assert depart_dir.exists(), depart_dir
        print("1/5 fabrication depuis une save jouée existante : ok")

        # --- 2. tour 0, jamais celui de la save jouée -----------------------
        depart_store = MemoryStore(depart_dir, lib.instructions_dir,
                                   lib.scenarios.dir(scen_slug))
        assert len(depart_store.turns()) == 0, depart_store.turns()
        print("2/5 save de départ au tour 0 : ok")

        # --- 3. personnage installé (fixture #257) --------------------------
        rpg = depart_store.rpg_state()
        assert rpg["player"]["stats"]["strength"] == 3, rpg["player"]["stats"]
        assert rpg["inventory"], "inventaire vide — fixture non appliquée"
        print("3/5 fixture personnage appliquée (arme + armure) : ok")

        # --- 4. refus d'écraser sans --force --------------------------------
        res2 = save_depart.fabriquer(depart_slug, from_save=played_slug,
                                     root=lib_root)
        assert res2["status"] == "refused", res2
        assert "existe déjà" in res2["message"], res2
        print("4/5 refus d'écraser sans --force : ok")

        # --- 5. --force reconstruit à neuf ----------------------------------
        res3 = save_depart.fabriquer(depart_slug, from_save=played_slug,
                                     root=lib_root, force=True)
        assert res3["status"] == "created", res3
        print("5/5 --force reconstruit à neuf : ok")

        # --- 6. verifier() détecte une save NON au tour 0 -------------------
        v = save_depart.verifier(played_dir)
        assert v["status"] == "refused", v
        print("6/6 verifier() refuse une save non fraîche (tour > 0) : ok")

        print("\nALL SAVE_DEPART TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(ROOT_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
