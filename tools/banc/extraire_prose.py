"""tools/banc/extraire_prose.py — extraction MÉCANIQUE de prose-NN.md depuis
tour-NN.md (Issue #269).

Le gabarit `banc-mj.md` (D-276 §4 — le gel ne couvre pas l'outillage de
test, décision Souhel #295) IMPOSE au MJ d'écrire la prose du narrateur
VERBATIM, INLINE, dans une section `## Prose du Narrateur` de `tour-NN.md`
lui-même (étape 8, § Journal du banc) — jamais un renvoi vers `prose-NN.md`,
que le MJ n'écrit plus lui-même. `prose-NN.md` reste l'organe zéro-spoiler
du banc (D-219) : le joueur ne doit lire QUE la prose du narrateur, jamais
la visée du Director, les événements moteur ou les chemins de paquets qui
vivent dans `tour-NN.md`. Ce script produit `prose-NN.md` par extraction
pure (aucun LLM, aucun jugement) de la section « Prose du Narrateur » de
`tour-NN.md` — tolérant aux variantes de titre (niveau de titre, casse,
suffixe « (verbatim) » ou non). C'est la voie PRIMAIRE depuis #295 ;
`tools/banc/arbitrer_prose.py` (appelé par `nuit.sh`) l'essaie en premier
et ne retombe sur la voie fichier (repli tolérant, MJ ayant malgré tout
écrit `prose-NN.md` lui-même) que si elle échoue — voir ce module, qui
arbitre entre les deux.

Usage :
    python tools/banc/extraire_prose.py <tour-NN.md> <prose-NN.md>

Sortie 0 : section trouvée et non vide, `prose-NN.md` écrit.
Sortie 1 : section absente ou vide — RIEN n'est écrit, message sur stderr
(appelant : craquement `prose-absente-NN`, voir tools/banc/nuit.sh).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Force UTF-8 sur stdout/stderr quel que soit le terminal (Issue #279) : sous
# Windows, sys.stdout/stderr sont en cp1252 hors terminal UTF-8 explicite, et
# un message d'erreur portant un caractère hors cp1252 (« », accents) fait
# planter le script avant même d'écrire quoi que ce soit. `reconfigure` peut
# lever si le flux n'en dispose pas (ex. capturé par un test) — sans
# conséquence, le flux garde alors son encodage d'origine.
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Titre de section : 1 à 6 '#', "Prose du Narrateur" (casse libre), puis
# n'importe quel suffixe (ex. " (verbatim)", " :", rien).
TITRE_RE = re.compile(r"^(#{1,6})\s*Prose du Narrateur\b.*$", re.IGNORECASE)
# N'importe quel titre — sert à borner la fin de la section.
TITRE_QUELCONQUE_RE = re.compile(r"^#{1,6}\s+\S")


def extraire_prose(texte: str) -> str | None:
    """Retourne le corps (trimmed) de la section « Prose du Narrateur » de
    `texte`, ou None si la section est absente ou vide."""
    lignes = texte.splitlines()
    debut = None
    for i, ligne in enumerate(lignes):
        if TITRE_RE.match(ligne):
            debut = i + 1
            break
    if debut is None:
        return None

    fin = len(lignes)
    for i in range(debut, len(lignes)):
        if TITRE_QUELCONQUE_RE.match(lignes[i]):
            fin = i
            break

    corps = "\n".join(lignes[debut:fin]).strip("\n ")
    return corps if corps else None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"Usage : {argv[0]} <tour-NN.md> <prose-NN.md>", file=sys.stderr)
        return 2

    tour_path = Path(argv[1])
    prose_path = Path(argv[2])

    try:
        texte = tour_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"REFUS : lecture de {tour_path} impossible ({e}).", file=sys.stderr)
        return 1

    corps = extraire_prose(texte)
    if corps is None:
        print(
            f"ABSENTE : aucune section « Prose du Narrateur » non vide dans "
            f"{tour_path}.",
            file=sys.stderr,
        )
        return 1

    prose_path.write_text(corps + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
