"""I-469 §F0.4 (Issue #332) — colonnes `rapport-nuit.md` : paquet médian
(jetons), paquet max, fenêtre MJ au tour 1, fenêtre MJ au dernier tour, et la
ligne de synthèse A/B Director quand deux modèles ont joué. Testé sur des
`events.jsonl` et une arborescence de run 100% synthétiques (jamais un vrai
run de banc), même discipline que `metriques_nuit_test.py`."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "metriques_nuit", REPO_ROOT / "tools" / "banc" / "metriques_nuit.py")
metriques_nuit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(metriques_nuit)


def _ecrire_partie(run_dir: Path, pnn: str, n_prose: int, casting: str,
                    events: list[dict]) -> Path:
    partie_dir = run_dir / f"partie-{pnn}"
    (partie_dir / "save" / "memory").mkdir(parents=True)
    for t in range(1, n_prose + 1):
        (partie_dir / f"prose-{t:02d}.md").write_text("x", encoding="utf-8")
    (partie_dir / "resume-run.md").write_text(
        f"tours_joues: {n_prose}\nfin_atteinte: N\nraison_arret: tours_max\n"
        f"casting: {casting}\n", encoding="utf-8")
    (partie_dir / "save" / "memory" / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + ("\n" if events else ""),
        encoding="utf-8")
    return partie_dir


def main() -> int:
    # --- 1. lecteurs unitaires -----------------------------------------------
    events = [
        {"type": "paquet", "turn": 1, "outil": "assemble_context_to_file",
         "chars": 4000, "tokens_est": 1000, "sections": {}},
        {"type": "paquet", "turn": 2, "outil": "paquet_narrateur",
         "chars": 8000, "tokens_est": 2000, "sections": {"a": 8000}},
        {"type": "paquet", "turn": 3, "outil": "paquet_narrateur",
         "chars": 12000, "tokens_est": 3000, "sections": {}},
        {"type": "fenetre", "turn": 1, "role": "mj", "pct": 62},
        {"type": "fenetre", "turn": 2, "role": "mj", "pct": 71},
        {"type": "fenetre", "turn": 3, "role": "mj", "pct": 83},
        {"type": "fenetre", "turn": 3, "role": "joueur", "pct": 40},  # jamais compté (rôle mj seul)
    ]
    assert metriques_nuit.lire_paquets_tokens(events) == [1000, 2000, 3000], events
    tour1, dernier = metriques_nuit.fenetre_mj_tour1_dernier(events)
    assert tour1 == 62 and dernier == 83, (tour1, dernier)
    print("1) lire_paquets_tokens / fenetre_mj_tour1_dernier lisent le bon rôle/tri par tour")

    # --- 2. entrée « non lisible » et absence totale : jamais une estimation ---
    events_nl = [{"type": "fenetre", "turn": 1, "role": "mj", "pct": "non lisible"}]
    assert metriques_nuit.fenetre_mj_tour1_dernier(events_nl) == (None, None), events_nl
    assert metriques_nuit.fenetre_mj_tour1_dernier([]) == (None, None)
    assert metriques_nuit.lire_paquets_tokens([]) == []
    print("2) « non lisible » / absence -> None, jamais un chiffre inventé")

    # --- 3. mesures_partie / paquet_fenetre_par_partie sur une arborescence ---
    tmp = Path(tempfile.mkdtemp(prefix="metriques-nuit-paquet-fenetre-test-"))
    try:
        run_dir = tmp / "nuit-20260906"
        _ecrire_partie(run_dir, "01", 3, "joueur=haiku(x) director=haiku(x) narrateur=x",
                       events)
        _ecrire_partie(run_dir, "02", 2, "joueur=haiku(x) director=sonnet(x) narrateur=x", [
            {"type": "paquet", "turn": 1, "outil": "paquet_narrateur",
             "chars": 40000, "tokens_est": 10000, "sections": {}},
            {"type": "fenetre", "turn": 1, "role": "mj", "pct": 30},
            {"type": "fenetre", "turn": 2, "role": "mj", "pct": 55},
        ])
        # partie-03 : aucun événement paquet/fenêtre (run d'avant cette lane)
        # -- doit rendre None partout, jamais planter ni deviner.
        _ecrire_partie(run_dir, "03", 1, "joueur=haiku(x) director=sonnet(x) narrateur=x", [])

        mp1 = metriques_nuit.mesures_partie(run_dir / "partie-01")
        assert mp1 == {"paquet_median": 2000, "paquet_max": 3000,
                       "fenetre_tour1": 62, "fenetre_dernier": 83}, mp1
        mp3 = metriques_nuit.mesures_partie(run_dir / "partie-03")
        assert mp3 == {"paquet_median": None, "paquet_max": None,
                       "fenetre_tour1": None, "fenetre_dernier": None}, mp3
        print("3) mesures_partie : chiffres corrects, None quand rien n'est journalisé")

        par_partie = metriques_nuit.paquet_fenetre_par_partie(run_dir)
        assert set(par_partie) == {"partie-01", "partie-02", "partie-03"}, par_partie
        assert par_partie["partie-02"]["paquet_median"] == 10000, par_partie
        print("4) paquet_fenetre_par_partie : une entrée par dossier partie-NN")

        # --- 4. A/B Director : paquet médian par modèle + ligne de synthèse ---
        ab = metriques_nuit.stats_ab_director(run_dir)
        assert set(ab) == {"haiku", "sonnet"}, ab
        assert ab["haiku"]["paquet_median"] == 2000, ab       # partie-01 seule
        assert ab["sonnet"]["paquet_median"] == 10000, ab     # partie-02 seule (partie-03 vide)
        print("5) stats_ab_director : paquet médian par modèle, deux modèles castés")

        # --- 5. rapport-nuit.md porte les colonnes + la ligne de synthèse -----
        rapport = metriques_nuit.calculer_rapport(run_dir, "tours_max", 120, "non")
        rendu = metriques_nuit.formater_rapport_markdown(rapport)
        assert "partie-01 : paquet médian 2000" in rendu, rendu
        assert "fenêtre mj tour 1 62% / dernier tour 83%" in rendu, rendu
        assert "partie-03 : paquet non mesuré" in rendu, rendu
        assert "fenêtre mj tour 1 non lisible / dernier tour non lisible" in rendu, rendu
        assert "haiku : tours moyens" in rendu and "paquet médian 2000 jetons" in rendu, rendu
        assert "sonnet : tours moyens" in rendu and "paquet médian 10000 jetons" in rendu, rendu
        assert "synthèse : paquet médian haiku 2000 jetons ⊥ sonnet 10000 jetons (#332)" in rendu, rendu
        assert "Budget consommé : durée 120s, paquet médian" in rendu, rendu
        print("6) rapport-nuit.md : colonnes paquet/fenêtre par partie + synthèse A/B présentes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL METRIQUES_NUIT_PAQUET_FENETRE (#332) TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
