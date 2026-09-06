"""Issue #313 : tools/banc/verifier-fumee-avant-nuit.sh -- verdict mécanique
du run de fumée (une paire, 3 tours, Director sonnet, -RunDir dédié) que
nuit.cmd lance avant toute nuit (I-468 point 3, décision Souhel 06/09) :
« le banc se prouve sur lui-même avant de mesurer le jeu ».

Ce script ne relance rien lui-même (aucun herdr/claude réel) -- il lit
seulement partie-01/ d'un -RunDir déjà produit, fabriqué ici à la main avec
des fichiers 100% synthétiques (D-109).

1. 3 prose-NN.md non vides, aucun craquement -> OK, code 0.
2. Un craquement-timeout-02.md présent -> REFUS, code non nul, cite le nom
   du craquement.
3. prose-03.md absente (partie arrêtée avant le tour 3) -> REFUS.
4. prose-02.md vide (0 octet) -> REFUS.
5. partie-01/ absent (RunDir vide, rien joué) -> REFUS.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "banc" / "verifier-fumee-avant-nuit.sh"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def lancer(run_dir: Path, tours: int = 3):
    return subprocess.run(
        [BASH, str(SCRIPT), str(run_dir), str(tours)],
        capture_output=True, timeout=60, encoding="utf-8", errors="replace",
    )


def ecrire_parties(tmp: Path, prose: dict, craquements: list = None):
    run_dir = tmp / "run"
    partie_dir = run_dir / "partie-01"
    partie_dir.mkdir(parents=True)
    for nn, contenu in prose.items():
        (partie_dir / f"prose-{nn}.md").write_text(contenu, encoding="utf-8")
    for nom in craquements or []:
        (partie_dir / nom).write_text("craquement synthétique.\n", encoding="utf-8")
    return run_dir


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"
    tmp = Path(tempfile.mkdtemp(prefix="verifier-fumee-test-"))
    try:
        # ------------------------------------------------------------
        # Cas 1 : 3 tours, prose non vide, aucun craquement -> OK
        # ------------------------------------------------------------
        run_dir = ecrire_parties(tmp / "cas1", {
            "01": "Prose synthétique du tour 1.\n",
            "02": "Prose synthétique du tour 2.\n",
            "03": "Prose synthétique du tour 3.\n",
        })
        p1 = lancer(run_dir)
        assert p1.returncode == 0, f"cas 1 : code attendu 0, reçu {p1.returncode}\n{p1.stderr}"
        assert "OK" in p1.stdout, p1.stdout
        print("PASS: cas 1 -- 3 tours de prose non vide, OK")

        # ------------------------------------------------------------
        # Cas 2 : craquement-timeout-02.md présent -> REFUS
        # ------------------------------------------------------------
        run_dir = ecrire_parties(tmp / "cas2", {"01": "Prose du tour 1.\n"},
                                  craquements=["craquement-timeout-02.md"])
        p2 = lancer(run_dir)
        assert p2.returncode != 0, f"cas 2 : code non nul attendu, reçu {p2.returncode}"
        assert "REFUS" in p2.stderr and "craquement-timeout-02.md" in p2.stderr, p2.stderr
        print("PASS: cas 2 -- craquement présent, REFUS nommé")

        # ------------------------------------------------------------
        # Cas 3 : prose-03.md absente (arrêtée avant le 3e tour) -> REFUS
        # ------------------------------------------------------------
        run_dir = ecrire_parties(tmp / "cas3", {
            "01": "Prose du tour 1.\n",
            "02": "Prose du tour 2.\n",
        })
        p3 = lancer(run_dir)
        assert p3.returncode != 0, f"cas 3 : code non nul attendu, reçu {p3.returncode}"
        assert "REFUS" in p3.stderr and "tour 03" in p3.stderr, p3.stderr
        print("PASS: cas 3 -- 3e tour manquant, REFUS")

        # ------------------------------------------------------------
        # Cas 4 : prose-02.md vide -> REFUS
        # ------------------------------------------------------------
        run_dir = ecrire_parties(tmp / "cas4", {
            "01": "Prose du tour 1.\n",
            "02": "",
            "03": "Prose du tour 3.\n",
        })
        p4 = lancer(run_dir)
        assert p4.returncode != 0, f"cas 4 : code non nul attendu, reçu {p4.returncode}"
        assert "REFUS" in p4.stderr and "tour 02" in p4.stderr, p4.stderr
        print("PASS: cas 4 -- prose vide, REFUS")

        # ------------------------------------------------------------
        # Cas 5 : aucune partie-01/ -> REFUS
        # ------------------------------------------------------------
        run_dir_vide = tmp / "cas5" / "run"
        run_dir_vide.mkdir(parents=True)
        p5 = lancer(run_dir_vide)
        assert p5.returncode != 0, f"cas 5 : code non nul attendu, reçu {p5.returncode}"
        assert "REFUS" in p5.stderr and "partie-01" in p5.stderr, p5.stderr
        print("PASS: cas 5 -- aucune partie jouée, REFUS")

        print("\nALL VERIFIER_FUMEE_AVANT_NUIT TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
