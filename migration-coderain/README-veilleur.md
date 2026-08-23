# README — `veilleur.ps1`

*Le veilleur de la boucle — palier v1 de [`D-191`](../meta-rpg/registre-decisions/D191-l-autonomie-de-la-boucle-par-paliers.md), livré le 2026-08-23, fiche [FICHE-veilleur-v1-2026-08-23.md](FICHE-veilleur-v1-2026-08-23.md). Corrigé le 2026-08-23 après premier cycle réel ([FICHE-correction-veilleur-bugs-premier-cycle-2026-08-23.md](FICHE-correction-veilleur-bugs-premier-cycle-2026-08-23.md)) puis v1.1, puis après l'incident de boucle de relance ([I-275](../meta-rpg/registre-items/MRPG-I-275-la-boucle-de-relance-du-veilleur.md) — [FICHE-incident-boucle-relance-veilleur-2026-08-23.md](FICHE-incident-boucle-relance-veilleur-2026-08-23.md)). Souhel ne lance plus : il reçoit un digest et rend ses arbitrages.*

## Usage

```powershell
.\veilleur.ps1                  # boucle continue, un tour toutes les 5 min
.\veilleur.ps1 -Once            # un seul tour (tests)
.\veilleur.ps1 -DryRun -Once    # affiche ce qu'il ferait, ne lance rien, n'écrit rien
.\veilleur.ps1 -Install         # (geste de SOUHEL) enregistre et démarre la tâche planifiée
```

