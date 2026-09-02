"""Issue #267 : tools/banc/verifier-liste-blanche-nuit.sh -- garde extraite
de verifier-avant-nuit.sh, sur les mêmes trois cas que
tests/liste_blanche_banc_test.py (absent, partiel, complet), + JSON invalide.

1. Fichier absent : OK, code 0 (le lanceur le posera complet).
2. Fichier partiel (les cinq entrées MCP historiques de la nuit N0, aucun
   Bash(*), aucun mcp__coderain-engine__*) : REFUS, code non nul, message
   citant les entrées manquantes.
3. Fichier complet (gabarit posé) : OK, code 0.
4. JSON invalide : REFUS, code non nul, message dédié.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "banc" / "verifier-liste-blanche-nuit.sh"

CINQ_ENTREES_HISTORIQUES = [
    "mcp__coderain-engine__load_save",
    "mcp__coderain-engine__get_world_state",
    "mcp__coderain-engine__ui_open",
    "mcp__coderain-engine__ui_panel",
    "mcp__coderain-engine__ui_sheet",
]


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def lancer(settings_path: Path):
    return subprocess.run(
        [BASH, str(SCRIPT), str(settings_path)],
        capture_output=True, timeout=60, encoding="utf-8", errors="replace",
    )


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"

    tmp_root = Path(tempfile.mkdtemp(prefix="verifier-liste-blanche-nuit-test-"))
    try:
        # --------------------------------------------------------------
        # Cas 1 : fichier absent -> OK
        # --------------------------------------------------------------
        settings1 = tmp_root / "absent" / "settings.local.json"
        p1 = lancer(settings1)
        assert p1.returncode == 0, f"cas 1 : code attendu 0, reçu {p1.returncode}\nstdout={p1.stdout}\nstderr={p1.stderr}"
        print("PASS: cas 1 -- fichier absent, OK")

        # --------------------------------------------------------------
        # Cas 2 : fichier partiel (cinq entrées historiques) -> REFUS
        # --------------------------------------------------------------
        settings2 = tmp_root / "partiel" / "settings.local.json"
        settings2.parent.mkdir(parents=True)
        contenu_partiel = {"permissions": {"allow": list(CINQ_ENTREES_HISTORIQUES), "deny": []}}
        settings2.write_text(json.dumps(contenu_partiel, ensure_ascii=False), encoding="utf-8")

        p2 = lancer(settings2)
        assert p2.returncode != 0, f"cas 2 : code non nul attendu, reçu {p2.returncode}\nstdout={p2.stdout}\nstderr={p2.stderr}"
        assert "Bash(*)" in p2.stderr, f"cas 2 : message REFUS ne cite pas Bash(*) manquant ({p2.stderr})"
        assert "mcp__coderain-engine__*" in p2.stderr, (
            f"cas 2 : message REFUS ne cite pas mcp__coderain-engine__* manquant ({p2.stderr})"
        )
        print("PASS: cas 2 -- fichier partiel, REFUS avec entrées manquantes citées")

        # --------------------------------------------------------------
        # Cas 3 : fichier complet -> OK
        # --------------------------------------------------------------
        settings3 = tmp_root / "complet" / "settings.local.json"
        settings3.parent.mkdir(parents=True)
        contenu_complet = {
            "permissions": {
                "allow": ["Bash(*)", "mcp__coderain-engine__*"],
                "deny": [
                    "Bash(git commit --no-verify*)",
                    "Bash(git commit -n*)",
                    "Bash(git push --no-verify*)",
                    "Bash(git push --force*)",
                    "Bash(git push -f*)",
                ],
            }
        }
        settings3.write_text(json.dumps(contenu_complet, ensure_ascii=False), encoding="utf-8")

        p3 = lancer(settings3)
        assert p3.returncode == 0, f"cas 3 : code attendu 0, reçu {p3.returncode}\nstdout={p3.stdout}\nstderr={p3.stderr}"
        print("PASS: cas 3 -- fichier complet, OK")

        # --------------------------------------------------------------
        # Cas 4 : JSON invalide -> REFUS dédié
        # --------------------------------------------------------------
        settings4 = tmp_root / "invalide" / "settings.local.json"
        settings4.parent.mkdir(parents=True)
        settings4.write_text("{ceci n'est pas du JSON valide", encoding="utf-8")

        p4 = lancer(settings4)
        assert p4.returncode != 0, f"cas 4 : code non nul attendu, reçu {p4.returncode}\nstdout={p4.stdout}\nstderr={p4.stderr}"
        assert "JSON valide" in p4.stderr, f"cas 4 : message REFUS ne mentionne pas le JSON invalide ({p4.stderr})"
        print("PASS: cas 4 -- JSON invalide, REFUS dédié")

        print("verifier_liste_blanche_nuit_test: 4/4 OK")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
