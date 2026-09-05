"""Issue #295 : tools/banc/arbitrer_prose.py — arbitrage MÉCANIQUE entre les
deux voies du gabarit `banc-mj.md` (D-276 §4 — le gel ne couvre pas
l'outillage de test, décision Souhel #295) pour obtenir `prose-NN.md` :
voie extraction (PRIMAIRE, section `## Prose du Narrateur` inline imposée
par le gabarit dans `tour-NN.md`, #269) et voie fichier (REPLI TOLÉRANT, le
MJ a malgré tout écrit `prose-NN.md` lui-même).

Cas couverts (constat #295, run du 05/09, + complément du gabarit) :
1. `prose-NN.md` présent (postérieur au go) + `tour-NN.md` sans section
   exploitable -> OK par la voie fichier, en repli (le craquement observé
   en production, corrigé ici).
2. section présente dans `tour-NN.md`, aucun `prose-NN.md` -> OK par la voie
   extraction (comportement #269, désormais PRIMAIRE).
3. ni l'un ni l'autre -> ABSENTE (code 1).
4. `prose-NN.md` présent mais antérieur au go (résidu d'un tour précédent)
   -> ignoré, retombe sur la voie extraction.
5. `prose-NN.md` pollué (titre markdown / bloc de code / mention Director
   ou visée) -> POLLUÉE (code 2), nommé, jamais laissé passer au joueur.
6. section exploitable dans `tour-NN.md` ET `prose-NN.md` présent (même
   pollué) -> la voie extraction PRIME, le fichier n'est même pas regardé.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "banc"))

from arbitrer_prose import arbitrer, main  # noqa: E402


def _toucher(chemin: Path, texte: str, mtime: float | None = None) -> None:
    chemin.write_text(texte, encoding="utf-8")
    if mtime is not None:
        os.utime(chemin, (mtime, mtime))


def main_test() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="arbitrer-prose-test-"))
    try:
        # 1) voie fichier : prose-NN.md déjà écrit par le MJ, postérieur au
        # go, tour-NN.md ne porte qu'un renvoi (pas de section exploitable)
        # -- exactement le craquement observé en production (#295).
        go_ts = time.time()
        tour1 = tmp / "tour-01.md"
        prose1 = tmp / "prose-01.md"
        tour1.write_text(
            "# tour 01\n\n## Visée du Director\n\nla marche glaciale...\n\n"
            "Prose retournée par le narrateur (verbatim) : voir prose-01.md "
            "-- relue sur le disque, non vide.\n",
            encoding="utf-8",
        )
        _toucher(prose1, "Le vent glacial mord les joues des voyageurs.\n",
                 mtime=go_ts + 5)
        code, msg = arbitrer(tour1, prose1, go_ts)
        assert (code, msg) == (0, "fichier"), (code, msg)
        assert "Le vent glacial" in prose1.read_text(encoding="utf-8")
        print("1) prose-NN.md présent (postérieur au go), tour-NN.md sans section : voie fichier")

        # 2) voie extraction : section présente dans tour-NN.md, aucun
        # prose-NN.md sur le disque.
        go_ts2 = time.time()
        tour2 = tmp / "tour-02.md"
        prose2 = tmp / "prose-02.md"
        tour2.write_text(
            "# tour 02\n\n## Prose du Narrateur (verbatim)\n\n"
            "La porte grince et s'ouvre sur le noir.\n\n"
            "## Événements moteur\n\nroll_check: ...\n",
            encoding="utf-8",
        )
        assert not prose2.exists()
        code, msg = arbitrer(tour2, prose2, go_ts2)
        assert (code, msg) == (0, "extraction"), (code, msg)
        assert prose2.read_text(encoding="utf-8").strip() == (
            "La porte grince et s'ouvre sur le noir."
        )
        print("2) aucun prose-NN.md, section présente dans tour-NN.md : voie extraction")

        # 3) ni l'un ni l'autre -> ABSENTE.
        go_ts3 = time.time()
        tour3 = tmp / "tour-03.md"
        prose3 = tmp / "prose-03.md"
        tour3.write_text("# tour 03\n\n## Visée du Director\n\nrien ici.\n",
                          encoding="utf-8")
        code, msg = arbitrer(tour3, prose3, go_ts3)
        assert code == 1, (code, msg)
        assert not prose3.exists()
        print("3) ni prose-NN.md ni section exploitable : ABSENTE (code 1)")

        # 4) prose-NN.md présent mais ANTÉRIEUR au go (résidu d'un tour
        # précédent) -> ignoré, retombe sur la voie extraction.
        tour4 = tmp / "tour-04.md"
        prose4 = tmp / "prose-04.md"
        _toucher(prose4, "Résidu du tour précédent, ne doit pas servir.\n",
                 mtime=1000)
        go_ts4 = 2000.0
        tour4.write_text(
            "## Prose du Narrateur (verbatim)\n\nLa prose fraîche du tour 4.\n",
            encoding="utf-8",
        )
        code, msg = arbitrer(tour4, prose4, go_ts4)
        assert (code, msg) == (0, "extraction"), (code, msg)
        assert "La prose fraîche du tour 4" in prose4.read_text(encoding="utf-8")
        print("4) prose-NN.md antérieur au go : ignoré, voie extraction utilisée")

        # 5) prose-NN.md pollué -- trois variantes de fuite zéro-spoiler.
        cas_pollues = [
            "## Un titre\n\nDu texte avec un titre markdown.\n",
            "Du texte avec un bloc :\n```\ncode\n```\n",
            "Le Director a décidé que la nuit tombait.\n",
        ]
        for i, texte in enumerate(cas_pollues, start=1):
            go_ts5 = time.time()
            tour5 = tmp / f"tour-p{i}.md"
            prose5 = tmp / f"prose-p{i}.md"
            tour5.write_text("# tour\n\nrien d'exploitable.\n", encoding="utf-8")
            _toucher(prose5, texte, mtime=go_ts5 + 5)
            code, msg = arbitrer(tour5, prose5, go_ts5)
            assert code == 2, (i, code, msg)
            assert prose5.exists() and prose5.read_text(encoding="utf-8") == texte, (
                "le fichier pollué reste sur le disque comme pièce du craquement"
            )
        print("5) prose-NN.md pollué (titre / bloc de code / mention Director) : POLLUÉE (code 2), fichier conservé")

        # 6) section exploitable dans tour-NN.md ET prose-NN.md présent,
        # même pollué -- la voie extraction PRIME : le fichier existant
        # n'est même pas regardé (jamais un faux craquement-prose-polluee
        # sur un run qui suit désormais le gabarit à la lettre).
        go_ts6 = time.time()
        tour6 = tmp / "tour-06.md"
        prose6 = tmp / "prose-06.md"
        tour6.write_text(
            "## Prose du Narrateur (verbatim)\n\nLa prose voulue, écrite dans "
            "tour-NN.md comme le gabarit l'impose désormais.\n",
            encoding="utf-8",
        )
        _toucher(prose6, "## Un vieux prose-NN.md pollué, jamais lu ici.\n",
                 mtime=go_ts6 + 5)
        code, msg = arbitrer(tour6, prose6, go_ts6)
        assert (code, msg) == (0, "extraction"), (code, msg)
        assert prose6.read_text(encoding="utf-8").strip() == (
            "La prose voulue, écrite dans tour-NN.md comme le gabarit "
            "l'impose désormais."
        )
        print("6) tour-NN.md exploitable ET prose-NN.md présent (même pollué) : voie extraction prime, écrase le fichier")

        # 7) CLI bout-en-bout : la voie retenue est imprimée sur stdout.
        go_ts7 = time.time()
        tour7 = tmp / "tour-07.md"
        prose7 = tmp / "prose-07.md"
        tour7.write_text("# tour\n\nrenvoi vers prose-07.md.\n", encoding="utf-8")
        _toucher(prose7, "Prose écrite directement par le MJ.\n", mtime=go_ts7 + 1)
        rc = main(["arbitrer_prose.py", str(tour7), str(prose7), str(go_ts7)])
        assert rc == 0, rc
        print("7) CLI : voie fichier (repli) -> sortie 0")

        print("\nALL ARBITRER_PROSE TESTS PASSED")
        return 0
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main_test())
