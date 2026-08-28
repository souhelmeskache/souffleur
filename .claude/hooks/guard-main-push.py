#!/usr/bin/env python
"""Garde de main (D-224, phase 1 point f) — refuse tout `git push` direct sur `main`.

Hook Claude Code PreToolUse (matcher "Bash|PowerShell"). Reçoit le JSON de l'appel
d'outil sur stdin, inspecte la commande shell : si elle est/contient un `git push`
dont la destination (explicite ou implicite) est `main`, le refuse. Tout le reste
(push d'une autre branche, `git pull`, `gh pr create`, ...) passe sans y toucher.

Ce n'est qu'un filet côté harnais (defense in depth) : la vraie porte est la branch
protection GitHub côté serveur (geste Souhel, cf. README-ci.md), qui rejette de toute
façon un push direct sur main même si ce hook était contourné ou absent.

Ne remplace pas un vrai parseur de ligne de commande — heuristique volontairement
prudente (bloque en cas de doute), pas exhaustive sur toutes les formes de shell.
"""
import json
import re
import subprocess
import sys

GIT_PUSH_RE = re.compile(r"(?:^|[;&|]|\s)git\s+push(?=\s|$)")
# Un "main" comme destination explicite : "origin main", "origin HEAD:main",
# "origin refs/heads/main", ":main" (refspec), etc. -- toujours en frontière de mot.
MAIN_TARGET_RE = re.compile(r"(?:^|[\s/:])main(?:$|[\s:])")
BARE_PUSH_RE = re.compile(
    r"^git\s+push(?:\s+(?:-u|--set-upstream|-f|--force|origin|upstream|HEAD))*\s*$"
)


def current_branch():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def deny(reason):
    print(json.dumps({
        "continue": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }))
    sys.exit(0)


def allow():
    print(json.dumps({"continue": True}))
    sys.exit(0)


QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\])*\'', re.DOTALL)


def strip_quoted(command):
    """Efface le contenu des chaînes entre guillemets (ex: message de -m "...")
    avant analyse -- sinon un texte qui PARLE de "git push" ou "main" (commit
    message, docstring, heredoc) peut faire déclencher la garde à tort."""
    return QUOTED_RE.sub(lambda m: '""', command)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        allow()
        return
    raw_command = (payload.get("tool_input") or {}).get("command") or ""
    if not raw_command.strip():
        allow()
        return
    command = strip_quoted(raw_command)

    # Découpe grossière en segments de commande (;, &&, ||, |) pour attraper les
    # commandes chaînées (ex: "cd repo && git push origin main").
    segments = re.split(r"&&|\|\||[;|]", command)
    for seg in segments:
        seg = seg.strip()
        if not GIT_PUSH_RE.search(seg):
            continue
        # Isole la partie après "git push" pour l'analyse des tokens.
        after = re.split(r"git\s+push", seg, maxsplit=1)[-1]
        if MAIN_TARGET_RE.search(after):
            deny(
                "Garde de main (D-224) : push direct vers main refuse par le hook "
                "du repo (.claude/hooks/guard-main-push.py). Passe par une branche "
                "+ Pull Request -- merge seulement une fois la CI verte."
            )
        if BARE_PUSH_RE.match(seg.strip()):
            branch = current_branch()
            if branch == "main":
                deny(
                    "Garde de main (D-224) : push implicite depuis la branche main "
                    "refuse par le hook du repo (.claude/hooks/guard-main-push.py). "
                    "Passe par une branche + Pull Request."
                )
    allow()


if __name__ == "__main__":
    main()
