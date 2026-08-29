# Snapshot automatique des saves à l'ouverture de partie (I-148, ESC-4, Issue #110)

*Périmètre : un filet de versionnement au-dessus du système de save existant —
zéro changement de format, zéro verrou invasif, rien de réinventé. Origine :
record vault `MRPG-I-148` et verdict `ESC-4`, purge du 2026-08-29.*

## 1. Où vivent les saves aujourd'hui

`coderain/config.py:saves_dir()` résout la racine des saves dans cet ordre :
`SAVES_DIR` (variable d'env) > clé `saves_dir:` de `config.yaml` > défaut
historique `ROOT / "saves"`, où `ROOT` est lui-même résolu par `_home_dir()` :

- checkout source (dev, ce repo) : la racine du repo elle-même — `saves/` y
  est gitignoré (`.gitignore:14`), jamais tracké ;
- build gelé (app desktop PyInstaller) : `%LOCALAPPDATA%\Coderain` (l'exe est
  remplacé à chaque update, les données ne peuvent pas y vivre) ;
- tout autre `library_root` (chaque harnais de `tests/` ouvre une `Library`
  contre un dossier temporaire jetable) : toujours `library_root / "saves"`,
  sans consulter l'override — pour ne jamais faire fuiter un `saves_dir:` de
  prod dans un test (et inversement).

Une save est un dossier `saves/<slug>/` (`SaveLibrary`, `coderain/memory.py`,
classe `SaveLibrary` puis `MemoryStore`) contenant :

- `meta.json` (titre, scénario d'origine, mode, timestamps) ;
- `state.json` (état mutable : horloge, RPG, `persistent`…) et
  `.fold_state.json` (curseurs de repli mémoire) ;
- les fichiers Markdown de jeu (`transcript.md`, `characters.md`,
  `memory/arc.md`, `memory/scenes.md`, fichiers de lore custom…) ;
- `.snapshots/` : copies datées déjà existantes (voir §3).

## 2. Qui écrit dedans

Quatre frontends, tous construits sur le même `Library`/`SaveLibrary` de
`coderain/memory.py`, peuvent toucher une save :

| Frontend | Point d'ouverture d'une save |
|---|---|
| `play.py` (CLI) | `_open()` |
| `server.py` (API web / webapp) | `_engine()` (1ʳᵉ requête sur un slug dans le process — les suivantes réutilisent l'`Engine` mis en cache) |
| `gui.py` (app desktop Tk) | `_open_story()` |
| `mcp_server.py` (outil MCP) | `load_save()` |

Ensuite, pendant la partie, c'est l'`Engine` (`coderain/engine.py`) et le
`Summarizer` (`coderain/summarizer.py`) qui écrivent — narration, repli
mémoire, état RPG — via les méthodes de `MemoryStore` (`write`, `write_state`,
`append_turn`, `upsert_entry`…).

**Le trou (I-148)** : depuis la fin de l'étanchéité (D-256), plusieurs de ces
acteurs peuvent toucher le même dossier de save à des instants proches (CLI +
webapp + MCP pointés sur le même `saves_dir`) sans qu'aucun d'eux ne
versionne quoi que ce soit — une collision ou une écriture corrompue n'a pas
de filet de rattrapage.

## 3. Ce qui existait déjà — réutilisé, pas réinventé

`MemoryStore.snapshot(keep=5)` existait déjà (repli mémoire, `/branch`) :
copie datée (`saves/<slug>/.snapshots/AAAAMMJJ-HHMMSS/`) de tous les `*.md`
plus `state.json`/`.fold_state.json`, avec rotation (les plus anciennes au-delà
de `keep` sont supprimées). Appelée jusqu'ici uniquement juste avant un repli
mémoire (`Summarizer.maybe_fold`), c'est le mécanisme qui alimente aussi
`/branch` (`_nearest_snapshot` reconstruit l'état à un tour donné à partir de
la snapshot la plus proche).

## 4. Décision arbitrée : copie datée réutilisée, pas de dépôt git séparé

Deux options envisagées (l'Issue en laissait le choix à la spec) :

- **commit dans un dépôt de saves dédié** — versionnement plus riche (diff,
  historique complet), mais ajoute une dépendance git dans le chemin de jeu,
  un dépôt de plus à gérer (cf. `ttrpg-corpus` déjà séparé pour le matériau
  de campagne), et un risque de verrou (git index) sur un dossier qui peut
  être touché par plusieurs process ;
- **copie datée** (retenue) — c'est *déjà* le mécanisme utilisé dans ce repo
  pour ce genre de filet (`snapshot()` pré-repli). Zéro dépendance nouvelle,
  zéro lock, rotation déjà en place, et il alimente déjà `/branch` — un
  filet à l'ouverture ne fait qu'ajouter des points de restauration plus
  fins sur le même mécanisme.

## 5. Ce qui a été fait

- `MemoryStore.snapshot()` : `meta.json` ajouté au périmètre copié (titre/
  scénario/mode n'étaient pas sauvegardés jusqu'ici — gap comblé au passage,
  addition strictement supplémentaire, sans effet sur les appels pré-repli
  existants).
- `SaveLibrary.open(slug, keep=5)` (+ `Library.open()` en passe-plat) :
  `store(slug)` suivi d'un `store.snapshot(keep=keep)` best-effort (une
  snapshot qui échoue — disque plein, permissions… — ne bloque jamais
  l'ouverture de la partie, elle est avalée silencieusement). `store()`
  lui-même reste inchangé et sans snapshot : il sert aussi des accès
  ponctuels en cours de session (édition du monde, application d'un
  personnage) qui ne sont pas une « ouverture » et qu'il ne faut pas
  faire crépiter dans `.snapshots/`.
- Les quatre points d'ouverture du §2 appellent désormais `.open(slug)` au
  lieu de `.store(slug)`.

## 6. Limites assumées

- Filet best-effort : une snapshot manquée (erreur silencieuse) n'est pas
  remontée à l'UI — cohérent avec le principe « zéro verrou invasif », mais
  ça veut dire qu'un disque plein persistant n'alerte personne.
- La fenêtre de collision elle-même (deux acteurs qui écrivent en même temps
  pendant la partie, pas seulement à l'ouverture) n'est pas fermée par ce
  travail — hors périmètre de l'Issue #110, qui demande un filet à
  l'ouverture, pas un verrou d'écriture concurrente.
- `server.py` ne snapshote qu'à la première requête par slug et par process
  (`_engines` est un cache mémoire) — un redémarrage du serveur redéclenche
  une snapshot au prochain accès, ce qui est le comportement voulu (nouvelle
  « ouverture » de partie du point de vue du process).

## 7. Tests

`tests/phase5_saves_test.py`, `tests/phase5_sweep_test.py` et
`tests/phase3_sweep_test.py` couvrent déjà `MemoryStore.snapshot()` (rotation,
collision même-seconde, contenu). `tests/snapshot_ouverture_i148_test.py`
(nouveau) couvre `SaveLibrary.open()`/`Library.open()` : une snapshot est bien
créée à l'ouverture, `meta.json` y figure, une ouverture répétée respecte la
rotation `keep`, et un échec de snapshot (dossier `.snapshots` rendu
non-writable) n'empêche pas `open()` de retourner un store utilisable.
