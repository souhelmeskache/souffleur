"""tools/banc/metriques_nuit.py — parseur des métriques §3 de #201 pour le
banc de nuit (#260), appelé par `tools/banc/nuit.sh` (jamais un LLM : lecture
de fichiers déjà écrits, calcul déterministe).

Métriques rendues (fonction `calculer`) :
- `tours_median` : médiane des tours sans craquement par partie (compte de
  `prose-NN.md` présents dans chaque dossier de partie).
- `parties_finies` / `parties_lancees` : nombre de `resume-run.md` marquant
  `fin_atteinte: O`, sur le nombre total de dossiers `partie-*` du run.
- `refus_outil` : entrées `events.jsonl` de type `attack`/`roll_check`
  portant une clé `error`. **Aujourd'hui aucun writer du moteur ne journalise
  ces refus dans `events.jsonl`** (`attack`/`roll_check` rendent
  `{"error": ...}` au Director sans `append_event_log`, cf.
  `coderain/mcp/jets_combat.py`) — ce compteur reste donc à 0 tant que ça n'a
  pas changé côté moteur, ce qui est HORS PÉRIMÈTRE #260 (« aucune
  modification du moteur »). Écrit quand même pour rester correct si un jour
  ce writer existe, plutôt que supposé impossible à coder.
- `bouchages` : entrées `events.jsonl` de type `bouchage_enregistre` (D-275,
  `coderain/mcp/bouchage.py::enregistrer_bouchage` — celui-ci journalise
  réellement, donc ce compteur est fiable dès aujourd'hui).
- `combats_sous_systeme` : entrées `events.jsonl` de type `start_combat`
  (dnd5e-engine, `coderain/mcp/jets_combat.py::start_combat`) — même réserve
  que `refus_outil` : non journalisé aujourd'hui, compteur à 0 tant que ça
  n'a pas changé côté moteur.
- `combats_hors_sous_systeme` : entrées `events.jsonl` dont l'enveloppe
  (`env.deltas.enemies`) porte un delta d'ennemi — la seule trace qu'un
  échange de coups hors dnd5e-engine (apply_envelope, ex. `attack`) laisse
  aujourd'hui dans le journal.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def lire_events(events_path: Path) -> list[dict]:
    """Lit un `events.jsonl` ; une ligne malformée est ignorée (jamais
    fatale — même discipline que `MemoryStore.truncate_event_log`).
    Fichier absent : liste vide (une partie qui n'a jamais tourné, ou
    craquée avant le premier tour, n'a simplement rien à compter)."""
    if not events_path.exists():
        return []
    out = []
    for ligne in events_path.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            rec = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def compter_refus_outil(events: list[dict]) -> int:
    return sum(1 for rec in events
               if rec.get("type") in ("attack", "roll_check") and rec.get("error"))


def compter_bouchages(events: list[dict]) -> int:
    return sum(1 for rec in events if rec.get("type") == "bouchage_enregistre")


def compter_combats(events: list[dict]) -> dict:
    sous_systeme = sum(1 for rec in events if rec.get("type") == "start_combat")
    hors = 0
    for rec in events:
        env = rec.get("env")
        if isinstance(env, dict) and isinstance(env.get("deltas"), dict) \
                and env["deltas"].get("enemies"):
            hors += 1
    return {"sous_systeme": sous_systeme, "hors_sous_systeme": hors}


def tours_sans_craquement(partie_dir: Path) -> int:
    """Nombre de `prose-NN.md` écrits dans le dossier d'une partie — le
    compte de tours effectivement joués avant que la partie ne s'arrête
    (craquement, fin de module, ou plafond -Tours atteint)."""
    return len(list(partie_dir.glob("prose-*.md")))


def lire_resume_run(partie_dir: Path) -> dict:
    """Relit les deux champs de `resume-run.md` que `calculer` utilise
    (`fin_atteinte`, sous forme `champ: valeur` en tête de ligne) — parseur
    tolérant, jamais fatal sur un fichier absent ou incomplet."""
    chemin = partie_dir / "resume-run.md"
    if not chemin.exists():
        return {}
    out: dict[str, str] = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if ":" not in ligne:
            continue
        cle, _, valeur = ligne.partition(":")
        out[cle.strip().lower()] = valeur.strip()
    return out


def calculer(run_dir: Path) -> dict:
    """Calcule toutes les métriques §3 de #201 pour un run `bench/nuit-*/`."""
    parties_dirs = sorted(p for p in run_dir.glob("partie-*") if p.is_dir())
    tours_par_partie = [tours_sans_craquement(p) for p in parties_dirs]
    finies = sum(1 for p in parties_dirs
                 if lire_resume_run(p).get("fin_atteinte", "").upper().startswith("O"))

    events_tous: list[dict] = []
    for p in parties_dirs:
        events_tous.extend(lire_events(p / "save" / "memory" / "events.jsonl"))

    combats = compter_combats(events_tous)
    return {
        "parties_lancees": len(parties_dirs),
        "parties_finies": finies,
        "tours_median": statistics.median(tours_par_partie) if tours_par_partie else 0,
        "refus_outil": compter_refus_outil(events_tous),
        "bouchages": compter_bouchages(events_tous),
        "combats_sous_systeme": combats["sous_systeme"],
        "combats_hors_sous_systeme": combats["hors_sous_systeme"],
    }


def formater_markdown(m: dict) -> str:
    """Rend les métriques en lignes Markdown prêtes à coller dans `nuit.md`."""
    return (
        f"- Parties finies / lancées : {m['parties_finies']} / {m['parties_lancees']}\n"
        f"- Tours sans craquement par partie (médiane) : {m['tours_median']}\n"
        f"- Refus d'outil (`attack`/`roll_check`, events.jsonl) : {m['refus_outil']}\n"
        f"- Bouchages enregistrés (D-275) : {m['bouchages']}\n"
        f"- Combats dans le sous-système (`start_combat`) : {m['combats_sous_systeme']}\n"
        f"- Combats hors sous-système (deltas d'ennemi hors dnd5e-engine) : "
        f"{m['combats_hors_sous_systeme']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("Usage : python tools/banc/metriques_nuit.py <run_dir>", file=sys.stderr)
        return 1
    run_dir = Path(argv[0])
    if not run_dir.is_dir():
        print(f"REFUS : dossier de run introuvable ({run_dir})", file=sys.stderr)
        return 1
    m = calculer(run_dir)
    print(formater_markdown(m), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
