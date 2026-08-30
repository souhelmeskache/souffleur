# CHEMINS.md — carte des chemins stables de la codebase

*Recense les chemins qui ne bougent pas d'une session à l'autre : points
d'entrée, outillage de tour, worktrees de lane, corpus/saves hors dépôt.
Chaque entrée est chemin · rôle · qui le lit. Périmètre : ce dépôt (`coderain`,
alias public `souffleur`) — le principe et l'historique de découpage
restent au vault (`C:\Vaults\MVP2\`), hors périmètre de ce fichier (ESC-3,
D-214 découpée).*

## Point d'entrée de la table

| Chemin | Rôle | Qui le lit |
|---|---|---|
| [`Coderain.bat`](../Coderain.bat) | Lanceur Windows (double-clic) : délègue à `start.py`, qui crée/retrouve le `.venv` et relance l'app web (`--cli`/`--gui` en options). | Le joueur, à l'ouverture d'une partie. |
| [`run.sh`](../run.sh) | Équivalent macOS/Linux de `Coderain.bat`. | Le joueur, hors Windows. |
| [`start.py`](../start.py) | Cible réelle des deux lanceurs ci-dessus : résout/crée le `.venv`, installe `requirements.txt`, relance le process dans ce venv, ouvre le navigateur sur `http://127.0.0.1:8377`. | `Coderain.bat`, `run.sh`. |

Aucun `jouer.bat` ni `moteur-actif.txt` n'existe dans ce dépôt à ce jour —
mentionnés comme hypothétiques dans l'Issue (« s'il existe ») ; à ajouter
ici s'ils apparaissent un jour.

## Dépôt moteur et pont MCP

| Chemin | Rôle | Qui le lit |
|---|---|---|
| Ce dépôt (`coderain`, remote GitHub `souhelmeskache/souffleur`) | Le moteur narratif + la couche campagne D&D 5e (voir [ARCHITECTURE.md](ARCHITECTURE.md)). | Tout agent Claude Code travaillant sur le moteur. |
| [`mcp_server.py`](../mcp_server.py) | Serveur MCP du moteur — outils exposés au Director/session (`get_world_state`, `get_event_rules`, `assemble_context_to_file`, `load_save`, `resolve_check`, etc., voir [ARCHITECTURE.md](ARCHITECTURE.md)). | Toute session/agent qui joue une partie via le pont MCP. |
| [`opencode.json`](../opencode.json) | Déclare le serveur MCP `coderain-engine` : commande `.venv/Scripts/python.exe mcp_server.py`. **C'est le point d'entrée MCP réel de ce dépôt** — il n'y a pas de `.mcp.json` à la racine. | opencode (et tout client MCP compatible) au démarrage d'une session. |

## Outillage tour (lanceur de lanes, hooks)

| Chemin | Rôle | Qui le lit |
|---|---|---|
| [`tools/lancer-lane.ps1`](../tools/lancer-lane.ps1) | Lanceur minimal d'une lane Herdr sur une Issue GitHub labellisée `prete` (mode par défaut), ou d'une lane de revue adversariale sur une PR (mode `-Revue`, D-251). Crée le worktree via `herdr worktree create`, injecte le corps de l'Issue **verbatim** dans le prompt (frontière de confiance = label `prete`, voir [CLAUDE.md](../CLAUDE.md)). | Le mainteneur (Souhel), depuis le tour de contrôle. |
| [`hooks/`](../hooks/) | Dossier de hooks git versionné du repo — active via `git config core.hooksPath hooks` (une fois par clone/worktree neuf ; hérité par toutes les worktrees car la config vit dans `.git/config`, partagé). | Git, à chaque commit/push. |
| [`hooks/pre-commit`](../hooks/pre-commit) | Relance `python run_tests.py` (hors `trinity_test.py`) et refuse tout commit sur suite rouge. | Git, au commit. |
| [`hooks/pre-push`](../hooks/pre-push) | Refuse tout push dont une refspec cible `refs/heads/main` (garde de branche `main`, D-224). | Git, au push. |

## Worktrees des lanes

