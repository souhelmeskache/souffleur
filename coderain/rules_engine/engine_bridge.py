"""Pont hôte coderain → `dnd5e-engine` (v0, D-200).

Pendant un combat, l'état mécanique (initiative, HP, conditions, dés) vit
DANS `dnd5e-engine` : ce pont ne fait que soumettre des intentions au moteur
et MIRRORER en lecture ses résultats vers l'état joué coderain. Zéro règle
réimplémentée ici — D-078 : appeler le moteur, jamais l'imiter.

Séquence d'un combat :
    bridge.start_combat(...)          -> handle_id + événements d'ouverture
    bridge.submit_intent(handle...)   -> tour d'un personnage
    bridge.monster_turn(handle)       -> tour d'un monstre (IA du moteur)
    bridge.drain_events(handle)       -> événements pendants depuis la fois
    bridge.end_combat(handle)         -> issue + nettoyage du handle côté pont

Les erreurs propres du moteur (`IntentRejectedError`) remontent telles
quelles : c'est le moteur qui refuse une intention illégale, pas le pont.
"""
from __future__ import annotations

import random
from typing import Any

from . import engine as _engine_fn

__all__ = ["CombatBridge", "get_bridge", "resolve_check", "intent_rejected_error"]


def _orch() -> Any:
    """Module orchestrateur du moteur (chargé paresseusement)."""
    return _engine_fn().orchestrator


def intent_rejected_error() -> type:
    """La classe `IntentRejectedError` du moteur — pour `except` côté hôte."""
    return _engine_fn().orchestrator.IntentRejectedError


def _dump(events: Any) -> list[dict]:
    """Mirror lecture : événements pydantic du moteur -> dicts JSON."""
    return [e.model_dump() for e in events]


def _unresolved_template_warnings(encounter: list[dict]) -> list[dict]:
    """Membres d'encounter dont ``monster_template_slug`` ne joue rien (I-205).

    Deux cas couverts, tous deux réduits par le moteur à un ``pass``
    silencieux (voir docstring de ``advance_monster_turn`` côté moteur) :
    aucun slug fourni du tout, ou un slug fourni mais absent de
    ``dnd5e-srd-data`` (corpus SRD). Un membre ``entity_type == "Character"``
    (un PJ) n'a jamais de comportement d'IA à résoudre — hors périmètre.
    Zéro règle réimplémentée ici (D-078) : on ne fait que consulter le même
    loader que le moteur interroge lui-même, jamais recalculer une action.
    """
    loader = _engine_fn().lib_loader.get_lib_loader()
    warnings = []
    for member in encounter:
        if member.get("entity_type") == "Character":
            continue
        entity_id = member.get("entity_id")
        slug = member.get("monster_template_slug")
        if slug is None:
            warnings.append({
                "entity_id": entity_id,
                "monster_template_slug": None,
                "reason": "aucun comportement de combat : template non résolu",
            })
        elif loader.get_monster(slug) is None:
            warnings.append({
                "entity_id": entity_id,
                "monster_template_slug": slug,
                "reason": "aucun comportement de combat : template non résolu",
            })
    return warnings


