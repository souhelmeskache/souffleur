"""tools/banc/cloturer_seance.py — écriture MÉCANIQUE du record `seance` de
clôture (F0.3, Issue #331 ; frontière D-282, Issue #311 ; détection #306).

`tools/banc/detecter_fin.py` STATUE (lecture pure, jamais un écrit) ; ce
script est le seul appelant qui, sur `fin_module`/`frontiere`, ÉCRIT l'état
via l'API de production (`coderain/validator.py::cloturer_seance`, qui passe
par `MemoryStore.set_world_state` — jamais un écrit direct de state.json) :

- `fin_module` -> raison="terminal"
- `frontiere`  -> raison="frontiere"
- `mort`/`non` -> rien à écrire (la mort n'est pas une raison de clôture de
  séance déclarée par l'Issue #331 ; `arret_joueur`, la troisième raison du
  schéma, reste hors détection mécanique de ce script — une brique
  ultérieure ou l'arrêt interactif de session la posera).

Appelé par `nuit.sh` juste après `detecter_fin_partie` (même lecture de
position, jamais une resélection séparée). Idempotent — `cloturer_seance`
(voir sa docstring) ne duplique jamais un record déjà écrit pour le même
`tour_fin` : un appel répété à chaque tour tant que la partie ne s'arrête
pas ne coûte qu'une lecture d'état de plus.

Usage :
    python tools/banc/cloturer_seance.py <save_dir>

Sortie 0 toujours (même garde que `detecter_fin.py` : une save sans
position/module lisible ne craque jamais ce script). Sur stdout, une ligne
en forme fixe :

    seance: (aucune)|ecrite n°<numero> (<raison>)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Force UTF-8 sur stdout/stderr quel que soit le terminal (#279, même garde
# que les autres scripts de tools/banc/).
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from coderain.memory import MemoryStore  # noqa: E402
from coderain import validator as validator_mod  # noqa: E402

# tools/banc n'est pas un package (pas de __init__.py) : même chargement par
# chemin que tests/detecter_fin_test.py, jamais un `from tools.banc import
# ...` qui échouerait.
_spec = importlib.util.spec_from_file_location(
    "detecter_fin", Path(__file__).resolve().parent / "detecter_fin.py")
detecter_fin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detecter_fin)

_RAISON_PAR_FIN = {"fin_module": "terminal", "frontiere": "frontiere"}


def cloturer(save_dir: str | Path) -> dict | None:
    """Rend le record écrit (ou None : pas de fin, ou déjà close)."""
    resultat = detecter_fin.evaluer(save_dir)
    raison = _RAISON_PAR_FIN.get(resultat["fin"])
    if raison is None:
        return None
    store = MemoryStore(save_dir)
    noeud = resultat["noeud"] or ""
    return validator_mod.cloturer_seance(store, raison, noeud)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage : {argv[0]} <save_dir>", file=sys.stderr)
        return 2
    record = cloturer(argv[1])
    if record is None:
        print("seance: (aucune)")
    else:
        print(f"seance: ecrite n°{record['numero']} ({record['raison']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
