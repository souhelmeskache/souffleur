"""Issue #306 : tools/banc/detecter_fin.py — détection MÉCANIQUE de fin de
partie (mort du joueur OU nœud terminal de la partition), sur des fixtures
100% synthétiques (D-109) : jamais de matériau de campagne réel, un
`module.json`/`nodes/*.md` fabriqués pour ce test seul."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "detecter_fin", REPO_ROOT / "tools" / "banc" / "detecter_fin.py")
detecter_fin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detecter_fin)


def _ecrire_node(partition_dir: Path, node_id: str, meta: dict) -> None:
    (partition_dir / "nodes").mkdir(parents=True, exist_ok=True)
    front = json.dumps(meta, ensure_ascii=False)
    (partition_dir / "nodes" / f"{node_id}.md").write_text(
        f"---\n{front}\n---\n\nCorps factice de {node_id}.\n", encoding="utf-8")


def _ecrire_save(save_dir: Path, partition_dir: Path, location: str,
                  dead: bool = False) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir), "titre": "Module factice"}),
        encoding="utf-8")
    state = {"player": {"location": location}}
    if dead:
        state["rpg"] = {"player": {"conditions": ["dead"]}}
    (save_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="detecter-fin-test-"))
    try:
        partition_dir = tmp / "partition"
        # para-12 : nœud NON terminal (des liens sortants) -> "non".
        _ecrire_node(partition_dir, "para-12", {
            "id": "para-12", "type": "scene", "titre": "Scène factice",
            "liens": [{"cible_id": "para-13", "condition_textuelle": ""}],
        })
        # para-60 : nœud TERMINAL (liens: [] + charniere_sortie) -> "fin_module".
        _ecrire_node(partition_dir, "para-60", {
            "id": "para-60", "type": "scene", "titre": "Scène finale factice",
            "liens": [],
            "charniere_sortie": {
                "ouvre_vers_md": "La résolution factice laisse le héros sortir.",
                "prerequis_etat": "etat: node para-60 atteint",
            },
        })
        # avant-propos : liens: [] SANS lien ni charnière -- jamais une fin,
        # même id exclu nommément (D-123).
        _ecrire_node(partition_dir, "avant-propos", {
            "id": "avant-propos", "type": "scene", "titre": "Entrée factice",
            "liens": [],
        })

        # --- 1. save positionnée sur para-60 -> fin_module -----------------
        save_60 = tmp / "save-60"
        _ecrire_save(save_60, partition_dir, "para-60")
        r = detecter_fin.evaluer(save_60)
        assert r == {"fin": "fin_module", "noeud": "para-60"}, r
        print("1) save sur para-60 (liens:[] + charniere_sortie) -> fin_module")

        # --- 2. save positionnée sur para-12 -> non ------------------------
        save_12 = tmp / "save-12"
        _ecrire_save(save_12, partition_dir, "para-12")
        r = detecter_fin.evaluer(save_12)
        assert r == {"fin": "non", "noeud": "para-12"}, r
        print("2) save sur para-12 (des liens sortants) -> non")

        # --- 3. joueur mort -> mort, quel que soit le nœud -----------------
        save_mort = tmp / "save-mort"
        _ecrire_save(save_mort, partition_dir, "para-12", dead=True)
        r = detecter_fin.evaluer(save_mort)
        assert r == {"fin": "mort", "noeud": "para-12"}, r
        print("3) rpg.player.conditions contient 'dead' -> mort (noeud reporté quand même)")

        # --- 4. avant-propos avec liens:[] mais SANS charnière -> non -----
        save_ap = tmp / "save-avant-propos"
        _ecrire_save(save_ap, partition_dir, "avant-propos")
        r = detecter_fin.evaluer(save_ap)
        assert r == {"fin": "non", "noeud": "avant-propos"}, r
        print("4) avant-propos (liens:[] mais id exclu, D-123) -> non")

        # --- 5. save sans position lisible -> non, noeud None -------------
        save_vide = tmp / "save-vide"
        save_vide.mkdir()
        (save_vide / "state.json").write_text("{}", encoding="utf-8")
        r = detecter_fin.evaluer(save_vide)
        assert r == {"fin": "non", "noeud": None}, r
        print("5) save sans position lisible -> non, noeud None")

        # --- 6. CLI : deux lignes en forme fixe ----------------------------
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "banc" / "detecter_fin.py"),
             str(save_60)],
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "fin: fin_module" in proc.stdout, proc.stdout
        assert "noeud: para-60" in proc.stdout, proc.stdout
        print("6) CLI : sortie 0, 'fin: fin_module' / 'noeud: para-60'")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL DETECTER_FIN TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
