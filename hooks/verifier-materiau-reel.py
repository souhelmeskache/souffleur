#!/usr/bin/env python3
"""Garde « materiau reel » (I-324) : refuse tout commit -- ou tout lancement
de lane -- qui ferait entrer un identifiant du corpus de campagne reel
(`corpus_dir()`, `coderain/config.py`) dans l'historique versionne ou dans le
prompt d'une lane.

Origine : PR #320 (lane #317) refusee en revue -- un slug reel du corpus
et le bloc de stats reel d'un record etaient deja entres dans le worktree
via un `git commit` avant que la revue les attrape (voir Issue #324 pour le
detail). Rien n'empechait cette entree en amont ; ce script est cette
premiere ligne de defense, locale et rapide.

Deux usages :
  - `hooks/verifier-materiau-reel.py`         -- garde pre-commit (a) : lit
    le diff INDEXE (`git diff --cached`), contenu ajoute ET noms de fichier.
  - `hooks/verifier-materiau-reel.py --text`  -- garde en amont (b), utilisee
    par `tools/lancer-lane.ps1` : lit un texte libre (corps d'Issue + section
    Cadrage) depuis stdin.

Source des identifiants reels : chaque fichier `records/*.md` sous
`corpus_dir()` (tous modules, toutes partitions converties). Le nom de
fichier (slug) et les champs `id`/`nom`/`title` de son frontmatter JSON
(entre les deux lignes `---`) comptent comme identifiants a proteger.

Tolerance : `hooks/materiau-reel-autorise.txt`, une liste blanche versionnee
(un terme par ligne, `#` pour les commentaires) pour les termes qui sont
AUSSI du vocabulaire courant -- revue a la main, jamais generee.

Sans corpus local (CI, poste sans `ttrpg-corpus`) : la garde est locale par
nature, elle dit « corpus absent, garde non jouee » et laisse passer
(exit 0) -- jamais de faux negatif silencieux cache derriere un exit 1
qu'on prendrait pour un bug de CI.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WHITELIST_PATH = REPO_ROOT / "hooks" / "materiau-reel-autorise.txt"

# Termes trop courts pour identifier quoi que ce soit (bruit garanti) --
# meme un slug/nom reel de 1-2 caracteres n'entre pas dans la garde.
LONGUEUR_MIN_TERME = 3


def _corpus_dir() -> Path:
    sys.path.insert(0, str(REPO_ROOT))
    from coderain.config import corpus_dir  # import tardif (sys.path plus haut)
    return corpus_dir()


def load_whitelist() -> set[str]:
    if not WHITELIST_PATH.exists():
        return set()
    termes = set()
    for ligne in WHITELIST_PATH.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        termes.add(ligne.lower())
    return termes


def _parse_frontmatter(texte: str) -> dict | None:
    """Frontmatter des records : JSON (pas YAML) entre deux lignes `---`."""
    lignes = texte.splitlines()
    if not lignes or lignes[0].strip() != "---":
        return None
    try:
        fin = lignes.index("---", 1)
    except ValueError:
        return None
    try:
        data = json.loads("\n".join(lignes[1:fin]))
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def collect_real_terms(corpus_root: Path) -> dict[str, str]:
    """terme (lowercase) -> chemin du record source, pour le message de
    refus. Un meme terme peut venir de plusieurs records ; on garde le
    premier trouve, suffisant pour identifier le fichier a inspecter."""
    termes: dict[str, str] = {}
    if not corpus_root.exists():
        return termes
    for record in corpus_root.rglob("records/*.md"):
        source = str(record.relative_to(corpus_root))
        slug = record.stem.strip().lower()
        if slug:
            termes.setdefault(slug, source)
            termes.setdefault(slug.replace("-", " "), source)
        try:
            texte = record.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        data = _parse_frontmatter(texte)
        if not data:
            continue
        for cle in ("id", "nom", "title"):
            val = data.get(cle)
            if isinstance(val, str) and val.strip():
                termes.setdefault(val.strip().lower(), source)
    return termes


def check_haystacks(haystacks: list[tuple[str, list[tuple[int, str]]]],
                     termes: dict[str, str],
                     whitelist: set[str]) -> list[str]:
    """Une entree par (etiquette, [(numero, ligne), ...]) a inspecter.
    L'etiquette est le CHEMIN du fichier touche pour un match de contenu (pas
    une position dans un blob concatene de tout le diff) -- le refus nomme
    ainsi le fichier ET la ligne, comme l'exige l'Issue #324. Retourne les
    lignes de refus (vide = rien trouve)."""
    problemes = []
    for terme, source in sorted(termes.items()):
        if len(terme) < LONGUEUR_MIN_TERME or terme in whitelist:
            continue
        motif = re.compile(
            r"(?<![a-z0-9])" + re.escape(terme) + r"(?![a-z0-9])",
            re.IGNORECASE,
        )
        for etiquette, lignes in haystacks:
            for numero, ligne in lignes:
                if motif.search(ligne):
                    problemes.append(
                        f"{etiquette}:{numero}: identifiant reel « {terme} » "
                        f"(source corpus: {source})"
                    )
    return problemes


# Repere le fichier NEUF ("+++ b/chemin") et le premier numero de ligne d'un
# hunk ("@@ -a,b +c,d @@") dans un diff unifie -U0, pour retomber sur le vrai
# numero de ligne dans le fichier plutot qu'une position dans un blob.
_DIFF_FICHIER_RE = re.compile(r"^\+\+\+ (?:b/(.+)|/dev/null)$")
_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _diff_haystacks() -> list[tuple[str, list[tuple[int, str]]]]:
    diff = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--diff-filter=ACMR"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout

    par_fichier: dict[str, list[tuple[int, str]]] = {}
    fichier_courant: str | None = None
    ligne_neuve = 0
    for ligne in diff.splitlines():
        m_fichier = _DIFF_FICHIER_RE.match(ligne)
        if m_fichier:
            fichier_courant = m_fichier.group(1)  # None si fichier supprime
            continue
        m_hunk = _DIFF_HUNK_RE.match(ligne)
        if m_hunk:
            ligne_neuve = int(m_hunk.group(1))
            continue
        if ligne.startswith("+") and not ligne.startswith("+++") and fichier_courant:
            par_fichier.setdefault(fichier_courant, []).append((ligne_neuve, ligne[1:]))
            ligne_neuve += 1

    haystacks = list(par_fichier.items())

    noms = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout
    haystacks.append((
        "nom de fichier indexe",
        list(enumerate(noms.splitlines(), start=1)),
    ))
    return haystacks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--text", action="store_true",
        help="lit un texte libre depuis stdin (corps d'Issue) au lieu du "
             "diff indexe -- usage tools/lancer-lane.ps1",
    )
    args = ap.parse_args(argv)

    corpus_root = _corpus_dir()
    if not corpus_root.exists():
        print("garde materiau reel : corpus absent, garde non jouee")
        return 0

    termes = collect_real_terms(corpus_root)
    whitelist = load_whitelist()

    if args.text:
        haystacks = [("texte", list(enumerate(sys.stdin.read().splitlines(), start=1)))]
    else:
        haystacks = _diff_haystacks()

    problemes = check_haystacks(haystacks, termes, whitelist)
    if problemes:
        print("MATERIAU REEL DETECTE -- refuse :", file=sys.stderr)
        for p in problemes:
            print(f"  {p}", file=sys.stderr)
        print(
            "Un terme AUSSI du vocabulaire courant se whiteliste a la main "
            "dans hooks/materiau-reel-autorise.txt.", file=sys.stderr,
        )
        return 1

    print(f"garde materiau reel : {len(termes)} identifiants reels "
          f"verifies, aucun trouve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
