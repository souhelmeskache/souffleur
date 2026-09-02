# Fixture de banc : personnage (I-257)

`bench/fixtures/personnage-banc.py <chemin-du-save> [--profil guerrier] [--force]`
installe un personnage synthétique de niveau 1 (100% inventé, D-109) dans un
save existant — `player.md`, `items.md` (une arme + une armure équipées) et
`state.json` écrits de façon cohérente, dans le vocabulaire que lit le moteur
(`derived_combat`). Ce n'est **pas** un éditeur de save (I-226) ni la brique
de création de personnage (#102, qui reste le vrai chemin) : un script
rejouable, idempotent, qui refuse d'écraser un `player.md` déjà occupé sauf
`--force`.

Rejeu : `python bench/fixtures/personnage-banc.py saves/<mon-save>`.
