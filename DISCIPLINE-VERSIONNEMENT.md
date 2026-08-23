# DISCIPLINE-VERSIONNEMENT.md — le filet du moteur (copie dépôt)

*Posée au poste technique (vault) le 2026-08-07 ; copie opérationnelle dans le
dépôt depuis le 2026-08-23 (lane CI, D-189). Ce fichier fait foi pour toute
modification du moteur. La version vault porte en plus l'historique de
l'incident du 07/08 et l'état des sauvegardes hors dépôt.*

---

## ⛔ Les trois commandes interdites

`git checkout <fichier>` · `git stash` · `git reset --hard` détruisent du
travail non enregistré, sans confirmation et sans corbeille.
⇒ **Aucune des trois sans avoir enregistré d'abord.**

## ⛔ Ce qui ne doit jamais entrer dans l'historique

Le `.gitignore` couvre : `saves/`, `scenarios/`, `instructions/`, `config.yaml`,
`.env`, `.venv/`, `.turn/`.
⭐ **Avant d'enregistrer un fichier nouveau, se demander : porte-t-il du
matériau de campagne ?** Un fichier entré dans l'historique y reste même s'il
est supprimé ensuite. Les fixtures de test sont 100 % synthétiques par design.

## ⛔ Le distant — pousser la branche avant rapport (D-189)

⭐ **Toute lane pousse sa branche vers `origin` AVANT de rendre son rapport.**
Un travail uniquement local n'est pas vérifiable : pas de run CI, pas de preuve,
pas de reprise possible après une perte de machine.

## Les trois gestes

1. **Enregistrer avant de patcher, et après que le patch est prouvé.** Un
   enregistrement « sale » vaut mieux qu'un travail perdu.
2. **Lancer la suite avant et après** — `python run_tests.py` (référence :
   toutes les suites vertes sauf `trinity_test.py`, échec préexistant I-270 ;
   le CI applique la même exclusion). Un nouvel échec = régression : on
   n'enregistre pas par-dessus, on comprend d'abord.
3. **Un enregistrement dit ce qu'il change et pourquoi, et signe quel poste a
   écrit quoi.**
