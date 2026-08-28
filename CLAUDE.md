# CLAUDE.md — repo `coderain`

*Socle court pour tout agent Claude Code travaillant dans ce repo. Décisions/
historique détaillé : vault `C:\Vaults\MVP2\meta-rpg\` (hors périmètre de ce
dépôt). Voir aussi [DISCIPLINE-VERSIONNEMENT.md](DISCIPLINE-VERSIONNEMENT.md)
et [README-ci.md](README-ci.md) pour le détail des gardes déjà en place.*

## Tester

```bash
python run_tests.py
```

Chaque fichier `tests/*.py` est un script autonome, 100% hors-ligne (pas de
modèle, pas de réseau). `trinity_test.py` est exclu (I-270, échec préexistant
documenté, ne compte pas comme régression). Un hook pré-commit local relance
déjà cette suite (sauf `trinity`) et refuse tout commit sur suite rouge —
jamais d'état rouge dans l'historique.

## Style

- Commentaires et messages de commit en français, code (identifiants, docstrings
  techniques) en anglais — cohérence avec l'existant, pas de convention à
  inventer.
- Fixtures de test 100% synthétiques (D-109) : jamais de vrai matériau de
  campagne dans un test. Le corpus réel (`corpus-modules/`) est gitignoré et
  ne doit jamais entrer dans l'historique — voir `specs/audit-securite-*.md`.
- Avant d'ajouter un fichier nouveau : se demander s'il porte du matériau de
  campagne ou un secret. Un fichier entré dans l'historique y reste même
  supprimé ensuite.
- Réutiliser les conventions du module touché plutôt qu'en importer de
  nouvelles (nommage, style de docstring, structure de test) — voir le fichier
  voisin le plus proche avant d'écrire.

## Règles de PR

- **Jamais de commit direct sur `main`.** Toute branche pousse vers `origin`
  avant tout rapport de fin de tâche (travail non poussé = non vérifiable).
  Un hook du repo (`.claude/hooks/guard-main-push.py`) refuse déjà les push
  directs côté harnais ; la porte réelle est la branch protection GitHub
  côté serveur.
- **Une PR par changement logique** — ne pas grouper plusieurs sujets non liés
  dans la même branche/PR.
- **Merge seulement CI verte.** Le workflow CI (`.github/workflows/`, décrit
  dans [README-ci.md](README-ci.md)) tourne sur chaque push ; le job
  `integration` ne tourne que sur `main`, entièrement hors-ligne (aucun
  secret, aucun matériau réel).
- Les trois commandes destructrices (`git checkout <fichier>`, `git stash`,
  `git reset --hard`) sont interdites sans avoir d'abord enregistré le
  travail en cours — voir [DISCIPLINE-VERSIONNEMENT.md](DISCIPLINE-VERSIONNEMENT.md).
