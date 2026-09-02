"""Issue #216 : tools/lancer-banc-fumee.ps1 -- trois cas en -DryRun sur un
dossier temporaire, sur le modèle de tests/lancer_lane_argv_test.py (un vrai
process PowerShell, pas une relecture de texte) :

1. Lancement neuf (pas de -Reprise) : réussit, ne crée aucun dossier
   (contrat -DryRun).
2. -Reprise sur un run synthétique portant prose-01.md à prose-03.md :
   réussit, déduit le prochain tour = 04, ne crée aucun dossier.
3. -Reprise sur un run absent : échoue, code de sortie non nul.

Aucun `herdr`/`gh` réel n'est invoqué : -DryRun sort avant tout appel
externe, mais le script résout quand même le chemin de `herdr` en tête de
fichier (Resolve-ExternalCommand) -- un faux exécutable `herdr` est donc
posé en tête de PATH pour ce process, comme le ferait un vrai binaire, sans
jamais être réellement lancé.

Le script est copié (avec les deux gabarits dont il dépend) dans un dépôt
Git jetable, 100% synthétique, plutôt que d'écrire dans le vrai
bench/banc-fumee/ du dépôt courant : $RepoRoot du script se déduit de
`git -C $PSScriptRoot rev-parse --show-toplevel`, donc un dépôt jetable
isolé garantit qu'aucun test ne peut toucher au bench/ réel.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REEL = REPO_ROOT / "tools" / "lancer-banc-fumee.ps1"
GABARIT_MJ_REEL = REPO_ROOT / "tools" / "prompts" / "banc-mj.md"
GABARIT_JOUEUR_REEL = REPO_ROOT / "tools" / "prompts" / "banc-joueur.md"

FAKE_HERDR_CMD = "@echo off\r\nexit /b 0\r\n"

# Env sans variables GIT_* héritées (même garde que garde_prepush_test.py) :
# quand ce test tourne DEPUIS un hook git (pre-commit), git pose GIT_DIR/
# GIT_INDEX_FILE dans l'environnement du process hook — hérité tel quel par
# nos propres appels `git init`/PowerShell sinon, ce qui redirigerait le
# dépôt jetable de ce test vers le dépôt parent au lieu du sien.
ENV_SANS_GIT = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def find_powershell():
    for name in ("powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_repo_jetable(tmp_root: Path) -> Path:
    """Dépôt Git jetable portant une copie du script sous test + ses deux
    gabarits (banc-mj.md, banc-joueur.md) -- suffisant pour que -DryRun
    tourne de bout en bout sans toucher au vrai dépôt."""
    repo = tmp_root / "repo-jetable"
    (repo / "tools" / "prompts").mkdir(parents=True)

    shutil.copy(SCRIPT_REEL, repo / "tools" / "lancer-banc-fumee.ps1")
    shutil.copy(GABARIT_MJ_REEL, repo / "tools" / "prompts" / "banc-mj.md")
    shutil.copy(GABARIT_JOUEUR_REEL, repo / "tools" / "prompts" / "banc-joueur.md")

    subprocess.run(["git", "init", "-q"], cwd=repo, env=ENV_SANS_GIT, check=True)
    return repo


def build_fake_herdr(tmp_root: Path) -> Path:
    """Un faux `herdr` sur PATH : Resolve-ExternalCommand doit le trouver,
    mais -DryRun ne l'exécute jamais réellement (il sort avant)."""
    bin_dir = tmp_root / "fake-bin"
    bin_dir.mkdir()
    (bin_dir / "herdr.cmd").write_text(FAKE_HERDR_CMD, encoding="utf-8")
    return bin_dir


def run_dryrun(ps_exe, script_path: Path, fake_bin: Path, args):
    env = {**ENV_SANS_GIT, "PATH": f"{fake_bin}{os.pathsep}{ENV_SANS_GIT.get('PATH', '')}"}
    cmd = [
        ps_exe, "-NoProfile", "-File", str(script_path),
        "-SessionTour", "banc-test-tour", "-Save", "banc-test-save",
        "-DryRun",
    ] + args
    return subprocess.run(
        cmd, capture_output=True, timeout=60, env=env,
        encoding="utf-8", errors="replace",
    )


