"""I-321 (Issue #321) : le gabarit de revue adversariale (Build-RevuePrompt
dans tools/lancer-lane.ps1) doit citer le bon motif pour un refus
d'étanchéité — « dépôt public, matériau tiers hors du repo » — et non
« zéro-spoiler / D-109 ».

Contexte : PR #320 a essuyé un refus de revue au motif « zéro-spoiler /
D-109 » pour avoir cité slug/stats d'un record déjà versionné dans
`corpus-modules/` (module de test sacrificiel, D-139). Cette règle est morte
(D-256) : l'étanchéité anti-spoiler par dossiers n'existe plus, et D-109
visait le canal joueur, pas les tests du dépôt. Le vrai motif de refus est
que ce dépôt est public et que le matériau de VRAIE campagne (tiers,
commercial) ne doit jamais y apparaître, même gitignoré (CLAUDE.md du repo,
`corpus_dir()` hors repo).

Test texte pur (pas de PowerShell requis) : isole le corps de
Build-RevuePrompt dans tools/lancer-lane.ps1 et vérifie que le motif « dépôt
public / matériau tiers hors du repo » y est présent, et que « zéro-spoiler »
et « D-109 » n'y apparaissent plus comme motif d'étanchéité.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "lancer-lane.ps1"


def extract_function_body(src: str, func_name: str) -> str:
    """Extrait le corps textuel d'une fonction PowerShell `function <nom> {...}`
    du script (même bornage que lancer_lane_gabarits_test.py : entre le nom
    de la fonction et le `\n}\n` qui suit le heredoc `@"`).
    """
    start = src.index(f"function {func_name}")
    assert start >= 0, f"fonction {func_name} introuvable dans {SCRIPT}"
    rest = src[start:]
    end_marker = rest.index("\n}\n", rest.index("@\""))
    return rest[:end_marker]


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"
    src = SCRIPT.read_text(encoding="utf-8")

    revue_body = extract_function_body(src, "Build-RevuePrompt")

    assert "zéro-spoiler" not in revue_body.lower(), (
        "Build-RevuePrompt : le motif « zéro-spoiler » est mort (D-256) — "
        "il ne doit plus apparaître comme motif d'étanchéité dans le gabarit "
        "de revue (voir Issue #321)."
    )
    assert "D-109" not in revue_body, (
        "Build-RevuePrompt : D-109 visait le canal joueur, pas les tests du "
        "dépôt — ne doit plus être cité comme motif d'étanchéité (Issue #321)."
    )
    assert "dépôt public" in revue_body and "matériau tiers hors du repo" in revue_body, (
        "Build-RevuePrompt : le motif correct « dépôt public, matériau tiers "
        "hors du repo » doit être présent dans la règle d'étanchéité "
        "(Issue #321)."
    )

    print("test-gabarit-revue-motif-etancheite-i321: OK")


if __name__ == "__main__":
    main()
