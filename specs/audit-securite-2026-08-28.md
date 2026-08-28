# Audit contenu sensible — 2026-08-28 (phase 1, point a)

*Périmètre : matériau de campagne (PDF au moins, dixit Souhel) et secrets (.env, jetons, chemins perso), recherchés dans l'arbre de travail actuel ET dans l'historique git complet (`--all`, tous refs locaux et distants — `origin/*`, `upstream/*`). Méthode : `git ls-files`/`find` pour l'arbre, `git rev-list --objects --all` + `git cat-file --batch-check` pour un inventaire exhaustif des blobs jamais créés dans la base d'objets (indépendant de la branche/du moment où un `.gitignore` a été ajouté), et `git log --all -S<motif>` (pickaxe) pour les motifs de secrets. Aucune commande destructive exécutée.*

## Résultat en une phrase

**Aucun PDF, aucun texte/image de campagne, aucun jeton/clé n'a jamais été commité dans ce dépôt (arbre actuel ET historique complet).** Une seule catégorie de fuite trouvée : un **chemin absolu personnel** (`C:\Users\souhe\...`) codé en dur dans 11 fichiers trackés — pas un secret exploitable, mais à corriger avant passage en public.

## 1. Matériau de campagne (PDF, texte extrait, cartes)

- **Arbre actuel** : un seul PDF présent sur disque — `corpus-modules/death-knights-squire/source/pdfcoffee.com_the-death-knightx27s-squire-adventure-booklet-pdf-free.pdf` — ainsi que tout le dossier `corpus-modules/` (texte extrait page par page, partition `pconv3`, cartes). **Aucun de ces fichiers n'est tracké** : `corpus-modules/` est gitignoré depuis l'origine (`.gitignore` ligne dédiée, commentaire *"P4 converter input corpus: extracted module text + measures (campaign material)"*, décision `D-178` citée au commit `01f3aac`).
- **Historique complet** (`git rev-list --objects --all` sur tous les refs, y compris `upstream/*`) : **zéro objet** sous `corpus-modules/`, **zéro fichier `*.pdf`**, **zéro image** (`jpg/jpeg/png/gif/webp`) hors `docs/demo.gif` (asset de démo du produit, sans rapport). Recherche indépendante du moment où le `.gitignore` a été posé — elle porte sur les objets réellement créés dans la base git, pas sur l'état d'un `.gitignore` à un instant donné.
- **Verdict** : rien à purger côté matériau de campagne. Le geste `D-178` (garder le corpus hors git) a été respecté sur toute la durée du projet.

## 2. Secrets (.env, jetons, clés)

- **Arbre actuel** : `.env` et `config.yaml` présents sur disque, tous deux confirmés gitignorés et non trackés (`git check-ignore -v`, `git status --ignored`). `.env.example` est un gabarit sans valeur réelle (`OLLAMA_API_KEY=ollama`, deux clés vides).
- **Historique complet** : recherche pickaxe (`git log --all -S<motif>`) sur `sk-`, `AKIA` (AWS), `ghp_`/`github_pat_` (jetons GitHub), en-têtes de clé privée (`BEGIN PRIVATE KEY`/`BEGIN RSA`), `password=`, `passwd=`, `api_key`, `apikey` — **aucun résultat**, sur aucun commit d'aucune branche.
- **Verdict** : rien à purger côté secrets.

## 3. Chemins personnels — seule fuite trouvée

`C:\Users\souhe\coderain\...` est codé en dur (chemins absolus Windows) dans **11 fichiers trackés**, présents sur `main` à HEAD (`bdb2407`) :

| Fichier | Occurrences |
|---|---|
| `tests/pconv3_ressource_test.py` | 3 (chemins `corpus-modules/...`) |
| `tests/test-auteur-codes-tension.py` | 2 |
| `tests/test-borne-deux-murs-i033.py` | 2 |
| `tests/test-conversation-b-outillage.py` | 1 |
| `tests/test-director-camera-patch.py` | 1 |
| `tests/test-personnage-destinee.py` | 2 |
| `tests/test-pval-bout-en-bout.py` | 2 |
| `tests/test-pval-extension-conversation-b.py` | 2 |
| `docs/ingestion-dks-analyse.md` | 1 |
| `opencode.json` | 2 (chemins `.venv\Scripts\python.exe`, `mcp_server.py`) |
| `statusline_gauge.py` | 1 (config embarquée) |

