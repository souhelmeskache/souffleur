"""tools/banc/detecter_fin.py — détection MÉCANIQUE de la fin d'une partie
de nuit (Issue #306).

`nuit.sh` ne connaissait jusqu'ici qu'un seul proxy de fin : le joueur mort
(`rpg.player.conditions` contient `"dead"`). Une partie qui n'atteint jamais
la mort sort toujours `fin_atteinte: N, raison_arret: tours_max` — même
quand elle a en réalité traversé tout le module et posé le joueur sur son
nœud terminal (`liens: []` + `charniere_sortie`, D-123). La partition porte
cette fin MÉCANIQUEMENT : ce script lit la position courante de la save (la
même lecture que `coderain/assembleur_position.py`, jamais une resélection
séparée — `coderain/validator.py::current_location` + le pointeur
`module.json` → partition → `nodes/<id>.md`) et statue, toujours sans LLM,
sans jugement narratif :

- **mort** : `rpg.player.conditions` contient `"dead"` (proxy historique,
  inchangé) ;
- **fin_module** : le nœud courant a `liens: []`, porte une
  `charniere_sortie` (D-123 — cette clé n'est émise par
  `coderain/converter/emit.py` QUE si elle est vraie, jamais un champ
  toujours présent), et n'est PAS `avant-propos` (l'entrée du module, qui
  n'a légitimement encore aucun lien sortant explorable au tour 0 — jamais
  une fin, D-123) ;
- **non** (aucune fin) sinon — la save n'a pas de position/partition
  (`eligible()` de `assembleur_position.py` refuserait aussi ce chemin), le
  nœud est introuvable, ou il porte encore des liens/n'a pas de charnière.

`noeud` (l'id du nœud courant, ou None si aucune position lisible) est
toujours rendu, fin atteinte ou non — c'est la mesure de PROGRESSION que
`nuit.sh` écrit dans chaque `resume-run.md` (#306), quelle que soit la
raison de sortie (tours_max, craquement, FinA).

Usage :
    python tools/banc/detecter_fin.py <save_dir>

Sortie 0 toujours (jamais un refus — une save sans position/module lisible
rend simplement `fin: non` / `noeud: (aucun)`, jamais une erreur qui
craquerait la partie). Sur stdout, deux lignes en forme fixe (parseur
tolérant `grep`/`sed`, même convention que `resume-run.md`) :

    fin: non|mort|fin_module
    noeud: <id>|(aucun)
"""
from __future__ import annotations

import json
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

from coderain import validator as validator_mod  # noqa: E402
from coderain.assembleur_position import _read_json_front  # noqa: E402

# Le nœud d'entrée du module (avant-propos) n'a légitimement aucun lien
# sortant explorable au tour 0 — jamais une fin, même s'il en venait à
# porter une charnière (D-123).
_NOEUD_ENTREE = "avant-propos"


def _lire_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _partition_dir(save_dir: Path) -> Path | None:
    """Même résolution que `mcp_server._partition_dir` / `Engine._partition_dir`
    (D-260, Issue #146) : le pointeur save → partition vit dans
    `module.json`."""
    data = _lire_json(save_dir / "module.json")
    partition = data.get("partition")
    return Path(partition) if partition else None


def evaluer(save_dir: str | Path) -> dict:
    """Rend `{"fin": "non"|"mort"|"fin_module", "noeud": str | None}`."""
    save_dir = Path(save_dir)
    state = _lire_json(save_dir / "state.json")

    conds = ((state.get("rpg") or {}).get("player") or {}).get("conditions") or []
    location = validator_mod.current_location(state) or None

    if "dead" in conds:
        return {"fin": "mort", "noeud": location}

    if not location:
        return {"fin": "non", "noeud": None}

    partition_dir = _partition_dir(save_dir)
    if partition_dir is None:
        return {"fin": "non", "noeud": location}

    meta = _read_json_front(partition_dir / "nodes" / f"{location}.md")
    liens = meta.get("liens") or []
    charniere = meta.get("charniere_sortie")
    if location != _NOEUD_ENTREE and not liens and charniere:
        return {"fin": "fin_module", "noeud": location}

    return {"fin": "non", "noeud": location}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage : {argv[0]} <save_dir>", file=sys.stderr)
        return 2
    resultat = evaluer(argv[1])
    print(f"fin: {resultat['fin']}")
    print(f"noeud: {resultat['noeud'] or '(aucun)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
