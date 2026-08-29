# AUDIT 2 — LE MATÉRIEL DE CAMPAGNE AU-DELÀ DU MODULE — D-252 (2026-08-29)

*Rapport de la lane Issue #65 (registre méta MRPG-D-252, volet audit). Question
posée : la Partition sait-elle accueillir ce qui n'apparaît QUE dans une
campagne longue publiée ? Suite de l'audit du matin
([audit-completude-buckets-d249.md](audit-completude-buckets-d249.md)) qui
couvrait le matériel d'un MODULE. Audit seul — aucune modification de
production, aucun matériau réel ouvert (typologie construite depuis la
structure générique des campagnes D&D publiées : arcs multi-chapitres, fronts,
downtime, bases, factions, domaines, voyages — connaissance générale
uniquement). Critère d'inclusion : D-141 « est-ce que ça change en jeu ? »
(`coderain/converter/buckets.py:16-26`).*

---

## 1. Le socle relu et la ligne de partage qui gouverne cet audit

Les 11 primitives + étage aventure sont celles de l'audit-1 §1 (liste ancrée,
inchangée depuis) : Manifest, Node, Record ×5 classes, RollTable, Secret,
Patch, Evenement+Aventure, Tension, Ressource, Personnage, Fenetre
(`coderain/converter/schemas.py:141-796`). Tous les dossiers de buckets
existent dans toute partition émise, même vides (`coderain/converter/emit.py:74-75`)
— la grille « système complet » D-249 est acquise par construction.

Deux faits de forme, décisifs pour le format campagne, cadrent tout ce qui
suit :

1. **Les étages `arc`/`univers` sont BANNIS de la Partition** — seuls
   `scene/scenario/adventure` portent du contenu de module
   (`coderain/converter/schemas.py:16-18`, D-122 + retour méta 2026-08-22).
   L'inter-module n'est donc pas une forme manquante : il est EXCLU par
   décision. Ce qui traverse les modules vit dans le **régime de
   re-scripting** : `campagne.md` (D-186, `coderain/campagne.py:1-25` — « la
   couche qu'aucun module ne porte jamais », ambition_finale + fils rouges à
   `porte` record/flag/quete_etat `coderain/campagne.py:40-43`), `toile.md`
   (D-241, `coderain/toile.py:1-33` — secrets dévoilés module après module,
   réadaptation qui « ajoute des fils ou fait progresser leur état, jamais ne
   réécrit » `coderain/toile.py:26-29`), et `Patch` (D-132, mutation adressée
   `coderain/converter/schemas.py:604-610`).
2. **État évolutif ⊥ matière ingérée** (l'attention particulière demandée par
   l'Issue) : la Partition ingère la MATIÈRE (l'échelle de rangs, la table de
   prix, le statblock initial) ; l'ÉTAT COURANT (le rang atteint, le prix
   négocié, les PV restants) est du côté moteur/save/re-scripting — `persistent`
   pour ce qui survit aux frontières de combat
   (`coderain/converter/schemas.py:336-353`), `porte` de campagne.md pour ce
   qui survit aux frontières de module. Chaque verdict ci-dessous dit de quel
   côté tombe chaque moitié du matériel.

**Grille acquise D-252** : les 4 extensions actées (documents typés,
objets magiques, classe `sort`, tables à mode consultation — audit-1
§3.1-3.4, [audit-completude-buckets-d249.md](audit-completude-buckets-d249.md):102-139)
sont considérées EXISTANTES pour les verdicts, conformément à l'Issue — en
notant qu'elles ne sont pas encore implémentées (`RESSOURCE_TYPES` encore
`("carte",)` `schemas.py:30` ; `RECORD_CLASSES` sans `sort` `schemas.py:20`).

## 2. Inventaire du matériel de campagne × couverture × verdict

Verdicts : **COUVERT** (primitive directe), **COMPOSITION** (assemblage de
primitives + régime de re-scripting existants), **TROU** (avec localisation
Partition vs régime, proposition §3), **HORS-PARTITION** (justifié D-141).

### A. Arc long et méta-intrigue

