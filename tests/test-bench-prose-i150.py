"""I-150 tension plafond (D-076) vs prose (D-079) : cadrage + protocole de bench.
100% hors-ligne (D-109 garde, zero appel modele, zero reseau) :
  1. Le cadrage documente le poste narrateur, la tension D-076/D-079 et son
     perimetre (ce qui est livre vs ce qui reste vault/meta)
  2. Le bench documente un protocole a cout quasi nul (echantillon resserre,
     modeles compares, mesure) sans executer aucun appel
  3. Le bench ne contient aucun materiau de campagne reel (garde D-109)
  4. Le tableau de resultats existe, meme vide (structure prete a remplir)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CADRAGE = ROOT / "docs" / "cadrage-puissance-i150.md"
BENCH = ROOT / "bench" / "bench-prose-i150.md"

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


assert CADRAGE.exists(), f"cadrage introuvable : {CADRAGE}"
assert BENCH.exists(), f"bench introuvable : {BENCH}"

cadrage = CADRAGE.read_text(encoding="utf-8")
bench = BENCH.read_text(encoding="utf-8")

# 1 -- Le cadrage documente le poste narrateur et la tension D-076/D-079 ---
section("cadrage : poste narrateur + tension D-076/D-079 + perimetre")

for motif in (r"D-076", r"D-079", r"poste\s+narrateur", r"Writer"):
    assert re.search(motif, cadrage), \
        f"cadrage : motif {motif!r} introuvable"

# le cadrage doit explicitement borner ce qu'il livre vs ce qu'il ne tranche pas
assert re.search(r"non\s+livr[eé]", cadrage, re.IGNORECASE), \
    "cadrage : perimetre 'non livre ici' absent (doit borner l'arbitrage vault)"
assert re.search(r"co[uû]t\s+quasi\s+nul", cadrage, re.IGNORECASE), \
    "cadrage : notion de cout quasi nul absente"

# 2 -- Le bench documente un protocole a cout quasi nul, sans l'executer ---
section("bench : protocole a cout quasi nul, non execute")

for motif in (r"[Pp]rotocole", r"co[uû]t\s+quasi\s+nul", r"WRITER_RULES",
              r"frontier|frontière|frontiere"):
    assert re.search(motif, bench), f"bench : motif {motif!r} introuvable"

assert re.search(r"NON\s+FAITE|non\s+ex[eé]cut[eé]", bench, re.IGNORECASE), \
    "bench : le statut doit dire explicitement que l'execution n'a pas eu lieu"

# au moins 3 prompts synthetiques (echantillon resserre du protocole)
prompts_section = re.search(r"## Prompts.*?(?=\n## |\Z)", bench, re.DOTALL)
assert prompts_section, "bench : section Prompts introuvable"
n_prompts = len(re.findall(r"^\d+\.\s+\*\*", prompts_section.group(0), re.MULTILINE))
assert n_prompts >= 3, f"bench : attendu >= 3 prompts, trouve {n_prompts}"

# 3 -- Garde D-109 : zero materiau de campagne reel -------------------------
section("bench : garde D-109 (zero materiau de campagne)")

assert re.search(r"D-109", bench), "bench : reference a la garde D-109 absente"
assert re.search(r"synth[eé]tique", bench, re.IGNORECASE), \
    "bench : mention explicite du caractere synthetique des prompts absente"

# 4 -- Tableau de resultats present, structure prete (vide ou rempli) ------
section("bench : tableau de resultats present")

table = re.search(r"\|.*mod[eè]le r[eé]f[eé]rence.*\|", bench, re.IGNORECASE)
assert table, "bench : en-tete du tableau de resultats introuvable"
lignes_tableau = re.findall(r"^\|\s*\d+\s*\|", bench, re.MULTILINE)
assert len(lignes_tableau) >= 3, \
    f"bench : attendu >= 3 lignes de resultats (memes 3 prompts), trouve {len(lignes_tableau)}"

print(f"\nOK -- {len(FAIT)} sections verifiees : {', '.join(FAIT)}")
sys.exit(0)
