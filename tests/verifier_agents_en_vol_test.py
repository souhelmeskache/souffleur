"""Issue #292 : tools/banc/verifier-agents-en-vol.sh -- garde extraite de
verifier-avant-nuit.sh, classant les agents « en vol » d'une sortie
`herdr agent list`.

Direction Souhel du 05/09 (#292) : une lane `lane-*`/`revue-*` (circuit.sh)
en vol n'est plus une anomalie -- une nuit tourne désormais en parallèle des
lanes. Seul un agent du banc (`banc-mj*`/`banc-joueur*`) survivant entre
réellement en collision (#271/#282) et reste un REFUS.

1. Aucun agent en vol -> OK, code 0, sortie vide.
2. lane-291 en vol -> OK, code 0, AVERTISSEMENT citant "lane-291" sur stdout.
3. Plusieurs lanes/revues en vol -> OK, code 0, AVERTISSEMENT citant le
   compte et les deux noms.
4. banc-mj en vol -> REFUS, code non nul, message sur stderr.
5. banc-joueur-02 (forme suffixée par paire, #282) en vol -> REFUS.
6. banc-mj ET lane-291 en vol en même temps -> REFUS (le banc prime).
"""
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "banc" / "verifier-agents-en-vol.sh"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def agent_list_json(*noms):
    agents = ",".join(f'{{"name":"{n}","status":"running"}}' for n in noms)
    return f'{{"agents":[{agents}]}}'


def lancer(sortie_herdr: str):
    return subprocess.run(
        [BASH, str(SCRIPT)],
        input=sortie_herdr, capture_output=True, timeout=60,
        encoding="utf-8", errors="replace",
    )


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"

    # ------------------------------------------------------------------
    # Cas 1 : rien en vol -> OK, sortie vide
    # ------------------------------------------------------------------
    p1 = lancer(agent_list_json("workspace-autre"))
    assert p1.returncode == 0, f"cas 1 : code attendu 0, reçu {p1.returncode}\n{p1.stderr}"
    assert p1.stdout.strip() == "", f"cas 1 : sortie attendue vide, reçu {p1.stdout!r}"
    print("PASS: cas 1 -- rien en vol, OK silencieux")

    # ------------------------------------------------------------------
    # Cas 2 : lane-291 en vol -> OK avec avertissement
    # ------------------------------------------------------------------
    p2 = lancer(agent_list_json("lane-291"))
    assert p2.returncode == 0, f"cas 2 : code attendu 0, reçu {p2.returncode}\n{p2.stderr}"
    assert "AVERTISSEMENT" in p2.stdout, f"cas 2 : AVERTISSEMENT attendu ({p2.stdout})"
    assert "lane-291" in p2.stdout, f"cas 2 : lane-291 attendu dans l'avertissement ({p2.stdout})"
    print("PASS: cas 2 -- lane en vol, OK avec avertissement")

    # ------------------------------------------------------------------
    # Cas 3 : plusieurs lanes/revues en vol -> OK avec avertissement complet
    # ------------------------------------------------------------------
    p3 = lancer(agent_list_json("lane-291", "revue-288"))
    assert p3.returncode == 0, f"cas 3 : code attendu 0, reçu {p3.returncode}\n{p3.stderr}"
    assert "AVERTISSEMENT" in p3.stdout
    assert "lane-291" in p3.stdout and "revue-288" in p3.stdout, (
        f"cas 3 : les deux noms attendus ({p3.stdout})"
    )
    print("PASS: cas 3 -- plusieurs lanes/revues en vol, OK avec avertissement")

    # ------------------------------------------------------------------
    # Cas 4 : banc-mj en vol -> REFUS
    # ------------------------------------------------------------------
    p4 = lancer(agent_list_json("banc-mj"))
    assert p4.returncode != 0, f"cas 4 : code non nul attendu, reçu {p4.returncode}"
    assert "REFUS" in p4.stderr and "banc-mj" in p4.stderr, f"cas 4 : {p4.stderr}"
    print("PASS: cas 4 -- banc-mj en vol, REFUS")

    # ------------------------------------------------------------------
    # Cas 5 : banc-joueur-02 (forme suffixée par paire, #282) en vol -> REFUS
    # ------------------------------------------------------------------
    p5 = lancer(agent_list_json("banc-joueur-02"))
    assert p5.returncode != 0, f"cas 5 : code non nul attendu, reçu {p5.returncode}"
    assert "REFUS" in p5.stderr and "banc-joueur-02" in p5.stderr, f"cas 5 : {p5.stderr}"
    print("PASS: cas 5 -- banc-joueur-02 en vol, REFUS")

    # ------------------------------------------------------------------
    # Cas 6 : banc-mj ET lane-291 en vol -> REFUS (le banc prime)
    # ------------------------------------------------------------------
    p6 = lancer(agent_list_json("banc-mj", "lane-291"))
    assert p6.returncode != 0, f"cas 6 : code non nul attendu, reçu {p6.returncode}"
    assert "REFUS" in p6.stderr and "banc-mj" in p6.stderr, f"cas 6 : {p6.stderr}"
    print("PASS: cas 6 -- banc + lane en vol ensemble, REFUS (le banc prime)")

    print("verifier_agents_en_vol_test: 6/6 OK")


if __name__ == "__main__":
    main()
