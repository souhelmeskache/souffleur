"""Issue #298 : tools/banc/verifier-workspace-banc-vide.sh -- classe les
workspaces herdr "banc*" d'une sortie `herdr workspace list`, extrait de
verifier-avant-nuit.sh pour être testable indépendamment de herdr.

1. Aucun workspace "banc*" -> OK, code 0, sortie vide.
2. Workspace "banc-20260905" avec pane_count=1 (juste le pane ancre, aucune
   partie en vol) -> OK, code 0, sortie vide.
3. Workspace "banc-20260905" avec pane_count=3 (partie survivante) -> REFUS,
   code non nul, message sur stderr citant le label et le compte de panes.
4. Un workspace "banc" (label nu, smoke test manuel) non vide -> REFUS aussi
   (le préfixe "banc" couvre les deux formes, pas seulement "banc-<date>").
5. Un autre workspace non-banc avec plusieurs panes (ex. une lane) -> OK,
   jamais refusé (seul le préfixe "banc" est concerné).
"""
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "banc" / "verifier-workspace-banc-vide.sh"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def workspace_list_json(*workspaces):
    ws = ",".join(
        f'{{"label":"{label}","workspace_id":"{wsid}","pane_count":{count}}}'
        for label, wsid, count in workspaces
    )
    return f'{{"result":{{"workspaces":[{ws}]}}}}'


def lancer(sortie_herdr: str):
    return subprocess.run(
        [BASH, str(SCRIPT)],
        input=sortie_herdr, capture_output=True, timeout=30,
        encoding="utf-8", errors="replace",
    )


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"

    # ------------------------------------------------------------------
    # Cas 1 : aucun workspace banc -> OK, sortie vide
    # ------------------------------------------------------------------
    p1 = lancer(workspace_list_json(("souffleur", "w1", 5)))
    assert p1.returncode == 0, f"cas 1 : code attendu 0, reçu {p1.returncode}\n{p1.stderr}"
    assert p1.stdout.strip() == "" and p1.stderr.strip() == "", f"cas 1 : sortie vide attendue ({p1.stdout!r}, {p1.stderr!r})"
    print("PASS: cas 1 -- aucun workspace banc, OK silencieux")

    # ------------------------------------------------------------------
    # Cas 2 : banc-20260905 avec 1 seul pane (l'ancre) -> OK
    # ------------------------------------------------------------------
    p2 = lancer(workspace_list_json(("banc-20260905", "w2", 1)))
    assert p2.returncode == 0, f"cas 2 : code attendu 0, reçu {p2.returncode}\n{p2.stderr}"
    assert p2.stderr.strip() == "", f"cas 2 : rien attendu sur stderr ({p2.stderr!r})"
    print("PASS: cas 2 -- workspace banc avec juste le pane ancre, OK")

    # ------------------------------------------------------------------
    # Cas 3 : banc-20260905 avec 3 panes -> REFUS
    # ------------------------------------------------------------------
    p3 = lancer(workspace_list_json(("banc-20260905", "w3", 3)))
    assert p3.returncode != 0, f"cas 3 : code non nul attendu, reçu {p3.returncode}"
    assert "REFUS" in p3.stderr and "banc-20260905" in p3.stderr, f"cas 3 : {p3.stderr!r}"
    print("PASS: cas 3 -- workspace banc non vide (partie survivante), REFUS")

    # ------------------------------------------------------------------
    # Cas 4 : label nu "banc" non vide -> REFUS aussi
    # ------------------------------------------------------------------
    p4 = lancer(workspace_list_json(("banc", "w4", 2)))
    assert p4.returncode != 0, f"cas 4 : code non nul attendu, reçu {p4.returncode}"
    assert "REFUS" in p4.stderr and "banc" in p4.stderr, f"cas 4 : {p4.stderr!r}"
    print("PASS: cas 4 -- label nu 'banc' non vide, REFUS")

    # ------------------------------------------------------------------
    # Cas 5 : un workspace non-banc (ex. lane-291) avec plusieurs panes ->
    # jamais refusé, seul le préfixe "banc" est concerné.
    # ------------------------------------------------------------------
    p5 = lancer(workspace_list_json(("lane-291", "w5", 4)))
    assert p5.returncode == 0, f"cas 5 : code attendu 0, reçu {p5.returncode}\n{p5.stderr}"
    assert p5.stderr.strip() == "", f"cas 5 : rien attendu sur stderr ({p5.stderr!r})"
    print("PASS: cas 5 -- workspace non-banc non vide, jamais refusé")

    print("verifier_workspace_banc_vide_test: 5/5 OK")


if __name__ == "__main__":
    main()
