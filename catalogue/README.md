# CATALOGUE DE MODULES — la TROISIÈME base ([I-193](https://github.com/souhelmeskache/ttrpg-mvp))

Trois bases, pas deux :

| base | remplie par | consommée par |
|---|---|---|
| bibliothèque de LORE | copiste | documentaliste, en séance |
| PARTITION | adaptateur | Director, en séance |
| 🆕 **CATALOGUE** | copiste | **Auteur**, entre deux aventures |

Le catalogue sert `D-123` §2 : les pistes dérivées du fil rouge biographique vont chercher
ici **le module suivant**. Il décrit des modules NON JOUÉS — c'est une base froide, remplie
**à froid, une fois, par module**, et c'est ce qui rend l'ingestion sélective possible :
**on ne paye l'adaptateur que sur le module choisi.**

## Qui écrit, comment

- **Le COPISTE seul** (`D-095`/`D-096`) : survol du module publié, **transcription et
  rangement sans jugement**. Écrire une entrée demande d'avoir LU le module — au moins en survol.
- Une entrée = un fichier = un module. Aucun journal de modification dans une entrée :
  elle se remplit une fois ; seul `statut` bascule à l'ingestion
  (`non-ingere` → `partition-existante`), tous les autres champs gèlent.

## Emplacement et cloisonnement

```
catalogue/univers-<nom>/module-<slug>.md
```

Indexation **PAR UNIVERS** (`D-122` §4) : une entrée n'existe que dans son univers ; toute
recherche documentaliste est scopée à UN univers ; la couverture se mesure PAR univers
(un chiffre agrégé sur deux univers ne pilote rien).

## LE SCHÉMA D'ENTRÉE

```markdown
## <slug> {#<slug>}
univers: <planescape|...>
themes: [<registres du fil rouge servis>]
personnage_sert: <ce qu'elle demande/offre à un protagoniste>
echelle: <mini|module|mini-campagne>
puissance_attendue: <plage>
statut: non-ingere | partition-existante
ancre_source: <référence PDF/bibliothèque>
```

Règles par champ :

- **univers** — cloisonnant ; identique au dossier parent `univers-<nom>`.
- **themes** — les **registres biographiques** du fil rouge que l'aventure sert, PAS un résumé
  d'intrigue. Liste de tokens `kebab-case`, ≥ 1.
- **personnage_sert** — ce que l'aventure **demande** à un protagoniste et ce qu'elle lui **offre**
  (forme conseillée : « demande … ; offre … »).
- **echelle** — `mini` | `module` | `mini-campagne`. Dimensionnement strict nécessaire (`D-076`);
  quel que soit le choix, l'étage reste AVENTURE (`D-122` §2).
- **puissance_attendue** — plage de niveaux telle que publiée.
- **statut** — `non-ingere` | `partition-existante` (le cas réel de round-trip : voir
  `univers-planescape/module-beyond-the-vale-of-madness.md`).
- **ancre_source** — référence dans la bibliothèque locale du poste (PDF), ou mention `FIXTURE`
  explicite pour les exemples. Jamais de contenu transcrit.

## LE VALIDEUR DE FORME (mécanique)

Une entrée passe si et seulement si :

1. Chemin exact `catalogue/univers-<nom>/module-<slug>.md`, slug `kebab-case` ASCII.
2. Exactement **un** bloc d'entrée par fichier, titré `## <slug> {#<slug>}`, où ancre = slug =
   nom de fichier sans `module-`/`.md`.
3. Les 7 champs présents, **dans l'ordre du schéma**, une ligne chacun, tous renseignés.
4. Champ `univers` = `<nom>` du dossier parent.
5. `themes` : liste crochets, ≥ 1 token `kebab-case`.
6. `echelle` ∈ {mini, module, mini-campagne}.
7. `statut` ∈ {non-ingere, partition-existante}.
8. `puissance_attendue` porte une plage explicite.
9. `ancre_source` pointe la bibliothèque locale **ou** porte la mention `FIXTURE`.
10. ⛔ Aucun contenu de module transcrit : pas de texte de scénario, bloc de stats, PNJ nommé
    ni solution — **métadonnées seules**. Les exemples sont factices.
11. Un commentaire HTML d'en-tête est autorisé AVANT le bloc ; rien après.

## LA RECHERCHE DOCUMENTALISTE PAR THÈME

Même primitive que la bibliothèque (`D-113`) : la recherche porte sur **la fonction/thèmes,
pas sur le NOM**. Requête = `(univers, thèmes)` → candidats classés, rendus ainsi :

> **Requête** : `univers=mornelune · themes=[origine-cachee]`
>
> **Sortie de lecture** — 2 candidat(s) :
> 1. `loraison-des-racines-mortes` — module, niveaux 5–7, non-ingéré
>    themes : origine-cachee, identite-contestee, pacte-des-aieux
>    sert : demande un protagoniste au passé scellé par autrui ; offre la confrontation
>    avec ce que les aïeux ont contracté à sa place
> 2. `le-bal-des-cendres` — mini-campagne, niveaux 8–10, non-ingéré
>    themes : masque-social, reputation-perdue, serment-brise
>    sert : (secondaire — correspondance partielle sur l'identité contestée)

**Cas vide = signal, pas silence** (`I-191`/`I-193` : le taux d'échec ici est le **troisième
signal**, ventilé par base ET par univers) :

> **Requête** : `univers=planescape · themes=[serment-brise]` → **0 candidat**
> ⇒ ticket d'échec portant sa **marche** (catalogue) et son **univers** — il alimente la mesure
> de couverture de CET univers et oriente le prochain batch copiste.

## ⛔ GARDES

- **Étanchéité (`D-109`, non négociable)** : le catalogue décrit des modules non joués, donc du
  matériau de campagne à venir — il **ne se lit JAMAIS depuis `meta-rpg/`**. Sa conception se fait
  en FORME ; son contenu vit au poste TECHNIQUE.
- Tout exemple embarqué ici est **factice** (univers fictif `mornelune`, ancres `FIXTURE`).
- **Hors périmètre** : le remplissage réel de la librairie (batch copiste futur) · toute
  modification du convertisseur · la lecture du catalogue depuis `meta-rpg/`.
