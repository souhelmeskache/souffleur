# DISCIPLINE-VERSIONNEMENT.md — le filet du moteur (copie dépôt)

*Posée au poste technique (vault) le 2026-08-07 ; copie opérationnelle dans le
dépôt depuis le 2026-08-23 (lane CI, D-189). Ce fichier fait foi pour toute
modification du moteur. La version vault porte en plus l'historique de
l'incident du 07/08 et l'état des sauvegardes hors dépôt.*
*Mise à jour 2026-08-23 (lane consolidation-relance) : porte de secousse du
gate normée (D-189) + protocole des lanes gravé (I-269 · D-188).*

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

## ⛔ La porte de secousse du gate — le cas « rouge voulu et tracé » (D-189)

Le hook pré-commit bloque tout commit sur suite rouge : *jamais d'état rouge
dans l'historique*. **Un seul cas normé le force : prouver que le gate mord**
(démo, audit). Hors de cette procédure, `--no-verify` est un incident —
contournement silencieux, zéro trace. La procédure :

1. **Branche jetable dédiée** (`gate-demo-*`) — jamais sur `main` ni sur la
   branche d'une lane active.
2. **Un seul fichier temporaire**, `tests/gate_demo_test.py`, qui échoue
   volontairement avec un message explicite (« GATE DEMO »). Rien d'autre
   n'est touché.
3. **Capturer le refus local du hook** (sortie tracée dans le rapport) :
   c'est déjà la preuve que le gate mord côté poste.
4. Si la preuve serveur est exigée (run CI rouge + artefact) : un unique
   `git commit --no-verify` dont le **message porte l'ordre exprès du
   pilotage** — « GATE DEMO TEMPORAIRE — cas rouge voulu, ordre de Souhel,
   session <réf> » — poussé immédiatement vers `origin`.
5. **Neutralisation au commit suivant** : le test devient inoffensif ou
   disparaît. L'état rouge ne survit jamais à deux commits ; le veilleur
   classe le run rouge attendu comme preuve tracée (D-189 étage 3 : ni
   régression, ni flaky).

## Le protocole des lanes (I-269 · D-188 · D-189)

Gravé après l'incident du 23/08 (trois fils, un seul arbre) :

- **P1 — périmètre d'écriture déclaré par fiche.** Toute écriture hors liste
  ⇒ STOP + remontée. Chevauchement entre fiches ⇒ séquencement, jamais
  parallélisme.
- **P2 — une lane = une branche + un worktree isolé**, créé depuis `main`
  à jour (`git worktree`). Les vieux worktrees finis se suppriment depuis
  le dépôt principal (+ `git worktree prune`).
- **P3 — un fil qui finit commite avant son rapport**, puis pousse sa
  branche (D-189).
- **P4 — merge séquentiel après run vert** ; vrai conflit de lignes
  ⇒ remontée Souhel.

**Self-merge conditionnel (D-188)** — une lane merge elle-même si et
seulement si : (a) suite verte hors échecs préexistants *recensés* ;
(b) `git diff --name-only` ⊆ le périmètre P1 de sa fiche ; (c) fast-forward
possible ou fichiers disjoints de toute lane active ; (d) zéro écart à
instruire dans son rapport. Sinon elle s'arrête et remonte. Quand plusieurs
lanes finissent ensemble, l'ordre des merges reste donné par le méta.

**Lancement (orchestrateur)** : le protocole ci-dessus est appliqué
mécaniquement par le script du poste technique (`nouvelle-lane <nom>
<fiche>`) — branche + worktree + fiche en prompt. ⛔ Ne s'automatisent
jamais : l'acte — la frappe de Souhel reste le feu vert de chaque
lancement (D-176) —, l'arbitrage de fond, la conception.

## Les trois gestes

1. **Enregistrer avant de patcher, et après que le patch est prouvé.** Un
   enregistrement « sale » vaut mieux qu'un travail perdu.
2. **Lancer la suite avant et après** — `python run_tests.py` (référence :
   les 42 suites vertes depuis le 23/08 — I-270 réparé, le profil de
   connexion est désormais déclaré par `trinity_test.py` lui-même ; le hook
   pré-commit et le workflow CI excluent encore ce test jusqu'à leur mise à
   jour, lane dédiée hors périmètre). Un nouvel échec = régression : on
   n'enregistre pas par-dessus, on comprend d'abord.
3. **Un enregistrement dit ce qu'il change et pourquoi, et signe quel poste a
   écrit quoi.**
