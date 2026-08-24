# AUDIT — paquet `dnd5e-engine` (réserve (a) de la veille SRD)

*Lane `audit-dnd5e-engine`, 2026-08-24 · fiche [FICHE-audit-dnd5e-engine-2026-08-24](../../Vaults/MVP2/Migration%20Coderain/FICHE-audit-dnd5e-engine-2026-08-24.md) · périmètre P1 tenu : ce fichier uniquement · zéro code écrit dans le dépôt · installation d'inspection en venv jetable hors dépôt (`%TEMP%\opencode\dnd5e-audit\venv`, supprimable sans trace).*

**La question unique** : *ce paquet est-il fiable et conforme à ses déclarations — peut-on envisager de le brancher au dispositif ?*

## Verdict : **intégrable sous conditions**

Moteur réel, zéro I/O prouvé statiquement ET dynamiquement, interface async exactement conforme à sa documentation, corpus 2024 massif et correctement attribué. Les conditions (§5) tiennent au profil du projet (jeune, bus factor 1) et aux obligations CC-BY-4.0 — pas à des défauts du code.

---

## 1. Provenance

| Mesure | Résultat |
|---|---|
| Éditeur déclaré | « Tapestria contributors », MIT © 2026 |
| Compte PyPI propriétaire | `tapestria.quest`, rôle **Owner unique** (API JSON `ownership.roles`) |
| Dépôt source | **https://github.com/tapestria/nat20** — PUBLIC, 94 commits, branche `main`, tag `v0.3.0` |