def lister_dossiers_bench(repo: Path):
    bench = repo / "bench" / "banc-fumee"
    if not bench.exists():
        return []
    return sorted(p.name for p in bench.iterdir() if p.is_dir())


def main():
    ps_exe = find_powershell()
    assert ps_exe, "powershell/pwsh introuvable -- requis pour ce test (CI: windows-latest)"
    assert SCRIPT_REEL.exists(), f"script absent : {SCRIPT_REEL}"
    assert GABARIT_MJ_REEL.exists(), f"gabarit absent : {GABARIT_MJ_REEL}"
    assert GABARIT_JOUEUR_REEL.exists(), f"gabarit absent : {GABARIT_JOUEUR_REEL}"

    tmp_root = Path(tempfile.mkdtemp(prefix="lancer-banc-fumee-test-"))
    try:
        repo = build_repo_jetable(tmp_root)
        fake_bin = build_fake_herdr(tmp_root)
        script_path = repo / "tools" / "lancer-banc-fumee.ps1"

        # ------------------------------------------------------------
        # Cas 1 : lancement neuf (pas de -Reprise)
        # ------------------------------------------------------------
        avant = lister_dossiers_bench(repo)
        p1 = run_dryrun(ps_exe, script_path, fake_bin, [])
        assert p1.returncode == 0, (
            f"lancement neuf : code de sortie attendu 0, recu {p1.returncode}\n"
            f"stdout={p1.stdout}\nstderr={p1.stderr}"
        )
        assert "DryRun" in p1.stdout, "lancement neuf : sortie DryRun attendue absente"
        apres = lister_dossiers_bench(repo)
        assert apres == avant, (
            f"lancement neuf : -DryRun ne doit creer aucun dossier "
            f"(avant={avant}, apres={apres})"
        )
        print("PASS: lancement neuf (DryRun, code 0, aucun dossier créé)")

        # ------------------------------------------------------------
        # Cas 2 : -Reprise sur un run synthétique prose-01..03 -> tour 04
        # ------------------------------------------------------------
        run_synthetique = "20260101-000000"
        journal_dir = repo / "bench" / "banc-fumee" / run_synthetique
        journal_dir.mkdir(parents=True)
        for n in ("01", "02", "03"):
            (journal_dir / f"prose-{n}.md").write_text(
                f"prose synthétique du tour {n}, fixture de test\n", encoding="utf-8"
            )

        avant = lister_dossiers_bench(repo)
        p2 = run_dryrun(ps_exe, script_path, fake_bin, ["-Reprise", run_synthetique])
        assert p2.returncode == 0, (
            f"-Reprise (run present) : code de sortie attendu 0, recu {p2.returncode}\n"
            f"stdout={p2.stdout}\nstderr={p2.stderr}"
        )
        assert "04" in p2.stdout, (
            f"-Reprise : prochain tour attendu 04 (dernier prose-03.md + 1) absent de la sortie\n"
            f"stdout={p2.stdout}"
        )
        apres = lister_dossiers_bench(repo)
        assert apres == avant, (
            f"-Reprise : -DryRun ne doit creer aucun dossier "
            f"(avant={avant}, apres={apres})"
        )
        print("PASS: -Reprise sur run synthétique (prose-01..03 -> prochain tour 04, aucun dossier créé)")

        # ------------------------------------------------------------
        # Cas 3 : -Reprise sur un run absent -> échec, code non nul
        # ------------------------------------------------------------
        p3 = run_dryrun(ps_exe, script_path, fake_bin, ["-Reprise", "20990101-999999-inexistant"])
        assert p3.returncode != 0, (
            f"-Reprise (run absent) : code de sortie non nul attendu, recu {p3.returncode}\n"
            f"stdout={p3.stdout}\nstderr={p3.stderr}"
        )
        print("PASS: -Reprise sur run absent (échec, code de sortie non nul)")

        print("lancer_banc_fumee_test: 3/3 OK")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
