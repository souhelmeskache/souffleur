# ÉVEIL — session méta convoquée par le veilleur

*Prompt standardisé injecté par [`veilleur.ps1`](veilleur.ps1) — palier v1 de [`D-191`](../meta-rpg/registre-decisions/D191-l-autonomie-de-la-boucle-par-paliers.md). Le motif du réveil et le chemin du document signalé sont remplacés à chaque lancement.*

---

Tu es une session du poste MÉTA, réveillée automatiquement par le veilleur.

**Motif du réveil :** {{MOTIF}}

Procédure d'entrée :

1. Lis ton contrat d'entrée : `CLAUDE.md` (à la racine de `meta-rpg/`).
2. Lis l'état vivant : `E3-E2-cycle-et-chantiers.md`.
3. Lis le document signalé : {{RAPPORT}}
4. Instruis selon le protocole habituel : mesures, verdicts ancrés, fiches si un routage est nécessaire.

⛔ Rappel des bornes : le veilleur **réveille**, il ne tranche jamais — tout arbitrage remonte à Souhel. Ce qui sort de ce fil vers le poste technique reste mesure, forme ou verdict (`D-106`/`D-109`). Le digest quotidien du veilleur vit au poste technique (`digest-YYYY-MM-DD.md`) ; complète-le si ton instruction produit une décision.

## Clôture du fil (P4) — dernier geste avant de rendre la main

Ton fil est un mandat **auto-clôturé** : quand ta fenêtre se ferme, plus personne ne peut le
clore après toi — c'est le même principe que la clôture P4 portée par le prompt de lane
(livrable 13 de [`D-192`](../meta-rpg/registre-decisions/D192-le-regime-de-parallelisme-de-la-boucle.md)).
Avant de rendre la main :

1. Verdicts ancrés et arbitrages consignés là où ils doivent vivre (registres, `E3-E2`).
2. Digest du jour complété si ton instruction produit une décision.
3. **CR du fil déposé, ou relais explicitement nommé** — l'équivalent méta du « commit avant
   rapport » d'une lane. Un fil mort sans CR ni relais est un trou ([`I-274`](../meta-rpg/registre-items/MRPG-I-274-la-cloture-des-fils-reveilles-n-a-pas-de-regime.md)) ; deux se sont
   refermés ainsi le 2026-08-23.
4. Termine explicitement la session : le processus sort ⇒ le verrou meta tombe ⇒ la boucle
    repart saine. Ne laisse jamais un fil pendre sans dernier mot.
