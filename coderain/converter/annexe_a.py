"""Annexe A (SPEC-P4 §5) — mandatory stats_5e fields per record class.

⏳ DRAFT v0: the spec marks this annexe "longue mais mécanique, à tirer du
SRD" and non-blocking. These minimal field sets are the coding skeleton; the
SRD-derived full sets replace them field-by-field without touching callers.
"""
from __future__ import annotations

REQUIRED_STATS: dict[str, tuple[str, ...]] = {
    "creature": ("nom", "ca", "pv", "vitesse", "attaque_bonus", "degats"),
    "pnj": ("nom", "role", "description_md"),
    "objet": ("nom", "description_md"),
    "lieu": ("nom", "description_md"),
    "faction": ("nom", "description_md"),
}

# The three-jet grouping used when collapsing an older saves block
# (ruletables.SAVE_GROUPS references these names).
SAVE_NAMES = ("vigueur", "reflexes", "volonte")


def required_fields(classe: str) -> tuple[str, ...]:
    if classe not in REQUIRED_STATS:
        raise KeyError(f"unknown record classe {classe!r}")
    return REQUIRED_STATS[classe]
