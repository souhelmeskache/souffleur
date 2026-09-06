"""I-324: garde pre-commit "materiau reel" -- refuse tout commit qui ferait
entrer un identifiant du corpus de campagne reel (slug/nom d'un record sous
`corpus_dir()`) dans l'historique.

Real end-to-end test: throwaway repo, hooks/ installe via
`git config core.hooksPath hooks` (comme documente dans le CLAUDE.md du
repo), CORPUS_DIR pointe vers un faux corpus SYNTHETIQUE (D-109 : aucun
materiau de campagne reel dans ce test). Un cas par point du critere de
l'Issue #324 : slug dans le contenu, slug dans un nom de fichier, nom
invente accepte, "garde non jouee" sans corpus -- plus une mesure de duree
sur un diff de 600 lignes.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_SRC = REPO_ROOT / "hooks"


def run(args, cwd, env):
    p = subprocess.run(args, cwd=str(cwd), env=env,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


def make_env(tmp: Path, corpus_dir: Path | None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(tmp), "USERPROFILE": str(tmp), "XDG_CONFIG_HOME": str(tmp),
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        # coderain n'existe pas dans le repo jetable -- le script du hook
        # (copie dans hooks/ du repo jetable) le retrouve via PYTHONPATH.
        "PYTHONPATH": str(REPO_ROOT),
    })
    env["CORPUS_DIR"] = str(corpus_dir) if corpus_dir else str(tmp / "corpus-absent")
    return env


def make_fake_corpus(root: Path) -> None:
    """Corpus synthetique (D-109) : deux records invente de toutes pieces,
    aucun rapport avec un vrai module."""
    records = root / "module-fictif" / "partition-pconv0" / "records"
    records.mkdir(parents=True)
    (records / "aile-noire.md").write_text(
        '---\n'
        '{\n'
        ' "id": "aile-noire",\n'
        ' "classe": "pnj",\n'
        ' "nom": "Aile Noire"\n'
        '}\n'
        '---\n'
        "Corps du record invente, sans rapport avec du materiau reel.\n",
        encoding="utf-8",
    )
    (records / "gouffre-cendre.md").write_text(
        '---\n'
        '{\n'
        ' "id": "gouffre-cendre",\n'
        ' "classe": "lieu",\n'
        ' "nom": "Gouffre de Cendre"\n'
        '}\n'
        '---\n'
        "Autre record invente.\n",
        encoding="utf-8",
    )


def make_repo(tmp: Path, env: dict) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    repo = tmp / "repo"
    assert run(["git", "init", "-b", "main", str(repo)], tmp, env)[0] == 0

    def git(*args, check=True):
        code, out, err = run(["git", *args], repo, env)
        if check:
            assert code == 0, f"git {args} a echoue: {err}"
        return code, out, err

    (repo / "hooks").mkdir()
    shutil.copy(HOOKS_SRC / "pre-commit", repo / "hooks" / "pre-commit")
    shutil.copy(HOOKS_SRC / "verifier-materiau-reel.py",
                repo / "hooks" / "verifier-materiau-reel.py")
    (repo / "f.md").write_text("seed\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "seed (garde pas encore active)")
    git("config", "core.hooksPath", "hooks")
    return repo


def commit(repo: Path, env: dict, filename: str, content: str, msg: str):
    (repo / filename).write_text(content, encoding="utf-8")
    code, out, err = run(["git", "add", "-A"], repo, env)
    assert code == 0, err
    return run(["git", "commit", "-m", msg], repo, env)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="garde-materiau-reel-"))
    try:
        corpus = tmp / "corpus"
        make_fake_corpus(corpus)

        # --- Cas 1 : slug reel dans le CONTENU -> refuse -------------------
        env = make_env(tmp, corpus)
        repo = make_repo(tmp / "c1", env)
        code, out, err = commit(
            repo, env, "notes.md",
            "Une ligne qui mentionne aile-noire au milieu du texte.\n",
            "contenu avec slug reel",
        )
        assert code != 0, f"aurait du etre REFUSE (slug en contenu):\n{out}{err}"
        assert "MATERIAU REEL DETECTE" in err, err
        assert "aile-noire" in err, err
        print("PASS refuse: slug reel dans le contenu")

        # --- Cas 2 : slug reel dans un NOM DE FICHIER -> refuse ------------
        env = make_env(tmp, corpus)
        repo = make_repo(tmp / "c2", env)
        code, out, err = commit(
            repo, env, "gouffre-cendre-notes.md",
            "Contenu innocent, aucun terme reel ici.\n",
            "slug reel dans le nom de fichier",
        )
        assert code != 0, f"aurait du etre REFUSE (slug en nom de fichier):\n{out}{err}"
        assert "MATERIAU REEL DETECTE" in err, err
        assert "gouffre-cendre" in err, err
        print("PASS refuse: slug reel dans un nom de fichier")

        # --- Cas 3 : nom INVENTE -> accepte ---------------------------------
        env = make_env(tmp, corpus)
        repo = make_repo(tmp / "c3", env)
        code, out, err = commit(
            repo, env, "faucon-dore-invente.md",
            "Un personnage totalement invente, faucon-dore-invente, sans "
            "rapport avec le corpus.\n",
            "nom invente",
        )
        assert code == 0, f"aurait du etre ACCEPTE (nom invente):\n{out}{err}"
        print("PASS accepte: nom invente")

        # --- Cas 4 : pas de corpus local -> garde non jouee, laisse passer -
        env = make_env(tmp, None)
        repo = make_repo(tmp / "c4", env)
        code, out, err = commit(
            repo, env, "notes.md",
            "Meme avec aile-noire ecrit ici, sans corpus la garde ne joue pas.\n",
            "pas de corpus local",
        )
        assert code == 0, f"aurait du etre ACCEPTE (corpus absent):\n{out}{err}"
        assert "garde non jouee" in err, f"{out}{err}"
        print("PASS accepte + 'garde non jouee': corpus absent")

        # --- Duree sur un diff de 600 lignes --------------------------------
        env = make_env(tmp, corpus)
        repo = make_repo(tmp / "c5", env)
        lignes = "\n".join(f"ligne inventee numero {i}" for i in range(600))
        debut = time.monotonic()
        code, out, err = commit(repo, env, "gros-fichier.md", lignes + "\n",
                                 "diff de 600 lignes, aucun terme reel")
        duree = time.monotonic() - debut
        assert code == 0, f"aurait du etre ACCEPTE (aucun terme reel):\n{out}{err}"
        print(f"PASS: diff de 600 lignes verifie en {duree:.2f}s (commit complet, "
              f"suite de tests incluse -- .md => aucune suite mappee)")
        assert duree < 5.0, f"garde trop lente sur 600 lignes: {duree:.2f}s (critere: <5s)"

        print("garde_materiau_reel_test: 5/5 OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
