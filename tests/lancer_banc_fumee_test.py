"""Issue #216 : tools/lancer-banc-fumee.ps1 -- quatre cas sur un dossier
temporaire, sur le modèle de tests/lancer_lane_argv_test.py (un vrai
process PowerShell, pas une relecture de texte) :

1. Lancement neuf (pas de -Reprise), -DryRun : réussit, ne crée aucun
   dossier (contrat -DryRun).
2. -Reprise sur un run synthétique portant prose-01.md à prose-03.md,
   -DryRun : réussit, déduit le prochain tour = 04 (assertion ancrée sur la
   ligne complète « Prochain tour  : 04 »), ne crée aucun dossier.
3. -Reprise sur un run absent, -DryRun : échoue, code de sortie non nul.
4. Exécution réelle (pas de -DryRun, herdr factice) : le settings.local.json
   posé pour les deux panes autorise Bash(*) ET mcp__coderain-engine__* —
   sans cette dernière règle, le premier appel MCP réel du MJ se bloque sur
   une demande de permission (constat #210, revue PR #224) — puis, relancé
   une seconde fois sur un fichier déjà présent, ne l'écrase pas.

Cas 1-3 : -DryRun sort avant tout appel externe, mais le script résout quand
même le chemin de `herdr` en tête de fichier (Resolve-ExternalCommand) --
un faux exécutable `herdr` est donc posé en tête de PATH pour ce process,
comme le ferait un vrai binaire, sans jamais être réellement lancé.
Cas 4 : le faux `herdr` DOIT répondre (JSON minimal) aux sous-commandes
`pane current`/`pane split` pour que le script aille jusqu'à la pose du
fichier d'automode ; `agent start`/`agent prompt` n'ont besoin que de
réussir (code 0), leur contenu n'est pas vérifié ici.

Le script est copié (avec les deux gabarits dont il dépend) dans un dépôt
Git jetable, 100% synthétique, plutôt que d'écrire dans le vrai
bench/banc-fumee/ du dépôt courant : $RepoRoot du script se déduit de
`git -C $PSScriptRoot rev-parse --show-toplevel`, donc un dépôt jetable
isolé garantit qu'aucun test ne peut toucher au bench/ réel.
"""
import json
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
LISTE_BLANCHE_REEL = REPO_ROOT / "tools" / "banc" / "liste-blanche.ps1"

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


def build_repo_jetable(tmp_root: Path, nom: str = "repo-jetable", gabarits_minimaux: bool = False) -> Path:
    """Dépôt Git jetable portant une copie du script sous test + ses deux
    gabarits (banc-mj.md, banc-joueur.md) -- suffisant pour que -DryRun
    tourne de bout en bout sans toucher au vrai dépôt.

    gabarits_minimaux=True : gabarits synthétiques (un placeholder chacun)
    au lieu d'une copie des vrais fichiers -- pour le cas 4 (exécution
    réelle), qui n'a besoin d'aucun contenu de prompt fidèle et où le vrai
    contenu, une fois substitué, produit une ligne de commande trop longue
    pour le faux `herdr.cmd` (limite de cmd.exe, ~8191 caractères -- une
    limite propre à l'interprète de script, pas à un vrai .exe herdr)."""
    repo = tmp_root / nom
    (repo / "tools" / "prompts").mkdir(parents=True)
    (repo / "tools" / "banc").mkdir(parents=True)

    shutil.copy(SCRIPT_REEL, repo / "tools" / "lancer-banc-fumee.ps1")
    shutil.copy(LISTE_BLANCHE_REEL, repo / "tools" / "banc" / "liste-blanche.ps1")
    if gabarits_minimaux:
        for nom_gabarit in ("banc-mj.md", "banc-joueur.md"):
            (repo / "tools" / "prompts" / nom_gabarit).write_text(
                "gabarit synthétique de test -- {{SAVE}} {{TOURS}} {{SESSION_TOUR}} {{JOURNAL_DIR}}\n",
                encoding="utf-8",
            )
    else:
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


# Faux `herdr` pour le cas 4 (exécution réelle, pas -DryRun) : répond aux
# sous-commandes `pane current`/`pane split` par le JSON minimal attendu
# (result.pane.pane_id) pour que le script avance jusqu'à la pose du
# fichier d'automode ; toute autre sous-commande (`agent start`,
# `agent prompt`) réussit simplement (code 0) -- son contenu n'est pas
# vérifié par ce cas.
FAKE_HERDR_REEL_CMD = (
    "@echo off\r\n"
    'if "%~1"=="pane" (\r\n'
    '  echo {"result":{"pane":{"pane_id":"pane-test"}}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    "exit /b 0\r\n"
)