| # | matériel | couverture | verdict |
|---|---|---|---|
| 1 | Vilain d'ensemble / méta-intrigue multi-actes (l'agenda qui traverse tous les chapitres) | par module : `transverse` fonction/charge/agenda/portee du Record `schemas.py:268-276` + `Tension` menace/horloge `schemas.py:25,400-435` + `Aventure.trajectoire` ; inter-module : étage banni `schemas.py:16-18` ⇒ `ambition_finale` + fils rouges `campagne.py:8,73` et fils de toile `toile.py:20-29` posés/avancés à chaque réadaptation | **COMPOSITION** (Partition par module + régime pour la traversée) |
| 2 | Fronts et menaces qui progressent SEULS si personne n'intervient | c'est la définition même de `Aventure.trajectoire` : « ce qui s'enchaîne si personne n'intervient, chaque événement déclarant CE QUI LE PERTURBE » `schemas.py:697-698` ; déclencheurs `delai/etat/date` `schemas.py:36,107` ; garde anti-rail `transplantee/abandonnee` `schemas.py:108-110` | **COUVERT** (à l'échelle du module joué ; l'échéance qui court ENTRE modules → ligne 23) |
| 3 | Structure en actes, flowchart de campagne, concordance des chapitres | nodes `chapitre` `schemas.py:15` + `debouches` D-118 (PAR QUOI on peut y aller, `prerequis_etat`) `schemas.py:77-91` + trajectoire | **COMPOSITION** |
| 4 | Épilogues conditionnels, fins de campagne multiples | `charniere_sortie` D-123 « jamais une fin » `schemas.py:194` + `Aventure.charniere_md` `schemas.py:699` + debouches conditionnels | **COUVERT** |
| 5 | Raccords « si les PJ ont fait X au chapitre précédent » | `heritage` (gel du bruit de branche, critère D-183) `schemas.py:94-104` + `prerequis_etat` `schemas.py:40-74` + fils rouges campagne.md (fait + `ancre_source` + `porte`) | **COMPOSITION** — c'est le cœur assumé du régime de re-scripting |

### B. Temps long

