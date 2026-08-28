# Garde d'agentivité — provenance des influences scénario (I-462)

*Périmètre de la lane Issue #8 : `coderain/validator.py` (le garde),
`coderain/summarizer.py` (le marquage, à la source du pipeline de fold —
ajouté à ce périmètre parce qu'un garde de provenance est sans objet tant que
rien n'écrit la provenance), `schemas/validator-provenance.json` (la forme du
rapport), `tests/test-garde-agentivite-i462.py` (le harnais). L'Issue citait
`converter/validator.py` et `schemas/emitter.json` ; le premier n'existe pas
tel quel (le garde réel de l'analogue I-159 vit déjà dans
`coderain/validator.py`, voir `docs/gabarit-autorat-secrets-i159.md`) et le
second est un schéma du pipeline de conversion statique (SPEC-P4 §8,
partition PDF → nodes/records), sans rapport avec le fold runtime — on a donc
suivi le même schéma de substitution que I-159 : un nouveau fichier
`schemas/validator-provenance.json`, symétrique de
`schemas/validator-secrets.json`.*

## La règle

**Toute entrée écrite par le fold dans un registre géré
(`characters.md`, `locations.md`, `factions.md`, `items.md`,
`canon-events.md`, `threads.md`) porte un attribut `origin` parmi
`player` / `narrator` / `inferred`.**

```markdown
## Elira la Voilée  {#elira-la-voilee}
origin: narrator

A avoué en secret avoir empoisonné le puits.
```

- `player` : le tour du JOUEUR déclare, exige ou effectue explicitement
  l'action qui rend ceci vrai.
- `narrator` : un tour NARRATEUR/PNJ l'énonce ou le révèle sans qu'aucune
  action du joueur ne l'ait exigé.
- `inferred` : ni l'un ni l'autre ne le dit noir sur blanc — le modèle déduit
  une conséquence implicite.

## Pourquoi

Le banc fold-arc a mesuré le symptôme : une action EXIGÉE par le joueur
redevient, après compression, une révélation SPONTANÉE d'un PNJ — la
provenance se perd, sans rien pour l'attraper.

Le mécanisme exact : `MemoryStore.turns()` (`coderain/memory.py`) conserve
bien un `role` par tour (player/narrator, `_render_turn`/`turns()`), mais
`Summarizer._turns_text` (`coderain/summarizer.py`) aplatit ces tours en
prose `[PLAYER]`/`[NARRATOR]` pour le prompt du fold — c'est la SEULE trace
de rôle dans tout le pipeline. Le JSON que le modèle renvoie
(`SCENE_INSTRUCTION` : `promotions`, `new_threads`, `resolved_threads`,
`facts`, `state_changes`) n'a jamais eu de champ pour la restituer, et
`_apply_promotions` écrivait les `Entry` (`status`, `when`,
`relationships`) sans jamais rien retenir de qui — joueur ou PNJ — est à
l'origine du fait. Une fois l'entrée réécrite (`merge_entry(..., rewrite=True)`
remplace le corps en entier), l'acteur d'origine est irrécupérable : rien en
aval ne peut plus distinguer un fait forcé par le joueur d'une invention
narrative du modèle.

## Ce qui détecte la violation aujourd'hui

- **`Summarizer._apply_promotions`** (`coderain/summarizer.py`) stampe
  désormais `attrs["origin"]` sur chaque promotion et chaque nouveau thread,
  et `attrs["resolved_origin"]` sur chaque thread résolu (clé distincte : qui
  ferme un thread n'est pas forcément qui l'a ouvert). `SCENE_INSTRUCTION`
  exige ce champ du modèle et explique les trois valeurs. Une valeur absente
  ou hors énumération dégrade silencieusement vers `"inferred"`
  (`_origin()`) — jamais un rejet de la promotion : un fold partiel ou mal
  formé doit toujours avancer (docstring du module), il perd seulement le
  droit de revendiquer une origine qu'il n'a pas vue.
- **`coderain.validator.scan_missing_origin(store)`** — la fonction pure qui
  scanne les registres gérés + `threads.md` et retourne un rapport structuré
  `{registry, slug}` par entrée dont `origin` est absent ou invalide (forme
  documentée dans
  [`schemas/validator-provenance.json`](../schemas/validator-provenance.json)).
  Comme `scan_hidden_forced`, elle ne renvoie jamais le titre ni le corps.
- **`tests/test-garde-agentivite-i462.py`** exerce le marquage bout en bout
  (fixtures synthétiques de fold JSON en entrée de `_apply_promotions`, puis
  `scan_missing_origin` sur le store résultant) et le garde seul sur des
  entrées écrites à la main (D-109 : aucun matériau de campagne réel).

## Ce que la garde ne fait pas

C'est un **avertissement de présence/validité**, pas une vérification de
véracité : `scan_missing_origin` confirme qu'un `origin` existe et vaut l'une
des trois valeurs — elle ne peut pas savoir si le modèle a menti (un `player`
halluciné n'est pas attrapé). C'est aussi une garde ponctuelle, pas encore
branchée à un appelant runtime comme `mcp_server._lore_warnings` le fait pour
I-159 — le brancher reste à faire, hors périmètre de cette lane.

La vraie garde de non-contradiction D-107 — vérifier qu'une entrée marquée
`origin: player` correspond réellement à un tour joueur validé dans
l'historique des enveloppes (`coderain/validator.validate`, les deltas
`reveal`/`event_fired` appliqués tour par tour) — demande de corréler la
sortie du fold avec l'historique tour-par-tour, ce qui reste un travail
distinct. Cette garde pose la précondition structurelle indispensable :
la provenance traverse maintenant le fold au lieu d'être silencieusement
perdue ; une vérification croisée future peut s'appuyer dessus.
