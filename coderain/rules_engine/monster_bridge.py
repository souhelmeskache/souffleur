"""Pont minimal : record de module -> comportement de combat 'brute' (I-205).

Un record de module (classe `creature`, `converter/annexe_a.py`) porte des
stats 5e en champs FRANÇAIS (`ca`, `pv`, `attaque_bonus`, `degats`) — jamais
un `monster_template_slug` : ce n'est pas un monstre du SRD, `dnd5e-engine`
n'a donc RIEN à jouer pour lui (voir `engine_bridge._unresolved_template_
warnings`, volet 1 de I-205, qui rend ce trou bruyant au lieu d'un pass
silencieux).

Ce module comble le trou a minima : à partir des MÊMES chiffres déjà lus sur
la fiche (CA/PV/bonus d'attaque/dégâts), il décrit un `Monster` du moteur
portant une seule attaque au corps-à-corps — un template générique 'brute',
paramétré, pas une créature du SRD imitée. Le moteur reste seul maître de la
résolution du jet et des dégâts (D-078) : rien ici ne calcule un jet, un
DC ou un montant de dégâts — on ne fait QUE remplir le schéma `Monster` du
moteur avec les nombres du record, puis on l'enregistre dans le loader que
le moteur interroge lui-même (`dnd5e_engine.lib_loader`).

Portée volontairement minimale (« suffit pour la fumée ») : une attaque,
pas de multiattaque, pas de résistances/immunités, pas de traits spéciaux.
Un besoin réel au-delà de la fumée (I-205 laisse ce raffinement pour plus
tard) lira les champs optionnels d'Annexe A (`immunites_degats`, etc.) et
enrichira `_brute_monster` en conséquence — sans toucher au reste du pont.

Usage :
    from coderain.converter.aval import get_record
    from coderain.rules_engine.monster_bridge import encounter_member_from_record

    record = get_record(partition, "ice-fiend")
    member = encounter_member_from_record(
        record, record_id="ice-fiend", entity_id="pnj:ice-fiend-1",
        zone_id="z1", initiative=8)
    # member["monster_template_slug"] == "brute:ice-fiend" et résout déjà
    # (install_brute_template a été appelé PAR encounter_member_from_record) :
    # passer `member` tel quel dans `encounter=[...]` à `start_combat`.
"""
from __future__ import annotations

import importlib
import re
from typing import Any

from ..converter.ruletables import ConversionException
from . import engine as _engine_fn

__all__ = [
    "brute_template_slug",
    "encounter_member_from_record",
    "install_brute_template",
]

_DICE_RE = re.compile(r"(\d+)\s*d\s*(\d+)(?:\s*([+-])\s*(\d+))?", re.I)
_INT_RE = re.compile(r"(\d+)")
_DAMAGE_TYPES = (
    "slashing", "piercing", "bludgeoning", "acid", "cold", "fire",
    "force", "lightning", "necrotic", "poison", "psychic", "radiant",
    "thunder",
)


def brute_template_slug(record_id: str) -> str:
    """Slug déterministe du template 'brute' d'un record — ex. ``brute:ice-fiend``."""
    return f"brute:{record_id}"


def _required_int(stats: dict, field: str, *, record_id: str) -> int:
    """Lit un champ numérique obligatoire de `stats` — refuse s'il est absent
    (D-274 §1) : jamais de nombre fabriqué à sa place (I-239)."""
    value = stats.get(field)
    m = _INT_RE.search(str(value)) if value is not None else None
    if not m:
        raise ConversionException(
            f"record {record_id!r} : champ {field!r} absent ou illisible "
            f"({value!r}) — aucun défaut ne le remplace")
    return int(m.group(1))


def _parse_dice(value: Any) -> tuple[int, int, int]:
    """``degats`` (``"12 (2d6+5) slashing"`` ou ``"1d6+2"`` nu) -> (nombre, face, bonus)."""
    m = _DICE_RE.search(str(value)) if value is not None else None
    if not m:
        return (1, 4, 0)
    number, sides, sign, bonus = m.groups()
    signed_bonus = int(bonus or 0) * (-1 if sign == "-" else 1)
    return (int(number), int(sides), signed_bonus)


def _damage_type(value: Any) -> str:
    low = str(value or "").lower()
    for dt in _DAMAGE_TYPES:
        if dt in low:
            return dt
    return "bludgeoning"


def _brute_monster(*, slug: str, name: str, ac: int, hp: int,
                   attack_bonus: int, damage_dice: tuple[int, int, int],
                   damage_type: str) -> Any:
    """Construit un ``Monster`` du moteur — une attaque unique, chiffres du
    record injectés en dur (``attack.flat=True`` : le bonus EST le nombre lu,
    aucun modificateur de caractéristique recalculé ici)."""
    _engine_fn()  # s'assure que dnd5e-engine (et donc dnd5e-srd-data) est là
    schema = importlib.import_module("dnd5e_srd_data.schema.monster")
    common = importlib.import_module("dnd5e_srd_data.schema.common")
    number, sides, bonus = damage_dice

    attack_activity = common.AttackActivity(
        activation=common.ActivationBlock(type="action", value=1),
        range=common.RangeBlock(value="5", units="ft"),
        attack=common.AttackBlock(
            bonus=str(attack_bonus), flat=True,
            type=common.AttackTypeBlock(value="melee", classification="weapon"),
        ),
        damage=common.AttackDamageBlock(
            include_base=False,
            parts=[common.DamagePartBlock(
                number=number, denomination=sides,
                bonus=str(bonus) if bonus else "", types=[damage_type])],
        ),
    )
    action = schema.MonsterAction(
        slug="brute-strike", name="Brute Strike",
        kind=schema.MonsterActionKind.ACTION,
        description="Attaque générique paramétrée par les stats du record.",
        activities=[attack_activity],
    )
    return schema.Monster(
        slug=slug, name=name, description="Template générique 'brute' (I-205).",
        creature_type=schema.CreatureType.MONSTROSITY,
        creature_size=schema.CreatureSize.MEDIUM,
        ac=max(1, ac), hp=max(1, hp), hp_dice=f"{max(1, hp)}d1",
        ability_scores=schema.AbilityScores(str=10, dex=10, con=10, int=10, wis=10, cha=10),
        movement=common.Movement(walk=30),
        senses=common.Senses(),
        cr=0.0, proficiency_bonus=2,
        saving_throws=schema.SavingThrowProficiencies(),
        skills=schema.SkillProficiencies(),
        actions=[action],
        provenance=common.Provenance(
            source="foundry", source_url="urn:i-205:brute-template",
            ingest_date="2026-08-31", ingest_version="brute-bridge-v0",
            srd_version=frozenset({"5.1"}),
        ),
        review=common.ReviewState(
            known_divergence="template générique 'brute' — pas une créature SRD"),
    )


