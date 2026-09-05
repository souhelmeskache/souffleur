"""Issue #287 : preuve sur `nuit.sh` RÉEL (pas seulement le mécanisme unitaire
de `tests/turn_dir_etancheite_test.py`) — `-Parties 2 -Paires 2` fait tourner
deux paires Director/joueur SIMULTANÉES (#282), chacune sa propre save sous
`partie-NN/save/` ; ce test vérifie qu'écrire dans `.turn/` DEPUIS ce chemin
réel (celui que `nuit.sh` construit et transmet à `lancer-banc-fumee.ps1` via
`-SavesDirOverride "$partie_dir"` / `-Save save`) atterrit bien sous
`partie-NN/save/.turn/`, jamais un dossier partagé — et que les deux parties
ne se croisent pas.

`-LancementCmd` (interne, #263, même convention que `nuit_paires_reel_test.py`)
simule un lancement réussi : au lieu d'invoquer un vrai agent, il appelle
`tools/banc/nuit.sh`'s propres variables locales `$save_dest`/`$pnn` (visibles
dans le sous-shell `eval`, même mécanisme que les tests voisins) pour lancer
un script Python DÉDIÉ (`_write_context.py`, écrit une fois par ce test) qui
charge la save réelle de la partie et appelle `assemble_context_to_file` avec
un marqueur propre à cette partie — le chemin exact qu'un vrai Director
emprunterait en tour 1. `$save_dest` est passé en ARGUMENT à `python.exe`
(traduit sans danger par Git Bash/MSYS, voir `tools/banc/README.md` §
« Frontière bash ⊥ Windows ») — jamais interpolé en littéral dans un bloc
Python, seul cas piégeux documenté.

Tours=1 (comme `nuit_paires_reel_test.py`) : la boucle de tours au-delà du
premier dépend de vrais agents (`herdr agent prompt`) que ce harnais ne fait
pas — hors périmètre de CE test, dont la preuve porte sur l'étanchéité de
`.turn/`, indépendante du nombre de tours joués."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from coderain.memory import Library  # noqa: E402

NUIT_SH = REPO_ROOT / "tools" / "banc" / "nuit.sh"

WRITE_CONTEXT_PY = f"""\
import sys
sys.path.insert(0, {str(REPO_ROOT)!r})
import mcp_server
from coderain.memory import MemoryStore

save_dest, marqueur = sys.argv[1], sys.argv[2]
store = MemoryStore(save_dest)
# Marqueur propre à CETTE partie, écrit dans world-bible.md (servi tel quel
# par assemble_context_to_file -- le player_action seul n'y figure pas
# verbatim, vérifié en 1re version de ce test).
store.write("world-bible.md", f"# World\\n\\nMarqueur {{marqueur}}.\\n")
mcp_server._store = store
mcp_server._engine = None
mcp_server.assemble_context_to_file("Action de test.")
"""


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-paires-turn-etancheite-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Paires Turn Etancheite Test", mode="rpg",
            premise="Save 100% synthétique — Issue #287, jamais de matériau réel.",
        )
        assert slug, "création de la save synthétique a échoué"
        # #281 : nuit.sh REFUSE désormais une save sans module installé
        # (garde monde vide, à côté de la garde tour 0) — module.json +
        # locations.md non vide, 100% synthétique (D-109).
        (lib.saves.dir(slug) / "module.json").write_text(
            '{"partition": "/dev/null/partition-factice", '
            '"titre": "Module factice de test"}', encoding="utf-8")
        (lib.saves.dir(slug) / "locations.md").write_text(
            (lib.saves.dir(slug) / "locations.md").read_text(encoding="utf-8")
            + "\n## Lieu factice  {#lieu-factice}\nimportance: 3\n\n"
              "Un lieu 100% synthétique.\n",
            encoding="utf-8")

        run_dir = tmp / "run"

        write_context_py = tmp / "_write_context.py"
        write_context_py.write_text(WRITE_CONTEXT_PY, encoding="utf-8")

        lancement_cmd = (
            f'python "{write_context_py}" "$save_dest" "PARTIE-$pnn"; '
            'printf \'# tour 01\\n\\n## Prose du Narrateur (verbatim)\\n\\n'
            'Prose de test synthetique.\\n\' > "$partie_dir/tour-01.md"; '
            'exit 0'
        )

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "NUIT_CONSERVER_SAVES_DIR": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "2", "-Paires", "2", "-Tours", "1",
             "-Save", slug, "-RunDir", str(run_dir), "-LancementCmd", lancement_cmd],
            capture_output=True, text=True, timeout=180, env=env,
        )
        assert p.returncode == 0, (
            f"attendu code 0 (2 paires, 2 parties, aucun craquement), reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -Paires 2 -Parties 2 -Tours 1 (agents réels simulés, "
              "écriture .turn/ réelle) : sortie 0")

        assert "AVERTISSEMENT" not in p.stderr and "Limite connue" not in p.stderr, (
            "Issue #287 : l'avertissement -Paires/.turn partagé doit avoir disparu -- "
            f"stderr={p.stderr}"
        )
        print("2) plus d'avertissement stderr sur -Paires/.turn (retiré, #287)")

        turns = []
        for pnn in ("01", "02"):
            partie_dir = run_dir / f"partie-{pnn}"
            save_dest = partie_dir / "save"
            turn_file = save_dest / ".turn" / "context.md"
            assert turn_file.exists(), (
                f".turn/context.md absent sous la save RÉELLE de la partie {pnn} "
                f"({turn_file}) -- .turn/ ne dérive plus de la save chargée ?"
            )
            texte = turn_file.read_text(encoding="utf-8")
            turns.append((pnn, turn_file, texte))
        print("3) .turn/context.md écrit sous partie-01/save/ ET partie-02/save/ "
              "(jamais un dossier partagé)")

        (pnn1, path1, texte1), (pnn2, path2, texte2) = turns
        assert path1 != path2, "les deux .turn/context.md doivent être deux fichiers distincts"
        assert f"PARTIE-{pnn1}" in texte1 and f"PARTIE-{pnn2}" not in texte1, texte1
        assert f"PARTIE-{pnn2}" in texte2 and f"PARTIE-{pnn1}" not in texte2, texte2
        print("4) étanchéité vérifiée : chaque .turn/context.md ne porte QUE le "
              "marqueur de SA propre partie -- aucun croisement")

        print("\nALL NUIT_PAIRES_TURN_ETANCHEITE TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
