# CLAUDE.md — repo `coderain` (gardes git)

## Garde de branche `main` (D-224)

Le dossier versionné [hooks/](hooks/) porte les hooks git du repo :
`pre-push` refuse tout push dont une refspec cible `refs/heads/main`
(message : passe par une branche + Pull Request) ; `pre-commit` refuse
tout commit sur suite de tests rouge (jamais d'état rouge dans l'historique).

Activation — **une ligne, à rejouer une fois par clone neuf** :

```bash
git config core.hooksPath hooks
```

Les worktrees héritent de cette config : elle vit dans `.git/config`,
partagé entre toutes les worktrees, et le chemin relatif `hooks` se résout
dans chaque copie de travail, qui contient le dossier puisqu'il est
versionné (vérifié par `tests/garde_prepush_test.py`).

**Limite résiduelle assumée** : `git push --no-verify` (comme
`git commit --no-verify`) saute les hooks. Interdiction écrite d'utiliser
`--no-verify` dans ce repo — aucune exception. La parade absolue reste la
protection de branche côté serveur, à activer au passage du repo en public
(indisponible sur repo privé en plan gratuit GitHub).

Tout passage sur `main` se fait par branche + Pull Request.