class CombatBridge:
    """Un combat actif par ``handle_id`` ; la vérité reste chez le moteur.

    Le pont ne garde que le ``CombatHandle`` opaque renvoyé par
    ``start_combat`` — jamais un état de combat copié.
    """

    def __init__(self) -> None:
        self._combats: dict[str, Any] = {}
        # entity_id -> avertissement, pour les membres d'encounter dont le
        # monster_template_slug ne résout à rien dans dnd5e-srd-data (I-205
        # volet 1) : rempli à start_combat, consulté par monster_turn pour
        # que CHAQUE tour d'un monstre non résolu porte l'avertissement,
        # jamais seulement l'ouverture du combat.
        self._unresolved: dict[str, dict[str, dict]] = {}

    # -- cycle de vie ------------------------------------------------------

    async def start_combat(
        self,
        *,
        session_id: str,
        party: list[dict],
        encounter: list[dict],
        rng_seed: int,
        zones: list[str] | None = None,
    ) -> dict:
        """Ouvre un combat ; retourne handle + événements d'ouverture.

        ``party``/``encounter`` sont des dicts au format ``PartyMemberSpec`` /
        ``EncounterMemberSpec`` du moteur (validation pydantic amont). Une
        attaque jouable exige ``weapon_id`` résolvable dans le corpus (l'attaque
        sans arme est acceptée mais n'arme aucun jet) ; un monstre jouable
        exige ``monster_template_slug`` présent dans `dnd5e-srd-data`
        (ex. ``goblin-warrior``), sinon son tour se résout en passe — **mais
        jamais silencieusement** : ``warnings`` (ici et sur chaque
        ``monster_turn`` suivant tant que le combat dure) porte un
        avertissement explicite par membre d'encounter dont le template n'a
        pas résolu (I-205).
        """
        eng = _engine_fn()
        result = await _orch().start_combat(
            session_id=session_id,
            party=[eng.PartyMemberSpec(**p) for p in party],
            encounter=[eng.EncounterMemberSpec(**e) for e in encounter],
            rng_seed=int(rng_seed),
            scene_zones=eng.SceneTopology(zones=list(zones or ("z1",))),
        )
        handle = result.handle
        self._combats[handle.handle_id] = handle
        warnings = _unresolved_template_warnings(encounter)
        self._unresolved[handle.handle_id] = {w["entity_id"]: w for w in warnings}
        # Le moteur rend les événements d'ouverture ET les met en file
        # (mêmes objets) : on sert la FILE comme unique source de livraison
        # pour garantir le exact-once avec drain_events/narration_events.
        queued = _dump(_orch().drain_pending_events(handle))
        return {
            "handle_id": handle.handle_id,
            "events": queued or _dump(result.events),
            "live": self.live(handle.handle_id),
            "warnings": warnings,
        }

    async def submit_intent(self, handle_id: str, actor_id: str,
                            intent: dict) -> dict:
        """Soumet l'intention d'un personnage (format ``PlayerIntent``).

        Lève ``IntentRejectedError`` (du moteur) si l'action est illégale ou
        jouée au mauvais tour — remonter telle quelle à l'appelant.
        """
        eng = _engine_fn()
        await _orch().submit_player_intent(
            self._handle(handle_id),
            actor_id=actor_id,
            intent=eng.PlayerIntent(**intent),
        )
        return {"events": self.drain_events(handle_id),
                "live": self.live(handle_id)}

    async def monster_turn(self, handle_id: str) -> dict:
        """Fait jouer le tour du monstre courant par l'IA du moteur.

        Si l'acteur dont c'est le tour n'a jamais eu de
        ``monster_template_slug`` résolu (I-205 volet 1), ``warnings`` porte
        l'avertissement AVANT de jouer le tour : le moteur va quand même
        résoudre un ``pass`` (comportement décrit dans
        ``advance_monster_turn``), mais l'appelant reçoit un signal explicite
        — jamais un pass indiscernable d'une passivité voulue.
        """
        warning = self._unresolved.get(handle_id, {}).get(
            self.live(handle_id)["active_actor_id"])
        await _orch().advance_monster_turn(self._handle(handle_id))
        return {"events": self.drain_events(handle_id),
                "live": self.live(handle_id),
                "warnings": [warning] if warning else []}

    async def end_combat(self, handle_id: str) -> dict:
        """Clôt le combat ; l'issue (``ended_reason``, morts, XP) vient du
        moteur. Le handle est ensuite oublié par le pont."""
        result = await _orch().end_combat(self._handle(handle_id))
        self._combats.pop(handle_id, None)
        self._unresolved.pop(handle_id, None)
        return {
            "outcome": result.outcome.model_dump(),
            "events": _dump(result.events),
        }

    # -- mirroring lecture ---------------------------------------------------

    def live(self, handle_id: str) -> dict:
        """Miroir LECTURE SEULE de la vue combat du moteur.

        C'est la seule façon dont l'état mécanique atteint l'état joué
        coderain : on copie ce que le moteur expose (`get_live`), on ne
        recalcule rien.
        """
        view = _orch().get_live(self._handle(handle_id))
        order = [c.entity_id for c in view.initiative]
        return {
            "round_number": view.round_number,
            "current_turn_index": view.current_turn_index,
            "active_actor_id": (order[view.current_turn_index]
                                if order and not view.ended else None),
            "initiative_order": order,
            "tracked_hp": dict(view.tracked_hp),
            "tracked_temp_hp": dict(view.tracked_temp_hp),
            "active_conditions": {k: sorted(v)
                                  for k, v in view.active_conditions.items()},
            "dead_ids": sorted(view.dead_ids),
            "ended": view.ended,
        }

    def drain_events(self, handle_id: str) -> list[dict]:
        """Événements pendants depuis le dernier appel (drain non bloquant).

        Même file que l'itérateur asynchrone `narration_events` du moteur ;
        premier arrivé, premier servi — l'état des événements aussi vit chez
        le moteur.
        """
        return _dump(_orch().drain_pending_events(self._handle(handle_id)))

    # -- interne -------------------------------------------------------------

    def _handle(self, handle_id: str) -> Any:
        try:
            return self._combats[handle_id]
        except KeyError:
            raise ValueError(f"combat inconnu ou déjà clos : {handle_id!r}"
                             ) from None


_BRIDGE: CombatBridge | None = None


def get_bridge() -> CombatBridge:
    """Singleton du pont (un seul espace de combats par process hôte)."""
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = CombatBridge()
    return _BRIDGE


def resolve_check(spec: dict, seed: int | None = None) -> dict:
    """Résout un jet 5e isolé (compétence / caractéristique / sauvegarde).

    ``spec`` est un dict au format ``CheckSpec`` du moteur. ``seed``, s'il est
    fourni, amorce le RNG global juste avant l'appel : `roll_d20` du moteur lit
    ce RNG, donc même graine ⇒ même jet (amorçage hôte — aucune règle ici).
    Retour : nat, modificateur, total, succès — mirror du ``CheckResult``.
    """
    eng = _engine_fn()
    if seed is not None:
        random.seed(int(seed))
    result = eng.resolve_check(eng.CheckSpec(**spec))
    return {
        "kind": result.kind,
        "skill": result.skill,
        "ability": result.ability,
        "natural_roll": result.natural_roll,
        "modifier": result.modifier,
        "roll_total": result.roll_total,
        "dc": result.dc,
        "success": result.success,
        "is_proficient": result.is_proficient,
    }
