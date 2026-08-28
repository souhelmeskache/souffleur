"""Le MOULE générique du test d'élément (I-382, MRPG-I-382).

Pas un test en soi — une bibliothèque d'outillage importée par les
`tests/test-element-*.py` déclinés du moule. Vit sous `tests/fixtures/`
(pas directement sous `tests/`) pour ne pas être ramassé par le glob
`tests/*.py` de `run_tests.py` : ce fichier n'imprime pas "OK" et ne
retourne pas 0/1, ce n'est pas une suite exécutable seule.

Doctrine (registre méta D-240, hors périmètre de ce repo — voir l'Issue
#33 pour le résumé opérationnel) :

  - **stimulus bête** : le scénario joué est une action fixe, écrite à la
    main, pas un dialogue improvisé — le but est de vérifier une brique,
    pas de tester un modèle. Dans ce repo 100 % hors-ligne (CLAUDE.md), le
    « stimulus bête » est le texte d'action fixe lui-même : pas d'appel
    modèle. Un futur agent-instrument (petit modèle, instructions simples)
    pourrait rejouer le même scénario en dehors de cette suite CI ; le moule
    n'en dépend pas.
  - **verdict mécanique d'abord** (D-134) : jamais de lecture de qualité en
    petit modèle. Chaque verdict de ce moule est une comparaison de chaînes
    ou de longueurs — présence/absence, sous-ensemble, longueur relative —
    jamais un jugement de style ou de cohérence.
  - **run court et borné** : `ElementMold` chronomètre son propre bloc et
    échoue si le budget de temps est dépassé — une brique qui se met à
    parcourir tout le corpus ou à boucler doit faire échouer le test, pas
    tourner indéfiniment.

Un exemplaire = un fichier `tests/test-element-<brique>.py` qui :
  1. nomme la brique visée en une ligne (docstring) ;
  2. construit ses fixtures d'entrée (états synthétiques, D-206/D-109) ;
  3. rejoue un scénario réduit (le stimulus bête) à travers la brique ;
  4. enregistre ses verdicts via `ElementMold.check(...)` — un par état de
     fixture, jamais un verdict global fourre-tout ;
  5. termine par `assert mold.report()`.

Voir `README-moule-test-element.md` (racine du repo) pour le gabarit pas à
pas et `tests/test-element-camera.py` pour le premier exemplaire qui tourne.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Verdict:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ElementMold:
    """Harnais d'un test d'élément : une brique jouée à travers des fixtures
    et un scénario réduit, sous compteurs de verdict mécaniques et une borne
    de coût (temps écoulé)."""

    brique: str
    budget_seconds: float = 5.0
    verdicts: list[Verdict] = field(default_factory=list)
    _t0: float | None = field(default=None, repr=False)

    def __enter__(self) -> "ElementMold":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._t0 is not None:
            elapsed = time.monotonic() - self._t0
            self.check(
                "cout-borne", elapsed <= self.budget_seconds,
                f"{elapsed:.3f}s / budget {self.budget_seconds:.2f}s")
        return False  # never swallow an exception raised inside the block

    def check(self, name: str, condition: object, detail: str = "") -> bool:
        """Enregistre un verdict mécanique nommé. Retourne la condition
        (bool) pour permettre `assert mold.check(...)` inline si voulu."""
        ok = bool(condition)
        self.verdicts.append(Verdict(name, ok, detail))
        return ok

    def report(self) -> bool:
        """Affiche les compteurs de verdict et retourne le verdict global
        (True seulement si tous les verdicts sont passés)."""
        n_ok = sum(v.passed for v in self.verdicts)
        n_total = len(self.verdicts)
        print(f"--- {self.brique}: {n_ok}/{n_total} verdicts OK")
        for v in self.verdicts:
            mark = "OK" if v.passed else "FAIL"
            suffix = f" — {v.detail}" if v.detail else ""
            print(f"  [{mark}] {v.name}{suffix}")
        return n_ok == n_total and n_total > 0


# --- vérifications mécaniques réutilisables entre briques ------------------

def absent(output: str, *needles: str) -> bool:
    """Verdict « hors champ » : aucun des repères donnés n'apparaît dans la
    sortie — le fait non activé ne doit fuiter nulle part."""
    return all(needle not in output for needle in needles if needle)


def present(output: str, *needles: str) -> bool:
    return all(needle in output for needle in needles if needle)


def degraded(full_render: str, perceived: str, kept: str, dropped: str) -> bool:
    """Verdict « perçu partiellement » : la sortie perçue garde le repère
    `kept` (ex. le titre), perd le repère `dropped` (ex. le corps/détail),
    et diffère du rendu complet — une dégradation mesurable (le détail a été
    retiré), pas une comparaison de longueur ni une lecture de qualité (le
    substitut affiché à la place peut très bien être plus long que le
    corps qu'il remplace)."""
    return (kept in perceived and dropped not in perceived
            and perceived != full_render)


def no_markers(output: str, *markers: str) -> bool:
    """Verdict « secret actif » : zéro marqueur de secret/id interne dans le
    perçu — aucun des repères (slug, titre du secret, mot-clé de section
    secrète) ne doit apparaître dans la sortie destinée au joueur."""
    return all(marker not in output for marker in markers if marker)