| # | matériel | couverture | verdict |
|---|---|---|---|
| 6 | Chronologie évolutive, événements datés à l'échelle campagne | déclencheur type `date` existe `schemas.py:36,107,642-644` ; rubrique `condition` = échéances/lois « sans limite spatiale » `schemas.py:698` ; la date COURANTE du monde est un état moteur/save (D-141), pas une donnée de Partition | **COUVERT** (forme) — `valeur` est une chaîne libre, aucun calendrier canonique imposé : convention de conversion, pas trou de forme |
| 7 | Événements calendaires récurrents (festivals, marées, cycles) | `Evenement(once=False)` `schemas.py:630,670` + déclencheur `date` | **COUVERT** |
| 8 | Downtime (artisanat, recherche, entraînement, commerce entre aventures) | les RÈGLES d'activité = précédent E5 « instructions globales du scénario installé » [ingestion-dks-analyse.md](ingestion-dks-analyse.md):88, côté moteur ; la MATIÈRE piochable (tables d'activités, complications, prix) = `RollTable` `schemas.py:356-377` + tables à mode consultation (grille acquise §3.4 audit-1) ; le RÉSULTAT (l'objet forgé, le contact gagné) = état évolutif → `porte` flag/record de campagne.md `campagne.py:40-43` | **COMPOSITION** |

### C. Possessions, statut, intendance

| # | matériel | couverture | verdict |
|---|---|---|---|
| 9 | Base du groupe (repaire, navire, forteresse) et son évolution | matière : record `lieu` (description, `habitants`, `pieges_md`) [annexe-a-stats-5e.md](annexe-a-stats-5e.md):204-238 + `Ressource` carte `schemas.py:438-486` + objets destructibles annexe A §3 ; évolution (aménagements, équipage) : `Patch` D-132 `schemas.py:604-610` + fil rouge campagne.md portant le record | **COMPOSITION** |
| 10 | Réputation/statut par faction, rangs dans une organisation | matière : record `faction` (`membres`, `posture_envers_joueur`) [annexe-a-stats-5e.md](annexe-a-stats-5e.md):243-279 + échelle de rangs/seuils/avantages = table à mode consultation (grille acquise) ; état courant (le rang atteint, le score de renom) : évolutif → flag `porte` campagne.md + `Patch` sur la posture | **COMPOSITION** — la posture enum 4 valeurs (annexe A t2) est l'état INITIAL ingéré, sa granularité fine vit dans l'échelle consultable + les flags |
| 11 | Domaines et intendance (terres, revenus, subordonnés) | matière : `lieu` + `faction` (subordonnés = `membres`) + tables de revenus/coûts en mode consultation (grille acquise) ; règles de gestion = E5 moteur ; état (trésorerie, loyauté) = évolutif re-scripting | **COMPOSITION** |
| 12 | Artefacts/objets légendaires à évolution (paliers, éveil) | extension objets magiques acquise (rarete/attunement/effets_md/charges, audit-1 §3.2) + `persistent` pour l'état qui survit `schemas.py:336-353` + `Patch` pour le passage de palier | **COMPOSITION** |

### D. Voyages et géographie

| # | matériel | couverture | verdict |
|---|---|---|---|
| 13 | Voyages au long cours (navigation, rythme, provisions) | règles de voyage/ravitaillement = E5 moteur ; rencontres par région = `RollTable` (pioche moteur `coderain/converter/aval.py:116`) ; distances/temps/prix de passage = tables mode consultation (grille acquise) | **COMPOSITION** |
| 14 | Gazetteer régional, chapitres d'atlas | nodes `chapitre/section` + records `lieu` + `Ressource` carte (poste uniquement D-217) | **COUVERT** |
| 15 | Tables de rencontres par région et par palier | `RollTable` `schemas.py:356-377`, une table par région/palier — moteur ET matière (audit-1 ligne 8) | **COUVERT** |
| 16 | Météo, hasards de route | `RollTable` idem | **COUVERT** |

### E. PNJ récurrents et monde vivant

| # | matériel | couverture | verdict |
|---|---|---|---|
| 17 | PNJ récurrents transversaux (alliés, rivaux, patrons) et leur agenda longue durée | par module : record `pnj` + `transverse` agenda/portee + `fonctions_aval` (« evenements qui dépendent de lui — perte détectable ») `schemas.py:268-276` ; traversée : fil rouge campagne.md `porte: <record_id>` + fils de toile rattachés | **COMPOSITION** — l'identité inter-partitions du MÊME PNJ repose sur une convention de slug non gardée → ligne 24 |
| 18 | Agenda de faction qui évolue entre les modules | `transverse.agenda` (matière) + `Evenement` conditions + réadaptation (patchs, nouveaux fils) — jamais réécriture d'un fil posé `toile.py:26-29` | **COMPOSITION** |
| 19 | Compagnons/sidekicks qui progressent avec le groupe | record `pnj` (sous-ensemble creature, annexe A §2) + `persistent`/`Patch` pour l'état durable ; règles de progression sidekick = E5 moteur | **COMPOSITION** |

### F. Économie et annexes de campagne

| # | matériel | couverture | verdict |
|---|---|---|---|
| 20 | Économie de campagne (prix régionaux, ressources rares, marchés) | tables à mode consultation (grille acquise §3.4) + records `objet` ; fluctuation en jeu = état évolutif moteur/flags | **COUVERT** (par la grille acquise) |
| 21 | Handouts d'échelle campagne (lettres du vilain, journal feuilletonné sur plusieurs chapitres) | documents typés (grille acquise §3.1) ; la re-remise dans un module ultérieur = réadaptation (le fichier vit au poste, D-217) | **COUVERT** (par la grille acquise) |
| 22 | Appendices monstres/objets/sorts de fin de campagne | audit-1 lignes 3, 19, 20 : `creature`+`ancre_srd`, extension objet magique, classe `sort` (grille acquise) | **COUVERT** |

### G. Ce qui traverse les modules — les deux verdicts restants

| # | matériel | couverture | verdict |
|---|---|---|---|
| 23 | Échéance/front daté TRANS-modules (posé au module N, échéant au module N+k : « dans 30 jours l'armée atteint la capitale ») | la Partition du module N porte l'`Evenement` `condition` ; mais AUCUN porteur persistant entre modules : campagne.md refuse tout futur stocké (Règle 5 D-186, [verification-campagne-md-d186.md](verification-campagne-md-d186.md):243-257 ; jalons passé/intention seuls `schemas.py:31-34,527-533`), la toile ne porte que des secrets conditionnels `toile.py:11-18`, et rien n'oblige la réadaptation à re-porter les `condition` non échues | **TROU — dans le RÉGIME de re-scripting, pas dans la Partition** → §3.1 |
| 24 | Identité persistante d'une entité récurrente à travers les partitions successives (le vilain du module 1 = celui du module 3) | chaque partition a SES records ; `porte` de campagne.md cite un record_id « connu du save ou signalé » (`campagne.py:40-43`, [verification-campagne-md-d186.md](verification-campagne-md-d186.md):85-97) mais aucune garde ne vérifie qu'une réadaptation réutilise le même slug | **TROU mineur — dans le RÉGIME**, → §3.2 |

### H. Hors-Partition

| # | matériel | couverture | verdict |
|---|---|---|---|
| 25 | Progression par jalons de campagne (« les PJ atteignent le niveau 5 à la fin de l'acte 1 ») | la feuille de personnage et sa progression sont côté moteur/scénario installé (précédent E5, [ingestion-dks-analyse.md](ingestion-dks-analyse.md):88) ; la destinée `Personnage` porte l'arc biographique, jamais les niveaux `schemas.py:489-546` | **HORS-PARTITION** (E5, cohérent D-141 : c'est le moteur qui monte le niveau, pas une donnée piochable) |
| 26 | Sous-systèmes optionnels campagne-spécifiques (folie, corruption, soif, poursuite navale) | déjà tranché audit-1 ligne 21 (E5) — la règle vit côté moteur, la Partition porte la matière (tables, seuils consultables) | **HORS-PARTITION** (rappel, non recompté ici) → compté ligne 25 seule |

## 3. Les deux trous — tous deux côté régime, aucun côté Partition

Constat central, symétrique de l'audit-1 : **aucune ligne de l'inventaire
campagne n'exige une primitive neuve, ni même une extension de primitive
au-delà des 4 déjà actées D-252.** Les deux trous restants sont dans le régime
de re-scripting (ce que la réadaptation doit garantir entre deux modules), pas
dans les formes. Chacun est un acte méta, rien n'est implémenté ici.

### 3.1 Le re-portage des échéances non échues (ligne 23)

Le monde qui avance seul est couvert DANS un module (`Aventure.trajectoire`/
`conditions`) ; entre deux modules, l'échéance vivante n'a pas de registre :
campagne.md est verrouillée contre le futur par conception (Règle 5 D-186 —
c'est une force, pas un défaut à défaire), la toile porte des secrets, pas des
fronts. Proposition, du plus léger au plus lourd : **(a)** acter une règle de
réadaptation « toute `condition`/`trajectoire` non échue et non caduque du
module précédent est ré-émise dans la partition suivante » — pure discipline
de passe, zéro forme nouvelle, vérifiable par un garde de réadaptation ;
**(b)** si le cas réel montre que (a) ne suffit pas (échéance qui court
pendant PLUSIEURS modules sans re-conversion), un registre d'échéances côté
Auteur, même convention d'entrées que campagne.md/toile.md (`parse_entries`,
`coderain/toile.py:52-54`), jamais chargé en contexte de tour. Recommandation :
(a) d'abord, (b) sur cas réel seulement.

### 3.2 La convention d'identité inter-modules (ligne 24)

Un PNJ/faction récurrent doit garder le MÊME slug de record d'une partition à
la suivante pour que les fils (`porte` campagne.md, `rattachement` toile) le
suivent. Aujourd'hui c'est une convention tacite. Proposition : la consigner
comme règle de réadaptation (« une entité déjà portée par un fil rouge
conserve son id ») + garde de forme au moment de la réadaptation (tout
`porte`/`rattachement` de type record_id doit résoudre dans la nouvelle
partition ou être signalé — le mécanisme « connus du save ou signalés »
existe déjà, `coderain/campagne.py:143-159`). Zéro extension de schéma.

## 4. Verdict d'ensemble

| compte | valeur |
|---|---|
| lignes d'inventaire | **26** (dont ligne 26 = rappel audit-1, non recomptée) |
| lignes comptées | **25** |
| couvertes (COUVERT + COMPOSITION) | **22** (10 COUVERT + 12 COMPOSITION) |
| trous | **2** (lignes 23, 24) — tous deux dans le RÉGIME de re-scripting, **zéro dans la Partition** |
| hors-Partition justifiées D-141 | **1** (ligne 25) |
| nouvelle primitive nécessaire | **0** |
| extension de primitive nécessaire au-delà des 4 actées D-252 | **0** |

Réponse au cadre de Souhel (« dépasser un module solo-RPG, aller sur du
véritable matériel de campagne ») : **oui, la Partition tient l'échelle
campagne** — parce que la ligne de partage D-122/D-141 est déjà tracée du bon
côté : la matière de campagne se décompose en matière de modules (formes
existantes + 4 extensions actées), et TOUT ce qui traverse les modules relève
du régime campagne.md/toile.md/Patch/réadaptation, où les deux seuls trous
identifiés sont des règles de passe à acter (§3.1-3.2), pas des formes à
créer. La grille acquise D-252 reste à implémenter (`schemas.py:20,30`), et
les propositions §3 sont des actes méta distincts.
