"""Issue #330 (D-264, brique 0 / F0.1) : tools/banc/verifier_reset.py — les 4
vérifications MÉCANIQUES du tour N+1 après un reset de session Director,
sur des fixtures 100% synthétiques (D-109) : partition de 3 nœuds + save
gelée « au tour N » fabriquées pour ce test seul, jamais de matériau réel —
même discipline que tests/detecter_fin_test.py.

Un cas PASS et un cas FAIL par point, comme demandé par la lane (§ Preuve à
fournir) : position, cliquet/visée, réintroduction de scène, mot-témoin.
"""
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
    "verifier_reset", REPO_ROOT / "tools" / "banc" / "verifier_reset.py")
verifier_reset = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verifier_reset)


def _ecrire_node(partition_dir: Path, node_id: str, meta: dict) -> None:
    (partition_dir / "nodes").mkdir(parents=True, exist_ok=True)
    front = json.dumps(meta, ensure_ascii=False)
    (partition_dir / "nodes" / f"{node_id}.md").write_text(
        f"---\n{front}\n---\n\nCorps factice de {node_id}.\n", encoding="utf-8")


def _preparer_partition(tmp: Path) -> Path:
    """Partition synthétique de 3 nœuds jouables + l'entrée du module,
    même convention que tests/detecter_fin_test.py."""
    partition_dir = tmp / "partition"
    _ecrire_node(partition_dir, "avant-propos", {
        "id": "avant-propos", "type": "scene", "titre": "Entrée factice",
        "liens": [{"cible_id": "para-1", "condition_textuelle": ""}],
    })
    _ecrire_node(partition_dir, "para-1", {
        "id": "para-1", "type": "scene", "titre": "Scène factice 1",
        "liens": [{"cible_id": "para-2", "condition_textuelle": ""}],
    })
    _ecrire_node(partition_dir, "para-2", {
        "id": "para-2", "type": "scene", "titre": "Scène factice 2",
        "liens": [{"cible_id": "para-3", "condition_textuelle": ""}],
    })
    _ecrire_node(partition_dir, "para-3", {
        "id": "para-3", "type": "scene", "titre": "Scène finale factice",
        "liens": [],
        "charniere_sortie": {"ouvre_vers_md": "Fin factice.", "prerequis_etat": "atteint"},
    })
    return partition_dir


