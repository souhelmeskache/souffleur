# README — `nouvelle-lane.ps1`

*Orchestrateur de lanes du poste TECHNIQUE — livré le 2026-08-23, fiche
[FICHE-orchestrateur-nouvelle-lane-2026-08-23.md](FICHE-orchestrateur-nouvelle-lane-2026-08-23.md).
Le fichier a disparu du tronc lors d'un miroir ; reconstruit et synchronisé avec le code mergé
au 2026-08-24 ([I-283](../meta-rpg/registre-items/MRPG-I-283-readmes-en-retard-sur-le-code-post-s.md)).
Une règle qui rappelle se câble ([I-269](../meta-rpg/registre-items/MRPG-I-269-le-parallelisme-exige-des-perimetres.md)).*

## Usage

```powershell
.\nouvelle-lane.ps1 -Nom <lane> -Fiche <chemin-vers-fiche.md>
```

| paramètre | rôle |
|---|---|
| `-Nom` | nom de la lane = nom de branche ; kebab-case minuscule (`^[a-z0-9][a-z0-9-]*$`), `main` interdit |
| `-Fiche` | chemin complet de la fiche de routage (doit porter une section **PÉRIMÈTRE D'ÉCRITURE**) |
| `-DryRun` | exécute contrôles + création + vérification d'isolement puis **nettoie tout** (jamais de session lancée) — sauf en reprise I-303 : rien créé ⇒ rien nettoyé (`81dd5b7`) |
| `-RepoRoot` | chemin du dépôt moteur (défaut : `coderain` à côté du profil) — le veilleur le propage toujours (`e227b2b`, diagnostic lane Q) |

Le script opère sur le dépôt moteur (worktrees et branches) mais **ne modifie jamais son code**.

## Ce qu'il fait, dans l'ordre

1. **Contrôles préalables** — échec propre (`exit 1`) si KO :
   - **Contrôle 1** : la fiche existe et contient une section `PÉRIMÈTRE D'ÉCRITURE` (le premier
     bloc de code après l'en-tête fait foi comme liste P1) ;
   - **Contrôle 1b (I-285, durci par `fb02249`)** — un P1 sans AUCUN chemin absolu testable
     **refuse la fiche à l'armement** ([nouvelle-lane.ps1:69](nouvelle-lane.ps1)) — un reçu de
     livraison qui ne teste rien n'est pas un reçu (cas réel lane audit-dnd5e-engine du 24/08 :
     reçu « non vérifiable » annoncé en vert, auto-nettoyage AVANT dépôt, exit 0 « honnête »).
     Toute fiche doit désigner ses livrables P1 par des chemins ABSOLUS ;
   - **Contrôle 2** : `main` du dépôt moteur est propre (`git status --porcelain` vide) ;
   - **Contrôle 3** : collisions branche/chemin + recouvrement de périmètre avec les lanes
     actives (`diff main...<branche>` de chaque worktree existant) — en cas de recouvrement :
     séquencement obligatoire, arbitrage au méta. **Résidu de lane morte** (branche ou chemin
     déjà présents) :
     - **Reprise I-303 (`81dd5b7`, mergé `faac51d`)**, testée AVANT tout diagnostic : le résidu
       appartient À CETTE lane — branche homonyme ∧ worktree ENREGISTRÉ exactement au chemin
       attendu ∧ dossier présent ⇒ arbre **RELU TEL QUEL**, ni nettoyé ni jugé (propre, sale,
       fusionné ou non) : le travail non commis est celui de la session même qu'on relance,
       jamais une cible de suppression ([nouvelle-lane.ps1:114](nouvelle-lane.ps1)). La création
       est sautée et la garde P2 éludée avec elle (son rollback `remove --force` + `branch -D`
       détruirait ce travail interdit de toucher) ; le DryRun ne nettoie RIEN en reprise
       (rien créé = rien à détruire) ;
     - sinon **auto-nettoyage I-287 (`c1cb688`, mergé `1586f22`)**, journalisé `[INFO]`, si et
       seulement si : chemin = worktree ENREGISTRÉ de CE dépôt ∧ arbre PROPRE (`status
       --porcelain` vide, fichiers non suivis compris — exactement le critère que
       `git worktree remove` exige lui-même) ∧ branche/HEAD à `main` ou fusionné dedans
       (`merge-base --is-ancestor`) ⇒ `git worktree remove` + `git branch -d`
       ([nouvelle-lane.ps1:150](nouvelle-lane.ps1)). Variante **branche seule fusionnée** (plus
       de worktree) = suppression de branche seule (`-d`, sécurité fusion conservée) ;
     - sinon **Fail CONSERVÉ avec la cause NOMMÉE** : on ne supprime JAMAIS du travail non
       commis, non intégré, ni un répertoire étranger.
2. **Création** : `git worktree add ..\coderain-<lane> -b <lane> main`
   ([nouvelle-lane.ps1:209](nouvelle-lane.ps1)) — arbre propre garanti : ni `--no-checkout`,
   ni dépôt nu (garde P2 vérifiée après création : le worktree doit contenir un checkout
   complet, sinon annulation et nettoyage automatiques). En reprise I-303 il n'y a RIEN à créer.
3. **Lancement** — prompt initial : *« Exécute \<fiche\>. Branche et worktree déjà en place.
   Commit avant rapport, hash inclus. Puis clôture P4 : git worktree remove de ton worktree +
   suppression de ta branche depuis le dépôt principal, selon README-nouvelle-lane — DERNIER
   geste avant de rendre la main. »* ([nouvelle-lane.ps1:268](nouvelle-lane.ps1))
   - le prompt voyage par **FICHIER** temporaire (jamais en positionnel : le premier
     positionnel d'opencode est un CHEMIN DE PROJET — bug du 2026-08-23), l'appel passe par
     `-EncodedCommand` (insensible aux espaces et guillemets), **`opencode.cmd` est invoqué
     directement** (pas le shim npm `.ps1`, qui habille la première ligne stderr en
     `NativeCommandError` rouge) et la console passe en **UTF8** (`chcp 65001`) AVANT l'appel.
     Le fichier de prompt est supprimé par la fenêtre après coup ;
   - **fenêtre VISIBLE et TITRÉE (I-302, `1d84931`)** : première instruction du script interne
     `$host.UI.RawUI.WindowTitle = 'LANE <nom>'` — signature carrée reprise par la trieuse
     (`LANE *`) — et `Start-Process -WindowStyle Normal`
     ([nouvelle-lane.ps1:298](nouvelle-lane.ps1),
     [nouvelle-lane.ps1:334](nouvelle-lane.ps1)) contre l'héritage du contexte caché de
     l'instance mère. NOTE : la fiche d'origine écrivait `$host.UI.RawTitle`, propriété
     INEXISTANTE (« RawTitle introuvable », constat bac à sable) — l'API réelle du titre
     console est `RawUI.WindowTitle` ;
   - **fenêtre (I-275 livrable 12, `D-192`)** : PLUS de `-NoExit`. Sortie 0 de
     `opencode.cmd run` ⇒ la fenêtre **se ferme seule** ; sortie ≠ 0 ⇒ elle **reste ouverte sur
     l'erreur visible** (message + code sortie, jusqu'à Entrée, qui propage le code). C'est le
     seul cas de fenêtre persistante — et ce qui rend possible la clôture P4 (livrable 13 :
     après la fermeture, plus personne ne pourrait retirer le worktree, donc la lane le fait
     ELLE-MÊME, voir §Clôture P4) ;
   - **reçu de livraison (I-281, durci I-285 par `fb02249`)** : APRÈS le run, les chemins
     absolus du P1 sont testés sur disque ; un exit 0 sans livrable n'est pas une completion ⇒
     code sortie FORCÉ à 3, chaque fichier absent nommé, fenêtre laissée ouverte (même régime
     D-192).
4. **Preuve et marque d'échec externe** — la fenêtre TEE la sortie vers
   `preuve-session-lane-<lane>-<horodatage>.log` au POSTE, là où le veilleur lit au tour
   suivant (I-287 livrable 2, `c1cb688`), et pose une MARQUE
   `echec-externe-<lane>-<horodatage>.flag` SEULEMENT si le run a échoué, portant sa cause
   ([nouvelle-lane.ps1:280](nouvelle-lane.ps1)). **Signatures ÉLARGIES (I-299 §2, `86bb040`,
   mergé dans le même commit)**, du plus précis au plus large
   ([nouvelle-lane.ps1:314](nouvelle-lane.ps1)) :
   1. `finish_reason: network_error` (signature I-287 d'origine) ;
   2. « Upstream request failed » (endpoint fournisseur indisponible — le cas réel du 24/08
      17:55 était passé AU TRAVERS : mort silencieuse, ni marque, ni compteur) ;
   3. critère idéal : TOUTE sortie non nulle SANS aucun travail d'outil constaté dans la
      preuve — un run mort avant d'avoir lu/écrit/exécuté quoi que ce soit n'a aucune faute de
      fiche à porter (marqueurs d'outils jugés APRÈS retrait des séquences ANSI).

   Côté veilleur, une marque fraîche (< 24 h) fait que l'échec de relance n'est PAS compté
   dans N=2 (fautes propres seulement, I-287) et, depuis `86bb040`, la consommation des marques
   a lieu AU SCAN avant de sauter une fiche « déjà lancée » (I-299 — voir
   [README-veilleur.md](README-veilleur.md)) : plus jamais une lane morte réseau ignorée en
   boucle.
5. **Sortie** : récapitulatif d'une ligne — lane · branche · chemin worktree · fiche ; puis
   **`exit 0` explicite** sur les deux issues réussies (dry-run et réel), pour que l'appelant
   (le veilleur) puisse vérifier le code sortie sans lire un `$LASTEXITCODE` périmé. En
   reprise : ligne `[INFO] reprise : worktree existant reelu tel quel`.

## ⛔ Clôture P4 — la lane nettoie elle-même son worktree (DERNIER geste)

Le prompt initial l'exige (I-275 livrable 13, `4a0ac28`) : une fois le travail commité, poussé
et le rapport rendu, la lane exécute DEPUIS LE DÉPÔT PRINCIPAL :

```powershell
git worktree remove C:\Users\souhe\coderain-<lane>
git branch -d <lane>          # depuis C:\Users\souhe\coderain
```

- `worktree remove` exige un arbre PROPRE — c'est voulu : on ne détruit jamais du travail non
  commis ;
- si `git branch -d` refuse (branche pas encore fusionnée dans `main` au moment de la clôture —
  le merge est demandé À la clôture, pas avant), `git branch -D` reste légitime parce que la
  branche a été poussée sur `origin` : rien n'est perdu, le travail vit sur le remote en
  attendant son merge ;
- après ces deux commandes : rendre la main. RIEN d'autre ne doit être écrit.

## Bannissement et déban officiel

Après N=2 échecs consécutifs PROPPRES d'armement (hors échec externe prouvé par marque,
I-287/`c1cb688` ; hors échec jugé sur une version périmée de la fiche — hash SHA256 avant/après,
I-298/`135f18a`), la fiche entre dans `fichesBannies` côté veilleur et sort de la file. Elle
n'en sort QUE par le **déban OFFICIEL** : `.\veilleur.ps1 -Deban <chemin-de-fiche>`
(I-277, `e227b2b`) — relit le state FRAIS sous verrou `Global\MRPG-Veilleur-State`, retire ban,
compteur d'échecs et marque du déjà-lancé. ⛔ Ne JAMAIS éditer `veilleur-state.json` à la main :
c'est exactement le lost update qui a motivé la garde (I-277).

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
  deux fils ne partagent jamais un arbre de travail) — sauf reprise I-303, où l'arbre EXISTANT
  est relu tel quel, quel que soit son état (`81dd5b7`).
- Aucune des trois commandes destructrices (`checkout <fichier>`, `stash`, `reset --hard`)
  n'est employée par ce script.
- Le dry-run (`-DryRun`) est le passage à blanc obligatoire : mêmes contrôles, création réelle,
  nettoyage vérifié (worktree ET branche supprimés, `main` intacte). Exception I-303 : en
  reprise, rien créé ⇒ rien nettoyé — le worktree existant et son travail restent REINTEGRAUX
  (`81dd5b7`).
