"""tools/banc/arbitrer_prose.py — arbitre MÉCANIQUE des deux voies légitimes
d'obtention de `prose-NN.md` (Issue #295).

Le gabarit `banc-mj.md` (D-276 §4 — le gel ne couvre pas l'outillage de
test, décision Souhel #295) impose désormais au MJ d'écrire la prose du
narrateur VERBATIM, INLINE, dans une section `## Prose du Narrateur` de
`tour-NN.md` lui-même (étape 8, § Journal du banc) — jamais un renvoi vers
`prose-NN.md`, et il n'écrit plus ce fichier lui-même. Ce script tranche
donc entre deux voies, dans cet ordre :

1. **voie extraction** (PRIMAIRE, #269, `tools/banc/extraire_prose.py`,
   inchangée) : `tour-NN.md` porte la section `## Prose du Narrateur`,
   dont le corps est extrait mécaniquement (aucun LLM) — le chemin nominal
   depuis la mise à jour du gabarit #295 ;
2. **voie fichier** (REPLI TOLÉRANT, historique #295) : si l'extraction
   échoue, mais que le MJ a malgré tout écrit lui-même un `prose-NN.md`
   (dérive du gabarit précédent, ou d'un modèle qui n'a pas suivi la
   consigne à la lettre) exploitable — non vide, postérieur à l'envoi du
   « go » du tour courant (preuve qu'il a été (ré)écrit pour CE tour, pas un
   résidu d'un tour précédent) — sous réserve du garde zéro-spoiler
   ci-dessous.

Le craquement `prose-absente` n'est levé QUE si aucune des deux voies ne
produit de prose exploitable. Voir tools/banc/README.md, § Contrat de
fichiers du tour.

Zéro-spoiler (D-219) : la voie fichier fait courir un risque que
l'extraction ne courait pas — un `prose-NN.md` écrit à la main par le MJ
peut, par erreur, embarquer un titre markdown, un bloc de code, ou une
mention de la visée du Director (fuite mécanique de matériau que le joueur
ne doit jamais lire). Ce script refuse nommément (`craquement-prose-polluee`)
un `prose-NN.md` qui porte un de ces signaux plutôt que de le laisser passer.

Usage :
    python tools/banc/arbitrer_prose.py <tour-NN.md> <prose-NN.md> <go_epoch>

`go_epoch` : horodatage Unix (secondes) de l'envoi du « go » du tour courant
à l'agent MJ (voir nuit.sh) — utilisé UNIQUEMENT par la voie fichier (repli) ;
un `prose-NN.md` déjà présent mais antérieur à ce « go » est un résidu d'un
tour précédent, jamais une preuve d'écriture pour CE tour, et il est ignoré.

Sortie 0 : prose obtenue (par l'une ou l'autre voie) — `prose-NN.md` sur le
disque, non vide, propre. La voie retenue est imprimée seule sur stdout
(`extraction` ou `fichier`), pour que l'appelant journalise le tour.
Sortie 1 : ABSENTE — ni section extractible ni fichier exploitable ;
message sur stderr (appelant : craquement `prose-absente`, voir nuit.sh).
Sortie 2 : POLLUÉE — `prose-NN.md` (voie fichier) contient un signal de
fuite zéro-spoiler ; message sur stderr, `prose-NN.md` laissé intact comme
pièce du craquement (appelant : craquement `prose-polluee`, voir nuit.sh).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Force UTF-8 sur stdout/stderr quel que soit le terminal (#279, même garde
# que extraire_prose.py).
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extraire_prose import extraire_prose  # noqa: E402

# Signaux de fuite zéro-spoiler (D-219) dans un prose-NN.md écrit à la main
# par le MJ : titre markdown, bloc de code, mention explicite du Director ou
# de sa visée — rien de tout ça n'a sa place dans de la prose pure.
TITRE_MD_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
BLOC_CODE_RE = re.compile(r"```")
MENTION_RE = re.compile(r"\b(director|vis[eé]e)\b", re.IGNORECASE)


def signal_pollution(texte: str) -> str | None:
    """Retourne une description du premier signal de fuite trouvé dans
    `texte`, ou None si le texte est de la prose pure."""
    if TITRE_MD_RE.search(texte):
        return "titre markdown ('#'...'######') trouvé dans le fichier"
    if BLOC_CODE_RE.search(texte):
        return "bloc de code (```) trouvé dans le fichier"
    m = MENTION_RE.search(texte)
    if m:
        return f"mention « {m.group(0)} » trouvée dans le fichier"
    return None


def arbitrer(tour_path: Path, prose_path: Path, go_epoch: float) -> tuple[int, str]:
    """Retourne (code, message) — code 0/1/2 comme documenté en tête de
    fichier ; message est le texte de la voie retenue (code 0) ou de
    l'erreur (code 1/2)."""
    # --- voie extraction (PRIMAIRE, #295) : mécanique, inchangée depuis #269.
    try:
        texte_tour = tour_path.read_text(encoding="utf-8")
    except OSError as e:
        return 1, f"REFUS : lecture de {tour_path} impossible ({e})."

    corps = extraire_prose(texte_tour)
    if corps is not None:
        prose_path.write_text(corps + "\n", encoding="utf-8")
        return 0, "extraction"

    # --- voie fichier (REPLI TOLÉRANT) : prose-NN.md déjà écrit par le MJ
    # lui-même, malgré le gabarit qui ne le lui demande plus, postérieur au go.
    try:
        if prose_path.exists() and prose_path.stat().st_size > 0:
            if prose_path.stat().st_mtime >= go_epoch:
                texte = prose_path.read_text(encoding="utf-8")
                if texte.strip():
                    pollution = signal_pollution(texte)
                    if pollution is not None:
                        return 2, (
                            f"POLLUÉE : {prose_path} contient un signal de fuite "
                            f"zéro-spoiler ({pollution})."
                        )
                    return 0, "fichier"
    except OSError as e:
        print(f"AVERTISSEMENT : lecture de {prose_path} impossible ({e}).",
              file=sys.stderr)

    return 1, (
        f"ABSENTE : ni section « Prose du Narrateur » non vide dans "
        f"{tour_path} (voie extraction) ni {prose_path.name} exploitable "
        f"(voie fichier, repli)."
    )


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(f"Usage : {argv[0]} <tour-NN.md> <prose-NN.md> <go_epoch>",
              file=sys.stderr)
        return 2

    tour_path = Path(argv[1])
    prose_path = Path(argv[2])
    try:
        go_epoch = float(argv[3])
    except ValueError:
        print(f"go_epoch invalide : {argv[3]!r} (attendu : nombre)", file=sys.stderr)
        return 2

    code, message = arbitrer(tour_path, prose_path, go_epoch)
    if code == 0:
        print(message)
    else:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
