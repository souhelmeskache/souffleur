"""TEMPORAIRE — preuve du gate (lane ci-integration-continue, D-189).

Ce fichier existe uniquement pour démontrer qu'un test cassé poussé sur une
branche rend le run rouge et produit l'artefact de log. Il est supprimé au
commit suivant. Aucun test existant n'est modifié.
"""
import sys

print("gate demo : ECHEC VOLONTAIRE (preuve que le gate mord)")
sys.exit(1)