def build_fake_herdr_reel(tmp_root: Path) -> Path:
    bin_dir = tmp_root / "fake-bin-reel"
    bin_dir.mkdir()
    (bin_dir / "herdr.cmd").write_text(FAKE_HERDR_REEL_CMD, encoding="utf-8")
    return bin_dir


def run_reel(ps_exe, script_path: Path, fake_bin: Path, args):
    """Comme run_dryrun, mais SANS -DryRun -- exécution réelle du script
    (herdr factice, cas 4 uniquement)."""
    env = {**ENV_SANS_GIT, "PATH": f"{fake_bin}{os.pathsep}{ENV_SANS_GIT.get('PATH', '')}"}
    cmd = [
        ps_exe, "-NoProfile", "-File", str(script_path),
        "-SessionTour", "banc-test-tour", "-Save", "banc-test-save",
    ] + args
    return subprocess.run(
        cmd, capture_output=True, timeout=60, env=env,
        encoding="utf-8", errors="replace",
    )


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
    assert LISTE_BLANCHE_REEL.exists(), f"module absent : {LISTE_BLANCHE_REEL}"

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
        assert "Prochain tour  : 04" in p2.stdout, (
            f"-Reprise : ligne 'Prochain tour  : 04' (dernier prose-03.md + 1) absente de la sortie\n"
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

        # ------------------------------------------------------------
        # Cas 4 : exécution réelle (herdr factice) -- settings.local.json
        # autorise Bash(*) ET mcp__coderain-engine__* (revue PR #224,
        # point bloquant #210), et n'écrase pas un fichier déjà présent.
        # ------------------------------------------------------------
        repo4 = build_repo_jetable(tmp_root, nom="repo-jetable-cas4", gabarits_minimaux=True)
        fake_bin_reel = build_fake_herdr_reel(tmp_root)
        script_path4 = repo4 / "tools" / "lancer-banc-fumee.ps1"
        settings_path = repo4 / ".claude" / "settings.local.json"

        assert not settings_path.exists(), "cas 4 : settings.local.json ne devrait pas encore exister"
        p4a = run_reel(ps_exe, script_path4, fake_bin_reel, [])
        assert p4a.returncode == 0, (
            f"cas 4 (pose initiale) : code de sortie attendu 0, recu {p4a.returncode}\n"
            f"stdout={p4a.stdout}\nstderr={p4a.stderr}"
        )
        assert settings_path.is_file(), "cas 4 : settings.local.json n'a pas été posé"

        # Set-Content -Encoding utf8 (PowerShell) pose un BOM -- utf-8-sig
        # le tolère silencieusement.
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        allow = settings.get("permissions", {}).get("allow", [])
        assert "Bash(*)" in allow, f"cas 4 : Bash(*) absent de permissions.allow ({allow})"
        assert "mcp__coderain-engine__*" in allow, (
            f"cas 4 : mcp__coderain-engine__* absent de permissions.allow -- le premier appel "
            f"MCP du MJ se bloquerait (constat #210, revue PR #224) ({allow})"
        )
        print("PASS: settings.local.json posé autorise Bash(*) et mcp__coderain-engine__*")

        # Fusion (#267) : un second lancement sur un fichier déjà présent
        # mais INCOMPLET (portant un marqueur synthétique de l'opérateur, ni
        # Bash(*) ni mcp__coderain-engine__*) doit COMPLÉTER la liste
        # blanche sans retirer le marqueur -- constat nuit N0 (02/09) : un
        # settings.local.json préexistant plus étroit laissait les deux
        # agents redemander des autorisations toute la nuit.
        marqueur = {"permissions": {"allow": ["marqueur-synthetique-test"]}}
        settings_path.write_text(json.dumps(marqueur), encoding="utf-8")
        p4b = run_reel(ps_exe, script_path4, fake_bin_reel, [])
        assert p4b.returncode == 0, (
            f"cas 4 (second lancement) : code de sortie attendu 0, recu {p4b.returncode}\n"
            f"stdout={p4b.stdout}\nstderr={p4b.stderr}"
        )
        settings_apres = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        allow_apres = settings_apres.get("permissions", {}).get("allow", [])
        assert "marqueur-synthetique-test" in allow_apres, (
            f"cas 4 : le marqueur posé par l'opérateur a été perdu lors de la fusion ({allow_apres})"
        )
        assert "Bash(*)" in allow_apres, f"cas 4 : Bash(*) pas ajouté par la fusion ({allow_apres})"
        assert "mcp__coderain-engine__*" in allow_apres, (
            f"cas 4 : mcp__coderain-engine__* pas ajouté par la fusion ({allow_apres})"
        )
        print("PASS: settings.local.json déjà présent mais incomplet est complété sans perte (#267)")

        print("lancer_banc_fumee_test: 4/4 OK")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
