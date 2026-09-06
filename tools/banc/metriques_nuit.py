"""tools/banc/metriques_nuit.py — parseur des métriques §3 de #201 pour le
banc de nuit (#260), appelé par `tools/banc/nuit.sh` (jamais un LLM : lecture
de fichiers déjà écrits, calcul déterministe).

Métriques rendues (fonction `calculer`) :
- `tours_median` : médiane des tours sans craquement par partie (compte de
  `prose-NN.md` présents dans chaque dossier de partie).
- `parties_finies` / `parties_lancees` : nombre de `resume-run.md` marquant
  `fin_atteinte: O`, sur le nombre total de dossiers `partie-*` du run.
- `parties_completes` / `parties_mortes` / `parties_frontiere` : trois
  sous-ensembles DISJOINTS de `parties_finies`, lus dans `raison_arret`
  (`fin_module` / `mort` / `frontiere` — D-282, Issue #311 : la garde du
  guichet a refusé un `location` hors partition, `nuit.sh` arrête la BOUCLE
  DU BANC au signal, `fin_atteinte: O`). Ceci n'arrête que la mesure
  mécanique du banc — la clôture de séance EN JEU (I-093) reste une brique
  séparée, hors périmètre #311.
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
- `paires` : nombre de paires Director/joueur DISTINCTES ayant joué dans ce
  run (#282, banc de nuit en parallèle) — relu dans la ligne `paire: NN`
  que `nuit.sh::ecrire_resume_run` écrit dans chaque `resume-run.md` ("01"
  en séquentiel, une paire par slot en parallèle). Une partie sans
  `resume-run.md` (interrompue avant sa fin) ne compte pour aucune paire ;
  1 par défaut si aucune partie n'a encore de `resume-run.md`.
- `timeouts_joueur` / `timeouts_mj` : nombre de `craquement-timeout-NN.md`
  imputés à chaque rôle (Issue #299 — départager « Haiku se tait » de « le
  banc attend mal ») — lu dans la ligne `agent : joueur (...)`/`agent : mj
  (...)` que `nuit.sh::attendre_fichier` écrit désormais en tête de chaque
  craquement timeout. Un craquement-timeout sans cette ligne (run d'avant
  #299) compte « non classé » côté rôle, ni joueur ni mj.
- `processus_sortis_joueur` / `processus_sortis_mj` : nombre de
  `craquement-processus-sorti-NN.md` imputés à chaque rôle (Issue #305 —
  « muet » (#299, timeout) et « sorti » (le process claude a quitté, pane
  vivant) sont deux diagnostics distincts que le banc doit compter à part) —
  même lecture de la ligne `agent : joueur (...)`/`agent : mj (...)` que les
  timeouts ci-dessus, sur ce nom de craquement.

Étendu pour #281 (garde monde vide) : `lire_module_info` lit `module.json` +
compte lieux/PNJ dans la save de la première partie qui en porte un — la
ligne « Module : <titre>, <n> lieux, <n> PNJ » en tête de `rapport-nuit.md`
rend visible, dans le rapport lui-même, qu'une nuit a bien joué un module et
pas un monde vide (#281, constat N1 du 05/09).

Étendu pour #276 (« lis la nuit » sans agent) : `calculer_rapport` /
`formater_rapport_markdown` produisent `rapport-nuit.md`, écrit par
`tools/banc/nuit.sh` à la fin de la nuit quelle que soit la raison d'arrêt
(voir `ecrire_rapport_nuit`/`finaliser_nuit` dans nuit.sh). Classement des
craquements par classe D-276 §4 (matériau / règle / Director / outillage) :
purement mécanique, lu dans le nom `craquement-<classe>-NN.md` — un fichier
dont le token de classe ne correspond à aucune des quatre compte « non
classé » (aujourd'hui la totalité des craquements mécaniques de nuit.sh :
fixture/lancement/nettoyage/timeout/prose-absente/prose-polluee ne portent pas ces noms de
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

# Import `coderain.memory` (#281, ligne « module : ... » du rapport) —
# sys.path résolu depuis __file__, jamais depuis le cwd : ce script est
# appelé par nuit.sh sans `cd "$REPO_ROOT"` préalable pour cet appel.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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


def lire_paquets_tokens(events: list[dict]) -> list[int]:
    """Jetons estimés (`tokens_est`) de chaque paquet journalisé ce run
    (I-469 §F0.4, Issue #332) — `mcp_server._log_paquet`, entrées `type:
    paquet` de `events.jsonl` (`assemble_context_to_file`/`paquet_narrateur`).
    Une entrée sans `tokens_est` entier n'est jamais devinée : ignorée."""
    out = []
    for rec in events:
        if rec.get("type") != "paquet":
            continue
        v = rec.get("tokens_est")
        if isinstance(v, int) and not isinstance(v, bool):
            out.append(v)
    return out


def fenetre_mj_tour1_dernier(events: list[dict]) -> tuple[int | None, int | None]:
    """Remplissage de fenêtre MJ (%) au tour 1 et au dernier tour journalisé
    (I-469 §F0.4, Issue #332) — entrées `type: fenetre, role: mj` de
    `events.jsonl` (`nuit.sh::journaliser_fenetre`), triées par `turn`. Un
    `pct` non entier (« non lisible ») ne compte tout simplement pas comme un
    tour lisible ; `None` si aucune entrée MJ n'a de `pct` lisible."""
    releves = []
    for rec in events:
        if rec.get("type") != "fenetre" or rec.get("role") != "mj":
            continue
        pct = rec.get("pct")
        turn = rec.get("turn")
        if isinstance(pct, int) and not isinstance(pct, bool) \
                and isinstance(turn, int) and not isinstance(turn, bool):
            releves.append((turn, pct))
    if not releves:
        return None, None
    releves.sort(key=lambda t: t[0])
    tour1 = next((pct for turn, pct in releves if turn == 1), None)
    dernier = releves[-1][1]
    return tour1, dernier


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


def _compter_craquements_par_role(run_dir: Path, motif_glob: str) -> dict:
    """Compte les craquements dont le nom suit `motif_glob` (ex.
    `craquement-timeout-*.md`) par rôle — lit la ligne `agent : joueur
    (...)`/`agent : mj (...)` écrite par `nuit.sh::attendre_fichier` en tête
    du détail. Fichier absent de cette ligne : ni joueur ni mj, jamais
    deviné. Partagée par #299 (timeouts) et #305 (processus sortis) — même
    forme de craquement, seul le nom de classe change."""
    joueur = mj = 0
    for p in sorted(run_dir.glob("partie-*")):
        if not p.is_dir():
            continue
        for f in sorted(p.glob(motif_glob)):
            try:
                contenu = f.read_text(encoding="utf-8")
            except OSError:
                continue
            m = re.search(r"^agent : (joueur|mj) ", contenu, re.MULTILINE)
            if not m:
                continue
            if m.group(1) == "joueur":
                joueur += 1
            else:
                mj += 1
    return {"joueur": joueur, "mj": mj}


def compter_timeouts_par_role(run_dir: Path) -> dict:
    """Compte les `craquement-timeout-NN.md` par rôle (#299)."""
    return _compter_craquements_par_role(run_dir, "craquement-timeout-*.md")


def compter_processus_sortis_par_role(run_dir: Path) -> dict:
    """Compte les `craquement-processus-sorti-NN.md` par rôle (#305) —
    diagnostic distinct du timeout (#299) : le processus claude a quitté
    (pane vivant, « Resume this session with: claude --resume <id> »), pas
    seulement silencieux."""
    return _compter_craquements_par_role(run_dir, "craquement-processus-sorti-*.md")


def lire_noeud(partie_dir: Path) -> str | None:
    """Relit le nœud atteint par cette partie (#306) — `noeud_final` si la
    partie a fini le module (`fin_atteinte: O`), `noeud_atteint` sinon
    (tours_max, craquement, FinA) : la mesure de PROGRESSION que
    `nuit.sh::ecrire_resume_run` écrit à toute sortie de partie, pas
    seulement fin atteinte. None si le champ est absent (run d'avant #306)
    ou vaut `(aucun)` (aucune position lisible sur cette save)."""
    r = lire_resume_run(partie_dir)
    noeud = r.get("noeud_final") or r.get("noeud_atteint")
    if not noeud or noeud == "(aucun)":
        return None
    return noeud


def tours_par_noeud(parties_dirs: list[Path]) -> dict[str, float]:
    """Tours joués MOYENS par nœud atteint (#306) — pour chaque nœud vu en
    sortie d'au moins une partie (`lire_noeud`), la moyenne des tours joués
    par les parties qui s'y sont arrêtées. La mesure de progression demandée
    par #306 : combien de tours il faut, en moyenne, pour atteindre CE
    nœud."""
    par_noeud: dict[str, list[int]] = {}
    for p in parties_dirs:
        noeud = lire_noeud(p)
        if noeud is None:
            continue
        par_noeud.setdefault(noeud, []).append(tours_sans_craquement(p))
    return {n: round(statistics.mean(v), 1) for n, v in par_noeud.items()}


def compter_paires(parties_dirs: list[Path]) -> int:
    """Nombre de paires Director/joueur distinctes ayant joué dans ce run
    (#282) — lu dans la ligne `paire: NN` de chaque `resume-run.md`. 1 par
    défaut si aucune partie n'a encore de `resume-run.md` (run tout juste
    démarré, ou entièrement craqué avant la première écriture)."""
    paires_vues = {lire_resume_run(p).get("paire") for p in parties_dirs}
    paires_vues.discard(None)
    return len(paires_vues) if paires_vues else 1


def calculer(run_dir: Path) -> dict:
    """Calcule toutes les métriques §3 de #201 pour un run `bench/nuit-*/`."""
    parties_dirs = sorted(p for p in run_dir.glob("partie-*") if p.is_dir())
    tours_par_partie = [tours_sans_craquement(p) for p in parties_dirs]
    finies = sum(1 for p in parties_dirs
                 if lire_resume_run(p).get("fin_atteinte", "").upper().startswith("O"))
    # Distinction #306 : « parties complètes » (nœud terminal de la
    # partition, raison_arret: fin_module) vs « parties mortes » (proxy
    # historique, raison_arret: mort) — deux sous-ensembles disjoints de
    # `finies` ci-dessus, lus dans raison_arret (absent = run d'avant #306,
    # compte pour ni l'un ni l'autre).
    completes = sum(1 for p in parties_dirs
                     if lire_resume_run(p).get("raison_arret", "") == "fin_module")
    mortes = sum(1 for p in parties_dirs
                 if lire_resume_run(p).get("raison_arret", "") == "mort")
    # frontiere (D-282, Issue #311) : la garde du guichet a refusé un
    # `location` hors partition — troisième sous-ensemble disjoint des deux
    # ci-dessus. `nuit.sh` arrête la boucle du banc au signal (fin_atteinte:
    # O, raison_arret: frontiere) — même geste mécanique que mort/fin_module,
    # la clôture de séance EN JEU (I-093) restant une brique séparée.
    frontieres = sum(1 for p in parties_dirs
                     if lire_resume_run(p).get("raison_arret", "") == "frontiere")

    events_tous: list[dict] = []
    for p in parties_dirs:
        events_tous.extend(lire_events(p / "save" / "memory" / "events.jsonl"))

    combats = compter_combats(events_tous)
    timeouts = compter_timeouts_par_role(run_dir)
    processus_sortis = compter_processus_sortis_par_role(run_dir)
    # Paquet (I-469 §F0.4, #332) — jetons estimés, tous les paquets de la
    # nuit confondus (pas encore ventilé par partie ; voir
    # `paquet_fenetre_par_partie` pour la colonne par partie de rapport-nuit).
    paquets_tokens = lire_paquets_tokens(events_tous)
    return {
        "parties_lancees": len(parties_dirs),
        "parties_finies": finies,
        "parties_completes": completes,
        "parties_mortes": mortes,
        "parties_frontiere": frontieres,
        "paires": compter_paires(parties_dirs),
        "tours_median": statistics.median(tours_par_partie) if tours_par_partie else 0,
        "refus_outil": compter_refus_outil(events_tous),
        "bouchages": compter_bouchages(events_tous),
        "combats_sous_systeme": combats["sous_systeme"],
        "combats_hors_sous_systeme": combats["hors_sous_systeme"],
        "timeouts_joueur": timeouts["joueur"],
        "timeouts_mj": timeouts["mj"],
        "processus_sortis_joueur": processus_sortis["joueur"],
        "processus_sortis_mj": processus_sortis["mj"],
        "tours_par_noeud": tours_par_noeud(parties_dirs),
        "paquet_median": round(statistics.median(paquets_tokens)) if paquets_tokens else None,
        "paquet_max": max(paquets_tokens) if paquets_tokens else None,
    }


def formater_markdown(m: dict) -> str:
    """Rend les métriques en lignes Markdown prêtes à coller dans `nuit.md`."""
    lignes = (
        f"- Parties finies / lancées : {m['parties_finies']} / {m['parties_lancees']}\n"
        f"- Parties complètes (fin_module) / mortes (mort) / frontière "
        f"(position hors partition, D-282) : {m['parties_completes']} / "
        f"{m['parties_mortes']} / {m['parties_frontiere']} (#306, #311)\n"
        f"- Paires simultanées : {m['paires']}\n"
        f"- Tours sans craquement par partie (médiane) : {m['tours_median']}\n"
        f"- Refus d'outil (`attack`/`roll_check`, events.jsonl) : {m['refus_outil']}\n"
        f"- Bouchages enregistrés (D-275) : {m['bouchages']}\n"
        f"- Combats dans le sous-système (`start_combat`) : {m['combats_sous_systeme']}\n"
        f"- Combats hors sous-système (deltas d'ennemi hors dnd5e-engine) : "
        f"{m['combats_hors_sous_systeme']}\n"
        f"- Timeouts par rôle (#299) : joueur {m['timeouts_joueur']} / mj {m['timeouts_mj']}\n"
        f"- Processus sortis par rôle (#305) : joueur {m['processus_sortis_joueur']} / "
        f"mj {m['processus_sortis_mj']}\n"
        "- Tours joués (moyenne) par nœud atteint (#306) : "
    )
    if m["tours_par_noeud"]:
        lignes += ", ".join(f"{n} {t}" for n, t in sorted(m["tours_par_noeud"].items())) + "\n"
    else:
        lignes += "(aucun)\n"
    return lignes


# --- rapport-nuit.md (#276) --------------------------------------------------

# Classes reconnues D-276 §4 — tout le reste (y compris les types mécaniques
# actuels de nuit.sh : fixture/lancement/nettoyage/timeout/prose-absente/prose-polluee)
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


def mesures_partie(partie_dir: Path) -> dict:
    """Paquet médian/max (jetons estimés) + fenêtre MJ tour 1/dernier tour
    pour UNE partie (I-469 §F0.4, Issue #332) — tranche la contradiction
    « 83% au tour 1 » (Haiku, lu à l'écran) ⊥ « 53k » (I-467) par un chiffre
    lu dans `events.jsonl`/l'écran, jamais une hypothèse. `None`/`0` quand la
    partie n'a aucune entrée du type correspondant (run d'avant cette lane)."""
    events = lire_events(partie_dir / "save" / "memory" / "events.jsonl")
    tokens = lire_paquets_tokens(events)
    tour1, dernier = fenetre_mj_tour1_dernier(events)
    return {
        "paquet_median": round(statistics.median(tokens)) if tokens else None,
        "paquet_max": max(tokens) if tokens else None,
        "fenetre_tour1": tour1,
        "fenetre_dernier": dernier,
    }


def paquet_fenetre_par_partie(run_dir: Path) -> dict[str, dict]:
    """`mesures_partie` pour chaque `partie-NN/` du run, clé = nom du
    dossier (#332 — colonnes du rapport « par partie »)."""
    out: dict[str, dict] = {}
    for p in sorted(run_dir.glob("partie-*")):
        if p.is_dir():
            out[p.name] = mesures_partie(p)
    return out


def stats_ab_director(run_dir: Path) -> dict[str, dict]:
    """Par modèle Director castée (haiku/sonnet) : tours moyens joués,
    craquements de classe `director` imputés à ce modèle, et paquet médian
    (jetons estimés, toutes les parties castées à ce modèle confondues) —
    la ligne de synthèse A/B qui tranche #332 quand les deux modèles ont
    joué dans ce run."""
    par_modele: dict[str, dict] = {}
    for p in sorted(run_dir.glob("partie-*")):
        if not p.is_dir():
            continue
        modele = lire_director_modele(p)
        if not modele:
            continue
        d = par_modele.setdefault(
            modele, {"tours": [], "craquements_director": 0, "tokens": []})
        d["tours"].append(tours_sans_craquement(p))
        for f in lister_craquements(p):
            if extraire_classe_craquement(f) == "director":
                d["craquements_director"] += 1
        d["tokens"].extend(lire_paquets_tokens(
            lire_events(p / "save" / "memory" / "events.jsonl")))
    out: dict[str, dict] = {}
    for modele, d in par_modele.items():
        out[modele] = {
            "tours_moyen": round(statistics.mean(d["tours"]), 1) if d["tours"] else 0,
            "craquements_director": d["craquements_director"],
            "paquet_median": round(statistics.median(d["tokens"])) if d["tokens"] else None,
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


def compter_resets(run_dir: Path) -> dict:
    """Compte les verdicts de reset (#330, D-264) : chaque `reset-NN.md`
    (écrit par `tools/banc/verifier_reset.py`, appelé par `nuit.sh` juste
    après le tour N+1 d'un `-Reset N`) porte une ligne `Verdict global :
    VERT (4/4)` ou `ROUGE (n/4)` en fin de fichier -- lue mécaniquement,
    jamais un jugement. Rend `{"joues": <total>, "verts": <VERT (4/4)>}`."""
    joues = verts = 0
    for p in sorted(run_dir.glob("partie-*")):
        if not p.is_dir():
            continue
        for f in sorted(p.glob("reset-*.md")):
            joues += 1
            try:
                contenu = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if re.search(r"^Verdict global : VERT \(4/4\)$", contenu, re.MULTILINE):
                verts += 1
    return {"joues": joues, "verts": verts}


def lire_module_info(run_dir: Path) -> dict | None:
    """Lit `module.json` + compte lieux/PNJ dans la save de la première
    partie du run qui en porte un (#281) — chaque partie copie fraîchement
    la même save source, son module est donc représentatif de la nuit
    entière. None si aucune partie n'a de `save/module.json` lisible (avant
    #281 ; ou lancement raté dès la partie 00) — le rapport le nomme alors
    plutôt que d'inventer un module, la garde de `nuit.sh` REFUSANT déjà en
    amont une save sans module (voir README, § « Save de DÉPART gelée »)."""
    from coderain.memory import MemoryStore
    for p in sorted(run_dir.glob("partie-*")):
        save_dir = p / "save"
        module_path = save_dir / "module.json"
        if not module_path.exists():
            continue
        try:
            module_ptr = json.loads(module_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        store = MemoryStore(save_dir)
        return {"titre": module_ptr.get("titre", "?"),
                "lieux": len(store.entries("locations.md")),
                "pnj": len(store.entries("characters.md"))}
    return None


def calculer_rapport(run_dir: Path, raison_arret: str, duree_totale_s: int,
                      limite_session: str) -> dict:
    """Calcule `rapport-nuit.md` (§ « Livrer » 2 de #276) — étend `calculer`
    sans dupliquer, sur le même `run_dir`."""
    m = calculer(run_dir)
    tours_par_partie = [tours_sans_craquement(p)
                         for p in sorted(run_dir.glob("partie-*")) if p.is_dir()]
    return {
        "module": lire_module_info(run_dir),
        "parties_finies": m["parties_finies"],
        "parties_completes": m["parties_completes"],
        "parties_mortes": m["parties_mortes"],
        "parties_lancees": m["parties_lancees"],
        "paires": m["paires"],
        "tours_par_noeud": m["tours_par_noeud"],
        "duree_totale_s": duree_totale_s,
        "raison_arret": raison_arret,
        "tours_median": m["tours_median"],
        "tours_min": min(tours_par_partie) if tours_par_partie else 0,
        "tours_max": max(tours_par_partie) if tours_par_partie else 0,
        "craquements_par_classe": craquements_par_classe(run_dir),
        "ab_director": stats_ab_director(run_dir),
        "paquet_fenetre_par_partie": paquet_fenetre_par_partie(run_dir),
        "paquet_median": m["paquet_median"],
        "paquet_max": m["paquet_max"],
        "limite_session": limite_session,
        "pires_craquements": pires_craquements(run_dir),
        "timeouts_joueur": m["timeouts_joueur"],
        "timeouts_mj": m["timeouts_mj"],
        "processus_sortis_joueur": m["processus_sortis_joueur"],
        "processus_sortis_mj": m["processus_sortis_mj"],
        "resets": compter_resets(run_dir),
    }


def formater_rapport_markdown(r: dict) -> str:
    """Rend `rapport-nuit.md` (dix à vingt lignes, forme fixe #276)."""
    module = r.get("module")
    module_ligne = (
        f"- Module : {module['titre']}, {module['lieux']} lieux, "
        f"{module['pnj']} PNJ" if module else
        "- Module : aucun (save sans module.json — voir garde nuit.sh, #281)")
    lignes = [
        "# rapport-nuit",
        "",
        module_ligne,
        f"- Parties finies / lancées : {r['parties_finies']} / {r['parties_lancees']}",
        f"- Parties complètes (fin_module) / mortes (mort) : "
        f"{r['parties_completes']} / {r['parties_mortes']} (#306)",
        f"- Paires simultanées : {r['paires']}",
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
            paquet = ("non mesuré" if d["paquet_median"] is None
                      else f"{d['paquet_median']} jetons")
            lignes.append(f"  - {modele} : tours moyens {d['tours_moyen']}, "
                           f"craquements imputés au Director {d['craquements_director']}, "
                           f"paquet médian {paquet}")
        if len(r["ab_director"]) >= 2:
            modeles = sorted(r["ab_director"].items())
            (m1, d1), (m2, d2) = modeles[0], modeles[1]
            if d1["paquet_median"] is not None and d2["paquet_median"] is not None:
                lignes.append(f"  - synthèse : paquet médian {m1} {d1['paquet_median']} "
                              f"jetons ⊥ {m2} {d2['paquet_median']} jetons (#332)")
    else:
        lignes.append("  - (aucune partie castée)")
    lignes.append(f"- Timeouts par rôle (#299) : joueur {r['timeouts_joueur']} / "
                  f"mj {r['timeouts_mj']}")
    lignes.append(f"- Processus sortis par rôle (#305) : joueur {r['processus_sortis_joueur']} / "
                  f"mj {r['processus_sortis_mj']}")
    lignes.append(f"- Resets (#330, D-264) : {r['resets']['joues']} joués, "
                  f"{r['resets']['verts']} verts (4/4)")
    lignes.append("- Tours joués (moyenne) par nœud atteint (#306) :")
    if r["tours_par_noeud"]:
        for noeud, t in sorted(r["tours_par_noeud"].items()):
            lignes.append(f"  - {noeud} : {t}")
    else:
        lignes.append("  - (aucun)")
    lignes.append(f"- Limite de session touchée : {r['limite_session']}")
    paquet_global = ("non mesuré" if r["paquet_median"] is None
                     else f"médian {r['paquet_median']} / max {r['paquet_max']} jetons")
    lignes.append(f"- Budget consommé : durée {r['duree_totale_s']}s, paquet {paquet_global}")
    lignes.append("- Paquet / fenêtre MJ par partie (I-469 §F0.4, #332) :")
    if r["paquet_fenetre_par_partie"]:
        for nom, mp in sorted(r["paquet_fenetre_par_partie"].items()):
            paquet = ("non mesuré" if mp["paquet_median"] is None
                      else f"médian {mp['paquet_median']} / max {mp['paquet_max']} jetons")
            t1 = "non lisible" if mp["fenetre_tour1"] is None else f"{mp['fenetre_tour1']}%"
            td = "non lisible" if mp["fenetre_dernier"] is None else f"{mp['fenetre_dernier']}%"
            lignes.append(f"  - {nom} : paquet {paquet} ; fenêtre mj tour 1 {t1} / dernier tour {td}")
    else:
        lignes.append("  - (aucune partie)")
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
