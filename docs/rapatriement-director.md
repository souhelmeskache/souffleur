# Rapatriement Director — patch conversation B + inventaire poste MJ (Issue #81)

*Rapport expurgé : aucun extrait de fiction, aucun nom propre de campagne.
Chaque phrase ci-dessous doit rester vraie indépendamment de la campagne
jouée.*

## 1. Patch appliqué

La cible confirmée pour « `director.md` » (diagnostic de l'Issue #15) est la
constante `DIRECTOR_SYS` dans `coderain/modules/trinity.py` — le prompt
système du Logic Agent (Director) du pipeline Quad. Le texte de patch du
commentaire TERMINÉ de l'Issue #15 (protocole des 4 fenêtres, D-219 ; jalons
de destinée acquis, D-220 ; garde négociable/non-négociable ; garde
zéro-identifiant-technique) y a été inséré comme paragraphe statique, avant
la ligne `Return ONLY a JSON object:` — l'encapsulage suivi est celui suggéré
par la note de diagnostic du patch pour une constante `%`-formatée : aucun
caractère `%` littéral dans le texte inséré, formatage vérifié pour les deux
queues de schéma (monde / RPG).

La variante « injection conditionnelle uniquement quand une conversation B
est active » (préférence énoncée par le patch) suppose un câblage d'état
séparé (remontée de `ConversationB.is_done`/`current_window` jusqu'au
contexte du Director) explicitement signalé par le patch lui-même comme hors
périmètre de son texte. Non fait ici, pour rester dans le périmètre de ce
patch — reste un geste de câblage disponible pour une session ultérieure.

**Tests** : un nouveau fichier de non-régression vérifie (a) la présence du
bloc et l'intégrité du formatage `%` pour les deux queues de schéma, (b) la
séparation structurelle Director/Writer déjà garantie par le pipeline (le
Writer ne reçoit jamais `DIRECTOR_SYS`, donc jamais le vocabulaire
négociable/non-négociable par cette voie), (c) un tour bout-en-bout avec
Director et Writer simulés. Suite complète rejouée (`python run_tests.py`) :
verte, aucune régression.

## 2. Inventaire du dossier vault indiqué par Souhel (poste MJ)

Lecture seule stricte appliquée — aucune écriture, aucune suppression.
Recherche ciblée sur les fichiers de dispositif (instructions, prompts,
protocoles), fiction et matériau de campagne strictement ignorés.

Un sous-agent nommé « director » existe dans ce dossier (fichier
d'instructions dédié, plus une copie archivée antérieure à sa dernière
modification). Il coexiste avec quatre autres sous-agents de dispositif
(recherche de faits en mémoire, dérivation de conséquences probables, résumé
de repli mémoire, narration) et trois fichiers de procédure de tour de jeu,
plus un fichier de configuration MCP pointant vers un serveur qui expose le
moteur de ce dépôt comme outils.

Comptage : 1 fichier d'instructions Director courant + 1 version archivée
(diff consulté) ; 4 fichiers de sous-agents adjacents ; 3 fichiers de
procédure de tour ; 1 fichier de style de sortie narrative (non retenu comme
matériau Director — hors périmètre du point 2) ; 1 fichier de configuration
MCP. Aucun autre fichier de dispositif touchant au Director trouvé à la
racine ni ailleurs sous ce dossier.

## 3. Confrontation au patch appliqué et verdict

**Recherche de recouvrement direct** : aucune occurrence du protocole des
4 fenêtres, de D-219, ni du vocabulaire négociable/non-négociable au sens du
patch, dans l'ensemble du dispositif inventorié au point 2 (les seules
occurrences textuelles de mots voisins — « négociable », « fenêtre » — s'y
emploient en un tout autre sens, sans rapport avec la conversation d'accord).
**Conclusion sur ce point précis : pas de divergence, pas de fusion à
faire** — le patch du point 1 n'a pas de contrepartie à réconcilier dans le
dispositif inventorié.

**Divergence structurelle trouvée, hors du périmètre direct du patch** : le
dispositif Director inventorié au point 2 décrit un mode d'exécution
différent de celui du pipeline patché. Le Director de ce dépôt (pipeline
Quad, `DIRECTOR_SYS`) est un unique appel à un modèle qui doit renvoyer
STRICTEMENT un objet JSON conforme à un schéma fixe — aucun appel d'outil,
aucune écriture de fichier, aucune délégation. Le Director inventorié décrit
au contraire un agent interactif qui appelle directement les outils du
moteur exposés en MCP, écrit un fichier de briefing sur disque, et délègue à
plusieurs sous-agents — un mode opératoire construit pour une séance jouée en
direct plutôt que pour le pipeline automatisé de ce dépôt.

Ce dispositif contient des principes plus riches sur un sujet voisin mais
distinct de celui du patch (sélection et dosage du matériau de mémoire
transmis en aval) — un sujet que ce dépôt traite déjà par un mécanisme
différent (assemblage déterministe, côté code, documenté en tête du fichier
patché), pas par jugement d'agent au tour le tour. Une transposition littérale
du texte inventorié dans `DIRECTOR_SYS` produirait des instructions
incohérentes avec ce que cette constante peut effectivement produire (appels
d'outils et écritures de fichier qu'un simple appel JSON ne peut pas exécuter).

**Verdict** : aucune fusion forcée effectuée. Le contenu inventorié n'est pas
un texte « plus riche » du même objet que `DIRECTOR_SYS` — c'est un dispositif
d'un autre mode d'exécution, construit sur le même moteur. La question de
savoir si (et comment) ce second mode mérite une représentation dans ce dépôt
dépasse le périmètre d'arbitrage de cette lane ; posée en commentaire d'Issue
pour arbitrage, en termes génériques.

## 4. Portée de ce rapport

Les originaux du dossier vault n'ont subi aucune modification ni suppression
(lecture seule stricte respectée du début à la fin). Aucun élément d'intrigue,
aucun nom propre de campagne, aucun extrait de fiction ne figure dans ce
document — seules des formes de dispositif (types de fichiers, comptages,
mécanismes) y sont décrites.
