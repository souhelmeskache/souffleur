"""I-056 doigte-verrou-central : 4 sous-sujets + D-089 recoupe + I-023 ancre + D-109 garde.
4 sections :
  1. Les 4 sous-sujets sont presents dans la doc
  2. D-089 trois regimes de jet recoupe comme exemple local
  3. I-023 ancrage transverse verifie
  4. D-109 zero materiau de campagne (garde)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "doigte-verrou-central.md"

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


assert DOC.exists(), f"doc introuvable : {DOC}"
texte = DOC.read_text(encoding="utf-8")
texte_lower = texte.lower()

# 1 -- Les 4 sous-sujets sont presents dans la doc -------------------------
section("4 sous-sujets presents dans la doc")

sous_sujets = {
    "pas de cote": [
        r"pas\s+de\s+c[oô]t[eé]",
        r"[eé]change\s+(de\s+)?monnaie\s+entre\s+axes",
    ],
    "caprice auteur": [
        r"caprice\s+d.?auteur",
        r"audace\s+r[eé]gl[eé]e",
        r"droit\s+[aà]\s+l.[eé]chec",
    ],
    "cap vivant": [
        r"cap\s+vivant",
        r"change\s+(avec\s+l.|au\s+fil\s+de\s+la\s+campagne|avec\s+l.arc)",
    ],
    "pont qui reoutille a froid": [
        r"pont\s+qui\s+r[eé]outil",
        r"[aà]\s+froid",
        r"sans\s+toucher\s+au\s+code",
    ],
}

for nom, motifs in sous_sujets.items():
    for motif in motifs:
        assert re.search(motif, texte, re.IGNORECASE), \
            f"sous-sujet {nom!r} : motif {motif!r} introuvable dans la doc"

critere_count = len(re.findall(r"crit[eè]re\s+op[eé]ratoire", texte, re.IGNORECASE))
assert critere_count >= 4, \
    f"attendu >= 4 criteres operatoires, trouve {critere_count}"

source_refs = []
for ref in ("D-089", "D-101", "D-218"):
    assert ref in texte, f"source {ref} non citee dans la doc"
    source_refs.append(ref)

print(f"  4 sous-sujets OK, {critere_count} criteres, sources {source_refs}")

# 2 -- D-089 trois regimes de jet recoupe comme exemple local ---------------
section("D-089 trois regimes recoupe comme exemple local")

assert "D-089" in texte, "D-089 non reference"
assert "trois" in texte_lower and "regime" in texte_lower, \
    "trois regimes non mentionnes"

regimes = ["silencieux", "opaque", "transparent"]
for regime in regimes:
    assert regime in texte_lower, \
        f"regime {regime!r} absent (D-089 non recoupe)"

assert "table" in texte_lower and ("12" in texte or "facteur" in texte_lower), \
    "table des facteurs D-089 non recoupee"

assert "veto" in texte_lower or "anti-railroad" in texte_lower, \
    "veto anti-railroad (facteur 8 D-089) non recoupe"

print("  D-089 recoupe : 3 regimes + table facteurs + veto")

# 3 -- I-023 ancrage transverse verifie -------------------------------------
section("I-023 ancrage transverse verifie")

assert "I-023" in texte, "I-023 non reference dans la doc"
assert "transverse" in texte_lower or re.search(r"fil\s+rouge", texte, re.IGNORECASE), \
    "caractere transverse du fil rouge non mentionne"
assert re.search(r"chaque\s+cycle.*contrib", texte, re.IGNORECASE), \
    "contribution par cycle non mentionnee (I-023)"
assert "contournements" in texte_lower and "empilables" in texte_lower, \
    "strategie contournements empilables non citee"
assert re.search(r"r[eé]solution\s+locale", texte, re.IGNORECASE) or \
       re.search(r"locale.*lieu", texte, re.IGNORECASE), \
    "resolution locale lieu par lieu non mentionnee"

print("  I-023 ancre : transverse + contribution cycle + contournements empilables")

# 4 -- D-109 zero materiau de campagne (garde) ------------------------------
section("D-109 zero materiau de campagne (garde)")

mots_campagne = [
    "vahn", "planescape", "campaign", "souhel.*jou[eé]",
    "brigand", "filature", "perception.*rat[eé]e",
    "death.knight", "au.del[aà].*vale",
]
for motif in mots_campagne:
    assert not re.search(motif, texte, re.IGNORECASE), \
        f"D-109 VIOLATION : materiau de campagne detecte (motif {motif!r})"

assert "D-109" in texte, "D-109 non reference comme garde"
assert re.search(r"z[eé]ro\s+m[ae]t[ie]riau|aucun\s+m[ae]t[ie]riau|pas\s+de\s+m[ae]t[ie]riau",
                 texte, re.IGNORECASE), \
    "garde D-109 (zero materiau) non explicitee"

assert re.search(r"transmissibilit[eé]|reste.t.elle.vraie|change.de.campagne",
                 texte, re.IGNORECASE), \
    "test de transmissibilite D-109 absent"

print("  D-109 garde OK : zero materiau de campagne, test transmissibilite present")

print(f"\nOK test-doigte-verrou-central -- {len(FAIT)}/4 sections vertes")
assert len(FAIT) == 4, f"attendu 4 sections, got {len(FAIT)}"
