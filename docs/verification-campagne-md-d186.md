# Vérification d'implantation — campagne.md contre D-186

*Lane #47 (I-372a). Phase de VÉRIFICATION : chaque verdict ci-dessous est
ancré dans le code (chemin + ligne + extrait), zéro spéculation. Aucun ecart
trivial n'a été trouvé à corriger — voir « Corrections triviales » en fin de
document.*

Portée du code inspecté : [`coderain/campagne.py`](../coderain/campagne.py)
(le module lui-même), [`coderain/memory.py`](../coderain/memory.py) (parseur
d'entrées réutilisé), [`coderain/author.py`](../coderain/author.py),
[`coderain/context.py`](../coderain/context.py), `coderain/converter/*`
(l'Adaptateur), `mcp_server.py`, `webui.py`, `coderain/config.py`, et une
recherche plein-texte `campagne` sur tout le dépôt pour écarter tout site
d'écriture ou de lecture non évident.

## 1. Champs — `ambition_finale`

**CONFORME.** Chaîne markdown libre, champ de tête du fichier, distincte des
entrées `fil_rouge`.

- Modèle : [`coderain/campagne.py:73`](../coderain/campagne.py#L73)
  `ambition_finale: str = ""` sur `@dataclass Campagne`.
- Lecture : [`coderain/campagne.py:83-88`](../coderain/campagne.py#L83-L88)
  — seule la première ligne `ambition_finale: ...` du préambule (avant la
  première entrée) est retenue ; le reste du préambule est ignoré, cohérent
  avec « fixe, révisée rarement, écrite UNE FOIS ».
- Écriture : [`coderain/campagne.py:109`](../coderain/campagne.py#L109)
  `out.append(f"ambition_finale: {camp.ambition_finale.strip()}")`.
- `validate()` exige sa présence :
  [`coderain/campagne.py:173-174`](../coderain/campagne.py#L173-L174)
  `if not camp.ambition_finale.strip(): errors.append("ambition_finale absente")`.

## 2. Champs — entrées `fil_rouge`

### 2.1 `id`

**CONFORME.**
- Champ : [`coderain/campagne.py:53`](../coderain/campagne.py#L53).
- Format slug imposé par `_ID_RE`
  ([`coderain/campagne.py:38`](../coderain/campagne.py#L38)) et vérifié par
  `validate()` ([`coderain/campagne.py:177-178`](../coderain/campagne.py#L177-L178)) ;
  unicité vérifiée lignes
  [179-181](../coderain/campagne.py#L179-L181).
- Le titre de section EST l'id (pas de champ « titre » distinct) — cohérent
  avec la structure attendue (« titre markdown de niveau 2 avec ancre
  d'id »), voir §4.

### 2.2 `registre` (monde | interieur)

**CONFORME.**
- `REGISTRES = ("monde", "interieur")` —
  [`coderain/campagne.py:32`](../coderain/campagne.py#L32) — exactement les
  deux registres de la spec, jamais un troisième.
- Extraction : [`coderain/campagne.py:93`](../coderain/campagne.py#L93).
- Validation : [`coderain/campagne.py:182-183`](../coderain/campagne.py#L182-L183)
  rejette toute valeur hors `REGISTRES`.

### 2.3 `fait_md`

**CONFORME** pour la forme (UN fait, pas une liste, pas de synthèse imposée
structurellement) ; **hors périmètre de cette lane** pour le contenu réel
(borne de la mission : « ne pas créer de contenu de campagne »).
- Champ : [`coderain/campagne.py:55`](../coderain/campagne.py#L55) — c'est le
  corps markdown de l'entrée (`e.body`), pas un attribut d'en-tête :
  [`coderain/campagne.py:96`](../coderain/campagne.py#L96).
- Le module ne peut pas mécaniquement distinguer « un fait » d'« une
  synthèse » (c'est un jugement d'Auteur, pas une forme) — `validate()` ne
  vérifie que la non-vacuité :
  [`coderain/campagne.py:184-185`](../coderain/campagne.py#L184-L185).
  Ce n'est **pas un écart** : D-186 place cette distinction du côté de
  l'Auteur, pas du valideur de forme.

### 2.4 `ancre_source`

**CONFORME.**
- Champ : [`coderain/campagne.py:56`](../coderain/campagne.py#L56).
- Validation de présence :
  [`coderain/campagne.py:186-187`](../coderain/campagne.py#L186-L187).
- Format libre (« référence tour/scène/état ») — le code ne contraint pas la
  syntaxe, cohérent avec la spec qui ne fixe pas un format unique (les
  fixtures de test emploient `T3-4`, `scene-fixture-a`, `etat:fixture-x` —
  [`tests/campagne_test.py:32-43`](../tests/campagne_test.py#L32-L43)).

### 2.5 `porte`

**CONFORME**, y compris la clause « ou signalée ».
- Champ : [`coderain/campagne.py:57`](../coderain/campagne.py#L57), liste de
  tokens.
- Grammaire des trois formes (record_id / flag:nom / quete_etat:id:etat) :
  `_PORTE_RE` — [`coderain/campagne.py:40-43`](../coderain/campagne.py#L40-L43).
- Résolution contre le save connu, ou acceptation si le token est dans
  `signales` (l'amendement « connus du save ou signalés ») :
  `_porte_cible` — [`coderain/campagne.py:143-159`](../coderain/campagne.py#L143-L159),
  branché dans `validate()` lignes
  [190-196](../coderain/campagne.py#L190-L196).
- Testé côté forme mal formée, cible inconnue et cible signalée :
  [`tests/campagne_test.py:96-117`](../tests/campagne_test.py#L96-L117).

### 2.6 `statut` (actif | promu | scelle)

**CONFORME.**
- `STATUTS = ("actif", "promu", "scelle")` —
  [`coderain/campagne.py:33`](../coderain/campagne.py#L33).
- Défaut à `"actif"` si absent au chargement (comportement raisonnable, non
  contredit par la spec) :
  [`coderain/campagne.py:94`](../coderain/campagne.py#L94)
  `statut = e.attrs.pop("statut", "").strip() or "actif"`.
- Validation de la valeur : [`coderain/campagne.py:188-189`](../coderain/campagne.py#L188-L189).
- Transition contrôlée par `set_statut()` (n'accepte que les statuts connus,
  ne fait rien sur id absent) :
  [`coderain/campagne.py:131-140`](../coderain/campagne.py#L131-L140).

### 2.7 `aventure_debut` (optionnel, amendement du 23/08)

**CONFORME.**
- Non modélisé comme champ dataclass dédié mais comme clé libre dans
  `attrs` (le même mécanisme générique qui porte toute extension future de
  l'en-tête) — accès typé via la méthode
  `aventure_debut()` : [`coderain/campagne.py:61-68`](../coderain/campagne.py#L61-L68).
  C'est un choix d'implémentation, pas un écart : le champ existe, round-trippe
  (§4) et est exposé.
- Absence ⇒ âge incalculable, listé comme tel (pas une erreur) : `rapport()`
  alimente `anciennete_inconnue` quand `aventure_debut()` retourne `None` —
  [`coderain/campagne.py:212-214`](../coderain/campagne.py#L212-L214), testé
  en [`tests/campagne_test.py:125-126`](../tests/campagne_test.py#L125-L126)
  (`fil-essai-trois`, sans `aventure_debut`, atterrit dans
  `anciennete_inconnue`).
- Aucun code ne le remplit automatiquement — voir Règle 1 : aucun site
  d'écriture n'existe du tout hors de l'Auteur humain (pas de calcul auto de
  cette valeur nulle part dans le dépôt).

## 3. Règle 1 — ÉCRIVAINS (l'Auteur écrit, les compteurs lisent)

**CONFORME pour la moitié négative de la règle ; ÉCART STRUCTUREL sur la
moitié positive — rapporté, pas tranché (hors périmètre de cette lane).**

Recherche plein-texte `campagne` sur tout le dépôt (hors ce rapport, les
tests et la documentation de conception) : les seules occurrences dans du
code exécutable sont dans `coderain/campagne.py` lui-même et un commentaire
non fonctionnel dans `coderain/author.py:13` (« même esprit que campagne.py »,
un module sans rapport — détecteur de répétition inter-scénarios, I-229).

- **Le fold n'écrit jamais dans campagne.md** — CONFORME. Le module de fold
  vit dans `coderain/memory.py` (`_fold_end`, `_filter_folds_after`,
  `_reconcile_fold_state` — lignes 2210, 2216, 2232) ; aucune de ces
  fonctions ni aucune autre partie de `memory.py` ne mentionne `campagne` ni
  n'importe `coderain.campagne`.
- **L'Adaptateur n'écrit jamais dans campagne.md** — CONFORME. Recherche sur
  les 14 fichiers de `coderain/converter/` (`convert.py`, `emit.py`,
  `directeur.py`, `projection.py`, etc.) : zéro occurrence de `campagne`.
- **L'Auteur écrit** — ÉCART STRUCTUREL non trivial. Aucun code de
  production n'appelle jamais `campagne.save_file()` ni `campagne.render()`
  écrit dans un fichier réel : les seuls appelants de ces fonctions dans tout
  le dépôt sont `tests/campagne_test.py` (round-trip de test, fichier
  temporaire). Il n'existe :
  - aucune constante de chemin pour `campagne.md` dans
    `coderain/config.py` (à comparer à `corpus_dir()`/`saves_dir()` qui
    existent pour le corpus) ;
  - aucun outil MCP dans `mcp_server.py` exposant `fil_rouge`,
    `ambition_finale` ou une opération d'écriture de campagne (recherche
    `campagne|fil_rouge|ambition_finale` sur ce fichier : une seule
    occurrence, sans rapport — un commentaire de prompt narrateur ligne
    1300-1301 parlant de « la campagne » au sens courant) ;
  - aucune commande CLI/webui équivalente.

  `campagne.py` est une bibliothèque de format complète (parseur, rendu,
  valideur, rapport) mais **non câblée** : rien dans le dépôt ne joue
  aujourd'hui le rôle de « l'Auteur qui écrit ». Le docstring du module lui-
  même le qualifie de « D-186, candidate »
  ([`coderain/campagne.py:1`](../coderain/campagne.py#L1)), cohérent avec ce
  constat : la brique est prête à être branchée, mais le geste d'écriture
  humaine (ou l'outil qui le sert) n'existe pas encore dans le code. Ceci
  n'est pas une violation de la règle négative (rien n'y écrit qui ne
  devrait pas), mais c'est un écart structurel par rapport à l'attendu
  complet de D-186 — **rapporté, pas tranché**, conformément au périmètre de
  cette lane.

## 4. Règle 2 — CHARGEMENT (rappelable hors tour, jamais en contexte de tour)

**CONFORME.**

- `coderain/context.py` (assemblage de contexte servi au narrateur) : zéro
  occurrence de `campagne` — vérifié par recherche plein-texte ciblée sur ce
  fichier.
- Recherche plein-texte `campagne` sur tout le dépôt : les seuls fichiers de
  code touchés sont `coderain/campagne.py` (le module lui-même),
  `coderain/author.py` (commentaire non fonctionnel, cf. §3) et les tests.
  Aucun assemblage de prompt/contexte (narrateur, Director de tour) ne lit
  ni n'importe `coderain.campagne`.
- Corollaire direct du constat de la Règle 1 (§3) : puisque rien n'écrit
  encore dans `campagne.md` en production, rien ne peut non plus le charger
  en tour par accident — le respect de cette règle est aujourd'hui garanti
  par l'absence totale de câblage, pas par un garde-fou actif dédié. À noter
  pour la suite (si l'écriture est câblée un jour, un garde explicite
  empêchant l'inclusion en contexte de tour devra être ajouté et testé, pas
  seulement supposé par omission).

## 5. Règle 3 — FORMAT (à la manière du moteur, round-trippable, pas de front-matter YAML)

**CONFORME.**

- Le module réutilise explicitement le parseur d'entrées partagé du moteur
  plutôt que d'inventer un format : commentaire et import —
  [`coderain/campagne.py:45-48`](../coderain/campagne.py#L45-L48)
  (« Reuses the registry parser so campagne.md round-trips exactly like
  every other md file the engine reads/writes »), `from .memory import
  Entry, parse_entries`.
- `parse_entries()` reconnaît des sections `## Titre {#slug}` avec bloc
  d'attributs `clé: valeur` puis corps markdown —
  [`coderain/memory.py:384-425`](../coderain/memory.py#L384-L425). C'est la
  même convention que le reste du moteur (mémoire, timeline, etc.).
- `render()` produit exactement ce format, sans front-matter YAML :
  [`coderain/campagne.py:107-124`](../coderain/campagne.py#L107-L124) —
  titre de niveau 2 avec ancre d'id (`## {id}  {#{id}}`, ligne 112),
  attributs de tête (`registre`, `statut`, `ancre_source`, puis toute clé
  libre dont `aventure_debut`, puis `porte`), une ligne vide, puis le corps
  (`fait_md`).
- Round-trip vérifié par test, y compris via fichier réel sur disque (pas
  seulement en mémoire) :
  [`tests/campagne_test.py:53-65`](../tests/campagne_test.py#L53-L65)
  (`render` → `load` → égalité champ à champ, puis `save_file` → `load_file`
  → égalité des entrées).
- Aucune trace de front-matter YAML dans `render()`/`load()` — le fichier
  commence directement par `# campagne` puis `ambition_finale: ...`.

## 6. Règle 4 — ARCHIVAGE (statut `scelle`, jamais supprimé)

**CONFORME.**

- `set_statut()` ne fait que muter `f.statut` sur l'entrée trouvée par id —
  aucun chemin de suppression d'entrée n'existe dans tout le module (aucune
  fonction `remove`/`delete`/`purge` dans `coderain/campagne.py`) :
  [`coderain/campagne.py:131-140`](../coderain/campagne.py#L131-L140).
- `render()` itère `camp.fil_rouge` sans filtre de statut
  ([`coderain/campagne.py:111`](../coderain/campagne.py#L111)) : une entrée
  `promu` ou `scelle` est écrite au même titre qu'une entrée `actif`.
- Testé explicitement (« trace biographique ») :
  [`tests/campagne_test.py:132-145`](../tests/campagne_test.py#L132-L145) —
  après `set_statut(..., "promu")` et `set_statut(..., "scelle")` puis un
  cycle `render`/`load`, le nombre d'entrées est inchangé et les statuts
  sont préservés.

## 7. Règle 5 — pas d'enchaînement d'aventures ni de cap stocké

**CONFORME.**

- Aucun champ `cap`, `enchainement`, `aventures_totales` ou équivalent dans
  `FilRouge`/`Campagne` (recherche sur les deux dataclasses,
  [`coderain/campagne.py:51-77`](../coderain/campagne.py#L51-L77)) ni dans le
  format rendu.
- `rapport()` calcule l'ancienneté à partir d'un paramètre **externe**
  `aventure_actuelle` passé par l'appelant à chaque appel
  ([`coderain/campagne.py:200-201`](../coderain/campagne.py#L200-L201)) — ce
  nombre n'est jamais lu depuis ni écrit dans `campagne.md` ; seul
  `aventure_debut` (par entrée, optionnel, posé par l'Auteur — §2.7) est
  persisté. L'enchaînement se dérive bien à la lecture, il ne se stocke
  pas.

## Corrections triviales

Aucune. La revue champ par champ (§1-§2) et règle par règle (§3-§7) n'a
trouvé aucun écart de nommage, aucun statut manquant dans le modèle, aucune
divergence corrigeable en petite PR. Le seul écart identifié (§3, Règle 1 —
absence de tout site d'écriture réel côté Auteur) est structurel par nature :
il ne se corrige pas en renommant un champ, il exige une décision de
conception (quel outil/geste sert l'écriture) qui dépasse le périmètre de
vérification de cette lane. Aucun code n'a donc été modifié — la suite de
tests était déjà verte avant cette vérification et reste verte après
(`python run_tests.py`, aucun fichier de production touché).
