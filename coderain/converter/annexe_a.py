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
    # D-252.3 : sorts inédits des appendices de campagne — ancre racine SRD
    # 5.1 › Spellcasting (docs/annexe-a-stats-5e.md §6). Bornes de valeur
    # (niveau 0-9, ecole SRD, composantes V/S/M...) vérifiées à part par
    # schemas.py::Record._check_sort — required_fields ne checke que la
    # présence.
    "sort": ("niveau", "ecole", "temps_incantation", "portee", "composantes",
             "duree", "effet_md", "listes_de_classes"),
}

# The three-jet grouping used when collapsing an older saves block
# (ruletables.SAVE_GROUPS references these names).
SAVE_NAMES = ("vigueur", "reflexes", "volonte")


# D-252.2 (issue #62) — objets magiques : extension de la classe objet par
# des champs OPTIONNELS (type_objet, rarete, harmonisation +
# condition_harmonisation, activation, charges + recharge, effets_md,
# secret_lie_id). Aucun n'entre dans REQUIRED_STATS ci-dessus (un objet
# ordinaire reste valide sans eux) ; les énumérations et la cohérence entre
# champs sont vérifiées par Record._objet_magique (schemas.py) et le lien
# vers Secret par validate_form.validate_form — voir docs/annexe-a-stats-5e.md
# §3bis pour le motif MALÉDICTION/IDENTIFICATION = câblage sur Secret.


def required_fields(classe: str) -> tuple[str, ...]:
    if classe not in REQUIRED_STATS:
        raise KeyError(f"unknown record classe {classe!r}")
    return REQUIRED_STATS[classe]