| paramètre | rôle |
|---|---|
| `-IntervalleSecondes` | période de poll (défaut 300) |
| `-DryRun` | détection + commandes affichées, **aucun lancement, aucune écriture** (state, log, digest, verrous) |
| `-Once` | un tour puis sortie |
| `-Install` | enregistre la tâche Windows `MRPG-Veilleur` (déclenchement à l'ouverture de session, fenêtre cachée, **`StopOnIdleEnd=false` depuis I-275**) puis la démarre. Retrait : `schtasks /Delete /TN MRPG-Veilleur` |
| `-SessionsIllimitees` | **(I-275 livrable 15 — CONDITIONNEL)** supprime le plafond 6/jour : le compteur `sessionsJour` reste tenu au journal mais ne refuse plus rien ; le garde de concurrence (3 lanes actives) devient le seul frein. Ne PAS activer tant que les livrables 1–14 d'I-275 ne sont pas prouvés en réel |

## Ce qu'il surveille, à chaque tour

1. **Nouveaux rapports** — tout `rapport-*.md` du poste dont le `LastWriteTimeUtc` diffère de
   celui consigné dans [`veilleur-state.json`](veilleur-state.json) ⇒ réveil d'une session méta
   : le prompt [`eveil-meta.md`](eveil-meta.md) instancié (jetons `{{MOTIF}}`/`{{RAPPORT}}`)
   est écrit dans un **fichier temporaire**, et la fenêtre lancée exécute
   `opencode.cmd run <contenu du fichier>` **depuis `meta-rpg/`** (le prompt ne transite jamais
   par la ligne de commande — le premier positionnel d'opencode est un chemin de projet ;
   invocation directe du `.cmd`, pas du shim npm `.ps1` qui habille la première ligne stderr en
   `NativeCommandError` rouge). La fenêtre passe en UTF8 (`chcp 65001`) AVANT l'appel.
   La sortie de la session est copiée dans `preuve-session-meta-<horodatage>.log` au poste.
2. **Fiches lançables — déclenchement par DISPONIBILITÉ (v1.1)** — lignes « lançables » du
   tableau §lanes de `meta-rpg/E3-E2-cycle-et-chantiers.md`. **Le changement de l'ensemble des
   fiches n'est plus un déclencheur** : chaque fiche lançable non lancée est examinée
   indépendamment à chaque tour — slot libre (< 3 actives) ∧ budget > 0 ⇒ lancement via
   `nouvelle-lane.ps1 -Nom <dérivé de la fiche> -Fiche <chemin>` ; sinon elle reste en file et
   repart au tour suivant sa libération. L'empreinte (`lanesEmpreinte`) ne sert plus qu'au
   journal. Le filtrage est **par cellule** : le marqueur de clôture (`livr|ferm|merg`) ne
   compte que dans la cellule d'état (dernière colonne) — un « mergé » ailleurs ne rend plus
   une fiche invisible, et toute fiche écartée malgré « lançable » produit un `[WARN]` citant
   la cause. Le code sortie de `nouvelle-lane.ps1` est vérifié : échec ⇒ ni `lanesLancees` ni
   `sessionsJour` incrémentés, `[WARN]` au journal + ligne au digest ; nouvelle tentative au
   tour suivant si la cause disparaît.
3. **CI rouge** — dernier run de `souhelmeskache/ttrpg-mvp` lu via `gh run list`.
   ⚠️ **`gh` n'est pas installé sur cette machine au 2026-08-23 : ce contrôle est IGNORÉ**
   tant que gh manque (installé ⇒ actif automatiquement, sans modification du script).
4. **Rien à signaler** ⇒ une ligne dans le log, rien d'autre.

Chaque action est tracée dans `veilleur.log` et résumée dans `digest-YYYY-MM-DD.md` (racine du poste).

## Les gardes

| garde | mécanisme |
|---|---|
| **Max 6 sessions lancées / jour** | compteur `sessionsJour` dans le state, remis à zéro au changement de jour ; tout dépassement est loggé `[GARDE]`. **Conditionnellement neutralisable** par `-SessionsIllimitees` (I-275 livrable 15, voir ci-dessus) |
| **Jamais deux sessions méta simultanées** | verrou par fichier `veilleur-meta.lock`, créé avant lancement, supprimé par la fenêtre lancée quand opencode se ferme. **Conservateur (correction du 2026-08-23)** : tout verrou **présent et frais** bloque, quel que soit son contenu ; un format inconnu est **respecté** (`[WARN]`), jamais traité comme inerte — c'est l'inversion de ce choix qui a causé le double réveil de 11:55/12:00. Seule soupape : un verrou au format du script datant de plus de 6 h est réputé obsolète |
| **Garde slots — lanes réellement actives** | critère déclaré : une lane compte comme active si sa branche **n'est pas fusionnée dans `main`**, ou si le worktree porte des **modifications non enregistrées**. Un worktree fini (fusionné, propre) ne bloque plus rien, même à commit récent (mesuré le 2026-08-23 : les trois lanes finies l'étaient moins de 3 h avant). Le dépôt racine n'est jamais compté (exclusion insensible aux slashes de git). Cas ambigus (HEAD détaché) ⇒ comptés actifs, par conservatisme |
| **Log horodaté** | `veilleur.log`, chaque lancement et chaque refus de garde |
| **Anti-instance multiple — deux couches (I-275 livrable 10)** | mutex nommé `Global\MRPG-Veilleur` **+ verrou PID** `veilleur-instance.lock`. Un mutex abandonné par une instance morte est **repris** sans échec ; un verrou PID dont le processus n'existe plus est écrasé ; un second démarrage tant qu'une instance vit sort avec `[WARN] instance deja active` |
| **Borne anti-boucle par fiche (I-275 livrable 3)** | compteur d'échecs consécutifs PAR fiche (`echecsParFiche`) ; après **N = 2** échecs consécutifs de `nouvelle-lane.ps1`, la fiche entre dans `fichesBannies` et sort de la file avec `[WARN]` au digest, **jusqu'à intervention** (déban = retirer son chemin de `fichesBannies` dans `veilleur-state.json`, geste méta/Souhel) |
| **Baseline sans réveil rétroactif** | au tout premier tour réel, l'état existant (rapports, empreinte des lanes, CI) est **consigné sans aucun réveil** — le veilleur ne se réveille pas sur le passé |

## Post-incident I-275 (2026-08-23) — ce qui a changé

L'incident ([I-275](../meta-rpg/registre-items/MRPG-I-275-la-boucle-de-relance-du-veilleur.md)) :
des fiches déjà lancées repartaient à chaque tour (fenêtres mort-nées), le processus mourait
silencieusement entre le lancement d'une lane et ses écritures (cause capturée en direct à
15:43 : `Add-Content` vers le digest en IOException, fichier tenu par un autre processus),
et le state a été remis à zéro deux fois par des instances à mémoire périmée.

1. **Mémoire du déjà-lancé (livrable 1)** — la fiche est marquée `lanesLancees` et l'état
   **sauvegardé AVANT** l'appel à `nouvelle-lane.ps1` : une fiche lancée ne repart JAMAIS,
   session morte ou pas ; un crash entre lancement et écriture ne peut plus perdre la marque.
   Le refus d'une fiche déjà lancée est désormais **visible** : ligne
   `[WARN] fiche deja lancee, ignoree : <fiche>` au journal à chaque tour.