**Comment le dépôt a été trouvé** (la veille SRD concluait « aucun dépôt public identifiable depuis PyPI » — c'est corrigé, avec la méthode) :

1. Métadonnées PyPI 0.3.0 : `author`, `home_page`, `project_urls` — **aucun lien dépôt** (c'est ce qui avait piégé la veille) ;
2. Page PyPI du fichier (wheel + sdist 0.3.0) : les deux portent des **attestations de provenance PEP 740 / Sigstore** (Trusted Publishing OIDC) nommant le workflow éditeur `.github/workflows/release.yml` du dépôt `github.com/tapestria/nat20`, permalink commit `24c607a17ab196ea5115f9208601e77a1489a3bf`, tag `refs/tags/v0.3.0`, entrées de transparence Sigstore 2414661299/2414661311 ;
3. Concordance croisée : README PyPI = README nat20 (liens relatifs `../dnd5e-srd-data`, layout `packages/dnd5e-*` retrouvés tels quels dans le dépôt) ; site tapestria.quest (« Nat20 is the deterministic rules oracle behind tapestria.quest ») ; org GitHub `tapestria` ne contient que ce dépôt. La chaîne est fermée, pas devinée.

**Hygiène des releases** : 5 versions en ~6 semaines (0.1.0 27/06 → 0.1.1 27/06 → 0.1.2 26/07 → 0.2.0 04/08 → 0.3.0 10/08/2026), chacune wheel + sdist ; pas de signature GPG (`has_sig: false`, standard actuel) mais **attestations in-toto signées Sigstore** sur chaque artefact = chaîne d'approvisionnement vérifiable ; upload `twine/7.0.0` via Trusted Publishing (pas de jeton long-vivant) ; `vulnerabilities: []` sur PyPI. **Absents** : CHANGELOG.md formel (BACKLOG.md + tags seulement), page « Releases » GitHub vide au scraping. Recherche documentée : recherche web `"dnd5e-engine" OR "tapestria.quest"` (8 résultats, tous concordants), aucune autre occurrence d'un tiers.

**Risque fournisseur résiduel** : projet jeune (1 star, 0 fork, 1 maintainer = bus factor 1), 0.x — l'API peut bouger sans préavis.

## 2. Chaîne de dépendances

Arbre **réellement installé** (pip 26.1.2, venv jetable, Python 3.14.6 — fonctionne aussi bien que sur 3.12/3.13 déclarés) :

| Paquet | Version | Licence | Dépôt déclaré | Note |
|---|---|---|---|---|
| dnd5e-engine | 0.3.0 | MIT (LICENSE+NOTICE embarqués) | github.com/tapestria/nat20 | objet de l'audit |
| dnd5e-srd-data | 0.3.0 | **CC-BY-4.0** (LICENSE+NOTICE) | idem (workspace uv) | données seules |
| d20 | 1.1.2 | MIT | github.com/avrae/formaldice | déjà jugée saine (veille) ✔ re-confirmée sur place |
| lark-parser | 0.9.0 | MIT | github.com/erezsh/lark | imposée par d20 |
| cachetools | 7.1.7 | MIT | github.com/tkem/cachetools | |
| pydantic | 2.13.4 | MIT | github.com/pydantic/pydantic | |
| pydantic_core | 2.46.4 | MIT | idem | seul binaire natif (Rust) |
| annotated-types | 0.8.0 | MIT | github.com/annotated-types | |
| typing_extensions | 4.16.0 | PSF-2.0 | github.com/python/typing_extensions | |
| typing-inspection | 0.4.4 | MIT | github.com/pydantic/typing-inspection | |

11 maillons runtime (+ dev extras non installés : pytest/ruff/mypy/bandit). **Toutes licences permissives**, compatibles usage interne comme redistribution. Aucune dépendance réseau, aucun téléchargement post-install. Poids : moteur 1,37 Mo (56 modules .py, `orchestrator.py` 4 977 lignes), corpus 10,8 Mo.

## 3. Code vs déclarations

Déclarations testées : *« host-agnostic, zero I/O… no network, no DB »*, interface async `start_combat` / `submit_player_intent` / `advance_monster_turn` / `resolve_check`.

**Statique** (grep sur les sources livrées des deux paquets) :
- motifs `urllib | httpx | aiohttp | requests | socket | subprocess | os.system | popen | telemetr | posthog | sentry | eval( | exec(` ;
- `dnd5e_srd_data` : **0 hit** ; `dnd5e_engine` : **3 hits, tous bénins** — commentaire ligne 4 d'`orchestrator.py` (le routeur session/websocket est explicitement le travail de l'hôte, pas du moteur), mot anglais « requests » dans un commentaire ligne 3757, et `ast.literal_eval` (parsing sûr de littéraux, pas d'exécution de code) dans `rules/_parsing.py:33`. **Aucun import réseau, aucune télémétrie, aucun subprocess.**

**Dynamique** (combat complet exécuté sous garde : `connect`/`connect_ex`/`create_connection`/`getaddrinfo`/`gethostbyname` interceptés, loopback seul toléré pour l'IPC interne d'asyncio) :
```
start_combat → handle + 2 événements d'ouverture
submit_player_intent(move)   OK
submit_player_intent(attack, weapon_id="longsword")  OK  ← arme résolue depuis le corpus typé
submit_player_intent(pass)   OK
advance_monster_turn         OK   (refus propre IntentRejectedError:not_actor_turn si appelé hors tour)
end_combat                   OK   (ended_reason)
narration_events             12 événements itérés
resolve_check(skill athletics dc12) → nat 3, mod 2, échec — déterministe
TENTATIVES RÉSEAU CAPTÉES : 0    exit 0
```
Exécution locale pure, **zéro I/O réseau à l'exécution, zéro télémétrie** — les déclarations sont exactes.

**Interface async** : signatures relevées par introspection, conformes à la doc au mot (keyword-only sur `start_combat`, retour `StartCombatResult`/`None`/`EndCombatResult`/`CheckResult`, `narration_events` async-iterator). Écart cosmétique relevé : `__version__` dans `__init__.py` dit « 0.2.0 » pour une distribution 0.3.0.

## 4. Corpus 2024 livré (`dnd5e-srd-data` 0.3.0)

**Volume mesuré** : 1 545 fichiers JSON canoniques, 10,6 Mo —

| Dossier | Fichiers | Octets |
|---|---|---|
| items | 546 | 2 420 471 |
| monsters | 341 | 5 172 829 |
| spells | 339 | 1 778 009 |
| features | 260 | 824 584 |
| species | 14 | 83 215 |
| feats | 17 | 25 907 |
| classes | 12 | 231 988 |
| subclasses | 12 | 65 327 |
| backgrounds | 4 | 11 253 |

**Qualité constatée** : schémas pydantic typés embarqués (`schema/*.py`, `py.typed` présent des deux côtés) ; une entrée prise au hasard du flux (`longsword`) résout bout-en-bout par le moteur (preuve fonctionnelle §3) ; granularity par entité (un JSON par créature/sort/objet, dragons anciens ~40 Ko chacun = fiches complètes). Couverture SRD 2024 crédible (341 monstres, 339 sorts).

**Obligations d'attribution CC-BY-4.0** — texte NOTICE complet embarqué dans les DEUX distributions (`*.dist-info/licenses/{LICENSE,NOTICE}`), chaîne explicite :
> Original source: System Reference Document 5.1 and 5.2 by Wizards of the Coast LLC, CC-BY-4.0 · Portions derived from the Foundry VTT dnd5e system (CC-BY-4.0) · Cross-checked against open5e (CC-BY-4.0) et 5e-bits/5e-database (MIT).

⇒ **Si nous redistribuons le corpus (ou un dérivé), nous devons reproduire cette attribution** ; code moteur MIT ⇒ conserver LICENSE+NOTICE. Rien d'insurmontable, mais c'est une obligation réelle à graver dans la future intégration.

## 5. Verdict motivé + conditions

**Intégrable sous conditions** — mesures portées aux §1-4. Conditions avant tout branchement (nouvelle décision requise selon la fiche, hors périmètre ici) :

1. **Épinglage strict** `dnd5e-engine==0.3.0` (+ transitive `==` vérifiée) avec le sha256 PyPI du wheel (`7d817eac…7efc14ff`) — impose par la jeunesse du projet (bus factor 1, 0.x).
2. **Attribution CC-BY-4.0 portée chez nous** (texte NOTICE repris dans notre dépôt/doc) dès qu'on redistribue ou expose le corpus — obligation de licence, non négociable.
3. **Veille de releases** légère (rythme actuel ≈ 2/mois) et point d'attention API avant chaque montée de version tant que < 1.0.

Non-bloquants, à noter au dossier : `__version__` dérivé (0.2.0 vs 0.3.0) ; pas de CHANGELOG formel ; lark-parser restée à 0.9.0 par l'écosystème avrae/d20 (connue saine) ; Python 3.14 local non listé dans les classifiers mais pleinement fonctionnel (mesuré).

---

### Budget

Plafond 150 000 tokens — **consommation estimée ≈ 95 000 tokens** (recherche web PyPI/GitHub + inspection venv + tests dynamiques), sous le plafond.

### Clôture de fil

Commit sur branche `audit-dnd5e-engine` AVANT rapport (hash communiqué dans le message de lane) · rien à merger côté lane (self-merge non applicable, P3) · push origin effectué pour miroir · auto-nettoyage P4 en dernier geste (`git worktree remove` + suppression de branche locale, la branche distante porte le commit).
