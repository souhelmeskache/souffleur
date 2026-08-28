"""D-224: versioned pre-push guard — refuse any push targeting refs/heads/main.

Real end-to-end test: throwaway repo + local bare remote, hooks/ installed via
`git config core.hooksPath hooks`. One case per bypass vector found by the
review of the old regex-based guard (HEAD:main, +main refspec, --force,
--force-with-lease, implicit push from main, git -C, shell-quoted form),
plus worktree inheritance of core.hooksPath, plus the legitimate-branch
control (fix/main must PASS).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_SRC = REPO_ROOT / "hooks"


def find_bash():
    """Prefer Git for Windows' bash (WSL's bash mangles C:\\ remote URLs)."""
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


def run(args, cwd, env, shell_via_bash=False):
    """Run a command, return (returncode, stdout, stderr)."""
    if shell_via_bash:
        bash = find_bash()
        assert bash, "bash introuvable (Git for Windows le fournit)"
        args = [bash, "-c", args]
    p = subprocess.run(args, cwd=str(cwd), env=env,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


def main():
    tmp = Path(tempfile.mkdtemp(prefix="garde-prepush-"))
    # Strip inherited GIT_* vars: when this test runs from a git hook,
    # GIT_DIR/GIT_INDEX_FILE would redirect the throwaway repo's commands
    # to the parent repo.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(tmp),
        "USERPROFILE": str(tmp),
        "XDG_CONFIG_HOME": str(tmp),
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
    })
    try:
        bare = tmp / "origin.git"
        clone = tmp / "clone"
        assert run(["git", "init", "--bare", "-b", "main", str(bare)],
                   tmp, env)[0] == 0
        assert run(["git", "clone", str(bare), str(clone)], tmp, env)[0] == 0

        def git(*args, cwd=clone, check=True):
            code, out, err = run(["git", *args], cwd, env)
            if check:
                assert code == 0, f"git {args} a echoue: {err}"
            return code, out, err

        # Seed main (guard not yet active) with a versioned hooks/ carrying
        # the pre-push under test (not pre-commit: it would rerun the full
        # suite at every throwaway commit).
        (clone / "f.txt").write_text("v1\n")
        (clone / "hooks").mkdir()
        shutil.copy(HOOKS_SRC / "pre-push", clone / "hooks" / "pre-push")
        git("add", "-A")
        git("commit", "-m", "seed")
        git("push", "origin", "main")

        # Activate the guard exactly as documented in CLAUDE.md.
        git("config", "core.hooksPath", "hooks")

        # Local main gets one commit ahead so pushes are never "up to date"
        # (an up-to-date push would skip the hook and vacuously succeed).
        (clone / "f.txt").write_text("v2\n")
        git("add", "-A")
        git("commit", "-m", "ahead")
        git("checkout", "-b", "feat")
        (clone / "g.txt").write_text("feat\n")
        git("add", "-A")
        git("commit", "-m", "feat work")

        baseline = run(["git", "rev-parse", "main"], bare, env)[1].strip()

        def expect_refused(label, args, cwd=clone, shell_via_bash=False):
            code, out, err = run(args, cwd, env, shell_via_bash)
            assert code != 0, f"{label}: le push aurait du etre REFUSE\n{out}{err}"
            assert "PUSH REFUSE" in err, \
                f"{label}: refus mais pas par la garde D-224\n{err}"
            now = run(["git", "rev-parse", "main"], bare, env)[1].strip()
            assert now == baseline, f"{label}: main du remote a bouge!"
            print(f"PASS refuse: {label}")

        expect_refused("HEAD:main", ["git", "push", "origin", "HEAD:main"])
        expect_refused("refspec +main", ["git", "push", "origin", "+main"])
        expect_refused("--force", ["git", "push", "--force", "origin", "main"])
        expect_refused("--force-with-lease",
                       ["git", "push", "--force-with-lease", "origin", "main"])
        expect_refused("git -C", ["git", "-C", str(clone), "push",
                                  "origin", "main"], cwd=tmp)
        expect_refused("forme entre guillemets",
                       'git push origin "main"', shell_via_bash=True)

        # Implicit push while checked out on main.
        git("checkout", "main")
        expect_refused("push implicite depuis main", ["git", "push"])
        git("checkout", "feat")

        # Worktree must inherit core.hooksPath (shared .git/config, relative
        # path resolved in each working copy — hooks/ is versioned there).
        wt = tmp / "wt"
        git("worktree", "add", str(wt), "-b", "feat2", "feat")
        expect_refused("worktree HEAD:main",
                       ["git", "push", "origin", "HEAD:main"], cwd=wt)

        # Control: a legitimate branch whose name merely contains "main".
        git("checkout", "-b", "fix/main")
        code, out, err = run(["git", "push", "origin", "fix/main"], clone, env)
        assert code == 0, f"fix/main aurait du PASSER: {err}"
        code, out, _ = run(["git", "rev-parse", "--verify",
                            "refs/heads/fix/main"], bare, env)
        assert code == 0, "fix/main absent du remote apres push"
        print("PASS autorise: fix/main")

        print("garde_prepush_test: 9/9 OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
