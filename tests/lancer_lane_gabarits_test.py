"""I-244 (Issue #244) : les deux gabarits de prompt de tools/lancer-lane.ps1
(Build-LanePrompt et Build-RevuePrompt) doivent tous deux porter :

- la règle fixe « appels shell simples » (zéro boucle d'attente, zéro
  substitution de commande, un appel = une commande simple, tests lancés en
  avant-plan et attendus) — chaque boucle d'attente shell a bloqué une lane
  sur invite de permission (9 blocages le 02/09, dont 7 sur la seule
  lane #235) ;
- la règle « BLOQUÉ : systématique » — sur invite de permission, outil
  refusé, test qui ne passe pas en trois essais, ou ambiguïté de l'Issue/PR,
  l'agent poste ``BLOQUÉ : <cause>`` et s'arrête, sans attendre en silence ni
  contourner.

Test texte pur (pas de PowerShell requis) : lit tools/lancer-lane.ps1, isole
le corps de chaque fonction Build-*Prompt, et vérifie la présence de chaînes
fixes dans chacun — pour qu'un futur remaniement des gabarits ne les perde
pas silencieusement.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "lancer-lane.ps1"

# Chaînes fixes attendues dans CHAQUE gabarit (lane ET revue).
REGLE_SHELL_SIMPLE = [
    "appels shell simples",
    "boucle d'attente",
    "substitution de commande",
    "avant-plan",
]
REGLE_BLOQUE_SYSTEMATIQUE = [
    "BLOQUÉ : systématique",
    "invite de permission",
    "outil t'est refusé",
    "ARRÊTE-TOI",
]


def extract_function_body(src: str, func_name: str) -> str:
    """Extrait le corps textuel d'une fonction PowerShell `function <nom> {...}`
    du script, en comptant les accolades (le corps porte lui-même des
    heredocs avec des accolades dans du texte français, donc une simple
    recherche de la première `}` fermante ne suffit pas — mais ici les
    gabarits ne contiennent pas d'accolades PowerShell imbriquées non plus ;
    on borne simplement entre deux marqueurs de fonction connus du script.
    """
    start = src.index(f"function {func_name}")
    assert start >= 0, f"fonction {func_name} introuvable dans {SCRIPT}"
    rest = src[start:]
    end_marker = rest.index("\n}\n", rest.index("@\""))
    return rest[:end_marker]


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"
    src = SCRIPT.read_text(encoding="utf-8")

    lane_body = extract_function_body(src, "Build-LanePrompt")
    revue_body = extract_function_body(src, "Build-RevuePrompt")

    for label, body in [("Build-LanePrompt", lane_body), ("Build-RevuePrompt", revue_body)]:
        for needle in REGLE_SHELL_SIMPLE:
            assert needle in body, (
                f"{label} : règle « appels shell simples » incomplète — "
                f"chaîne absente : {needle!r}"
            )
        for needle in REGLE_BLOQUE_SYSTEMATIQUE:
            assert needle in body, (
                f"{label} : règle « BLOQUÉ : systématique » incomplète — "
                f"chaîne absente : {needle!r}"
            )
        print(f"PASS: {label} porte les deux règles")

    print("lancer_lane_gabarits_test: 2/2 OK")


if __name__ == "__main__":
    main()