def install_brute_template(*, record_id: str, name: str, ac: int, hp: int,
                           attack_bonus: int, damage: Any) -> str:
    """Enregistre le template 'brute' de ce record dans le loader du moteur.

    Composite avec délégation : le loader courant (souvent déjà un composite
    posé par un appel précédent) reste la source pour tout le reste du
    corpus SRD (armes, autres monstres) — cet appel n'AJOUTE qu'une entrée,
    il ne remplace jamais le corpus. Retourne le slug installé.
    """
    slug = brute_template_slug(record_id)
    monster = _brute_monster(
        slug=slug, name=name, ac=ac, hp=hp, attack_bonus=attack_bonus,
        damage_dice=_parse_dice(damage), damage_type=_damage_type(damage))
    ll = _engine_fn().lib_loader
    current = ll.get_lib_loader()
    if not isinstance(current, _CompositeLoader):
        current = _CompositeLoader(base=current)
        ll.set_lib_loader_for_tests(current)
    current.add_monster(monster)
    return slug


class _CompositeLoader:
    """Délègue tout au loader de base, sauf les monstres 'brute' ajoutés ici.

    Nom de la méthode d'injection moteur (`set_lib_loader_for_tests`) hors de
    notre contrôle — c'est le seul point d'extension que `dnd5e-engine`
    expose pour le loader ; on le réutilise en gardant TOUJOURS une
    délégation vers le corpus SRD groupé (jamais un remplacement).
    """

    def __init__(self, *, base: Any) -> None:
        self._base = base
        self._extra: dict[str, Any] = {}

    def add_monster(self, monster: Any) -> None:
        self._extra[monster.slug] = monster

    def get_monster(self, slug: str) -> Any:
        return self._extra.get(slug) or self._base.get_monster(slug)

    def list_slugs(self, category: str) -> list[str]:
        base_slugs = self._base.list_slugs(category)
        if category != "monsters":
            return base_slugs
        return sorted(set(base_slugs) | set(self._extra))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def __contains__(self, key: tuple[str, str]) -> bool:
        category, slug = key
        if category == "monsters" and slug in self._extra:
            return True
        return key in self._base


def encounter_member_from_record(record: dict, *, record_id: str, entity_id: str,
                                 zone_id: str, initiative: int = 10,
                                 entity_type: str = "Monster",
                                 hp_current: int | None = None) -> dict:
    """Record de module (`get_record()`) -> dict ``EncounterMemberSpec``.

    Lit les champs obligatoires de la classe `creature`
    (`converter/annexe_a.py::REQUIRED_STATS["creature"]`) : `nom`, `ca`,
    `pv`, `attaque_bonus`, `degats` — installe le template 'brute'
    correspondant (`install_brute_template`) puis retourne un dict prêt à
    entrer dans ``encounter=[...]`` de `start_combat`, `monster_template_slug`
    déjà résolu.

    Lève `ConversionException` si `ca`, `pv` ou `attaque_bonus` est absent ou
    illisible sur `stats` (D-274 §1, I-239) : un nombre manquant n'entre
    jamais en combat fabriqué — l'appelant doit remonter ce refus (jamais un
    `pass` silencieux), typiquement en `{"error": str(e)}` côté pont MCP.
    """
    stats = record.get("stats", record) if isinstance(record, dict) else {}
    meta = record.get("meta", {}) if isinstance(record, dict) else {}
    nom = stats.get("nom") or meta.get("nom") or entity_id
    ac = _required_int(stats, "ca", record_id=record_id)
    hp = _required_int(stats, "pv", record_id=record_id)
    attack_bonus = _required_int(stats, "attaque_bonus", record_id=record_id)
    damage = stats.get("degats")

    slug = install_brute_template(
        record_id=record_id, name=nom, ac=ac, hp=hp,
        attack_bonus=attack_bonus, damage=damage)
    number, sides, bonus = _parse_dice(damage)
    dice_str = f"{number}d{sides}" + (f"+{bonus}" if bonus > 0
                                      else f"{bonus}" if bonus < 0 else "")
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "name": nom,
        "initiative": initiative,
        "hp_current": hp_current if hp_current is not None else hp,
        "hp_max": hp,
        "ac": ac,
        "attack_bonus": attack_bonus,
        "damage_dice": dice_str,
        "damage_type": _damage_type(damage),
        "zone_id": zone_id,
        "monster_template_slug": slug,
    }
