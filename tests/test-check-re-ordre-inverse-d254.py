"""D-254 (I-328/Issue-77) : CHECK_RE ordre inverse + table competence -> 5e.

100% synthetique (D-109) : les phrases ci-dessous REPRODUISENT la FORME
mesuree dans docs/pconv1-3-pval-ecarts.md (checks=0) — "Make a perception
check, DC N", "roll survival, DC N", "wisdom save, DC N" — sans aucun mot
de contenu narratif reel du module source.

Couvre :
- REVERSE_CHECK_RE : competence/caracteristique AVANT le DC, en plus de
  CHECK_RE (forme existante, DC avant), sans regression sur elle.
- SKILL_TO_ABILITY_5E : table de correspondance competence -> caracteristique
  5e (18 competences SRD + thieves' tools), utilisee pour router le jet.
- extract_checks() fusionne les deux formes sans double-compte.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter.aval import (SKILL_TO_ABILITY_5E, extract_checks)
from coderain.converter.schemas import Unit

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def _checks(texte):
    u = Unit("u1", "S1", 0, len(texte))
    return extract_checks(texte, [u]).get("u1", [])


# 1 -- forme existante : DC avant caracteristique (retrocompat) -----------------
section("forme existante : DC avant caracteristique — inchangee")
texte = "The rogue must succeed on a DC 15 wisdom (perception) check to notice."
found = _checks(texte)
assert len(found) == 1, found
assert found[0] == {"dc": 15, "ability": "wisdom", "skill": "perception",
                    "kind": "check", "regime_propose": "SILENCIEUX"}, found

texte = "The target must make a DC 12 dexterity saving throw or take damage."
found = _checks(texte)
assert len(found) == 1, found
assert found[0]["dc"] == 12
assert found[0]["ability"] == "dexterity"
assert found[0]["kind"] == "saving_throw"

# 2 -- forme mesuree pconv1-3 : "Make a <skill> check, DC N" --------------------
section('ordre inverse : "Make a perception check, DC N"')
texte = "Make a perception check, DC 12 to notice the ambush."
found = _checks(texte)
assert len(found) == 1, found
assert found[0]["dc"] == 12
assert found[0]["skill"] == "perception"
assert found[0]["ability"] == "wisdom"          # table competence -> 5e
assert found[0]["kind"] == "check"
assert found[0]["regime_propose"] == "SILENCIEUX"   # perception = passif (A1)

# 3 -- forme mesuree pconv1-3 : "roll <skill>, DC N" -----------------------------
section('ordre inverse : "roll survival, DC N"')
texte = "Roll survival, DC 15, to track the beast through the forest."
found = _checks(texte)
assert len(found) == 1, found
assert found[0]["dc"] == 15
assert found[0]["skill"] == "survival"
assert found[0]["ability"] == "wisdom"
assert found[0]["kind"] == "check"

# 4 -- forme mesuree pconv1-3 : "<ability> save, DC N" ---------------------------
section('ordre inverse : "wisdom save, DC N"')
texte = "The target attempts a wisdom save, DC 10, or falls prone."
found = _checks(texte)
assert len(found) == 1, found
assert found[0]["dc"] == 10
assert found[0]["ability"] == "wisdom"
assert found[0]["skill"] is None
assert found[0]["kind"] == "saving_throw"
assert found[0]["regime_propose"] == "OPAQUE"       # subi (A2)

# 5 -- pas de faux positif : DC de statblock sans mot-cle de jet -----------------
section("pas de faux positif : DC de statblock sans check/save/roll")
texte = "The creature has Strength 18 (+4), grapple DC 15."
found = _checks(texte)
assert found == [], found

# 6 -- table competence -> caracteristique : couverture complete SRD ------------
section("table SKILL_TO_ABILITY_5E : couverture des 18 competences SRD")
ATTENDU = {
    "athletics": "strength",
    "acrobatics": "dexterity", "sleight of hand": "dexterity", "stealth": "dexterity",
    "arcana": "intelligence", "history": "intelligence", "investigation": "intelligence",
    "nature": "intelligence", "religion": "intelligence",
    "animal handling": "wisdom", "insight": "wisdom", "medicine": "wisdom",
    "perception": "wisdom", "survival": "wisdom",
    "deception": "charisma", "intimidation": "charisma", "performance": "charisma",
    "persuasion": "charisma",
}
for skill, ability in ATTENDU.items():
    assert SKILL_TO_ABILITY_5E[skill] == ability, (skill, ability)
assert SKILL_TO_ABILITY_5E["thieves' tools"] == "dexterity"

# 7 -- pas de double-compte quand la forme existante matche deja ----------------
section("pas de double-compte sur une phrase deja captee par CHECK_RE")
texte = "The rogue must succeed on a DC 15 dexterity (stealth) check to hide."
found = _checks(texte)
assert len(found) == 1, found      # une seule occurrence, pas deux

# 8 -- regime D-089 inchange : la detection alimente, ne modifie pas le moteur --
section("regime propose : perception passif reste SILENCIEUX peu importe l'ordre")
for texte in ("The scout must attempt a DC 12 wisdom (perception) check to spot the guard.",
             "Make a perception check, DC 12 to spot the guard."):
    found = _checks(texte)
    assert len(found) == 1, found
    assert found[0]["regime_propose"] == "SILENCIEUX", found

print(f"\nOK test-check-re-ordre-inverse-d254 — {len(FAIT)} sections vertes")
