"""Generate the DIRECTING BRIEF shipped inside every Partition (D-177).

Two tiers, as normed by the meta:
  1. GABARIT TRANSVERSE — identical for every module, containing ONLY
     already-actée rules. The kit never invents here.
  2. INSTANCE ZONE — minimal per-module facts, all derived from conversion
     output (counts, structures). No creation.
The Director remains an organ of the coderain engine: this file is the
instruction sheet at its door, not the organ itself.
"""
from __future__ import annotations

import json
from pathlib import Path

GABARIT = """# BRIEF DE DIRECTION — {titre}

*Pièce standard de la Partition (`MRPG-D-177`). Gabarit transverse v1 +
instanciation du {date}. S'adresse au Director ; le joueur ne lit ni ce
fichier ni les nodes brutes.*

## GABARIT TRANSVERSE (identique à toutes les partitions)

1. **Les nodes sont des notes privées de MJ** — tu t'en sers pour décrire,
   tu ne les recopies jamais. Le texte montré au joueur est une narration
   à la deuxième personne du présent.
2. **Aucun numéro de paragraphe, AUCUN menu de choix, AUCUN carrefour.**
   Interdit au joueur d'entendre « go to 12 » ou « paragraphe 19 ». Interdit
   d'énumérer les options, interdit de cadrer la fin de scène comme un
   CHOIX (« deux voies s'offrent à toi », « où décides-tu d'aller ? »).
   Le monde existe AVANT le joueur : les autres passages, les autres pièces,
   les autres directions sont du DÉCOR qui reste là sans être annoncés.
   Une scène se termine sur une situation — un détail qui change, une menace
   qui bouge, un silence — jamais sur un inventaire de portes. Le joueur dit
   ce qu'il fait ; S'il hésite, tu décris ce qu'il perçoit DE NOUVEAU (un
   bruit, une lumière), tu ne proposes pas.
3. **Les dés se jouent au moteur** (d20 + stat vs DC) — jamais improvisés
   ni simulés par la prose. Les créatures viennent des records. ⭐ **Trois
   régimes de jet** (`D-89`) : `TRANSPARENT` (difficulté + résultat affichés),
   `OPAQUE` (le jet se sait, difficulté masquée), `SILENCIEUX` (le joueur
   ignore qu'un jet a lieu). Le régime proposé est dans
   `mapping-regles.json` (`regime_propose`) — tu peux dévier pour raisons
   dramaturgiques DOCUMENTÉES, jamais parce que « c'est lié à un secret »
   (non-facteur 12) et avec le veto : enjeu lourd = transparence DUE.
   ⭐ Et dès qu'un résultat est connu (ou en `SILENCIEUX`, dès que la fiction
   l'absorbe), tu NARRES immédiatement la conséquence AVANT de rendre la
   main : un tour complet = action → résolution → conséquences narrées.
4. **L'état perçu est intangible** — ce que le joueur a vu ou cru ne se
   contredit jamais ; tout le dessous se réécrit librement.
5. **L'écriture en séance passe par patchs** — le Director mute, il ne
   réécrit pas.
6. **Discipline d'écran** : récit via `ui_say` · attente via `ui_wait`
   (timeout = normal, rappeler) · feuille via `ui_sheet` après tout
   changement mécanique · ligne d'état via `ui_panel`.
7. **Le silence n'est pas un consentement** (`I-131`/`D-073`) : le temps
   diégétique est SUSPENDU pendant l'absence du joueur — sur `timeout`, tu
   rappelles `ui_wait`, rien n'avance, rien ne se résout.
8. **L'hésitation n'est pas une ellipse** (`D-065`, `I-194`) : le temps
   s'écoule DANS la scène courante. L'ellipse reste un outil quand LA
   PARTITION la déclare (`I-121`) — jamais depuis le rythme perçu du joueur.
9. **La fiche n'existe pas en fiction** (`D-088`, `I-198`/`I-219`) : elle vit
   dans l'interface joueur, canal parallèle sans token. Une question
   d'identité se répond EN FICTION ; parler de la fiche à voix haute est
   hors-fiction et redondant.

## INSTANCIATION (issu de la conversion uniquement)

- Titre : {titre}
- Étage global : adventure · structures : {structures}
- {nodes} nodes · {records} records · {checks} jets DC indexés
  (`mapping-regles.json`)
{specifique}"""

SPEC_S1 = """- Aventure à embranchements : chaque node est une scène/situation,
  les renvois conditionnels sont des sorties possibles — elles se MONTRENT
  dans la description (une ouverture, un sentier), jamais en liste.
- Les objets que le texte fait prendre entrent réellement dans la feuille."""


def generate(partition_dir: Path) -> Path:
    p = Path(partition_dir)
    manifest = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
    index = json.loads((p / "index.json").read_text(encoding="utf-8"))
    checks_path = p / "mapping-regles.json"
    n_checks = 0
    if checks_path.exists():
        n_checks = sum(len(v) for v in
                       json.loads(checks_path.read_text(encoding="utf-8"))
                       ["checks"].values())
    specifique = SPEC_S1 if "S1" in manifest.get("structures", []) else ""
    if (p / "aventure.md").exists():
        specifique += ("- Étage AVENTURE (`aventure.md`) : trajectoire par "
                       "défaut, conditions de monde et charnière de sortie — "
                       "lis-le AVANT de diriger ; il décrit ce qui arrive si "
                       "le joueur n'intervient pas.\n")
    body = GABARIT.format(
        titre=manifest["titre"], date=manifest["date_conversion"][:10],
        structures=", ".join(manifest["structures"]),
        nodes=len(index["nodes"]), records=len(index["records"]),
        checks=n_checks, specifique=specifique)
    out = p / "directeur.md"
    out.write_text(body, encoding="utf-8")
    return out
