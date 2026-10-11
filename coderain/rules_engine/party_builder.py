"""Fiche joueur (save) -> `PartyMemberSpec` du moteur (chantier 7a, I-28 suite).

Décision Souhel : dans une partie D&D, le personnage joué est une vraie
fiche 5e — six SCORES, niveau, classe et espèce désignés par leur
identifiant du catalogue moteur (`get_lib_loader()`), équipement par les
`srd:` des objets équipés. `party_member_from_sheet` assemble le dict
`PartyMemberSpec` (`dnd5e_engine.specs`) depuis ces champs — PURE, zéro
accès fichier/réseau, zéro règle réimplémentée (D-078) : chaque valeur lui
arrive déjà lue sur la save et déjà validée au catalogue.

La lecture de la save ET la validation catalogue (classe/espèce/`srd:`
inconnus du moteur) vivent côté outil MCP
(`coderain/mcp/jets_combat.py::_build_player_party_member`) — jamais ici,
et jamais dans `coderain/rules_engine/engine_bridge.py`, qui ne gagne
aucun accès à la save (consigne du chantier 7a, §2).

Ne porte pas `initiative` : un membre de `party` qui n'en fournit pas en
reçoit une jetée (d20 + mod Dextérité 5e, même discipline reproductible que
`coderain.modules.rpg.roll_check`) au moment de la résolution
(`_resolve_party_member`), jamais de ce builder pur ni inventée par
l'appelant (chantier 7a §6).
"""
from __future__ import annotations

from typing import Any

__all__ = ["MissingFieldError", "party_member_from_sheet"]


class MissingFieldError(ValueError):
    """Un champ nécessaire à la fiche 5e du joueur est absent ou illisible —
    refus nommé (D-274 §1), jamais un défaut inventé à sa place."""


def party_member_from_sheet(
    *, entity_id: str, name: str,
    strength: int, dexterity: int, constitution: int,
    intelligence: int, wisdom: int, charisma: int,
    hp_current: int, hp_max: int, ac: int, attack_bonus: int,
    level: int, class_slug: str, species_slug: str,
    equipment: tuple[str, ...], zone_id: str,
) -> dict[str, Any]:
    """Assemble un dict `PartyMemberSpec` depuis les champs DÉJÀ lus sur la
    fiche (scores 5e), DÉJÀ dérivés (`rpg.derived_combat` -> `ac`/
    `attack_bonus`) et DÉJÀ validés au catalogue moteur (`class_slug`/
    `species_slug`/`equipment`, un par un, côté appelant).

    Chaque argument `None` est un refus nommé (`MissingFieldError`) — jamais
    un 0/""/[] fabriqué à sa place (D-274 §1). `equipment` seul peut être
    vide (aucun objet équipé ne porte de `srd:` résolu) sans que ce soit un
    refus : un personnage à mains nues entre quand même en combat."""
    fields = {
        "entity_id": entity_id, "name": name,
        "strength": strength, "dexterity": dexterity,
        "constitution": constitution, "intelligence": intelligence,
        "wisdom": wisdom, "charisma": charisma,
        "hp_current": hp_current, "hp_max": hp_max,
        "ac": ac, "attack_bonus": attack_bonus,
        "character_level": level, "class_slug": class_slug,
        "species_slug": species_slug, "zone_id": zone_id,
    }
    for key, value in fields.items():
        if value is None:
            raise MissingFieldError(
                f"champ manquant pour construire la fiche 5e du joueur : {key!r}")
    fields["equipment"] = tuple(equipment or ())
    return fields
