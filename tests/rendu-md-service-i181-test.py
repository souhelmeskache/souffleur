"""Issue #181 (volet SERVICE) : sert `rendu_md` (socle #176) au narrateur
via l'Angle, jamais au Director. Bout-en-bout sur une partition SYNTHÉTIQUE
(D-109 : zéro matériau réel) : projette une partition portant un node avec
`rendu_md` non vide, puis exerce :
  1. `assembleur_position.rendu_md_for` — lit le rendu_md du node courant ;
  2. `assembleur_position.build_sections` (le paquet servi au Director) —
     ne contient JAMAIS ce texte (garde D-179/D-065) ;
  3. `modules/trinity.py::_writer_directive` — ajoute la section DIRECTION
     DE RENDU quand rendu_md est non vide, rien quand il est vide/absent
     (aucun bruit, aucune régression sur les saves sans le champ).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain import assembleur_position as ap
from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition
from coderain.memory import Library
from coderain import validator as validator_mod
from coderain.modules.trinity import _writer_directive

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


COULEUR = ("registre feutré ; joue les silences et les regards, ne révèle "
           "rien, laisse le doute monter")


def _manifest():
    return Manifest(titre="module factice I-181", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="1" * 64,
                    date_conversion="2026-08-30T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil", "Vous êtes devant une porte close.",
        "scene", anchors=[(0, 40)], rendu_md=COULEUR))
    p.nodes.append(Node(
        "para-02", "scene", "La salle des gardes",
        "Une torche brûle contre le mur du fond.", "scene",
        anchors=[(40, 80)]))                       # pas de rendu_md ici
    p.aventure = None
    return p


TMP = Path(tempfile.gettempdir()) / "se_rendu_md_service_i181"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)
(partition_dir / "directeur.md").write_text(
    "## Brief de direction\n\nReste tendu, jamais expéditif.\n",
    encoding="utf-8")

lib = Library(TMP / "app")
slug = lib.create_story("Test I-181", "Un donjon oublié.")
projection.derive(partition_dir, TMP / "app", slug, corpus_dir=TMP / "corpus")
store = lib.saves.store(slug)
state = store.world_state()
assert validator_mod.current_location(state) == "para-01", state.get("player")

section("1) rendu_md_for lit le node courant, chaîne vide sur node sans rendu_md")
assert ap.rendu_md_for(partition_dir, "para-01") == COULEUR
assert ap.rendu_md_for(partition_dir, "para-02") == ""

section("2) le paquet Director (build_sections) ne contient JAMAIS rendu_md")
history = [{"role": "player", "text": "J'observe la porte."}]
sections = ap.build_sections(partition_dir, store, "para-01", history,
                             "Je pousse la porte.")
director_text = "\n\n".join(s.render() for s in sections)
assert "registre feutré" not in director_text
assert COULEUR not in director_text
print("  OK : rendu_md absent du contexte Director")

section("3) _writer_directive ajoute la section DIRECTION DE RENDU si non vide")
plan = {"beat_plan": "Le joueur pousse la porte, elle grince.",
       "must_stay_consistent": []}
directive = _writer_directive(plan, {}, [], ap.rendu_md_for(partition_dir, "para-01"))
assert "# DIRECTION DE RENDU" in directive
assert COULEUR in directive
print("  OK : section DIRECTION DE RENDU présente avec le texte du node")

section("4) node sans rendu_md => aucune section, directive inchangée")
directive_sans = _writer_directive(plan, {}, [], ap.rendu_md_for(partition_dir, "para-02"))
directive_defaut = _writer_directive(plan, {}, [])
assert "DIRECTION DE RENDU" not in directive_sans
assert directive_sans == directive_defaut
print("  OK : rendu_md vide/absent => directive octet-identique, aucune section")

print(f"\nOK rendu-md-service-i181-test — {len(FAIT)} sections vertes")
