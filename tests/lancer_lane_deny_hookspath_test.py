"""Issue #335 : les règles `deny` posées par `tools/lancer-lane.ps1` (et
répliquées dans `.claude/settings.json`) couvraient déjà `--no-verify`,
`--force`, `-f` — pas `git config core.hooksPath`, ni `git -c
core.hooksPath=`, ni les variables `GIT_CONFIG_*`. Contourner un hook par sa
configuration est le même geste que `--no-verify` (lane-324, 06/09, prompt
« commit it with core.hooksPath temporarily unset » rédigé mais non exécuté).

Ce test est statique (pas de PowerShell requis) : il vérifie par recherche
textuelle que les nouvelles règles apparaissent dans les DEUX blocs `deny`
générés par `tools/lancer-lane.ps1` (mode -Issue et mode -Revue) ainsi que
dans le `deny` versionné de `.claude/settings.json` — même trio que
`tests/settings_deny_force_push_test.py` pour `--force`/`-f`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "lancer-lane.ps1"
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"

NOUVELLES_REGLES = (
    "Bash(git config * core.hooksPath*)",
    "Bash(git -c core.hooksPath*)",
    "Bash(git -c *hooksPath*)",
    "Bash(export GIT_CONFIG_*)",
    "Bash(GIT_CONFIG_*=*)",
)


def main() -> int:
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"
    assert SETTINGS_PATH.exists(), f"fichier absent : {SETTINGS_PATH}"

    src = SCRIPT.read_text(encoding="utf-8")
    # Les deux blocs deny du script (mode -Revue puis mode -Issue) doivent
    # chacun porter les nouvelles règles — recherche textuelle simple, comme
    # les autres tests statiques sur ce script (pas de parsing PowerShell).
    occurrences = {regle: src.count(f"'{regle}'") for regle in NOUVELLES_REGLES}
    for regle, n in occurrences.items():
        assert n >= 2, (
            f"règle absente d'au moins un des deux blocs deny de {SCRIPT} : "
            f"{regle} (trouvée {n} fois, attendu >= 2)"
        )
    print("1) les 5 nouvelles règles hooksPath/GIT_CONFIG_* sont présentes dans les 2 blocs deny du script")

    # Règles pré-existantes (#276) toujours là dans les deux blocs, non
    # écrasées par cet ajout.
    for regle in ("Bash(git commit --no-verify*)", "Bash(git commit -n*)",
                  "Bash(git push --no-verify*)", "Bash(git push --force*)",
                  "Bash(git push -f*)"):
        n = src.count(f"'{regle}'")
        assert n >= 2, f"règle deny pré-existante disparue d'un bloc : {regle} (trouvée {n} fois)"
    print("2) règles deny pré-existantes toujours présentes dans les 2 blocs")

    donnees = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    deny = donnees.get("permissions", {}).get("deny", [])
    for regle in NOUVELLES_REGLES:
        assert regle in deny, f"règle deny absente de {SETTINGS_PATH} : {regle}\ndeny actuel : {deny}"
    print("3) les 5 nouvelles règles sont présentes dans le deny versionné .claude/settings.json")

    print("\nALL LANCER_LANE_DENY_HOOKSPATH TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
