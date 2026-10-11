"""D-264 -- outillage du banc de fumée (Issue #151) : test de forme, 100%
hors-ligne (aucun appel LLM). Vérifie que les gabarits de prompt
(tools/prompts/banc-mj.md, tools/prompts/banc-joueur.md) portent bien le
protocole go/pause, le contrat de la table (paquet fait foi, mémoire
jetable) et la consigne de sobriété joueur -- et que le lanceur
(tools/lancer-banc-fumee.ps1) expose les bons paramètres, substitue
correctement les gabarits et couvre le DryRun. Ne joue aucun tour réel,
n'invoque aucun modèle.

MODIFIÉ par D-404/D-415 (chantier 3) : `tools/prompts/banc-mj.md` n'est
plus le Director -- c'est LA TABLE, qui relance un Director PRODUIT neuf à
chaque tour (sous-agent `director`, rôle `coderain/roles/director.md`) et
ne voit plus ni la photo ni le paquet ni un secret. Les sections 2/2bis
ci-dessous ont été réécrites pour ce contrat : le vieux contrat D-263
(table=Director, `assemble_context_to_file` appelé par la table,
directive=caméra D-110 écrite par la table elle-même) est RETIRÉ de ce
gabarit à dessein -- ces règles vivent maintenant dans le rôle produit,
couvert par `tests/test-role-director-d404-d415.py`, jamais recopiées ici.
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
# 2) D-404/D-415 (chantier 3) : la session n'est plus le Director, elle est
# LA TABLE -- le contrat D-263 (table=Director, assemble_context_to_file,
# gestes ordonnancer/cadrer/écrire tenus par la table elle-même) est RETIRÉ
# de ce gabarit : il vit désormais dans coderain/roles/director.md (couvert
# par tests/test-role-director-d404-d415.py), jamais recopié ici.
# ============================================================
basse_mj = texte_mj.lower()
assert "jetable" in basse_mj, "gabarit MJ : mémoire jetable non mentionnée"
assert "photo_director" in texte_mj, \
    "gabarit MJ : appel outil MCP photo_director absent (D-415)"
assert "d-415" in basse_mj, "gabarit MJ : contrat D-415 non référencé"
assert "d-263" not in basse_mj, \
    "gabarit MJ : le contrat D-263 (table=Director) devrait être retiré (D-415)"
assert "assemble_context_to_file" not in texte_mj, \
    "gabarit MJ : la table ne devrait plus appeler assemble_context_to_file " \
    "elle-même (remplacé par photo_director + sous-agent director, D-415)"
assert "secret" in basse_mj, "gabarit MJ : interdit de fuite de secret non déclenché absent"
assert "{{journal_dir}}" in basse_mj, "gabarit MJ : placeholder dossier journal absent"
assert "{{save}}" in basse_mj, "gabarit MJ : placeholder save absent"
print("2) contrat D-415 (photo_director / mémoire jetable / interdits) présent, "
      "contrat D-263 (table=Director) bien retiré du gabarit MJ")

# ============================================================
# 2bis) D-415 : la table relance un Director NEUF à chaque tour (sous-agent
# `director`), jamais elle-même ne juge/ordonnance/cadre/écrit la visée ; la
# prose part d'un sous-agent `narrateur` ; un bouchage (D-275) passe par un
# sous-agent `boucheur` ; les durées Director/narrateur sont mesurées
# (D-412) ; le rôle du Director vit dans coderain/roles/director.md, jamais
# recopié ici ; test d'étanchéité en ouverture de banc, inchangé depuis
# D-264/Issue #161.
# ============================================================
assert "ne narre" in basse_mj or "ne narres" in basse_mj, \
    "gabarit MJ : interdit de narrer soi-même absent"
assert "ne juge" in basse_mj or "juge jamais" in basse_mj, \
    "gabarit MJ : interdit de juger le tour soi-même absent (D-415)"
assert "sous-agent narrateur" in basse_mj or "sous-agent" in basse_mj and "narrateur" in basse_mj, \
    "gabarit MJ : sous-agent narrateur non mentionné"
assert "director" in basse_mj and "sous-agent" in basse_mj, \
    "gabarit MJ : sous-agent director non mentionné (D-415)"
assert "boucheur" in basse_mj, \
    "gabarit MJ : sous-agent boucheur non mentionné (D-415, bouchage D-275)"
assert "coderain/roles/director.md" in basse_mj, \
    "gabarit MJ : devrait pointer vers coderain/roles/director.md, jamais " \
    "recopier son rôle"
assert "bouchage" in basse_mj, "gabarit MJ : traitement du bouchage absent"
assert "d-412" in basse_mj, "gabarit MJ : mesure de latence D-412 absente"
assert "étanchéité" in basse_mj, "gabarit MJ : test d'étanchéité harnais absent"
assert "avant le tour 1" in basse_mj, \
    "gabarit MJ : le test d'étanchéité doit se situer avant le tour 1"
print("2bis) amendement D-415 : la table relance un Director neuf par tour "
      "(jamais elle-même ne juge/narre), sous-agents director/narrateur/"
      "boucheur, rôle jamais recopié, latence D-412, test d'étanchéité "
      "avant le tour 1 -- tous présents dans le gabarit MJ")

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

# ============================================================
# 7) Issue #295 : la prose du narrateur va INLINE dans tour-NN.md sous un
# titre dédié -- jamais un renvoi vers prose-NN.md, que le MJ n'écrit plus
# lui-même (voie extraction = primaire, tools/banc/arbitrer_prose.py).
# ============================================================
assert "## Prose du Narrateur" in texte_mj, \
    "gabarit MJ : titre de section '## Prose du Narrateur' absent (#295)"
assert "jamais un renvoi" in basse_mj or "jamais renvoyer" in basse_mj, \
    "gabarit MJ : interdiction du renvoi vers prose-NN.md absente (#295)"
assert "n'écris plus" in basse_mj or "n'écrit plus" in basse_mj, \
    "gabarit MJ : consigne 'n'écrit plus prose-NN.md lui-même' absente (#295)"
print("7) Issue #295 : section '## Prose du Narrateur' inline imposée, renvoi interdit, "
      "le MJ n'écrit plus prose-NN.md lui-même")

print("\nOK -- outillage du banc de fumée (D-264, Issue #151) : forme des gabarits + du lanceur")
