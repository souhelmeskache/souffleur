"""I-22/I-15/I-18 : la photo sert QUI joue, jamais le rôle d'un AUTRE pipeline.

Défaut mesuré (constat du chantier) : la photo servie au Director
(`coderain/assembleur_position.py::build_sections`, appelée par
`mcp_server.py::_position_context_text`) ne servait JAMAIS `player.md` — ni
le nom ni le genre du personnage. Mesuré sur papier : nom en tête sans genre
explicite, 3 réussites sur 5 ; avec une ligne de genre explicite, 5 sur 5.
Elle portait en outre `DIRECTOR_SYS` (section « Rôle (Director) », le rôle
d'UN AUTRE pipeline — JSON + conversation d'accord 4 fenêtres, D-219) et le
point « 6. Discipline d'écran » du brief de direction (canal `ui_say`/
`ui_wait`/... d'un régime qui n'est pas celui-ci) — bruit pour le Director
comme pour le narrateur au régime principal (Claude Code branché par MCP).

Ce test, 100 % synthétique (D-109, zéro matériau de campagne réel) :

  1. la photo du Director (chemin MCP, `assemble_context_to_file`) porte
     « Personnage joué », le NOM du personnage ET sa ligne `genre:` — la
     section est marquée stable et vient avant toute section volatile ;
  2. le paquet du narrateur (`paquet_narrateur`) porte aussi « Personnage
     joué » ;
  3. la photo du Director (chemin MCP) ne contient ni « LOGIC AGENT » ni
     « CONVERSATION D'ACCORD » (DIRECTOR_SYS, Issue #198 suite) ;
  4. ni la photo du Director ni le paquet du narrateur ne contiennent
     « Discipline d'écran » ;
  5. le chemin `coderain/engine.py` (régime secondaire — `build_sections`/
     `assemble()` à leurs défauts, ce que `engine.py` appelle réellement)
     sert TOUJOURS `DIRECTOR_SYS` (« LOGIC AGENT ») : `director_sys` ne
     change rien à ce chemin, inchangé octet pour octet.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain import assembleur_position as ap
from coderain.converter import directeur, projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition
from coderain.memory import Entry, Library
from coderain import validator as validator_mod

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


GENRE = "femme — elle ; accords au féminin"
NOM = "Mika Thorne"


def _manifest():
    return Manifest(titre="module factice I-22", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="5" * 64,
                    date_conversion="2026-10-11T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil", "Vous êtes devant une porte close.",
        "scene", anchors=[(0, 40)]))
    p.aventure = None
    return p


TMP = Path(tempfile.gettempdir()) / "se_photo_identite_i15_i18_i22"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)
# Le VRAI gabarit (`converter/directeur.py::GABARIT`), pas un brief minimal
# écrit à la main : il porte le point « 6. Discipline d'écran » dont ce
# chantier vérifie l'absence AU SERVICE (I-18) -- jamais à la source.
directeur.generate(partition_dir)

lib = Library(TMP / "app")
slug = lib.create_story("Test I-22", "Un donjon oublié.")
projection.derive(partition_dir, TMP / "app", slug, corpus_dir=TMP / "corpus")
sdir = lib.saves.dir(slug)
(sdir / "module.json").write_text(
    json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
store = lib.store(slug)

# La partition s'est bien projetée avec le point 6 dans le brief SOURCE —
# preuve que sa future absence au service est bien un retrait AU SERVICE,
# jamais une absence déjà présente à la source.
brief_source = store.read("custom-instructions.md")
assert "Discipline d'écran" in brief_source, \
    "le brief source devrait porter le point 6 avant tout retrait au service"

# Personnage joué : nom + genre explicite (I-15), jamais fourni par le
# gabarit vierge -- écrasé ici comme le ferait un outil de création réel
# (ou la fixture de banc `bench/fixtures/personnage-banc.py`).
store.upsert_entry("player.md", Entry(
    title=NOM, slug="player", importance=5,
    attrs={"status": "prête au combat, armée et armurée", "genre": GENRE},
    body="**Visual:** Silhouette trapue.\n\nIdentity: combattante de test "
         "(D-109), sans lien avec un module joué.\n"))

mcp_server._engine = None       # pas d'Engine chargé -- le pont MCP seul
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None

state = store.world_state()
location = validator_mod.current_location(state)
history = [{"role": "player", "text": "J'observe la porte."}]

section("1) photo du Director (chemin MCP) : Personnage joué, nom, genre, "
        "stable, avant toute section volatile")
result = mcp_server.assemble_context_to_file("J'observe la porte.")
texte_director = Path(result["path"]).read_text(encoding="utf-8")
assert "Personnage joué" in texte_director, \
    f"section « Personnage joué » absente -> {texte_director[:2000]!r}"
assert NOM in texte_director, \
    f"nom du personnage absent de la photo -> {texte_director[:2000]!r}"
assert f"genre: {GENRE}" in texte_director, \
    f"ligne genre: absente ou tronquée -> {texte_director[:2000]!r}"

sections_mcp = ap.build_sections(partition_dir, store, location, history,
                                 "J'observe la porte.", director_sys=False)
joue = next(s for s in sections_mcp if s.title == "Personnage joué")
assert joue.marker == "stable", f"Personnage joué devrait être stable -> {joue}"
idx_joue = sections_mcp.index(joue)
idx_volatile = next(i for i, s in enumerate(sections_mcp)
                    if s.marker == "volatile")
assert idx_joue < idx_volatile, \
    "Personnage joué (stable) doit venir avant toute section volatile"
print("  OK : « Personnage joué » présente (nom + genre), stable, en tête")

section("2) photo du Director (chemin MCP) : ni LOGIC AGENT ni CONVERSATION "
        "D'ACCORD (DIRECTOR_SYS, Issue #198 suite)")
assert "LOGIC AGENT" not in texte_director, \
    f"LOGIC AGENT (DIRECTOR_SYS) ne devrait plus atteindre le Director MCP " \
    f"-> {texte_director[:2000]!r}"
assert "CONVERSATION D'ACCORD" not in texte_director, \
    f"CONVERSATION D'ACCORD (DIRECTOR_SYS) ne devrait plus atteindre le " \
    f"Director MCP -> {texte_director[:2000]!r}"
print("  OK : DIRECTOR_SYS absent de la photo du Director (chemin MCP)")

section("3) photo du Director (chemin MCP) : Discipline d'écran absente "
        "du brief servi")
assert "Discipline d'écran" not in texte_director, \
    f"le point Discipline d'écran ne devrait plus être servi -> " \
    f"{texte_director[:4000]!r}"
print("  OK : Discipline d'écran absente de la photo du Director")

section("4) paquet du narrateur : Personnage joué présente, Discipline "
        "d'écran absente")
paquet = mcp_server.paquet_narrateur(
    "Angle : calme avant la tempête.", "J'observe la porte.",
    sans_mecanique=True)
texte_narrateur = Path(paquet["path"]).read_text(encoding="utf-8")
assert "Personnage joué" in texte_narrateur, \
    f"« Personnage joué » devrait aussi atteindre le narrateur -> " \
    f"{texte_narrateur[:2000]!r}"
assert NOM in texte_narrateur, \
    f"nom du personnage absent du paquet narrateur -> " \
    f"{texte_narrateur[:2000]!r}"
assert "Discipline d'écran" not in texte_narrateur, \
    f"Discipline d'écran ne devrait jamais atteindre le narrateur -> " \
    f"{texte_narrateur[:4000]!r}"
print("  OK : paquet narrateur avec Personnage joué, sans Discipline d'écran")

section("5) coderain/engine.py (régime secondaire) : DIRECTOR_SYS toujours "
        "servi, inchangé")
messages = ap.assemble(partition_dir, store, state, history,
                       "J'observe la porte.")
sys_text_engine = messages[0]["content"]
assert "LOGIC AGENT" in sys_text_engine, \
    f"le chemin engine.py (director_sys=True par défaut) doit toujours " \
    f"servir DIRECTOR_SYS -> {sys_text_engine[:2000]!r}"
print("  OK : DIRECTOR_SYS toujours servi au chemin engine.py (défaut "
     "inchangé)")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nOK test-photo-identite-i15-i18-i22 — {len(FAIT)} sections vertes")