| Chemin | Rôle | Qui le lit |
|---|---|---|
| `~/.herdr/worktrees/souffleur/lane-<numéro-Issue>/` | Worktree jetable créé par `herdr worktree create --branch lane-<Issue> --base origin/main` (via `tools/lancer-lane.ps1`) pour l'exécution d'une lane sur l'Issue `<numéro>`. Chaque lane travaille exclusivement dans le sien (voir consigne « Travaille exclusivement dans ce worktree » de tout prompt de lane). | La lane elle-même (agent Claude Code), le temps de sa session. |
| `~/.herdr/worktrees/souffleur/revue-pr-<numéro-PR>-.../` | Worktree jetable dédié au mode `-Revue` de `tools/lancer-lane.ps1` — jamais le checkout principal (corrigé après la revue de la PR #60, D-251). | La lane de revue adversariale. |

## Corpus et saves — hors dépôt

Le matériau de campagne réel (modules source, adaptations converties,
vraies parties jouées) ne vit **jamais** dans ce dépôt — même gitignoré
(D-109) — voir `specs/audit-securite-*.md`.

| Chemin | Résolution | Rôle | Qui le lit |
|---|---|---|---|
| [`coderain/config.py::corpus_dir()`](../coderain/config.py) | `CORPUS_DIR` env var > clé `corpus_dir:` de `config.yaml` > défaut historique `C:\Users\souhe\ttrpg-corpus\modules-source`. | Racine du corpus de matériau de campagne (texte de modules extraits, fixtures de partition réelle pour le convertisseur). Optionnel : jamais requis, les appelants vérifient `.exists()`. | Le pipeline convertisseur (`coderain/converter/`), les tests qui exercent des fixtures réelles (sautées si absent). |
| Dépôt privé `ttrpg-corpus` (GitHub) | — | Dépôt Git séparé de `coderain`, avec sa propre discipline de push (aucune protection tant que le travail n'est pas poussé). Sauvegarde de `modules-source/` depuis 2026-08-28 (assainissement phase 1). | Toute session qui convertit un module ou modifie le corpus — doit se terminer par un commit + push de **ce dépôt-là**, séparément de `coderain`. |
| [`coderain/config.py::saves_dir()`](../coderain/config.py) | Pour la racine de production (`ROOT`) : `SAVES_DIR` env var > clé `saves_dir:` de `config.yaml` > défaut `ROOT/saves`. Pour toute autre racine (tests, `Library` sur un tmp dir) : toujours `<racine>/saves`, sans override — isolation garantie des tests. | Racine de la bibliothèque de saves (transcripts, mémoire par partie, état) pour un `Library` donné. | Le moteur (chargement/sauvegarde de partie), les tests via un `Library` isolé sur tmp dir. |
| `saves/` (à la racine du dépôt, si `saves_dir:` n'est pas surchargé) | Défaut historique de `saves_dir()`. Gitignoré (`.gitignore`). | Contient la save démo (`untitled`, scénario `the-veil`) livrée avec le dépôt, plus toute save locale tant que `saves_dir:` n'a pas été repointée hors dépôt. | Le joueur en local ; jamais versionné. |

### Autres données utilisateur gitignorées (racine du dépôt)

Auto-amorcées au premier lancement, jamais versionnées ni distribuées —
voir [`.gitignore`](../.gitignore) :

- `scenarios/`, `instructions/`, `characters.json`, `library.json`,
  `config.yaml` — configuration et données de jeu locales.
- `.env` — secrets (clé API modèle hébergé, etc.).
- `corpus-modules/` — entrée brute du convertisseur (texte de module extrait).
- `bench/banc-fumee/` — journal du banc de fumée (D-264), peut citer la
  fiction du module sacrificiel DKS (D-109/D-178) — rien de cette fiction
  ne se versionne, y compris le journal mécanique qui la cite.
- `.turn/` — scratch d'assemblage de contexte de tour (matériau de campagne).

## Résolution de `ROOT` (`coderain/config.py::_home_dir()`)

Sert de base à `saves_dir()` (cas par défaut) et à tout autre chemin de
données utilisateur non explicitement surchargé :

1. `CODERAIN_HOME` env var (installs portables, tests) — gagne toujours.
2. Build gelé (app desktop PyInstaller) : `%LOCALAPPDATA%\Coderain` — le
   dossier de l'exe est remplacé à chaque mise à jour, les données ne
   peuvent pas y vivre.
3. Checkout source : racine du dépôt (comportement historique).
