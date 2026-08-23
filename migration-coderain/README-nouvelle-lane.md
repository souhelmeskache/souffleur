# README — `nouvelle-lane.ps1`

*Orchestrateur de lanes du poste TECHNIQUE — livré le 2026-08-23, fiche
[FICHE-orchestrateur-nouvelle-lane-2026-08-23.md](FICHE-orchestrateur-nouvelle-lane-2026-08-23.md).
Une règle qui rappelle se câble ([I-269](../meta-rpg/registre-items/MRPG-I-269-le-parallelisme-exige-des-perimetres.md)).*

## Usage

```powershell
.\nouvelle-lane.ps1 -Nom <lane> -Fiche <chemin-vers-fiche.md>
```

| paramètre | rôle |
|---|---|
| `-Nom` | nom de la lane = nom de branche ; kebab-case minuscule (`^[a-z0-9][a-z0-9-]*$`), `main` interdit |
| `-Fiche` | chemin complet de la fiche de routage (doit porter une section **PÉRIMÈTRE D'ÉCRITURE**) |
| `-DryRun` | exécute contrôles + création + vérification d'isolement puis **nettoie tout** (jamais de session lancée) |
| `-RepoRoot` | chemin du dépôt moteur (défaut : `coderain` à côté du profil) |

Le script opère sur le dépôt moteur (worktrees et branches) mais **ne modifie jamais son code**.

## Ce qu'il fait, dans l'ordre

1. **Contrôles préalables** — échec propre (`exit 1`) si KO :
   - la fiche existe et contient une section `PÉRIMÈTRE D'ÉCRITURE` (le premier bloc de code
     après l'en-tête fait foi comme liste P1) ;
   - `main` du dépôt moteur est propre (`git status --porcelain` vide) ;
   - branche et chemin cible libres ; **avertissement** si le périmètre P1 de la fiche
     recouvre des fichiers déjà modifiés par une lane active (`diff main...<branche>` de chaque
     worktree existant) — en cas de recouvrement : séquencement obligatoire, arbitrage au méta.
2. **Création** : `git worktree add ..\coderain-<lane> -b <lane> main` — arbre propre garanti :
   ni `--no-checkout`, ni dépôt nu (garde P2 vérifiée après création : le worktree doit contenir
   un checkout complet, sinon annulation et nettoyage automatiques).
3. **Lancement** : ouvre une nouvelle fenêtre PowerShell dans le worktree et démarre opencode
   avec le prompt initial : *« Exécute \<fiche\>. Branche et worktree déjà en place. Commit avant
   rapport, hash inclus. Puis clôture P4 : git worktree remove de ton worktree + suppression de
   ta branche depuis le dépôt principal, selon README-nouvelle-lane — DERNIER geste avant de
   rendre la main. »* — **le prompt voyage par fichier temporaire** (jamais en positionnel :
   le premier positionnel d'opencode est un CHEMIN DE PROJET — bug du 2026-08-23, corrigé comme
   côté réveil du veilleur), l'appel passe par `-EncodedCommand` (insensible aux espaces et
   guillemets), **`opencode.cmd` est invoqué directement** (pas le shim npm `.ps1`, qui habille
   la première ligne stderr en `NativeCommandError` rouge) et la console est passée en **UTF8**
   (`chcp 65001`) avant l'appel. Le fichier de prompt est supprimé par la fenêtre après coup.
   Les autorisations habituelles restent données par Souhel au démarrage.
   **Fenêtre (I-275 livrable 12, `D-192`)** : PLUS de `-NoExit`. Sortie 0 de `opencode.cmd run`
   ⇒ la fenêtre **se ferme seule** ; sortie ≠ 0 ⇒ elle **reste ouverte sur l'erreur visible**
   (message + code sortie, jusqu'à Entrée, qui propage le code). C'est le seul cas de fenêtre
   persistante ; la clôture P4 du prompt (auto-nettoyage du worktree/branche par la lane
   elle-même, livrable 13) devient possible parce que plus personne ne pourrait le faire après
   la fermeture.
4. **Sortie** : récapitulatif d'une ligne — lane · branche · chemin worktree · fiche ; puis
   **`exit 0` explicite** sur les deux issues réussies (dry-run et réel), pour que l'appelant
   (le veilleur) puisse vérifier le code sortie sans lire un `$LASTEXITCODE` périmé.

> ⚠️ Second passage d'une lane déjà posée (branche existante) : échec PROPRE au contrôle 3
> (« la branche '…' existe deja », exit 1, rien créé ni détruit). Reproduit le 2026-08-23
> (tentatives 15:40–15:41 sur `veille-srd-relance`, dont la branche avait été créée par une
> instance fantôme à ~15:32) : c'est ce comportement voulu qui a protégé les compteurs du
> veilleur (ni `lanesLancees` ni budget consommés), la borne anti-boucle (livrable 3) bannissant
> la fiche après 2 échecs consécutifs si la cause persiste.

## ⛔ Le self-merge conditionnel (D-188) — règle que TOUTE lane applique en fin de fil

Merge autorisé **si et seulement si** les quatre conditions tiennent :

1. **suite verte hors échecs préexistants recensés**
   ([I-270](../meta-rpg/registre-items/MRPG-I-270-ticket-trinity-test-openrouter.md)) — un échec
   présent avant la lane ne compte pas ; toute régression compte double ;
2. **périmètre tenu** : `git diff --name-only HEAD~n` ⊆ liste P1 de la fiche — un fichier hors
   périmètre modifié = merge refusé ;
3. **fast-forward possible**, ou fichiers disjoints des lanes actives ;
4. **zéro écart à instruire** — tout écart non résolu bloque.

Si une seule manque : **STOP + remontée** (rapport, pas de merge). Plusieurs lanes finies en même
temps ⇒ **l'ordre de merge se demande au méta** — jamais décidé côté lane.

## Garde-fous rappelés

- Le worktree créé est **toujours** un arbre propre (P2 du protocole anti-récidive du 2026-08-23 :
  deux fils ne partagent jamais un arbre de travail).
- Aucune des trois commandes destructrices (`checkout <fichier>`, `stash`, `reset --hard`)
  n'est employée par ce script.
- Le dry-run (`-DryRun`) est le passage à blanc obligatoire : mêmes contrôles, création réelle,
  nettoyage vérifié (worktree ET branche supprimés, `main` intacte).