def _preparer_partie(tmp: Path, nom: str, partition_dir: Path, tour: int,
                      location_avant: str, location_apres: str,
                      cliquet_avant: dict | None = None, cliquet_apres: dict | None = None,
                      visee_avant: str | None = None, visee_apres: str | None = None,
                      events_tour_n1: list[dict] | None = None,
                      temoins_avant: list[str] | None = None,
                      textes_tour_n1: dict | None = None) -> Path:
    nn = f"{tour:02d}"
    nn1 = f"{tour + 1:02d}"
    partie_dir = tmp / nom
    save_dir = partie_dir / "save"
    (save_dir / "memory").mkdir(parents=True)

    (partie_dir / f"etat-avant-reset-{nn}.json").write_text(json.dumps({
        "player": {"location": location_avant},
        "rpg": {"cliquet": cliquet_avant, "visee_courante": visee_avant},
    }), encoding="utf-8")

    (save_dir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir), "titre": "Module factice"}),
        encoding="utf-8")
    (save_dir / "state.json").write_text(json.dumps({
        "player": {"location": location_apres},
        "rpg": {"cliquet": cliquet_apres, "visee_courante": visee_apres},
    }), encoding="utf-8")

    lignes = [json.dumps(rec) for rec in (events_tour_n1 or [])]
    (save_dir / "memory" / "events.jsonl").write_text(
        "\n".join(lignes) + ("\n" if lignes else ""), encoding="utf-8")

    if temoins_avant:
        contenu_etancheite = "\n".join(f"TEMOIN: {t}" for t in temoins_avant) + "\n"
        (partie_dir / f"etancheite-avant-reset-{nn}.md").write_text(
            contenu_etancheite, encoding="utf-8")

    for suffixe, texte in (textes_tour_n1 or {}).items():
        (partie_dir / f"{suffixe}-{nn1}.md").write_text(texte, encoding="utf-8")

    return partie_dir


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="verifier-reset-test-"))
    try:
        partition_dir = _preparer_partition(tmp)

        # --- 1. Position : PASS (inchangée) --------------------------------
        p = _preparer_partie(tmp, "position-pass", partition_dir, 5,
                              "para-1", "para-1")
        r = verifier_reset.evaluer(p, 5)
        assert r["position"]["pass"], r["position"]
        print("1) position inchangée (tour N+1 = tour N) -> PASS")

        # --- 2. Position : PASS (débouché valide de la partition) ---------
        p = _preparer_partie(tmp, "position-pass-debouche", partition_dir, 5,
                              "para-1", "para-2")
        r = verifier_reset.evaluer(p, 5)
        assert r["position"]["pass"], r["position"]
        print("2) position avancée par un débouché VALIDE (para-1 -> para-2) -> PASS")

        # --- 3. Position : FAIL (retour à l'ouverture) ---------------------
        p = _preparer_partie(tmp, "position-fail", partition_dir, 5,
                              "para-2", "avant-propos")
        r = verifier_reset.evaluer(p, 5)
        assert not r["position"]["pass"], r["position"]
        print("3) position retombée sur l'ouverture (avant-propos) -> FAIL")

        # --- 4. Cliquet/visée : PASS (conservés) ---------------------------
        p = _preparer_partie(tmp, "cliquet-pass", partition_dir, 5,
                              "para-1", "para-1",
                              cliquet_avant={"acte1": True}, cliquet_apres={"acte1": True},
                              visee_avant="sortir-du-manoir", visee_apres="sortir-du-manoir")
        r = verifier_reset.evaluer(p, 5)
        assert r["cliquet_visee"]["pass"], r["cliquet_visee"]
        print("4) cliquet + visée courante identiques avant/après -> PASS")

        # --- 5. Cliquet/visée : FAIL (perdus/altérés au reset) -------------
        p = _preparer_partie(tmp, "cliquet-fail", partition_dir, 5,
                              "para-1", "para-1",
                              cliquet_avant={"acte1": True}, cliquet_apres=None,
                              visee_avant="sortir-du-manoir", visee_apres=None)
        r = verifier_reset.evaluer(p, 5)
        assert not r["cliquet_visee"]["pass"], r["cliquet_visee"]
        print("5) cliquet + visée courante effacés par le reset -> FAIL")

        # --- 6. Réintroduction : PASS (aucun événement suspect au tour N+1) -
        p = _preparer_partie(tmp, "reintro-pass", partition_dir, 5,
                              "para-1", "para-1",
                              events_tour_n1=[{"turn": 6, "type": "attack"}])
        r = verifier_reset.evaluer(p, 5)
        assert r["reintroduction"]["pass"], r["reintroduction"]
        print("6) aucun scene_intro ni location=ouverture au tour N+1 -> PASS")

        # --- 7. Réintroduction : FAIL (scene_intro au tour N+1) ------------
        p = _preparer_partie(tmp, "reintro-fail-type", partition_dir, 5,
                              "para-1", "para-1",
                              events_tour_n1=[{"turn": 6, "type": "scene_intro"}])
        r = verifier_reset.evaluer(p, 5)
        assert not r["reintroduction"]["pass"], r["reintroduction"]
        print("7) événement scene_intro journalisé au tour N+1 -> FAIL")

        # --- 7bis. Réintroduction : FAIL (location = ouverture au tour N+1) -
        p = _preparer_partie(tmp, "reintro-fail-location", partition_dir, 5,
                              "para-1", "para-1",
                              events_tour_n1=[{"turn": 6, "env": {"deltas": {"location": "avant-propos"}}}])
        r = verifier_reset.evaluer(p, 5)
        assert not r["reintroduction"]["pass"], r["reintroduction"]
        print("7bis) delta location réintroduisant l'ouverture au tour N+1 -> FAIL")

        # --- 8. Mot-témoin : PASS (absent du tour N+1) ----------------------
        p = _preparer_partie(tmp, "temoin-pass", partition_dir, 5,
                              "para-1", "para-1",
                              temoins_avant=["aurore-ecarlate"],
                              textes_tour_n1={"tour": "# tour 06\n\nProse neutre, sans fuite.\n"})
        r = verifier_reset.evaluer(p, 5)
        assert r["temoin"]["pass"], r["temoin"]
        print("8) mot-témoin d'avant reset absent de tour-06.md -> PASS")

        # --- 9. Mot-témoin : FAIL (fuite dans tour-N+1.md) ------------------
        p = _preparer_partie(tmp, "temoin-fail", partition_dir, 5,
                              "para-1", "para-1",
                              temoins_avant=["aurore-ecarlate"],
                              textes_tour_n1={"tour": "# tour 06\n\nOn se souvient de aurore-ecarlate.\n"})
        r = verifier_reset.evaluer(p, 5)
        assert not r["temoin"]["pass"], r["temoin"]
        print("9) mot-témoin d'avant reset retrouvé dans tour-06.md -> FAIL")

        # --- 10. formater_markdown + CLI : verdict global VERT/ROUGE -------
        p_vert = _preparer_partie(tmp, "verdict-vert", partition_dir, 5,
                                   "para-1", "para-1",
                                   cliquet_avant={"a": 1}, cliquet_apres={"a": 1},
                                   visee_avant="v", visee_apres="v",
                                   events_tour_n1=[],
                                   temoins_avant=["mot-x"],
                                   textes_tour_n1={"tour": "prose propre"})
        resultats = verifier_reset.evaluer(p_vert, 5)
        markdown = verifier_reset.formater_markdown(5, resultats)
        assert "Verdict global : VERT (4/4)" in markdown, markdown
        (p_vert / "reset-05.md").write_text(markdown, encoding="utf-8")

        import subprocess
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "banc" / "verifier_reset.py"),
             str(p_vert), "5"],
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (p_vert / "reset-05.md").exists()
        assert "VERT (4/4)" in (p_vert / "reset-05.md").read_text(encoding="utf-8")
        print("10) verdict global VERT (4/4) sur un cas tout-PASS, CLI sortie 0, reset-05.md écrit")

        r_rouge = verifier_reset.evaluer(p, 5)  # p = temoin-fail ci-dessus (1 FAIL)
        markdown_rouge = verifier_reset.formater_markdown(5, r_rouge)
        assert "ROUGE (3/4)" in markdown_rouge, markdown_rouge
        print("11) verdict global ROUGE (n/4) sur un cas avec un point FAIL")

        print("\nALL VERIFIER_RESET TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
