# BENCH — I-150 : grain de prose, modèle frontière vs référence D-079

*Protocole de mesure à coût quasi nul pour le poste narrateur (Writer),
voir [`docs/cadrage-puissance-i150.md`](../docs/cadrage-puissance-i150.md)
pour le cadrage complet. Statut : **PROTOCOLE PRÊT — EXÉCUTION MANUELLE NON
FAITE** (aucun appel modèle n'est joué par ce fichier ni par la CI).*

## Objectif

Déterminer si, sur le poste Writer (`WRITER_RULES`, `coderain/templates.py`),
un modèle « frontière » au sens de `coderain/models.py` (entrées notées
« frontier prose » dans `BYO_ALTERNATIVES`, ex. Claude Sonnet 5) produit un
grain de prose perceptiblement distinct du modèle actuellement retenu comme
référence de prose par D-079 — à un coût d'exécution quasi nul.

## Portée et garde D-109

Tous les prompts et scènes de ce bench sont **100 % synthétiques** (D-109) :
aucun matériau de campagne réel, aucune fixture tirée de `ttrpg-corpus`. Les
situations ci-dessous sont génériques, réutilisables sans droit d'auteur ni
confidentialité.

## Protocole

1. **Échantillon resserré** — 3 prompts fixes, mêmes pour chaque modèle
   comparé (voir § Prompts). Trois est le minimum qui couvre les trois
   registres où `WRITER_RULES` fixe des attentes explicites : action/sensoriel,
   dialogue/personnage, transition/continuité.
2. **Modèles comparés** — exactement deux par run :
   - **Référence** : le modèle retenu par D-079 pour le poste Writer (à
     renseigner par la personne qui exécute le bench — non fixé dans ce
     fichier, dépend du profil actif au moment du run).
   - **Candidat frontière** : un modèle listé « frontier prose » dans
     `coderain/models.py::BYO_ALTERNATIVES` (ex. Claude Sonnet 5) ou l'un des
     `RECOMMENDED_DEFAULTS`.
3. **Même contexte injecté** — les deux appels reçoivent le même
   `WRITER_RULES`, la même fiche de prémisse synthétique, le même historique
   court (voir § Prompts). Seul le modèle change.
4. **Mesure** — pour chaque paire de réponses (référence / candidat), noter
   dans le tableau § Résultats :
   - respect des règles de `WRITER_RULES` (voix 2e personne présent, montrer
     plutôt que résumer, longueur ~2-4 paragraphes, fin sur un beat) ;
   - grain distinct perçu (Oui/Non/Marginal) et en une phrase, en quoi ;
   - coût mesuré (appels + caractères entrée/sortie, à la `TokenMeter`,
     I-145) — pas d'estimation, le chiffre réel du run.
5. **Verdict** — après les 3 paires, une ligne de synthèse : le grain
   observé justifie-t-il, à ce coût, de rouvrir la lecture ouverte du poste
   narrateur (cf cadrage §2) ? Ce verdict alimente l'arbitrage méta/vault,
   il ne le remplace pas.

## Prompts (100 % synthétiques, D-109)

1. **Action/sensoriel** — « Le personnage force la porte rouillée d'un
   entrepôt abandonné sous la pluie. » (attend : détail sensoriel concret,
   pas de résumé.)
2. **Dialogue/personnage** — « Un garde marchand refuse de laisser passer le
   groupe sans un mot de passe qu'ils n'ont pas. » (attend : le monde réagit,
   sans décider à la place du joueur.)
3. **Transition/continuité** — « Le groupe revient au village trois jours
   après avoir vaincu le loup qui terrorisait les fermes. » (attend :
   cohérence avec un fait antérieur donné, sans contradiction.)

## Résultats

*(à remplir lors de l'exécution manuelle — vide tant que le run n'a pas eu
lieu ; une ligne par prompt)*

| # prompt | modèle référence (D-079) | modèle candidat frontière | grain distinct ? | note | coût (appels / caractères) |
|---|---|---|---|---|---|
| 1 | — | — | — | — | — |
| 2 | — | — | — | — | — |
| 3 | — | — | — | — | — |

**Verdict global** : *(non exécuté)*
