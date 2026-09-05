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

Étendu pour #276 (« lis la nuit » sans agent) : `calculer_rapport` /
`formater_rapport_markdown` produisent `rapport-nuit.md`, écrit par
`tools/banc/nuit.sh` à la fin de la nuit quelle que soit la raison d'arrêt
(voir `ecrire_rapport_nuit`/`finaliser_nuit` dans nuit.sh). Classement des
craquements par classe D-276 §4 (matériau / règle / Director / outillage) :
purement mécanique, lu dans le nom `craquement-<classe>-NN.md` — un fichier
dont le token de classe ne correspond à aucune des quatre compte « non
classé » (aujourd'hui la totalité des craquements mécaniques de nuit.sh :
fixture/lancement/nettoyage/timeout/prose-absente ne portent pas ces noms de
classe — la classification D-276 réelle est l'analyste N2, hors périmètre
#276). L'A/B Director (haiku ⊥ sonnet) relit le casting déjà écrit par
`ecrire_resume_run` dans `resume-run.md` (ligne `casting: ... director=<modele>(...)`).
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

# Force UTF-8 sur stdout/stderr quel que soit le terminal (Issue #279) : sous
# Windows, sys.stdout/stderr sont en cp1252 hors terminal UTF-8 explicite —
# `nuit.sh` redirige la sortie de ce script (rapport-nuit.md, nuit.md), et un
# rapport contenant « » ou des accents faisait tomber le calcul avant
# d'écrire quoi que ce soit (UnicodeEncodeError, nuit du 03/09). `reconfigure`
# peut lever si le flux n'en dispose pas (ex. capturé par un test) — sans
# conséquence, le flux garde alors son encodage d'origine.
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


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


# --- rapport-nuit.md (#276) --------------------------------------------------

# Classes reconnues D-276 §4 — tout le reste (y compris les types mécaniques
# actuels de nuit.sh : fixture/lancement/nettoyage/timeout/prose-absente)
# compte « non classé » (classification N2, hors périmètre #276).
CLASSES_D276 = {"materiau", "matériau", "regle", "règle", "director", "outillage"}
NON_CLASSE = "non classé"


def extraire_classe_craquement(chemin: Path) -> str:
    """Lit la classe dans le nom `craquement-<classe>-NN.md` — purement
    mécanique (aucun jugement) : un token qui ne correspond à aucune des
    classes D-276 §4 compte `NON_CLASSE`."""
    m = re.match(r"^craquement-(.+)-\d+\.md$", chemin.name)
    if not m:
        return NON_CLASSE
    classe = m.group(1).strip().lower()
    return classe if classe in CLASSES_D276 else NON_CLASSE


def lister_craquements(partie_dir: Path) -> list[Path]:
    return sorted(partie_dir.glob("craquement-*.md"))


def craquements_par_classe(run_dir: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in sorted(run_dir.glob("partie-*")):
        if not p.is_dir():
            continue
        for f in lister_craquements(p):
            classe = extraire_classe_craquement(f)
            out[classe] = out.get(classe, 0) + 1
    return out


def lire_director_modele(partie_dir: Path) -> str | None:
    """Relit le modèle Director castée pour cette partie depuis la ligne
    `casting: joueur=...(...) director=<modele>(...) narrateur=...` de
    `resume-run.md` (écrite par `ecrire_resume_run` dans nuit.sh)."""
    casting = lire_resume_run(partie_dir).get("casting", "")
    m = re.search(r"director=([a-zA-Z0-9_-]+)", casting)
    return m.group(1) if m else None


def stats_ab_director(run_dir: Path) -> dict[str, dict]:
    """Par modèle Director castée (haiku/sonnet) : tours moyens joués et
    craquements de classe `director` imputés à ce modèle."""
    par_modele: dict[str, dict] = {}
    for p in sorted(run_dir.glob("partie-*")):
        if not p.is_dir():
            continue
        modele = lire_director_modele(p)
        if not modele:
            continue
        d = par_modele.setdefault(modele, {"tours": [], "craquements_director": 0})
        d["tours"].append(tours_sans_craquement(p))
        for f in lister_craquements(p):
            if extraire_classe_craquement(f) == "director":
                d["craquements_director"] += 1
    out: dict[str, dict] = {}
    for modele, d in par_modele.items():
        out[modele] = {
            "tours_moyen": round(statistics.mean(d["tours"]), 1) if d["tours"] else 0,
            "craquements_director": d["craquements_director"],
        }
    return out


def pires_craquements(run_dir: Path, n: int = 3) -> list[str]:
    """Jusqu'à `n` pointeurs (chemins) vers les `tour-NN.md` des craquements
    les plus récents du run (le seul ordre disponible sans jugement — le
    tri par « gravité » est de l'analyse N2, hors périmètre #276). Si le
    `tour-NN.md` correspondant n'existe pas, pointe le craquement lui-même."""
    tous: list[Path] = []
    for p in sorted(run_dir.glob("partie-*")):
        if p.is_dir():
            tous.extend(lister_craquements(p))
    tous.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    pointeurs: list[str] = []
    for f in tous[:n]:
        m = re.match(r"^craquement-.+-(\d+)\.md$", f.name)
        if m:
            tour_path = f.parent / f"tour-{m.group(1)}.md"
            pointeurs.append(str(tour_path) if tour_path.exists() else str(f))
        else:
            pointeurs.append(str(f))
    return pointeurs


def calculer_rapport(run_dir: Path, raison_arret: str, duree_totale_s: int,
                      limite_session: str) -> dict:
    """Calcule `rapport-nuit.md` (§ « Livrer » 2 de #276) — étend `calculer`
    sans dupliquer, sur le même `run_dir`."""
    m = calculer(run_dir)
    tours_par_partie = [tours_sans_craquement(p)
                         for p in sorted(run_dir.glob("partie-*")) if p.is_dir()]
    return {
        "parties_finies": m["parties_finies"],
        "parties_lancees": m["parties_lancees"],
        "duree_totale_s": duree_totale_s,
        "raison_arret": raison_arret,
        "tours_median": m["tours_median"],
        "tours_min": min(tours_par_partie) if tours_par_partie else 0,
        "tours_max": max(tours_par_partie) if tours_par_partie else 0,
        "craquements_par_classe": craquements_par_classe(run_dir),
        "ab_director": stats_ab_director(run_dir),
        "limite_session": limite_session,
        "pires_craquements": pires_craquements(run_dir),
    }


def formater_rapport_markdown(r: dict) -> str:
    """Rend `rapport-nuit.md` (dix à vingt lignes, forme fixe #276)."""
    lignes = [
        "# rapport-nuit",
        "",
        f"- Parties finies / lancées : {r['parties_finies']} / {r['parties_lancees']}",
        f"- Durée totale : {r['duree_totale_s']}s",
        f"- Raison d'arrêt : {r['raison_arret']}",
        "- Tours sans craquement par partie (médiane / min / max) : "
        f"{r['tours_median']} / {r['tours_min']} / {r['tours_max']}",
        "- Craquements par classe (D-276 §4) :",
    ]
    if r["craquements_par_classe"]:
        for classe, n in sorted(r["craquements_par_classe"].items()):
            lignes.append(f"  - {classe} : {n}")
    else:
        lignes.append("  - (aucun)")
    lignes.append("- A/B Director (haiku ⊥ sonnet) :")
    if r["ab_director"]:
        for modele, d in sorted(r["ab_director"].items()):
            lignes.append(f"  - {modele} : tours moyens {d['tours_moyen']}, "
                           f"craquements imputés au Director {d['craquements_director']}")
    else:
        lignes.append("  - (aucune partie castée)")
    lignes.append(f"- Limite de session touchée : {r['limite_session']}")
    lignes.append(f"- Budget consommé : durée {r['duree_totale_s']}s (jetons non mesurés)")
    lignes.append("- Pires craquements (jusqu'à 3, ordre : plus récent d'abord) :")
    if r["pires_craquements"]:
        for chemin in r["pires_craquements"]:
            lignes.append(f"  - {chemin}")
    else:
        lignes.append("  - (aucun)")
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    usage = (
        "Usage : python tools/banc/metriques_nuit.py <run_dir>\n"
        "        python tools/banc/metriques_nuit.py <run_dir> rapport "
        "<raison_arret> <duree_totale_s> <limite_session:oui|non>"
    )
    if len(argv) == 1:
        run_dir = Path(argv[0])
        if not run_dir.is_dir():
            print(f"REFUS : dossier de run introuvable ({run_dir})", file=sys.stderr)
            return 1
        print(formater_markdown(calculer(run_dir)), end="")
        return 0
    if len(argv) == 5 and argv[1] == "rapport":
        run_dir = Path(argv[0])
        if not run_dir.is_dir():
            print(f"REFUS : dossier de run introuvable ({run_dir})", file=sys.stderr)
            return 1
        raison_arret, duree_s, limite_session = argv[2], argv[3], argv[4]
        try:
            duree_totale_s = int(duree_s)
        except ValueError:
            print(f"REFUS : durée totale invalide ({duree_s})", file=sys.stderr)
            return 1
        rapport = calculer_rapport(run_dir, raison_arret, duree_totale_s, limite_session)
        print(formater_rapport_markdown(rapport), end="")
        return 0
    print(usage, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
