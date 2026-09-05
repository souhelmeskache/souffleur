"""Issue #276 : tools/banc/metriques_nuit.py -- `calculer_rapport` /
`formater_rapport_markdown` (`rapport-nuit.md`), sur une arborescence de run
100% synthétique (jamais un vrai run de banc, D-109)."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "metriques_nuit", REPO_ROOT / "tools" / "banc" / "metriques_nuit.py")
metriques_nuit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(metriques_nuit)


def ecrire_partie(run_dir: Path, pnn: str, *, n_prose: int, fin: str, modele: str,
                   craquements: list[str]) -> Path:
    partie_dir = run_dir / f"partie-{pnn}"
    partie_dir.mkdir(parents=True)
    for t in range(1, n_prose + 1):
        (partie_dir / f"prose-{t:02d}.md").write_text("x", encoding="utf-8")
    (partie_dir / "resume-run.md").write_text(
        f"casting: joueur=haiku(low) director={modele}(medium) narrateur=haiku\n"
        f"tours_joues: {n_prose}\nfin_atteinte: {fin}\n", encoding="utf-8")
    for nom in craquements:
        (partie_dir / nom).write_text("craquement synthétique", encoding="utf-8")
        # tour-NN.md associé, pour au moins un craquement -- vérifie le
        # pointeur `pires_craquements` vers le tour plutôt que le craquement.
    return partie_dir


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="rapport-nuit-test-"))
    try:
        # --- 1. extraire_classe_craquement : mécanique, D-276 §4 ------------
        assert metriques_nuit.extraire_classe_craquement(Path("craquement-materiau-03.md")) == "materiau"
        assert metriques_nuit.extraire_classe_craquement(Path("craquement-director-01.md")) == "director"
        assert metriques_nuit.extraire_classe_craquement(Path("craquement-outillage-12.md")) == "outillage"
        # types mécaniques actuels de nuit.sh -- aucun n'est une classe D-276,
        # donc "non classé" tant que l'analyste N2 (hors périmètre) n'a pas
        # requalifié le craquement.
        assert metriques_nuit.extraire_classe_craquement(Path("craquement-timeout-05.md")) == "non classé"
        assert metriques_nuit.extraire_classe_craquement(Path("craquement-prose-absente-07.md")) == "non classé"
        assert metriques_nuit.extraire_classe_craquement(Path("pas-un-craquement.md")) == "non classé"
        print("1) extraire_classe_craquement : classes D-276 §4 reconnues, reste = non classé")

        # --- 2. arborescence synthétique -------------------------------------
        run_dir = tmp / "nuit-20260101"
        p1 = ecrire_partie(run_dir, "01", n_prose=4, fin="O", modele="haiku",
                            craquements=["craquement-director-05.md"])
        (p1 / "tour-05.md").write_text("tour cinq", encoding="utf-8")
        time.sleep(0.01)
        p2 = ecrire_partie(run_dir, "02", n_prose=2, fin="N", modele="sonnet",
                            craquements=["craquement-timeout-03.md"])
        # pas de tour-03.md pour partie-02 : pires_craquements doit alors
        # pointer le craquement lui-même.

        rapport = metriques_nuit.calculer_rapport(run_dir, "budget -Parties atteint", 120, "non")
        assert rapport["parties_finies"] == 1, rapport
        assert rapport["parties_lancees"] == 2, rapport
        assert rapport["tours_min"] == 2 and rapport["tours_max"] == 4, rapport
        assert rapport["craquements_par_classe"] == {"director": 1, "non classé": 1}, rapport
        assert rapport["ab_director"]["haiku"]["tours_moyen"] == 4, rapport
        assert rapport["ab_director"]["haiku"]["craquements_director"] == 1, rapport
        assert rapport["ab_director"]["sonnet"]["craquements_director"] == 0, rapport
        assert rapport["limite_session"] == "non", rapport
        assert len(rapport["pires_craquements"]) == 2, rapport
        assert any(str(p2 / "craquement-timeout-03.md") == c for c in rapport["pires_craquements"]), rapport
        assert any(str(p1 / "tour-05.md") == c for c in rapport["pires_craquements"]), rapport
        print("2) calculer_rapport() sur arborescence synthétique : classes, A/B Director, "
              "pointeurs pires craquements OK")

        rendu = metriques_nuit.formater_rapport_markdown(rapport)
        for attendu in ("Parties finies / lancées : 1 / 2", "Raison d'arrêt : budget -Parties atteint",
                         "director : 1", "non classé : 1", "haiku : tours moyens 4",
                         "Limite de session touchée : non"):
            assert attendu in rendu, f"'{attendu}' absent du rendu :\n{rendu}"
        print("3) formater_rapport_markdown() : rendu cohérent avec calculer_rapport()")

        # --- 4. cas « aucune partie » -- jamais fatal -------------------------
        run_dir_vide = tmp / "nuit-vide"
        run_dir_vide.mkdir()
        rapport_vide = metriques_nuit.calculer_rapport(run_dir_vide, "lancement impossible", 5, "non")
        assert rapport_vide["parties_lancees"] == 0
        assert rapport_vide["tours_min"] == 0 and rapport_vide["tours_max"] == 0
        assert rapport_vide["craquements_par_classe"] == {}
        assert rapport_vide["ab_director"] == {}
        assert rapport_vide["pires_craquements"] == []
        rendu_vide = metriques_nuit.formater_rapport_markdown(rapport_vide)
        assert "(aucun)" in rendu_vide and "(aucune partie castée)" in rendu_vide, rendu_vide
        print("4) aucune partie jouée : calculer_rapport()/formater_rapport_markdown() ne crashent pas")

        # --- 5bis. ligne « Module : ... » (#281), depuis save/module.json ---
        (p1 / "save" / "memory").mkdir(parents=True)
        (p1 / "save" / "module.json").write_text(
            json.dumps({"titre": "Module Factice Rapport",
                       "partition": "/dev/null/partition"}),
            encoding="utf-8")
        (p1 / "save" / "locations.md").write_text(
            "# Locations\n\n## Entree  {#entree}\nimportance: 3\n\nUn hall.\n",
            encoding="utf-8")
        (p1 / "save" / "characters.md").write_text(
            "# Characters\n\n## Garde  {#garde}\nimportance: 3\n\nUn garde.\n\n"
            "## Aubergiste  {#aubergiste}\nimportance: 2\n\nSert la biere.\n",
            encoding="utf-8")
        info = metriques_nuit.lire_module_info(run_dir)
        assert info == {"titre": "Module Factice Rapport", "lieux": 1, "pnj": 2}, info
        rapport_module = metriques_nuit.calculer_rapport(run_dir, "STOP", 10, "non")
        assert rapport_module["module"] == info, rapport_module
        rendu_module = metriques_nuit.formater_rapport_markdown(rapport_module)
        assert "Module : Module Factice Rapport, 1 lieux, 2 PNJ" in rendu_module, rendu_module
        print("5bis) lire_module_info() + ligne « Module : ... » en tête du rapport : OK")

        # aucune save avec module.json dans l'arbre -> ligne nommée, jamais fatal
        info_absent = metriques_nuit.lire_module_info(run_dir_vide)
        assert info_absent is None, info_absent
        rendu_sans_module = metriques_nuit.formater_rapport_markdown(rapport_vide)
        assert "Module : aucun" in rendu_sans_module, rendu_sans_module
        print("5ter) aucun module.json dans l'arbre -> ligne nommée « aucun », pas fatal")

        # --- 6. CLI `main()` mode rapport ------------------------------------
        rc = metriques_nuit.main([str(run_dir), "rapport", "STOP", "42", "oui"])
        assert rc == 0
        rc_bad = metriques_nuit.main([str(run_dir), "rapport", "STOP"])
        assert rc_bad == 1
        print("6) CLI `<run_dir> rapport <raison> <duree_s> <limite_session>` OK, usage sinon")

        print("\nALL RAPPORT_NUIT TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
