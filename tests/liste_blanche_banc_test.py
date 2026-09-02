"""Issue #267 : Assure-ListeBlancheBanc (tools/banc/liste-blanche.ps1) --
trois fichiers synthétiques dans un dossier temporaire (absent, partiel,
complet), sur le modèle de tests/lancer_banc_fumee_test.py (un vrai process
PowerShell, pas une relecture de texte).

Cas :
1. Fichier absent : la fonction le crée, allow = [Bash(*), mcp__coderain-
   engine__*], les cinq refus deny du gabarit. Status 'cree'.
2. Fichier partiel (les cinq entrées MCP historiques de la nuit N0, #267 --
   load_save/get_world_state/ui_open/ui_panel/ui_sheet, aucun Bash, aucun
   deny) : la fonction AJOUTE Bash(*), mcp__coderain-engine__* et les cinq
   deny, sans retirer les cinq entrées historiques. Status 'complete'.
3. Fichier déjà complet (gabarit + une entrée allow supplémentaire posée par
   l'opérateur) : rien n'est ajouté, l'entrée supplémentaire de l'opérateur
   survit telle quelle. Status 'deja_complet'.
4. Fichier présent mais JSON invalide : REFUS, le fichier n'est PAS modifié.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_REEL = REPO_ROOT / "tools" / "banc" / "liste-blanche.ps1"

ALLOW_GABARIT = ["Bash(*)", "mcp__coderain-engine__*"]
DENY_GABARIT = [
    "Bash(git commit --no-verify*)",
    "Bash(git commit -n*)",
    "Bash(git push --no-verify*)",
    "Bash(git push --force*)",
    "Bash(git push -f*)",
]

CINQ_ENTREES_HISTORIQUES = [
    "mcp__coderain-engine__load_save",
    "mcp__coderain-engine__get_world_state",
    "mcp__coderain-engine__ui_open",
    "mcp__coderain-engine__ui_panel",
    "mcp__coderain-engine__ui_sheet",
]


def find_powershell():
    for name in ("powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def appeler_assure_liste_blanche(ps_exe, settings_path: Path):
    """Dot-source le module réel et appelle Assure-ListeBlancheBanc sur
    settings_path, renvoie (returncode, résultat JSON décodé ou None)."""
    ps_command = (
        f". '{MODULE_REEL}'; "
        f"$r = Assure-ListeBlancheBanc -SettingsLocalPath '{settings_path}'; "
        "$r | ConvertTo-Json -Depth 5"
    )
    p = subprocess.run(
        [ps_exe, "-NoProfile", "-Command", ps_command],
        capture_output=True, timeout=60, encoding="utf-8", errors="replace",
    )
    resultat = None
    if p.returncode == 0 and p.stdout.strip():
        try:
            resultat = json.loads(p.stdout)
        except json.JSONDecodeError:
            resultat = None
    return p, resultat


def lire_settings(settings_path: Path):
    return json.loads(settings_path.read_text(encoding="utf-8-sig"))


def main():
    ps_exe = find_powershell()
    assert ps_exe, "powershell/pwsh introuvable -- requis pour ce test (CI: windows-latest)"
    assert MODULE_REEL.exists(), f"module absent : {MODULE_REEL}"

    tmp_root = Path(tempfile.mkdtemp(prefix="liste-blanche-banc-test-"))
    try:
        # --------------------------------------------------------------
        # Cas 1 : fichier absent -> création complète, Status 'cree'
        # --------------------------------------------------------------
        settings1 = tmp_root / "absent" / "settings.local.json"
        assert not settings1.exists()
        p1, r1 = appeler_assure_liste_blanche(ps_exe, settings1)
        assert p1.returncode == 0, f"cas 1 : échec process\nstdout={p1.stdout}\nstderr={p1.stderr}"
        assert r1 is not None, f"cas 1 : sortie JSON illisible\nstdout={p1.stdout}"
        assert r1["Status"] == "cree", f"cas 1 : Status attendu 'cree', reçu {r1['Status']}"
        assert settings1.is_file(), "cas 1 : le fichier n'a pas été créé"
        data1 = lire_settings(settings1)
        allow1 = data1["permissions"]["allow"]
        deny1 = data1["permissions"]["deny"]
        for entree in ALLOW_GABARIT:
            assert entree in allow1, f"cas 1 : {entree} absent de allow ({allow1})"
        for entree in DENY_GABARIT:
            assert entree in deny1, f"cas 1 : {entree} absent de deny ({deny1})"
        print("PASS: cas 1 -- fichier absent, création complète")

        # --------------------------------------------------------------
        # Cas 2 : fichier partiel (cinq entrées historiques de la nuit N0)
        # -> complété sans perte, Status 'complete'
        # --------------------------------------------------------------
        settings2 = tmp_root / "partiel" / "settings.local.json"
        settings2.parent.mkdir(parents=True)
        contenu_partiel = {"permissions": {"allow": list(CINQ_ENTREES_HISTORIQUES), "deny": []}}
        settings2.write_text(json.dumps(contenu_partiel, ensure_ascii=False), encoding="utf-8")

        p2, r2 = appeler_assure_liste_blanche(ps_exe, settings2)
        assert p2.returncode == 0, f"cas 2 : échec process\nstdout={p2.stdout}\nstderr={p2.stderr}"
        assert r2 is not None, f"cas 2 : sortie JSON illisible\nstdout={p2.stdout}"
        assert r2["Status"] == "complete", f"cas 2 : Status attendu 'complete', reçu {r2['Status']}"
        data2 = lire_settings(settings2)
        allow2 = data2["permissions"]["allow"]
        deny2 = data2["permissions"]["deny"]
        for entree in CINQ_ENTREES_HISTORIQUES:
            assert entree in allow2, f"cas 2 : entrée historique {entree} perdue ({allow2})"
        for entree in ALLOW_GABARIT:
            assert entree in allow2, f"cas 2 : {entree} pas ajouté à allow ({allow2})"
        for entree in DENY_GABARIT:
            assert entree in deny2, f"cas 2 : {entree} pas ajouté à deny ({deny2})"
        print("PASS: cas 2 -- fichier partiel (cinq entrées historiques), complété sans perte")

        # --------------------------------------------------------------
        # Cas 3 : fichier déjà complet (+ une entrée posée par l'opérateur)
        # -> rien d'ajouté, Status 'deja_complet', entrée opérateur intacte
        # --------------------------------------------------------------
        settings3 = tmp_root / "complet" / "settings.local.json"
        settings3.parent.mkdir(parents=True)
        contenu_complet = {
            "permissions": {
                "allow": list(ALLOW_GABARIT) + ["mcp__autre-outil-operateur__*"],
                "deny": list(DENY_GABARIT),
            }
        }
        settings3.write_text(json.dumps(contenu_complet, ensure_ascii=False), encoding="utf-8")

        p3, r3 = appeler_assure_liste_blanche(ps_exe, settings3)
        assert p3.returncode == 0, f"cas 3 : échec process\nstdout={p3.stdout}\nstderr={p3.stderr}"
        assert r3 is not None, f"cas 3 : sortie JSON illisible\nstdout={p3.stdout}"
        assert r3["Status"] == "deja_complet", f"cas 3 : Status attendu 'deja_complet', reçu {r3['Status']}"
        data3 = lire_settings(settings3)
        assert "mcp__autre-outil-operateur__*" in data3["permissions"]["allow"], (
            "cas 3 : entrée posée par l'opérateur perdue"
        )
        assert data3 == contenu_complet, f"cas 3 : fichier modifié alors que déjà complet ({data3})"
        print("PASS: cas 3 -- fichier déjà complet, rien ajouté, entrée opérateur intacte")

        # --------------------------------------------------------------
        # Cas 4 : JSON invalide -> REFUS, fichier non modifié
        # --------------------------------------------------------------
        settings4 = tmp_root / "invalide" / "settings.local.json"
        settings4.parent.mkdir(parents=True)
        texte_invalide = "{ceci n'est pas du JSON valide"
        settings4.write_text(texte_invalide, encoding="utf-8")

        p4, r4 = appeler_assure_liste_blanche(ps_exe, settings4)
        assert p4.returncode == 0, f"cas 4 : échec process\nstdout={p4.stdout}\nstderr={p4.stderr}"
        assert r4 is not None, f"cas 4 : sortie JSON illisible\nstdout={p4.stdout}"
        assert r4["Status"] == "refus", f"cas 4 : Status attendu 'refus', reçu {r4['Status']}"
        assert settings4.read_text(encoding="utf-8") == texte_invalide, (
            "cas 4 : fichier JSON invalide modifié malgré le refus attendu"
        )
        print("PASS: cas 4 -- JSON invalide, REFUS, fichier non modifié")

        print("liste_blanche_banc_test: 4/4 OK")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