- **Nature** : ces chemins pointent tous vers `corpus-modules/...` (déjà gitignoré — le contenu qu'ils référencent n'est pas exposé, seul le chemin littéral l'est) ou vers l'arborescence locale du dépôt (`opencode.json`, `statusline_gauge.py`). Aucun ne contient de secret ; le seul élément personnel exposé est le nom d'utilisateur Windows `souhe`.
- **Effet pratique déjà visible** : ces tests sont non portables (ils supposent le chemin exact `C:\Users\souhe\coderain`) — hors périmètre de cet audit, mais à signaler pour une fiche de nettoyage séparée si Souhel le veut (paramétrer via variable d'env / chemin relatif).
- **Historique** : introduit progressivement depuis `01f3aac` (26/08) et répété à chaque nouveau test réutilisant le même patron — présent sur de nombreux commits intermédiaires, pas seulement HEAD.
- **Mention à part** : `catalogue/README.md` référence l'URL `github.com/souhelmeskache/ttrpg-mvp` — c'est le nom de compte GitHub déjà public (visible dans l'URL du dépôt lui-même), pas une fuite au sens de cet audit.

## Plan de purge `git filter-repo` (préparé, NON exécuté)

**Pour le matériau de campagne et les secrets : aucun plan nécessaire, rien n'est présent dans l'historique.**

**Pour les chemins personnels** (facultatif, sévérité faible — à trancher par Souhel) :

```bash
# 1. Sauvegarde impérative avant toute réécriture d'historique
git clone --mirror https://github.com/souhelmeskache/ttrpg-mvp C:\Backups\ttrpg-mvp-mirror-avant-purge-2026-08-28.git

# 2. Fichier de substitution (texte littéral, pas de commit touché s'il ne matche pas)
#    expressions.txt :
#    C:\Users\souhe\coderain==>C:\Users\<USER>\coderain

# 3. Purge (réécrit TOUS les commits contenant le motif, change les hash)
git filter-repo --replace-text expressions.txt

# 4. Après validation locale : push forcé (coordination requise, personne d'autre ne doit
#    avoir de clone en cours) + toute personne avec un clone existant doit re-cloner.
git push origin --force --all
git push origin --force --tags
```

**Recommandation** : vu la sévérité faible (pas un secret, juste un nom d'utilisateur Windows) et le coût d'une réécriture d'historique (hash changés, re-clone obligatoire pour quiconque a un clone), un **correctif en avant** (nouveau commit qui paramètre le chemin, ex. variable d'env `CORPUS_MODULES_DIR` ou chemin relatif au repo) est probablement suffisant et beaucoup moins risqué que la purge. La purge `filter-repo` ne devient vraiment utile que si le dépôt passe en **public** un jour ET que Souhel juge le nom d'utilisateur Windows gênant à laisser dans l'historique — arbitrage `I-1623` point 3, pas tranché ici.

## Ce que ça change pour la suite

- **Aucun geste destructif nécessaire pour rendre le dépôt sûr côté secrets/matériau** — le seul point ouvert est cosmétique (chemins perso), et forward-fixable sans réécriture d'historique.

---

# Point (b) — Proposition de destination pour le matériau (sans déplacer)

*Le matériau (`corpus-modules/`, 21 Mo, 1805 fichiers : PDF source, texte extrait page par page, 19 cartes JPEG, partition `pconv3`) n'a jamais été dans git — il vit uniquement sur ce poste (`C:\Users\souhe\coderain\corpus-modules\`), gitignoré. **Aujourd'hui, aucune copie de sauvegarde n'existe en dehors de ce poste** : contrairement à l'invariant de sauvegarde `D-224` (« tout est gardé sous GitHub ou Obsidian Sync »), ce dossier n'est ni sous GitHub ni sous Obsidian Sync. C'est le vrai risque à couvrir — pas une fuite, une absence de sauvegarde.*

## Option A — Repo GitHub privé dédié (`materiau`, ou nom équivalent)

- **Pour** : versionné (historique des extractions, diff propre si le corpus évolue), sauvegarde automatique dès le premier push, accès simple en clone depuis n'importe quel poste, cohérent avec l'invariant `D-224` (« tout est gardé sous GitHub ») sans changer d'outil.
- **Contre** : un dépôt git n'est pas fait pour 19 JPEG + un PDF (pas de diff utile sur binaire, gonfle vite si le corpus grossit) ; nécessite de créer et gérer un repo privé de plus (permissions, `gh` déjà en place le rend trivial à créer).
- **Effort** : minime — `gh repo create materiau --private`, un `git init` local dans une copie de `corpus-modules/`, un commit, un push.

## Option B — Vault Obsidian (`C:\Vaults\MVP2\...`)

- **Pour** : déjà synchronisé (Obsidian Sync), déjà l'endroit où vit le reste du matériau de campagne narratif (fiches, décisions) — cohérence éditoriale avec le reste du projet.
- **Contre** : le vault est un espace de notes Markdown, pas taillé pour 21 Mo de PDF/JPEG/texte brut extrait à la page ; risque de alourdir la sync Obsidian sur tous les postes qui montent le vault ; contredit l'invariant socle `D-224` cité au brief lui-même (« le code vit sous git, jamais dans le vault ») — même si ce n'est pas du code, le principe de séparation des outils par nature de contenu s'applique probablement aussi ici.

## Recommandation

**Option A (repo GitHub privé dédié)**, pour deux raisons : (1) c'est un contenu qui *appartient* techniquement au pipeline de conversion (corpus source du convertisseur `coderain`), pas au journal narratif du vault — plus proche en nature du code que des notes ; (2) ça referme le vrai trou trouvé par l'audit : aucune sauvegarde actuelle. Un repo privé, même sans usage git sophistiqué, suffit à combler ça immédiatement une fois `gh` en place.

**Ce point reste un arbitrage Souhel** (`I-1623`) — rien n'a été déplacé, créé, ni committé pour cette section.
