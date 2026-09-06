"""tools/banc/verifier_reset.py — les 4 vérifications MÉCANIQUES du tour N+1
après un reset de session Director (Issue #330, D-264 ; brique 0 / F0.1).

`tools/banc/nuit.sh::effectuer_reset` tue la session MJ en vol au tour N et
en relance une NEUVE (jamais `--resume`) sur la même save, avant le go du
tour N+1 -- preuve visée : l'état vit à 100% dans la save
(`docs/ARCHITECTURE.md` §1), jamais dans la fenêtre de conversation du
Director. Ce script lit UNIQUEMENT l'état et les fichiers déjà écrits sur
disque (jamais un jugement LLM sur la prose, D-131/D-134) et rend un
verdict PASS/FAIL pour chacun des quatre points de l'Issue :

1. **Position** : la position du tour N+1 est égale à celle du tour N, ou a
   avancé par un débouché VALIDE de la partition (un `cible_id` listé dans
   les `liens` du nœud du tour N) -- jamais un retour à l'ouverture du
   module (`avant-propos`) si le tour N n'y était pas déjà.
2. **Cliquet / visée courante** : les champs `rpg.cliquet` et
   `rpg.visee_courante` de l'état (drapeaux de progression posés par le
   Director en session, D-264) sont identiques avant/après le reset --
   signal retenu ici, documenté faute d'un nom de champ déjà établi
   ailleurs dans le moteur (aucune occurrence de "cliquet"/"visée" hors du
   vault avant cette lane) ; une fixture ou un moteur qui poserait ces
   drapeaux sous d'autres clés devra adapter cette fonction, pas la
   contourner.
3. **Pas de réintroduction de scène** : aucun événement `scene_intro`, et
   aucun delta `location` égal au nœud d'entrée du module (`avant-propos`),
   journalisé au tour N+1 dans `memory/events.jsonl` -- signal mécanique
   retenu (Issue #330 § « à définir mécaniquement »).
4. **Mot-témoin absent** : le(s) mot-témoin(s) choisis par la session TUÉE
   (§ Test d'étanchéité harnais, `tools/prompts/banc-mj.md`, journalisés
   ligne `TEMOIN: <mot>` dans `etancheite.md`) sont absents de tout ce que
   la session NEUVE écrit pour le tour N+1 (`tour-NN.md`, `action-NN.md`,
   `prose-NN.md`) -- la preuve qu'aucune mémoire de fenêtre n'a survécu.

Usage :
    python tools/banc/verifier_reset.py <partie_dir> <tour>

Où `<tour>` est le tour DE RESET (N, pas N+1). Lit :
- `<partie_dir>/etat-avant-reset-NN.json` (snapshot de state.json au moment
  du reset, écrit par `nuit.sh::effectuer_reset`) et l'état COURANT de
  `<partie_dir>/save/state.json` (supposé être celui du tour N+1 -- ce
  script est appelé juste après que ce tour a été journalisé, jamais plus
  tard) ;
- `<partie_dir>/save/module.json` + la partition qu'il pointe, pour la
  liste des débouchés valides du nœud du tour N (point 1) ;
- `<partie_dir>/save/memory/events.jsonl`, filtré sur `turn == N+1`
  (point 3) ;
- `<partie_dir>/etancheite-avant-reset-NN.md` (snapshot de etancheite.md au
  moment du reset) et `tour-N+1.md`/`action-N+1.md`/`prose-N+1.md` (point 4).

Écrit `<partie_dir>/reset-NN.md` (verdict par point + verdict global) et
rend 0 si les 4 points sont PASS, 1 sinon -- jamais fatal à la partie qui
l'appelle (`nuit.sh` ignore le code de sortie, § effectuer_reset) : c'est
une MESURE, pas une garde.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from coderain.assembleur_position import _read_json_front  # noqa: E402

# Force UTF-8 sur stdout/stderr quel que soit le terminal (#279, même garde
# que les autres scripts de tools/banc/).
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Le nœud d'entrée du module -- jamais une position légitime à retrouver au
# tour N+1 d'un reset si le tour N ne l'était pas déjà (même id que
# tools/banc/detecter_fin.py::_NOEUD_ENTREE, D-123).
_NOEUD_ENTREE = "avant-propos"


def _lire_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _partition_dir(save_dir: Path) -> Path | None:
    """Même résolution que `detecter_fin.py::_partition_dir` (D-260)."""
    data = _lire_json(save_dir / "module.json")
    partition = data.get("partition")
    return Path(partition) if partition else None


def _liens_cibles(partition_dir: Path | None, node_id: str | None) -> list[str]:
    """Ids-cibles des `liens` du nœud `node_id` de la partition -- liste vide
    si le nœud ou la partition est introuvable (jamais une erreur)."""
    if partition_dir is None or not node_id:
        return []
    node_path = partition_dir / "nodes" / f"{node_id}.md"
    if not node_path.exists():
        return []
    meta = _read_json_front(node_path)
    return [l.get("cible_id") for l in (meta.get("liens") or []) if l.get("cible_id")]


def verifier_position(etat_avant: dict, etat_apres: dict, partition_dir: Path | None) -> dict:
    pos_avant = (etat_avant.get("player") or {}).get("location")
    pos_apres = (etat_apres.get("player") or {}).get("location")
    if not pos_avant or not pos_apres:
        return {"pass": False,
                "detail": f"position illisible (avant={pos_avant!r}, apres={pos_apres!r})"}
    if pos_apres == pos_avant:
        return {"pass": True, "detail": f"position inchangée ({pos_apres})"}
    if pos_apres == _NOEUD_ENTREE and pos_avant != _NOEUD_ENTREE:
        return {"pass": False,
                "detail": f"retour à l'ouverture du module ({pos_avant} -> {pos_apres})"}
    if pos_apres in _liens_cibles(partition_dir, pos_avant):
        return {"pass": True,
                "detail": f"avancée par débouché valide de la partition ({pos_avant} -> {pos_apres})"}
    return {"pass": False,
            "detail": f"position hors partition/débouché connu ({pos_avant} -> {pos_apres})"}


def verifier_cliquet_visee(etat_avant: dict, etat_apres: dict) -> dict:
    rpg_avant = etat_avant.get("rpg") or {}
    rpg_apres = etat_apres.get("rpg") or {}
    cliquet_avant, cliquet_apres = rpg_avant.get("cliquet"), rpg_apres.get("cliquet")
    visee_avant, visee_apres = rpg_avant.get("visee_courante"), rpg_apres.get("visee_courante")
    if cliquet_avant == cliquet_apres and visee_avant == visee_apres:
        return {"pass": True,
                "detail": f"cliquet={cliquet_apres!r} visée={visee_apres!r} conservés"}
    return {"pass": False,
            "detail": f"cliquet {cliquet_avant!r} -> {cliquet_apres!r} ; "
                      f"visée {visee_avant!r} -> {visee_apres!r}"}


def _lire_events_pour_tour(events_path: Path, tour: int) -> list[dict]:
    out: list[dict] = []
    if not events_path.exists():
        return out
    for ligne in events_path.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            rec = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("turn") == tour:
            out.append(rec)
    return out


def verifier_pas_de_reintroduction(events_tour_n1: list[dict]) -> dict:
    for rec in events_tour_n1:
        if rec.get("type") == "scene_intro":
            return {"pass": False, "detail": "événement scene_intro journalisé au tour N+1"}
        loc = ((rec.get("env") or {}).get("deltas") or {}).get("location")
        if loc == _NOEUD_ENTREE:
            return {"pass": False,
                    "detail": f"delta location réintroduisant l'ouverture ({_NOEUD_ENTREE!r})"}
    return {"pass": True, "detail": "aucun scene_intro ni location = ouverture au tour N+1"}


def _lire_temoins(chemin: Path) -> list[str]:
    if not chemin.exists():
        return []
    return [m.strip() for m in
            re.findall(r"^TEMOIN:\s*(.+)$", chemin.read_text(encoding="utf-8"), re.MULTILINE)
            if m.strip()]


def verifier_temoin_absent(temoins_avant: list[str], textes: list[str]) -> dict:
    if not temoins_avant:
        return {"pass": True,
                "detail": "aucun mot-témoin à vérifier (etancheite.md absent/vide avant reset)"}
    corpus = "\n".join(textes)
    fuites = [t for t in temoins_avant if t in corpus]
    if fuites:
        return {"pass": False, "detail": f"mot-témoin d'avant reset retrouvé : {fuites}"}
    return {"pass": True,
            "detail": f"{len(temoins_avant)} mot-témoin(s) d'avant reset absent(s) du tour N+1"}


def evaluer(partie_dir: str | Path, tour: int) -> dict:
    """Rend les 4 verdicts `{"position": {...}, "cliquet_visee": {...},
    "reintroduction": {...}, "temoin": {...}}`, chacun `{"pass": bool,
    "detail": str}`."""
    partie_dir = Path(partie_dir)
    nn = f"{tour:02d}"
    nn1 = f"{tour + 1:02d}"
    save_dir = partie_dir / "save"

    etat_avant = _lire_json(partie_dir / f"etat-avant-reset-{nn}.json")
    etat_apres = _lire_json(save_dir / "state.json")
    partition_dir = _partition_dir(save_dir)

    r_position = verifier_position(etat_avant, etat_apres, partition_dir)
    r_cliquet = verifier_cliquet_visee(etat_avant, etat_apres)

    events_n1 = _lire_events_pour_tour(save_dir / "memory" / "events.jsonl", tour + 1)
    r_reintro = verifier_pas_de_reintroduction(events_n1)

    temoins_avant = _lire_temoins(partie_dir / f"etancheite-avant-reset-{nn}.md")
    textes = []
    for nom in (f"tour-{nn1}.md", f"action-{nn1}.md", f"prose-{nn1}.md"):
        chemin = partie_dir / nom
        if chemin.exists():
            textes.append(chemin.read_text(encoding="utf-8"))
    r_temoin = verifier_temoin_absent(temoins_avant, textes)

    return {"position": r_position, "cliquet_visee": r_cliquet,
            "reintroduction": r_reintro, "temoin": r_temoin}


_LIBELLES = (
    ("position", "Position (tour N+1 = tour N, ou débouché valide de la partition, "
                  "jamais un retour à l'ouverture)"),
    ("cliquet_visee", "Drapeaux du cliquet et visée courante conservés"),
    ("reintroduction", "Aucun événement de réintroduction de scène au tour N+1"),
    ("temoin", "Mot-témoin d'avant reset absent de tout ce que la session neuve écrit"),
)


def formater_markdown(tour: int, resultats: dict) -> str:
    nn = f"{tour:02d}"
    lignes = [f"# reset-{nn} — verdict (#330)", ""]
    n_pass = 0
    for cle, libelle in _LIBELLES:
        v = resultats[cle]
        statut = "PASS" if v["pass"] else "FAIL"
        if v["pass"]:
            n_pass += 1
        lignes.append(f"- {libelle} : {statut} — {v['detail']}")
    lignes.append("")
    if n_pass == len(_LIBELLES):
        lignes.append(f"Verdict global : VERT ({n_pass}/{len(_LIBELLES)})")
    else:
        lignes.append(f"Verdict global : ROUGE ({n_pass}/{len(_LIBELLES)})")
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("Usage : python tools/banc/verifier_reset.py <partie_dir> <tour>", file=sys.stderr)
        return 2
    partie_dir = Path(argv[0])
    try:
        tour = int(argv[1])
    except ValueError:
        print(f"REFUS : tour invalide ({argv[1]!r})", file=sys.stderr)
        return 2
    resultats = evaluer(partie_dir, tour)
    markdown = formater_markdown(tour, resultats)
    (partie_dir / f"reset-{tour:02d}.md").write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    return 0 if all(v["pass"] for v in resultats.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
