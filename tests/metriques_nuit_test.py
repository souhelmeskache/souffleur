"""Issue #260 : tools/banc/metriques_nuit.py — parseur des métriques §3 de
#201, testé sur un `events.jsonl` synthétique et une arborescence de run
synthétique (jamais un vrai run de banc)."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
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


def main() -> int:
    # --- 1. compteurs unitaires sur des events.jsonl synthétiques -----------
    events = [
        {"turn": 0, "env": {}},
        {"turn": 1, "type": "attack", "error": "missing ca on goblin"},
        {"turn": 1, "env": {"deltas": {"hp_delta": -3}}},
        {"turn": 2, "type": "roll_check", "error": "unknown skill 'foo'"},
        {"turn": 2, "type": "roll_check"},  # pas d'erreur -> pas un refus
        {"turn": 3, "type": "bouchage_demande", "id": "x"},
        {"turn": 3, "type": "bouchage_enregistre", "id": "x"},
        {"turn": 4, "type": "bouchage_enregistre", "id": "y"},
        {"turn": 5, "type": "start_combat"},
        {"turn": 6, "env": {"deltas": {"enemies": {"goblin": {"hp_delta": -5}}}}},
        {"turn": 7, "env": {"deltas": {"enemies": {"goblin2": {"hp_delta": -2}}}}},
    ]
    assert metriques_nuit.compter_refus_outil(events) == 2, events
    assert metriques_nuit.compter_bouchages(events) == 2, events
    combats = metriques_nuit.compter_combats(events)
    assert combats == {"sous_systeme": 1, "hors_sous_systeme": 2}, combats
    print("1) compteurs unitaires (refus_outil/bouchages/combats) OK")

    # --- 2. ligne malformée ignorée, jamais fatale ---------------------------
    tmp = Path(tempfile.mkdtemp(prefix="metriques-nuit-test-"))
    try:
        ev_path = tmp / "events.jsonl"
        ev_path.write_text(
            '{"turn": 1, "type": "bouchage_enregistre"}\n'
            'CECI N\'EST PAS DU JSON\n'
            '{"turn": 2, "type": "bouchage_enregistre"}\n',
            encoding="utf-8",
        )
        lus = metriques_nuit.lire_events(ev_path)
        assert len(lus) == 2, lus
        assert metriques_nuit.compter_bouchages(lus) == 2, lus
        print("2) ligne malformée ignorée, pas fatale")

        assert metriques_nuit.lire_events(tmp / "absent.jsonl") == []
        print("3) events.jsonl absent -> liste vide (pas d'exception)")

        # --- 4. calculer() sur une arborescence de run synthétique ----------
        run_dir = tmp / "nuit-20260101"
        for pnn, n_prose, fin, evs in (
            ("01", 3, "O", [{"turn": 1, "type": "bouchage_enregistre"}]),
            ("02", 5, "N", [{"turn": 1, "type": "attack", "error": "x"}]),
        ):
            partie_dir = run_dir / f"partie-{pnn}"
            (partie_dir / "save" / "memory").mkdir(parents=True)
            for t in range(1, n_prose + 1):
                (partie_dir / f"prose-{t:02d}.md").write_text("x", encoding="utf-8")
            (partie_dir / "resume-run.md").write_text(
                f"tours_joues: {n_prose}\nfin_atteinte: {fin}\n", encoding="utf-8")
            events_path = partie_dir / "save" / "memory" / "events.jsonl"
            events_path.write_text(
                "\n".join(json.dumps(e) for e in evs) + "\n", encoding="utf-8")

        m = metriques_nuit.calculer(run_dir)
        assert m["parties_lancees"] == 2, m
        assert m["parties_finies"] == 1, m
        assert m["tours_median"] == 4, m  # médiane de [3, 5]
        assert m["bouchages"] == 1, m
        assert m["refus_outil"] == 1, m
        print("4) calculer() sur arborescence synthétique : "
              f"{m['parties_finies']}/{m['parties_lancees']} finies, "
              f"médiane {m['tours_median']}")

        rendu = metriques_nuit.formater_markdown(m)
        assert "1 / 2" in rendu, rendu
        print("5) formater_markdown() : rendu Markdown cohérent avec calculer()")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- 6. UTF-8 forcé sur stdout, sans dépendre de l'environnement ---------
    # (Issue #279) : `metriques_nuit.py` en sous-processus, PYTHONIOENCODING
    # retiré de l'environnement — sous Windows, sans cet override,
    # sys.stdout du sous-processus tombe en cp1252 (encodage console par
    # défaut) plutôt qu'en UTF-8. Le rapport porte « ⊥ » (A/B Director) et
    # des accents (« arrêté ») : avant le correctif, ceci levait
    # UnicodeEncodeError (nuit du 03/09, cf. #279) au lieu de sortir 0.
    tmp2 = Path(tempfile.mkdtemp(prefix="metriques-nuit-utf8-test-"))
    try:
        run_dir2 = tmp2 / "nuit-utf8"
        partie_dir = run_dir2 / "partie-01"
        (partie_dir / "save" / "memory").mkdir(parents=True)
        (partie_dir / "prose-01.md").write_text("x", encoding="utf-8")
        (partie_dir / "resume-run.md").write_text(
            "tours_joues: 1\nfin_atteinte: O\n", encoding="utf-8")

        env = dict(os.environ)
        env.pop("PYTHONIOENCODING", None)
        script = REPO_ROOT / "tools" / "banc" / "metriques_nuit.py"
        proc = subprocess.run(
            [sys.executable, str(script), str(run_dir2), "rapport",
             "arrêté à heure fixe", "42", "non"],
            env=env, capture_output=True,
        )
        assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
        rapport = proc.stdout.decode("utf-8")
        assert "⊥" in rapport, rapport
        assert "arrêté" in rapport, rapport
        print("6) sous-processus PYTHONIOENCODING retiré : sortie 0, "
              "« ⊥ » et accents intacts en UTF-8")
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    print("\nALL METRIQUES_NUIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
