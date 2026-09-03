"""Issue #276 (cadrage complémentaire, 03/09) : D-232 interdit le force-push
partout, mais `Bash(git push --force*)`/`Bash(git push -f*)` ne vivaient que
dans `.claude/settings.local.json` (non versionné, propriété de
l'opérateur) — les ajoute au bloc `deny` du fichier VERSIONNÉ
`.claude/settings.json`, sans toucher au bloc `allow`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"


def main() -> int:
    assert SETTINGS_PATH.exists(), f"fichier absent : {SETTINGS_PATH}"
    donnees = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    deny = donnees.get("permissions", {}).get("deny", [])

    for regle in ("Bash(git push --force*)", "Bash(git push -f*)"):
        assert regle in deny, f"règle deny absente de {SETTINGS_PATH} : {regle}\ndeny actuel : {deny}"
    print("1) Bash(git push --force*) et Bash(git push -f*) présentes dans le deny versionné")

    # Règles déjà existantes (pré-#276) : jamais retirées par cet ajout.
    for regle in ("Bash(git commit --no-verify*)", "Bash(git commit -n*)",
                  "Bash(git push --no-verify*)"):
        assert regle in deny, f"règle deny pré-existante disparue : {regle}"
    print("2) règles deny pré-existantes (--no-verify) toujours présentes")

    allow = donnees.get("permissions", {}).get("allow", [])
    assert "Bash(git push *)" in allow, (
        "le bloc allow ne doit pas avoir été touché par cet ajout"
    )
    print("3) bloc allow inchangé (Bash(git push *) toujours présent)")

    print("\nALL SETTINGS_DENY_FORCE_PUSH TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
