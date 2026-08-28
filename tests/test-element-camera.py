"""Test d'élément — la caméra (I-382, premier exemplaire du MOULE).

Brique visée : la caméra du Director (D-184) — `Store.assemble` /
`Store.lookup` (coderain/memory.py) via `mcp_server._assemble_text`, qui
décide ce que le joueur perçoit d'un fait du monde. Voir
`tests/fixtures/element_mold.py` pour la doctrine du moule et
`README-moule-test-element.md` pour le gabarit de déclinaison.

Fixtures d'états (matériau 100% synthétique, D-109/D-206 — aucun contenu de
module réel) :
  1. fait hors champ — une entrée non déclenchée par l'action jouée.
  2. fait perçu partiellement — une entrée cachée (`hidden: true`) consultée
     via `store.lookup()`, le canal de rappel (D-082) : titre visible,
     détails masqués.
  3. secret actif — la même entrée cachée, déclenchée par l'action jouée et
     assemblée sur le chemin narrateur (`secrets=False`, D-082) : la sortie
     destinée au joueur ne doit porter aucun marqueur du secret.

Verdicts mécaniques (D-134, pas de lecture de qualité) :
  1. hors-champ absent de la sortie ;
  2. partiel dégradé (titre gardé, corps perdu, sortie plus courte) ;
  3. zéro marqueur de secret/id interne dans le perçu.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.element_mold import ElementMold, absent, degraded, no_markers
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_element_camera")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("ElementCamera", "Test d'élément — la caméra."))

# ---- fixtures synthétiques -------------------------------------------------

# 1) hors champ : jamais déclenchée par l'action jouée (aucun trigger commun).
off_screen = Entry(
    "The Copper Bell", "the-copper-bell", importance=3,
    attrs={"triggers": "bell"}, body="Rings only at low tide, never heard.")
store.upsert_entry("locations.md", off_screen)

# 2/3) fait caché : déclenché par l'action jouée, jamais révélé au joueur.
hidden_fact = Entry(
    "The Ferryman's Debt", "the-ferrymans-debt", importance=3,
    attrs={"triggers": "ferry", "hidden": "true"},
    body="He owes the tide-court a name not yet spoken.")
store.upsert_entry("characters.md", hidden_fact)

# stimulus bête : action fixe, écrite à la main, ne mentionne ni "bell" ni
# le titre/corps du secret — seulement le déclencheur "ferry".
ACTION = "I hail the ferry at the landing."

with ElementMold("camera", budget_seconds=5.0) as mold:
    import mcp_server
    mcp_server._store = store
    mcp_server._engine = None
    mcp_server._slug = "elementcamera"

    # ---- 1. fait hors champ : absent de la sortie narrateur ---------------
    text_narrator, _info = mcp_server._assemble_text(
        ACTION, 120000, secrets=False, event_rules=False)
    mold.check(
        "1-hors-champ-absent",
        absent(text_narrator, off_screen.title, off_screen.body),
        "The Copper Bell ne doit apparaître nulle part : jamais déclenchée")

    # ---- 2. fait perçu partiellement : dégradé via le rappel --------------
    full_render = hidden_fact.render()
    perceived = store.lookup(hidden_fact.slug)
    mold.check(
        "2-partiel-degrade",
        degraded(full_render, perceived, hidden_fact.title, hidden_fact.body),
        f"titre gardé, corps perdu, {len(perceived)} chars perçus "
        f"(vs {len(full_render)} en rendu complet)")

    # ---- 3. secret actif : zéro marqueur dans le perçu du joueur ----------
    mold.check(
        "3-secret-sans-marqueur",
        no_markers(text_narrator, hidden_fact.title, hidden_fact.slug,
                   hidden_fact.body, "Secrets you know", "SECRET"),
        "la brique caméra ne doit laisser fuiter ni le titre, ni le slug, "
        "ni le corps, ni le libellé de section secrète")

assert mold.report(), "test-element-camera: au moins un verdict a échoué"
print("test-element-camera: OK — moule I-382, 3 verdicts mécaniques + coût borné")
