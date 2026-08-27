# Doigte -- verrou central : decomposition en sous-sujets

*Specification de conception -- lane I-056, fil rouge transverse I-023.
Sources : [D-089](../../meta-rpg/registre-decisions/D89-les-trois-regimes-de-jet.md) (trois regimes de jet),
[D-101](../../meta-rpg/registre-decisions/D101-le-doigte-aux-modeles-la-comptabilite-au-code.md) (doigte aux modeles, comptabilite au code),
[D-218](../../meta-rpg/registre-decisions/D218-les-codes-de-tension-traversent-analyse-adaptation-auteur.md) (codes de tension traversants).
Zero materiau de campagne (D-109).*

## Strategie

**Decomposer en sous-sujets, resolution LOCALE lieu par lieu en contournements empilables.**
Pas de solution centrale unique : des petites solutions partielles cumulees, chacun
de ses criteres operatoires propres, chacun son ancrage dans une decision actee.

Ancrage transverse I-023 : chaque cycle de conception declare sa contribution au
doigte (la justesse de dosage entre plans/registres/axes). Ce document est la
premiere decomposition operatoire ; il est reutilisable par l'Auteur (I-232) et
l'Adaptateur.

## Les 4 sous-sujets

### 1. Pas de cote -- echange de monnaie entre axes

**Critere operatoire :** tout ajustement de dosage sur un axe (ton, thematique, enjeu)
exige un ajustement compensatoire sur au moins un autre axe. Le doigte n'est pas un
curseur unique mais un socle decompose ton X thematique X enjeu, ou chaque deplacement
se paie.

**Source :** D-101 -- le doigte est aux modeles (le socle decompose est un modele),
la comptabilite au code (l'echange est trace par des compteurs, pas juge par un agent).

**Exemple local (D-089) :** la table des 12 facteurs des trois regimes de jet
(SILENCIEUX / OPAQUE / TRANSPARENT) est un pas de cote applique au regime de
visibilite. Deplacer le regime (TRANSPARENT vers SILENCIEUX) sur l'axe verification
exige un ajustement compensatoire sur l'axe dramaturgie (position dans la courbe
de tension) et sur l'axe fonction mecanique (veto anti-railroad). Chaque facteur
de la table est un axe graduable ; le regime est la resultante, pas une case.

### 2. Caprice d'auteur -- audace reglee avec droit a l'echec

**Critere operatoire :** l'auteur a droit a l'audace (ecart volontaire par rapport
au socle), mais cet ecart est regi par une regle explicite : il est PAYE par la
solidite du socle. Un caprice qui ne s'appuie pas sur un socle solide est un defaut ;
un caprice qui s'appuie sur un socle auditable est du doigte.

**Source :** D-101 -- une question de jugement se repond par un modele (le socle),
pas par un compteur. Le caprice est un ecart modele, pas une derive compteur.

**Exemple local (D-089) :** le choix situationnel du regime (Souhel a explicitement
rejete la regle categorielle « un type d'action = un regime ») est un caprice d'auteur
regle. Le regime se decide sur des raisons independantes du secret (verification et
effet dramatique), mais la combinaison concrete est un jugement -- paye par la table
des 12 facteurs qui rend le jugement auditable a posteriori.

### 3. Cap vivant -- le doigte change avec l'arc

**Critere operatoire :** le regime applicable a une meme action change au fil de la
campagne, parce que le personnage change. Le doigte n'est pas un parametrage fixe
mais un etat du personnage a un instant de son arc.

**Source :** D-218 -- les codes de tension traversent toute la chaine (analyse,
adaptation, Auteur). Le cap vivant est la consequence directe : si les codes de
tension sont les memes du module a la partition a l'Auteur, alors l'etat du
personnage (qui determine le regime) est un code de tension comme les autres --
il traverse.

**Exemple local (D-089) :** le facteur 4 de la table (maitrise de soi a ce point
de l'arc) est decisif et variable dans le temps. Le regime est un enonce sur le
personnage (« tu n'as pas encore le controle de ton corps »), donc il change pour
une meme action au fil de la campagne. La perception passive reste SILENCIEUX,
mais la raison pour laquelle elle l'est peut migrer de l'incompetence vers la
discretion choisie.

### 4. Pont qui reoutille a froid

**Critere operatoire :** une erreur de doigte se corrige sans toucher au code.
Les regles sont lisibles et auditable (le voyant explicable), jamais un jugement
libre du planificateur a chaque occurrence. Le pont entre le modele et le code
permet de recalibrer les seuils UNE fois, a froid, sans redeployer.

**Source :** D-101 -- le gestionnaire d'interruption est du code, pas un agent.
Un compteur coute zero token et zero latence : c'est le seul organe qu'on peut
multiplier sans arbitrage budgetaire. Le pont est le contrat entre le compteur
(qui presente) et le modele (qui decide).

**Exemple local (D-089) :** le code est trivial (`_echo_checks(events)` est un
point d'affichage unique, un filtre partiel existe deja). Ce qui est complexe
c'est le choix du regime -- c'est-a-dire le doigte. Une erreur de regime se
corrige en modifiant la table des facteurs (le modele), pas le filtre (le code).
C'est D-046 : « le doigte relocalise, reduit a sa plus petite surface -- caler
3-4 seuils UNE fois, a froid ».

## Contribution au fil rouge I-023

Cette decomposition est la premiere contribution operatoire de la lane I-056 au
fil rouge transverse I-023. Chaque sous-sujet porte son critere, sa source, et
un exemple local recoupe sur D-089 (trois regimes de jet). Le dispositif est
reutilisable : l'Auteur (I-232) consomme les 4 sous-sujets comme contrat de
dosage, l'Adaptateur les consomme comme contrat de validation.

## Gardes

- **D-109 (la lecon, jamais le cas) :** ce document ne contient aucun materiau
  de campagne. Les exemples sont tous tires de D-089 (decision generique), jamais
  d'une campagne concrete. Test de transmissibilite : la phrase reste-t-elle vraie
  si on change de campagne ? Oui ==> generique, elle traverse.
- **D-101 (doigte aux modeles, comptabilite au code) :** aucun des 4 sous-sujets
  ne propose un compteur pour juger. Chaque sous-sujet est un modele (jugement)
  dont la comptabilite (trace) est du code.
- **D-218 (codes de tension traversants) :** les 4 sous-sujets sont coherents
  avec les 6 codes de tension (menace, horloge, echeance, cout, choix, revelation).
  Le cap vivant (sous-sujet 3) est le sous-sujet qui les relie au personnage.
