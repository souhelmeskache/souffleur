# tools/banc/ — scripts de veille du banc

- `nuit.sh` / `nuit.cmd` / `verifier-avant-nuit.sh` / `metriques_nuit.py` :
  **banc de nuit N1** (#201, D-276 ; #260) — voir section dédiée ci-dessous.
- `veiller.sh` : veille sur l'apparition d'un fichier du journal, sans
  envoyer de go ; mêmes conditions de sortie que ci-dessus.
- `circuit.sh` : **point d'entrée unique du circuit de lane** (I-243, « ce
  qui crée détruit » ; I-250, « la veille est dans l'outil, pas dans un
  scratchpad » ; #255, un seul point d'entrée). Sans argument, imprime
  l'aide des six verbes.
  - `lancer <ISSUE> [modele] [effort]` : enveloppe `lancer-lane.ps1 <ISSUE>
    [-Modele <modele>] [-Effort <effort>]` (appel
    `powershell.exe -NoProfile -ExecutionPolicy Bypass -File …`). Appelle
    systématiquement `garde` avant de lancer — plus de geste manuel séparé.
  - `revoir <PR>` : enveloppe `lancer-lane.ps1 -Revue <PR>`, même garde
    systématique avant lancement.
  - Mode de démarrage des lanes et des revues (#265, remplace
    `bypassPermissions`/I-232) : `--permission-mode auto`. Aucun écran
    d'acceptation au démarrage — les règles `deny` du `settings.local.json`
    du worktree (`--no-verify`, `--force`, `-f`) s'appliquent toujours en
    premier, puis un classificateur tranche chaque appel restant (allow /
    deny motivé / deny par défaut si aucun verdict), sans jamais interroger
    un humain. Ce que ce mode ne couvre pas : un refus du classificateur sur
    un geste légitime de la lane — à observer sur les premières lanes en
    auto, à remonter en commentaire d'Issue si ça arrive.
  - `garde` : vérifie `core.bare` sur le checkout principal
    (`git config --show-origin --get core.bare`) ; s'il est présent, le
    retire (`--unset`) et journalise une ligne datée (heure, origine,
    commande en cours) dans `tools/banc/core-bare.log` (I-231, #231 — cause
    de réapparition inconnue). Idempotent : sortie 0 que `core.bare` ait été
    trouvé et retiré, ou déjà absent. Appelée par `lancer`/`revoir`, et
    rejouable seule.
  - `nettoyer <lane-NNN|revue-NNN>` ferme le workspace herdr, retire le
    worktree Git et la branche ; `nettoyer --orphelins` purge les dossiers de
    `.herdr/worktrees/souffleur/` qu'aucun worktree Git ni workspace herdr ne
    tient plus ; `etat` liste en une commande lanes en vol, PR ouvertes,
    workspaces, worktrees et orphelins. Les deux verbes de `nettoyer` sont
    idempotents (sortie 0 si déjà propre). Appelé par `veiller` après merge
    et après chaque REFUS (teardown du worktree de revue).
  - `veiller <ISSUE>` : UN watcher par circuit, qui couvre toutes les phases
    d'une lane jusqu'à son merge.

    **Phases** (dans l'ordre, celle atteinte au moment d'une sortie non
    nulle est journalée sur l'Issue) :
    1. `attente_pr` — attend la PR de `lane-<ISSUE>` : par branche, puis
       `closingIssuesReferences`, puis commentaire `TERMINÉ` de l'issue.
    2. `ci` — attend la CI verte de la PR.
    3. `revue` — relance une revue fraîche (`lancer-lane.ps1 -Revue <PR>`)
       et attend son verdict (`REVUE : APPROUVE` / `REVUE : REFUS`).
    4. `merge` — sur `APPROUVE` : merge squash, `circuit.sh nettoyer` de la
       lane et de la revue, `pull --ff-only`, sortie 0.
    5. `attente_termine` — sur `REFUS` : renvoie automatiquement le verdict
       à la lane (`herdr agent prompt lane-<ISSUE> "<verdict>… pousse puis
       poste un nouveau TERMINÉ"`), nettoie le worktree de revue, puis
       attend un `TERMINÉ` postérieur au verdict et reboucle en phase `ci`.
       **Au plus 2 cycles de refus** — le 3ᵉ `REFUS` sort en code 4 (REFUS
       persistant) plutôt que de rerenvoyer indéfiniment.

    **CI rouge et REFUS de revue sont le même cas (#280)** : un juge
    automatique a dit non, la lane doit corriger — ni l'un ni l'autre n'est
    une sortie tant que la lane est vivante.
    - **CI rouge, lane `lane-<ISSUE>` vivante** (`herdr agent list`) : renvoi
      automatique (`herdr agent prompt lane-<ISSUE> "CI ROUGE sur la PR #N
      (run <id>) : lis \`gh run view <id> --log-failed\`, corrige, pousse,
      reposte TERMINÉ"`), puis `attente_termine` — **même compteur de cycles**
      que les `REFUS` de revue (2 max, puis sortie 4 « CI rouge persistante »).
    - **CI rouge, lane morte** : sortie 1 immédiate (« CI rouge, lane
      absente »), aucun renvoi tenté.
    - **REFUS de revue, lane morte** (cas symétrique, mesuré sur #271 le
      03/09) : sortie 1 immédiate (« REFUS, lane absente — relancer un agent
      neuf sur le worktree avec le verdict ») plutôt que d'attendre 90 min un
      `TERMINÉ` impossible ; le worktree de revue est quand même nettoyé.

    **Codes de sortie** :
    - `0` — succès : merge fait, ou Issue déjà soldée détectée au lancement
      (rejeu idempotent — Issue fermée ou PR déjà mergée pour elle).
    - `1` — CI rouge (lane morte), REFUS de revue (lane morte), verdict de
      revue absent/en timeout, ou échec du merge.
    - `2` — agent `lane-<ISSUE>` relevé `blocked` deux fois de suite : lit
      les 20 dernières lignes du pane (`herdr agent read`), les poste en
      commentaire `BLOQUÉ (watcher) : …` sur l'Issue.
    - `3` — 90 min sans changement de phase.
    - `4` — CI rouge ou REFUS persistant (3ᵉ cycle, compteur partagé).

    Chaque sortie non nulle poste en commentaire de l'Issue une ligne
    `VEILLE <ISSUE> : <code> <raison> <phase>` — le journal du circuit vit
    sur l'Issue, jamais dans un scratchpad.
  - `solder-issue.sh <ISSUE>`, `attendre-termine.sh <ISSUE> <PR>` et
    `solder3.sh <PR>` sont des alias de compatibilité qui délèguent tous à
    `circuit.sh veiller <ISSUE>` (habitude d'appel du poste META) ; la
    logique elle-même vit uniquement dans `circuit.sh`.

Origine : banc de nuit du 31/08 → 01/09/2026 (fiche #201). Versionnés en
l'état, pas encore intégrés au lanceur (#210).

## Frontière bash ⊥ Windows (#270)

Un chemin produit sous Git Bash (`pwd`, `$REPO_ROOT`, `$partie_dir`, tout
dérivé de `cd ... && pwd`) est en forme `/c/Users/...` — valide pour bash,
**invalide pour tout binaire Windows natif** (`python.exe`, `powershell.exe`)
qui le recevrait comme donnée plutôt que comme argument de ligne de commande :
lu comme un chemin raciné sur le lecteur courant (`C:\c\Users\...`),
silencieusement faux — jamais une erreur bruyante avant #270 (la garde de
#267 refusait toute nuit avec un message trompeur : « n'est pas un JSON
valide » alors que le fichier existait bel et bien).

**Règle : jamais un chemin `pwd` brut vers Python/PowerShell.** Deux cas
distincts, et un seul est piégeux :

- **Argument passé à un exe natif directement par bash** (ex. `python
  "$FIXTURE_PY" "$save_dest"`, ou `powershell.exe -File … -SavesDirOverride
  "$partie_dir"`) : Git Bash (MSYS2) traduit ces arguments automatiquement au
  moment de l'exec — **sans danger**, vérifié (#270).
- **Chemin embarqué en littéral dans un bloc de code interprété** (ex.
  `python -c "open(r'$chemin', ...)"`, où `$chemin` est interpolé dans le
  texte source Python avant exécution) : MSYS ne voit passer AUCUN argument
  ici, donc ne traduit rien — **c'est le cas qui casse** (#267, #270).
  Convertir d'abord avec `chemin_windows_depuis_bash` (`tools/banc/chemin-windows.sh`,
  `source`é par `verifier-liste-blanche-nuit.sh` et `nuit.sh`) :

  ```bash
  source "$(dirname "${BASH_SOURCE[0]}")/chemin-windows.sh"
  chemin_win="$(chemin_windows_depuis_bash "$chemin")"
  python -c "open(r'$chemin_win', ...)"
  ```

  Tests : `tests/chemin_windows_test.py` (la fonction seule, quatre formes :
  `/c/Users/x`, `C:/Users/x`, `C:\Users\x`, `/home/x`) et
  `tests/verifier_liste_blanche_nuit_test.py` cas 5 (la garde, chemin `/c/…`
  simulé — reproduit le défaut #270 sans dépendre d'un vrai poste cassé).

## Deux protections partagées avec `tools/lancer-lane.ps1` (#276, cadrage complémentaire 03/09)

- **Refus nommé Haiku + mode `auto`** (`tools/refus-haiku-auto.ps1`,
  fonction `Assure-ModeAutoCompatibleAvecModele`, partagée avec
  `tools/lancer-lane.ps1`) : `--permission-mode auto` n'existe pas pour
  Haiku — Claude Code y retombe EN SILENCE en mode manuel, et un agent de
  nuit gèle à la première question posée à personne. Appelée avant chaque
  `herdr agent start` des deux lanceurs ; sans effet ici puisque
  `lancer-banc-fumee.ps1` démarre toujours les deux agents en
  `acceptEdits`, jamais `auto` (voir « Liste blanche » ci-dessous) — gardée
  pour la même discipline dans les deux lanceurs d'agents. Test :
  `tests/refus_haiku_auto_test.py`.
- **`deny` force-push versionné** (D-232) : `Bash(git push --force*)` et
  `Bash(git push -f*)` sont désormais dans le bloc `deny` de
  `.claude/settings.json` (suivi par Git), pas seulement dans
  `settings.local.json` (propriété de l'opérateur, non versionné). Test :
  `tests/settings_deny_force_push_test.py`.

## Liste blanche des agents du banc (#210, garantie #267)

Les deux agents du banc (`banc-mj`, `banc-joueur`) tournent en
`--permission-mode acceptEdits` (Haiku ne supporte pas `auto`, voir doc
Claude Code § « permission modes ») : sans liste blanche, chaque appel Bash
ou outil MCP `coderain-engine` redemande une autorisation à la main — une
nuit sans humain se fige (agent `blocked`) jusqu'au timeout.

- **Où elle vit** : `.claude\settings.local.json` du checkout/worktree qui
  lance le banc — fichier **ignoré par Git**, propriété de l'opérateur, à ne
  jamais confondre avec `.claude\settings.json` (suivi par Git, checkout
  principal). Un correctif manuel posé par erreur dans `settings.json` au
  lieu de `settings.local.json` a causé le constat #267 (nuit N0 du 02/09) :
  deux fichiers au nom voisin, deux rôles.
- **Ce que le lanceur garantit** (`tools\lancer-banc-fumee.ps1`, fonction
  `Assure-ListeBlancheBanc` extraite dans `tools\banc\liste-blanche.ps1`) :
  - fichier absent → création complète (`allow`: `Bash(*)`,
    `mcp__coderain-engine__*` ; `deny`: les cinq refus `--no-verify`/
    `--force`/`-f` sur `git commit`/`git push`).
  - fichier présent, JSON valide → **complète** les entrées `allow`/`deny`
    du gabarit qui manquent, sans retirer quoi que ce soit que l'opérateur y
    a mis. C'est le correctif #267 : avant, un fichier déjà présent mais
    plus étroit (ex. cinq outils MCP historiques seulement, aucun `Bash`)
    n'était jamais complété — « Automode déjà présent, non modifié » alors
    que la liste blanche réelle était incomplète.
  - fichier présent, JSON invalide → **REFUS explicite** (le lanceur
    s'arrête, code de sortie non nul), jamais un écrasement.
- **Garde avant nuit** (`tools\banc\verifier-avant-nuit.sh`, délègue à
  `tools\banc\verifier-liste-blanche-nuit.sh`) : REFUSE de démarrer une nuit
  si `.claude\settings.local.json` existe et ne porte pas encore les deux
  entrées `allow` requises (message : ce qui manque) — la nuit ne démarre
  plus avec une liste blanche incomplète en apparence « vérifiée ».
- **Tests** : `tests/liste_blanche_banc_test.py` (la fonction, trois
  fichiers synthétiques : absent, partiel, complet, + JSON invalide) et
  `tests/verifier_liste_blanche_nuit_test.py` (la garde, mêmes cas) —
  dossier temporaire uniquement, jamais le `.claude\settings.local.json`
  réel du checkout principal.

## Banc de nuit N1 (#201, D-276 ; #260) — la boucle-ferme sans LLM

Joue des parties complètes la nuit, sans humain, sans analyste, avec budget,
arrêt propre et sorties en forme fixe. `nuit.sh` ne prend AUCUNE décision de
jeu : il copie des fichiers, lance/observe/ferme les deux agents existants
(joueur, Director — via `lancer-banc-fumee.ps1` réutilisé, pas réécrit), et
journalise des faits mécaniques. Toute décision narrative reste dans les
gabarits gelés (`tools/prompts/banc-mj.md`/`banc-joueur.md`, D-276 §4) ou le
sous-agent narrateur qu'ils spawnent.

### La commande du soir

```
.\tools\banc\nuit.cmd
```

Lancable par double-clic ou depuis un terminal ordinaire (PowerShell ou
cmd.exe), **sans ouvrir Claude Code**. Résout Git Bash lui-même (pas de
dépendance au PATH pour bash), reste ouverte le temps de la nuit, et
enchaîne : `git pull --ff-only` → garde de prérequis + « rien en vol »
(`verifier-avant-nuit.sh` : herdr joignable, `claude`/`gh` présents, save
présente, aucun agent `lane-*`/`revue-*` de circuit.sh NI `banc-mj`/
`banc-joueur` (forme nue ou suffixée par paire `banc-mj-N`, #282) déjà en
vol, aucune PR ouverte, envoi à blanc des deux gabarits rendus vers un
agent inexistant — #263,
`tools/banc/verifier-envoi-gabarits.ps1` — REFUS si l'un des deux casse
l'échappement de l'envoi plutôt que de rendre `agent_not_found`) →
`tools/banc/nuit.sh -Parties 4 -Director ab` (défauts — un argument passé au
`.cmd` les remplace intégralement, ex. `.\tools\banc\nuit.cmd -Parties 8
-Director sonnet`) → affiche le chemin de `nuit.md` produit.

**Le matin** : ouvrir un fil et dire « lis la nuit » — Claude relit
`bench/nuit-AAAAMMJJ/nuit.md` et les `resume-run.md` de chaque partie.

### `nuit.sh` — paramètres

```
tools/banc/nuit.sh -Parties N [-Paires N] [-Director haiku|sonnet|ab] [-Tours 40]
                    [-Save <slug>] [-TimeoutTour <minutes>]
                    [-FinA HH:MM] [-DryRun]
```

- `-Parties N` (obligatoire) : nombre de parties à jouer ce lancement — le
  budget de la nuit. Plafond dur : aucune (N+1)-ème partie n'est lancée.
- `-Paires N` (défaut 1, Issue #282) : N parties tournent SIMULTANÉMENT (N
  paires Director/joueur). Quand une paire finit sa partie, elle reprend la
  suivante du budget `-Parties` — jusqu'à épuisement du budget ou `-FinA`.
  Étanchéité par paire : agents suffixés (`banc-mj-1`/`banc-joueur-1`,
  `banc-mj-2`/`banc-joueur-2`, ... — jamais de collision de nom, #271), sa
  propre copie de save et son propre dossier `partie-NN` (déjà vrai avant
  #282). `-Paires 1` (défaut) est le chemin séquentiel historique, INCHANGÉ
  bit à bit. Voir « Limite connue : `.turn/` partagé » ci-dessous avant
  d'utiliser `-Paires > 1`.
- `-Director haiku|sonnet|ab` (défaut `sonnet`) : modèle du Director
  (agent MJ). `ab` alterne haiku/sonnet en commençant par haiku (N0 = 4
  parties : 2 et 2) — le casting de chaque partie est écrit dans son
  `resume-run.md`. Le joueur tourne toujours en haiku/low, le narrateur
  (sous-agent spawné par le Director) en haiku.
- `-Tours 40` : plafond de tours par partie.
- `-Save <slug>` (défaut `banc-depart-beyond-the-vale-of-madness`) : save
  source (`saves/<slug>`, résolution `coderain/config.py::saves_dir`),
  copiée fraîche pour chaque partie — jamais jouée directement. **Doit être
  une save de DÉPART au tour 0** (voir § ci-dessous) — `nuit.sh` REFUSE
  nommément toute save dont `transcript.md` porte déjà un tour (« REFUS : la
  save '<slug>' est au tour N, une nuit ne joue qu'une save de départ (tour
  0). »).

### Save de DÉPART gelée (#275, I-465)

**Une nuit ne doit jamais pouvoir jouer une partie en cours.** Constat #274
(nuit N0 du 02/09) : `nuit.sh` copiait jusque-là `beyond-the-vale-of-madness`
telle qu'elle est dans `saves_dir()` — la partie JOUÉE jusqu'à la mort du
personnage (tour 28) puis prolongée en post-mortem. Chaque partie de nuit
démarrait donc APRÈS la fin du module, avec des dizaines de tours dans le
contexte, et le module DKS source était spoilé par la seule lecture de la
save.

`tools/banc/save-depart.py` fabrique **une fois** une save FRAÎCHE (tour 0,
`transcript.md` vierge, personnage installé — fixture #257, Mika Thorne, arme
+ armure équipées) depuis le scénario déjà enregistré (celui dont la save
jouée a été instanciée, `coderain/converter/install.py`), au moyen de
`coderain/templates.py::new_save` (jamais réécrit). Rangée hors dépôt sous
`saves_dir()`, comme toute autre save (D-224) — jamais commitée, jamais
écrasée sans `--force` :

```
python tools/banc/save-depart.py
    [--slug banc-depart-beyond-the-vale-of-madness]
    [--from-save beyond-the-vale-of-madness]   # source du scénario à reprendre
    [--scenario <slug scénario, déduit de --from-save par défaut>]
    [--profil guerrier] [--force]
```

`--from-save` ne sert qu'à retrouver, dans son `meta.json`, le slug du
scénario dont repartir — la save de départ n'en copie ni l'état ni les
tours. Le slug de départ et le profil de fixture sont des paramètres, pas
des constantes : d'autres profils de personnage (hors périmètre #275)
n'exigeront pas de réécrire ce script.

`tools/banc/verifier-avant-nuit.sh` vérifie, en plus de ses gardes
existantes, que la save `-Save` (ou son défaut) existe et est bien au tour
0 — même contrat que la garde de `nuit.sh`, pour échouer avant même de
tenter un lancement.
- `-TimeoutTour <minutes>` (défaut 6) : au-delà, sans nouveau fichier de
  tour, la partie craque (`craquement-timeout-NN.md`) et se ferme ; la
  suivante démarre.
- `-FinA HH:MM` (#276, heure locale du poste, défaut `06:00` dans
  `nuit.cmd`, pas de défaut dans `nuit.sh` seul) : plus aucune partie ne
  démarre après cette heure ; une partie en cours s'arrête proprement au
  tour suivant, par le **même chemin que STOP** (fermeture et vérification
  des agents, `resume-run.md`, `nuit.md`, sortie **130**), raison d'arrêt
  « heure de fin atteinte (HH:MM) ».
  **Résolution : deux règles distinctes, jamais une comparaison d'égalité à
  l'horloge courante** (une comparaison d'égalité — « `-FinA` tombe
  exactement sur la minute du lancement » — s'est révélée être une course :
  selon l'instant précis où `nuit.sh` lit l'horloge face à l'instant capturé
  par un test, la minute peut déjà avoir changé ; corrigé en 2ᵉ revue REFUS
  du 03/09 par une comparaison d'INÉGALITÉ, robuste à n'importe quel écart) :
  1. **Au lancement d'une nuit FRAÎCHE** (aucune partie encore jouée ce jour
     dans le `-RunDir` visé) : HH:MM déjà passée pour le jour calendaire du
     lancement bascule à **DEMAIN** plutôt que de refuser (résolue une seule
     fois au lancement, jamais recalculée après minuit pendant le run).
     C'est ce qui permet le cas d'usage nominal : `nuit.cmd` lancé en
     soirée avec le défaut `-FinA 06:00` vise 06:00 le **lendemain matin**,
     jamais un refus — une première version qui résolvait « aujourd'hui
     seulement » refusait tout lancement fait entre 06:00 et minuit, ce qui
     aurait tué le but de #276 (1ʳᵉ revue REFUS). Sous cette sémantique
     « prochaine occurrence », aucune heure n'est jamais authentiquement
     « passée » au lancement d'une nuit fraîche — seul le **format** de
     `-FinA` reste refusable (exit 1, avant toute écriture).
  2. **Pendant la nuit, sur un relancement en CONTINUATION** (`partie-01`
     déjà présente dans le `-RunDir`) : **jamais** de bascule au lendemain —
     HH:MM déjà atteinte pour aujourd'hui (par n'importe quelle marge) fait
     s'arrêter la nuit **tout de suite** (exit 130) avant la partie
     suivante, par le même chemin que STOP. Une continuation ne recule
     jamais son heure de fin d'un jour entier.
- `-DryRun` : crée toute l'arborescence (copies de save + fixture) et les
  `resume-run.md`/`nuit.md`, mais ne lance AUCUN agent — sert au test de
  forme (`tests/nuit_dryrun_test.py`) et à vérifier un montage sans
  consommer de budget de session.

Un second appel le même jour reprend au numéro de partie suivant (ne
réécrase jamais une partie déjà jouée — idempotence).

### Ce que fait une partie

1. Copie fraîche de la save vers `bench/nuit-AAAAMMJJ/partie-NN/save/` et
   installation de la fixture de personnage (`bench/fixtures/personnage-banc.py`,
   #257).
2. Lancement des deux agents (`lancer-banc-fumee.ps1`, avec `-ModeleMj`,
   `-ModeleJoueur`, `-SavesDirOverride` et `-JournalDirOverride` — trois
   paramètres additifs #260, défauts inchangés pour le banc de fumée
   historique) — le journal ET la save isolée de la partie vivent tous deux
   sous `bench/nuit-AAAAMMJJ/partie-NN/`. `lancer-banc-fumee.ps1` REFUSE
   nommément (« agent <nom> déjà en vol sur le pane <id> ») si `banc-mj` ou
   `banc-joueur` est déjà en vol avant tout `pane split`/`agent start` (#271)
   — au lieu d'un « échec de `herdr agent start` » muet.
3. Boucle de tours par lots (go joueur → `action-NN.md` → go MJ →
   `prose-NN.md`/`tour-NN.md`), jusqu'à fin de partie, craquement, ou
   `-Tours`.
4. Fermeture des agents (`herdr pane close` des deux panes — l'équivalent
   banc de `circuit.sh nettoyer`, I-243 : ce qui crée détruit).
5. Partie suivante.

### Contrat de fichiers du tour (#269)

| fichier | écrit par | quand | contenu |
|---|---|---|---|
| `action-NN.md` | joueur (banc-joueur) | sur le « go » joueur | l'action du joueur, un paragraphe, verbatim |
| `tour-NN.md` | MJ (banc-mj) | sur le « go » MJ, spécifié par le gabarit `banc-mj.md` (§ Journal du banc) | visée du Director, chemins/tailles de paquets, événements moteur, ET la section `## Prose du Narrateur (verbatim)` |
| `prose-NN.md` | `tools/banc/extraire_prose.py`, appelé par `nuit.sh` | juste après que `tour-NN.md` apparaît, avant le « go » joueur suivant | UNIQUEMENT le corps de la section « Prose du Narrateur » de `tour-NN.md` — l'organe zéro-spoiler (D-219) : c'est le seul fichier que lit le joueur |

`prose-NN.md` n'est **jamais** un livrable attendu du MJ — le gabarit
`banc-mj.md` (gelé, D-276 §4) ne spécifie que `tour-NN.md` ; le message
« go » d'ouverture de `nuit.sh` ne demande plus que celui-ci. L'extraction
(`tools/banc/extraire_prose.py`) est purement mécanique (aucun LLM) :
elle cherche une ligne de titre `#`…`######` suivie de « Prose du
Narrateur » (casse libre, suffixe libre — ex. « (verbatim) »), tolérante
aux variantes de titre, et prend tout le texte jusqu'au titre suivant (ou
la fin du fichier). Si la section est absente ou vide, la partie craque
(`craquement-prose-absente-NN.md`, classe Director, D-276 §4) et se ferme —
comme un timeout de tour, ça n'arrête pas la nuit.

### Sorties en forme fixe

`bench/nuit-AAAAMMJJ/partie-NN/` reçoit `tour-NN.md`, `prose-NN.md`,
`action-NN.md`, `craquement-*.md` (comme le banc de fumée) + un
`resume-run.md` MINIMAL écrit par le script (casting, **paire** — #282,
numéro de la paire Director/joueur qui a joué cette partie, "01" en
séquentiel —, tours joués, fin atteinte O/N, raison de l'arrêt, liste des
craquements, durée) — l'analyse est N2, pas ce script.

`bench/nuit-AAAAMMJJ/nuit.md` : table des parties (director, tours joués,
fin atteinte, raison), budget consommé, nombre de paires (`-Paires`, #282),
raison de l'arrêt de la nuit, les métriques §3 de #201
(`tools/banc/metriques_nuit.py`, calculées par le script, jamais un
jugement — inclut désormais « Paires simultanées », #282), et le statut du
dépôt de `rapport-nuit.md` sur l'Issue #201 (voir ci-dessous). La table est
reconstruite mécaniquement à partir des `resume-run.md` déjà écrits (jamais
accumulée en mémoire pendant la nuit) — fonctionne identiquement en
séquentiel et en parallèle.

### `rapport-nuit.md` — « lis la nuit » sans agent (#276)

Écrit dans `bench/nuit-AAAAMMJJ/` à la **fin de la nuit, quelle que soit la
raison d'arrêt** (budget `-Parties` atteint, STOP/PAUSE, `-FinA` atteinte,
limite de session, échec de lancement répété, agent non fermé) — jamais
d'exception à « rapport écrit ». Forme fixe (`tools/banc/metriques_nuit.py`,
fonctions `calculer_rapport`/`formater_rapport_markdown`, appelées `<run_dir>
rapport <raison_arret> <duree_totale_s> <limite_session:oui|non>` — étend
`metriques_nuit.py`, ne duplique rien) :

- parties finies / lancées, durée totale, raison d'arrêt ;
- tours sans craquement par partie (médiane / min / max) ;
- craquements par classe D-276 §4 (matériau / règle / Director / outillage)
  — lue **mécaniquement** dans le nom `craquement-<classe>-NN.md` ; un
  fichier dont le token de classe ne correspond à aucune des quatre compte
  « non classé ». Les types mécaniques actuels de `nuit.sh`
  (`fixture`/`lancement`/`nettoyage`/`timeout`/`prose-absente`) ne portent
  aucun de ces noms de classe : ils comptent tous « non classé » aujourd'hui
  — la classification D-276 réelle est l'analyste N2 (hors périmètre #276).
- A/B Director (haiku ⊥ sonnet) : tours moyens et craquements de classe
  `director` imputés à chaque modèle castée (relu dans `resume-run.md`) ;
- limite de session touchée : oui / non ;
- budget consommé : durée (jetons non mesurés — aucun compteur de jetons
  n'existe côté banc aujourd'hui) ;
- jusqu'à trois pointeurs (chemins) vers les `tour-NN.md` des craquements les
  plus récents du run (le craquement lui-même si le `tour-NN.md`
  correspondant n'existe pas).

Si le calcul (`metriques_nuit.py … rapport …`) échoue, `rapport-nuit.md`
n'est **jamais** silencieusement vide : `ecrire_rapport_nuit` (nuit.sh) y
écrit alors un en-tête « ÉCHEC DE CALCUL » suivi de la sortie d'erreur —
même discipline que le dépôt `gh` ci-dessous, jamais une erreur avalée.

**Dépôt sur l'Issue #201** (`deposer_rapport_201` dans `nuit.sh`, via `gh`) :
tenté à chaque fin de nuit, jamais en `-DryRun`. Statut toujours cité dans
`nuit.md` (`dépôt Issue #201 : ...`) :
- `posté sur #201` — `gh issue comment 201 --repo souhelmeskache/souffleur
  --body-file rapport-nuit.md` a réussi ;
- `non posté (gh indisponible)` / `non posté (gh non authentifié)` / `non
  posté (échec gh issue comment)` / `non posté (-DryRun)` — le fichier
  `rapport-nuit.md` seul reste la source, lisible sans ouvrir le poste dans
  tous les cas puisqu'il est déjà dans `bench/nuit-AAAAMMJJ/`.

### Budget, arrêt propre, codes de sortie

- **Timeout par tour** (`-TimeoutTour`, défaut 6 min, en attente de
  `action-NN.md` ou `tour-NN.md`) : craquement `timeout` journalisé, partie
  fermée, suivante lancée — n'arrête PAS la nuit.
- **Section prose absente ou vide** (#269) : `tour-NN.md` apparaît mais ne
  porte aucune section « Prose du Narrateur » exploitable — craquement
  `prose-absente` journalisé (`craquement-prose-absente-NN.md`), partie
  fermée, suivante lancée — n'arrête PAS la nuit non plus (voir § Contrat de
  fichiers du tour ci-dessus).
- **Limite de session** : texte « session limit »/« usage limit » détecté
  dans un pane, OU agent `blocked` + idle sans progrès > 10 min → `nuit.md`
  écrit, les deux panes de la partie en cours sont fermés, **sortie 5** —
  arrête TOUTE la nuit (jamais un agent laissé en vol), même si `-Parties`
  n'est pas atteint.
- **Échec de lancement répété** (#263) : `lancer-banc-fumee.ps1` échoue
  (rc non nul) à lancer les deux agents d'une partie. Un échec isolé craque
  SEULEMENT cette partie (`craquement-lancement-00.md`), la suivante
  démarre — mais **deux échecs de lancement consécutifs** signalent une
  cause structurelle (ex. gabarit qui casse l'échappement de l'envoi, voir
  `tools/lancer-banc-fumee.ps1` § 0bis) qui répétera l'échec à l'identique
  sur chaque partie restante : la nuit s'arrête là plutôt que de consommer
  tout le budget `-Parties` sur le même craquement, `nuit.md` reçoit
  `raison_arret: lancement impossible (2 échecs de lancement consécutifs,
  partie NN)`, **sortie 6**.
- **Interruption (Ctrl+C)** : `trap INT/TERM` — ferme les agents en vol,
  écrit `nuit.md` avec `raison_arret: interrompu (SIGNAL)`, sort 130. **Non
  garanti sous Windows** (constat #271, nuit N0 02/09 : le trap n'a jamais
  tourné depuis un shell Windows exécutant `nuit.sh` via Git Bash) — **pour
  arrêter la nuit de façon garantie, créer le fichier
  `bench/nuit-AAAAMMJJ/STOP`** (ou `tools/PAUSE`, déjà lu par
  `lancer-lane.ps1`). Testé à chaque poll (`attendre_fichier`) et entre deux
  parties, quel que soit le shell qui a lancé la nuit : nettoyage des agents
  en vol, `nuit.md` réécrit (`raison_arret: arrêt demandé (fichier
  STOP/PAUSE)`), sortie 130.
- **Heure de fin `-FinA` atteinte (#276)** : même chemin que STOP/PAUSE
  ci-dessus (testé à chaque poll et entre deux parties) — `nuit.md` reçoit
  `raison_arret: heure de fin atteinte (HH:MM)`, sortie 130. Voir « `-FinA
  HH:MM` » ci-dessus pour le refus au lancement sur une heure déjà passée.
- **Fin de partie vérifiée (#271)** : après la fermeture des panes, `nuit.sh`
  attend (bornée 30 s) que `herdr agent list` ne porte plus ni `banc-mj` ni
  `banc-joueur` — nuit N0 02/09 : un `banc-joueur` survivant a fait échouer
  TOUTE partie suivante par collision de nom sur `agent start`. Un agent
  survivant reçoit `/exit` (`herdr agent send-keys`, **jamais** `agent
  prompt` depuis bash — `/exit` y est réécrit `C:/Program Files/Git/exit` par
  la conversion de chemin MSYS de Git Bash) puis une dernière vérification ;
  s'il survit encore, la nuit s'arrête (craquement `craquement-nettoyage-NN.md`,
  `raison_arret: agent non fermé (partie NN : <agents>)`, **sortie 7**) —
  jamais de partie suivante lancée sur un nom déjà pris. Si `herdr pane
  close` répond `confirmation_required` (dernier pane d'un workspace, nuit N0
  cas 1), c'est journalisé et `/exit` est tenté directement, sans dépendre
  d'un pane « principal » resté ouvert.
- **Environnement propre (#271)** : `SAVES_DIR` hérité de l'environnement du
  pane qui lance `nuit.sh` (posé par `herdr pane split --env` sur une partie
  précédente) est ignoré (`unset`, avec avertissement) — la save source se
  résout toujours depuis `coderain/config.py::saves_dir()` sans override
  hérité du pane.
- **`0`** : la nuit s'est terminée normalement (budget `-Parties` consommé).
- **`1`** : argument invalide (refus avant tout lancement).
- **`5`** : limite de session — voir ci-dessus.
- **`6`** : échec de lancement répété — voir ci-dessus.
- **`7`** : agent non fermé après `pane close` + `/exit` — voir « Fin de
  partie vérifiée » ci-dessus.
- **`130`** : interrompu (Ctrl+C, ou fichier `STOP`/`tools/PAUSE`).

### Limite connue : `.turn/` partagé entre paires (#282)

`.turn/` (`mcp_server.ROOT / ".turn"`, `coderain/mcp/narrateur.py` +
`coderain/mcp/position_etat.py`) est un scratch d'assemblage de contexte de
tour — `mcp_server.ROOT` se résout au dossier du fichier `mcp_server.py`,
c'est-à-dire CE worktree, jamais par process/cwd/partie. En séquentiel
(`-Paires 1`, un seul Director actif à la fois) ça ne collisionne jamais.
Avec `-Paires > 1`, **N Directors concurrents dans le même worktree
partagent le même `.turn/paquet-narrateur.md`** — un Director peut lire un
paquet destiné à une AUTRE partie au même instant. `nuit.sh` avertit sur
stderr dès `-Paires > 1` ; ce point dur n'est PAS résolu par #282 (isoler
`.turn/` par partie demanderait de faire dépendre `mcp_server.ROOT` du cwd
de l'agent, hors périmètre : aucune modification du moteur). `.turn/`
n'est jamais relu au-delà du tour courant (scratch, jamais une source de
vérité de la save) — le risque réel touche la PROSE narrée à un instant T
d'une partie parallèle, pas une corruption de save ni de `transcript.md`.

### Ce que la nuit ne fait pas

- **Pas d'analyse, pas de correction** — N2/N3 lisent `nuit.md` et les
  `resume-run.md`, ce script les écrit seuls.
- **Pas de détection narrative de « fin de module »** : aucun signal
  générique de complétion narrative n'existe côté moteur sans jugement
  humain/LLM (hors périmètre #260 : « aucun LLM dans le script »). `fin
  atteinte` dans `resume-run.md` est un PROXY MÉCANIQUE — mort du joueur
  (`rpg.player.conditions` contient `"dead"`) — pas une lecture de la
  progression narrative. Une partie qui épuise `-Tours` sans mourir sort
  avec `fin_atteinte: N`, `raison_arret: tours_max`, sans que ce soit un
  échec.
- **Pas de protocole de tour 1 « froid »** : les gabarits gelés
  (`banc-mj.md`/`banc-joueur.md`, D-276 §4) supposent une reprise, pas un
  démarrage à vide. `nuit.sh` comble ce trou en envoyant le premier « go »
  au Director seul (« ouverture, pas d'action joueur — établis la scène
  d'ouverture ») plutôt qu'au joueur — une limite assumée, pas un défaut du
  gabarit.
- **Refus d'outil / combats sous-système dans les métriques** :
  `attack`/`roll_check` (refus) et `start_combat` (combat dnd5e-engine)
  n'écrivent aujourd'hui RIEN dans `events.jsonl` côté moteur — ces deux
  compteurs de `metriques_nuit.py` restent à 0 tant que ça ne change pas
  (hors périmètre #260 : aucune modification du moteur). Les bouchages
  (D-275) et les combats hors sous-système (deltas d'ennemi via
  `apply_envelope`) sont, eux, fiables dès aujourd'hui.
