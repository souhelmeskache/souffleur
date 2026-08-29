"""D-264 -- outillage du banc de fumée (Issue #151) : test de forme, 100%
hors-ligne (aucun appel LLM). Vérifie que les gabarits de prompt
(tools/prompts/banc-mj.md, tools/prompts/banc-joueur.md) portent bien le
protocole go/pause, le contrat MJ (paquet fait foi, mémoire jetable) et la
consigne de sobriété joueur -- et que le lanceur (tools/lancer-banc-fumee.ps1)
expose les bons paramètres, substitue correctement les gabarits et couvre le
DryRun. Ne joue aucun tour réel, n'invoque aucun modèle.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GABARIT_MJ = ROOT / "tools" / "prompts" / "banc-mj.md"
GABARIT_JOUEUR = ROOT / "tools" / "prompts" / "banc-joueur.md"
LANCEUR = ROOT / "tools" / "lancer-banc-fumee.ps1"

# ============================================================
# 0) les trois fichiers existent
# ============================================================
for chemin in (GABARIT_MJ, GABARIT_JOUEUR, LANCEUR):
    assert chemin.is_file(), f"fichier attendu absent : {chemin}"
print("0) les trois fichiers de l'outillage (2 gabarits + 1 lanceur) existent")

texte_mj = GABARIT_MJ.read_text(encoding="utf-8")
texte_joueur = GABARIT_JOUEUR.read_text(encoding="utf-8")
texte_lanceur = LANCEUR.read_text(encoding="utf-8")

# ============================================================
# 1) protocole go/pause present dans les DEUX gabarits
# ============================================================
for nom, texte in (("MJ", texte_mj), ("joueur", texte_joueur)):
    basse = texte.lower()
    assert "go" in basse and "pause" in basse, f"gabarit {nom} : protocole go/pause absent"
    assert "{{session_tour}}" in basse, f"gabarit {nom} : placeholder session tour absent"
    assert "{{tours}}" in basse, f"gabarit {nom} : placeholder nombre de tours absent"
print("1) protocole go/pause + placeholders {{SESSION_TOUR}}/{{TOURS}} presents dans les deux gabarits")

# ============================================================
# 2) contrat MJ : paquet fait foi, mémoire jetable, D-263
# ============================================================
basse_mj = texte_mj.lower()
assert "jetable" in basse_mj, "gabarit MJ : mémoire jetable non mentionnée"
assert "assemble_context_to_file" in texte_mj, "gabarit MJ : appel outil MCP attendu absent"
assert "d-263" in basse_mj, "gabarit MJ : contrat D-263 non référencé"
for geste in ("ordonnancer", "cadrer", "écrire"):
    assert geste in basse_mj, f"gabarit MJ : geste '{geste}' du contrat D-263 absent"
assert "secret" in basse_mj, "gabarit MJ : interdit de fuite de secret non déclenché absent"
assert "{{journal_dir}}" in basse_mj, "gabarit MJ : placeholder dossier journal absent"
assert "{{save}}" in basse_mj, "gabarit MJ : placeholder save absent"
print("2) contrat MJ (paquet fait foi / mémoire jetable / D-263 / interdits) présent dans le gabarit MJ")

# ============================================================
# 3) sobriété joueur : un paragraphe, première personne, actes concrets
# ============================================================
basse_joueur = texte_joueur.lower()
assert "première personne" in basse_joueur, "gabarit joueur : consigne 1re personne absente"
assert "paragraphe" in basse_joueur, "gabarit joueur : consigne longueur (un paragraphe) absente"
assert "méta" in basse_joueur, "gabarit joueur : interdit méta-commentaire absent"
assert "{{save}}" in basse_joueur, "gabarit joueur : placeholder save absent"
print("3) sobriété joueur (1 paragraphe / 1re personne / pas de méta) présente dans le gabarit joueur")

# ============================================================
# 4) le lanceur expose les bons paramètres (-SessionTour, -Save, -Tours,
# -DryRun) et couvre le DryRun sans rien lancer -- lecture de forme, pas
# d'exécution PowerShell ici (hors-ligne, aucun herdr requis pour ce test)
# ============================================================
assert re.search(r"\[Parameter\(Mandatory = \$true\)\]\s*\[string\]\$SessionTour", texte_lanceur), \
    "lanceur : -SessionTour doit être un paramètre obligatoire"
assert re.search(r"\[Parameter\(Mandatory = \$true\)\]\s*\[string\]\$Save", texte_lanceur), \
    "lanceur : -Save doit être un paramètre obligatoire"
assert "[int]$Tours = 12" in texte_lanceur, "lanceur : -Tours doit défaulter à 12"
assert "[switch]$DryRun" in texte_lanceur, "lanceur : -DryRun absent"
assert "bench\\banc-fumee\\" in texte_lanceur or "bench/banc-fumee/" in texte_lanceur, \
    "lanceur : chemin du journal (bench/banc-fumee/) absent"
print("4) le lanceur expose -SessionTour (obligatoire), -Save (obligatoire), -Tours (défaut 12), -DryRun")

# ============================================================
# 5) le lanceur lit bien les DEUX gabarits versionnés (pas de prompt inline
# dupliqué qui divergerait du fichier vérifié ci-dessus)
# ============================================================
assert "tools\\prompts\\banc-mj.md" in texte_lanceur, "lanceur : ne référence pas tools/prompts/banc-mj.md"
assert "tools\\prompts\\banc-joueur.md" in texte_lanceur, "lanceur : ne référence pas tools/prompts/banc-joueur.md"
print("5) le lanceur lit les deux gabarits versionnés (pas de prompt dupliqué en dur)")

# ============================================================
# 6) .gitignore couvre bench/banc-fumee/ (D-109/D-178 : rien de la fiction
# du banc ne se versionne)
# ============================================================
gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
assert "bench/banc-fumee/" in gitignore, ".gitignore ne couvre pas bench/banc-fumee/"
print("6) .gitignore couvre bench/banc-fumee/ (journal du banc jamais versionné)")

print("\nOK -- outillage du banc de fumée (D-264, Issue #151) : forme des gabarits + du lanceur")