2. **Écritures tolérantes aux verrous (livrable 6)** — toute écriture digest/log/state passe
   en retry borné (**3 × 500 ms**) puis journalise `[ERROR]` **sans tuer le processus** ;
   la ligne « tour terminé » est atteinte quel que soit le sort du tour (`finally`), et une
   erreur de tour n'arrête plus la boucle (catch par tour).
3. **Fusion anti-écrasement du state (livrable 5, mitigation)** — avant chaque sauvegarde, le
   fichier est relu : `lanesLancees`, `fichesBannies`, `echecsParFiche` (max) et
   `sessionsJour` du jour (max) ne peuvent plus **rétrograder** sous la plume d'une instance
   dont la mémoire est périmée.
4. **File qui continue (livrable 9)** — un échec de lane est spécifique à sa fiche :
   `continue` au lieu de `break` (l'échec de `veille-srd-relance` à 15:40–15:41 empêchait
   `catalogue-relance` de partir).
5. **Tâche planifiée (livrable 10)** — `StopOnIdleEnd=false` (appliqué à la tâche live le
   2026-08-23 ~16:50, XML vérifié) + double couche anti-instance ci-dessus.
6. **Remplissage continu / budget (livrables 14–15, `D-192`)** — aucun code nouveau : c'est
   la preuve croisée des points 1, 4 et du nettoyage P4 côté `nouvelle-lane.ps1`. Le saut du
   budget reste **conditionnel** (`-SessionsIllimitees`, activation = geste de Souhel).

Le veilleur **réveille, il ne tranche jamais** (`D-191` §v2 fermé). Aucune décision d'arbitrage
n'est automatisée ; les arbitrages restent à Souhel via le méta.

## Premier cycle réel (protocole d'observation)

1. Souhel exécute `.\veilleur.ps1 -Install` (tâche enregistrée + premier tour = baseline).
2. Déposer un `rapport-factice-*.md` au poste.
3. Au tour suivant (≤ 5 min) : session méta ouverte avec le prompt d'éveil, ligne dans log + digest.
4. Fermer la session méta (le verrou tombe), supprimer le rapport factice.

> ⚠️ Au 2026-08-23, `rapport-factice-demonstration-veilleur.md` (déposé pour le dry-run de
> démonstration) est **toujours présent** : tant qu'il n'est pas supprimé, le premier tour réel
> après installation le détectera et réveillera réellement une session méta. Le supprimer avant
> l'installation si ce réveil n'est pas voulu — c'est exactement le scénario du premier cycle réel.

## Limites connues (déclarées)

- **CI** : inactif tant que `gh` n'est pas installé (état vérifié au démarrage de chaque instance).
- **Lanes** : si le dépôt moteur (`C:\Users\souhe\coderain`) est absent ou illisible, la
  surveillance lanes est désactivée pour le tour (log `[WARN]`), les autres contrôles tournent.
- Le verrou méta repose sur la fermeture de la fenêtre lancée ; la garde anti-obsolescence
  (6 h) ne s'applique qu'aux verrous au format du script — un verrou de format inconnu bloque
  jusqu'à suppression manuelle (conservateur, voulu).
- **Permission opencode** : constaté le 2026-08-23, les sessions méta lancées se heurtent à un
  refus auto (`external_directory`) quand l'éveil leur fait lire un document du poste technique ;
  elles lisent leur éveil et démarrent l'instruction, mais la lecture du document signalé échoue
  tant que la permission n'est pas accordée côté configuration opencode de `meta-rpg/`.
- Le compteur journalier compte des **lancements**, pas des sessions terminées.
- La détection des rapports est **temporelle** (mtime), pas sémantique : le veilleur ne lit
  jamais le contenu d'aucun rapport.
- **Défaut constaté non corrigé (hors livrables d'I-275, à signaler)** — le marqueur de clôture
  de cellule (`livr|ferm|merg`, `veilleur.ps1` §Get-Lancables) attrape les SUB-chaînes : le mot
  « **livr**ables » dans une cellule d'état écarte la fiche de la file (cas réel 15:57 du
  2026-08-23 sur la fiche incident elle-même, `[WARN] fiche lanable ECARTEE`). Une fiche dédiée
  devra borner ces motifs (mots entiers / formes fléchées exactes).
- **Journal des tâches planifiées désactivé** sur cette machine
  (`Microsoft-Windows-TaskScheduler/Operational` : IsEnabled=False) : la chronologie fine des
  instances du 2026-08-23 n'a pu être établie que par recoupement log/digest.
