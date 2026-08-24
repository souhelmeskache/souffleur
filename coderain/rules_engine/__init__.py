"""coderain → `dnd5e-engine` : le pont vers l'organe de règles 5e (D-200).

Coderain reste LE moteur hôte (narration, mémoire, état joué, boucle) ;
`dnd5e-engine` est une bibliothèque APPELÉE qui détient l'état de combat et
calcule la mécanique — D-078 : appeler le moteur, jamais l'imiter. Ce paquet
n'implémente aucune règle : il charge la bibliothèque paresseusement
(`engine()`) et expose le pont hôte (`CombatBridge`, `resolve_check`).

Coexistence v0 : les jets simples hors combat restent dans
`coderain.modules.rpg` (roll_check MCP), NON touché.
"""
from __future__ import annotations

import importlib
from typing import Any

_ENGINE: Any | None = None


class RulesEngineNotInstalled(ImportError):
    """`dnd5e-engine` absent de l'environnement.

    Installer les dépendances épinglées (`pip install -r requirements.txt`) :
    l'épinglage strict ==0.3.0 (+ transitives ==, sha256 du wheel vérifié)
    est une condition d'intégration D-194/D-200, pas un détail.
    """


def engine() -> Any:
    """Charge et retourne le module `dnd5e_engine` (une seule fois).

    Chargement paresseux : importer `coderain.rules_engine` n'impose PAS la
    présence de la bibliothèque ; seule sa première utilisation lève
    :class:`RulesEngineNotInstalled` si elle manque.
    """
    global _ENGINE
    if _ENGINE is None:
        try:
            _ENGINE = importlib.import_module("dnd5e_engine")
        except ImportError as exc:
            raise RulesEngineNotInstalled(
                "dnd5e-engine n'est pas installé — voir requirements.txt "
                "(épinglage strict ==0.3.0)."
            ) from exc
    return _ENGINE


def __getattr__(name: str) -> Any:  # PEP 562 — ré-export paresseux
    return getattr(engine(), name)


from .engine_bridge import (  # noqa: E402
    CombatBridge,
    get_bridge,
    intent_rejected_error,
    resolve_check,
)

__all__ = [
    "RulesEngineNotInstalled",
    "engine",
    "CombatBridge",
    "get_bridge",
    "intent_rejected_error",
    "resolve_check",
]
