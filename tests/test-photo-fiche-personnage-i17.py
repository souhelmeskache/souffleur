"""Issue #17 : `mcp_server._position_context_text` (chemin position de
`assemble_context_to_file`) appelait `assembleur_position.build_sections`
sans `char_sheet`/`rpg_on`/`rpg_rules` — même quand la save a `rpg.enabled:
true`. La photo perdait donc la section « Fiche de personnage » et la
section « RPG MODULE (mechanics ON) », et la section « Rôle (Director) »
sortait dans sa variante SANS jeu (`_ENV_WORLD` au lieu de `_ENV_RPG`),
exactement comme sur une save sans RPG du tout.

Ce test, 100 % synthétique (D-109/D-206, aucun matériau de campagne réel) :
  1. une save au jeu ACTIF (mode="rpg") avec une partition projetée (node +
     locations.md, condition d'éligibilité du chemin position) -> la photo
     servie par `mcp_server.assemble_context_to_file` porte la section
     « Fiche de personnage » et la section « RPG MODULE (mechanics ON) » ;
  2. une save au jeu INACTIF (mode="simple"), même partition -> ni l'une ni
     l'autre section, rien ne fuite ;
  3. `mcp_server.paquet_narrateur`, qui réutilise ce même chemin avec
     `role_section=False`, reste INCHANGÉ : toujours aucune fiche, ni avant
     ni après ce correctif (le narrateur reçoit la perception du
     personnage jouée, jamais sa fiche mécanique).

MODIFIÉ par I-22/I-15/I-18 (`tests/test-photo-identite-i15-i18-i22.py`
couvre le changement en détail) : le point 1b vérifiait que la variante du
Rôle (Director) servie sur ce chemin était bien celle AVEC jeu (`_ENV_RPG`,
pas `_ENV_WORLD`). I-22 fait de `_position_context_text` un pont qui ne sert
QUE le régime principal (Director Claude Code branché par MCP, déjà son
propre rôle) : il passe désormais `director_sys=False` à `build_sections`
par défaut, donc la section « Rôle (Director) » — `DIRECTOR_SYS`, quelle que
soit sa variante — n'atteint plus CE chemin du tout. Le point 1b vérifie
maintenant son ABSENCE complète plutôt que sa variante ; rien d'autre ne
change (la fiche + le socle RPG restent gouvernés par `role_section`,
inchangé)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def _manifest():
    return Manifest(titre="module factice I-17", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="7" * 64,
                    date_conversion="2026-10-11T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "La clairière", "Une clairière silencieuse.",
        "scene", anchors=[(0, 30)]))
    p.aventure = None
    return p


TMP = Path(tempfile.gettempdir()) / "se_photo_fiche_i17"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)

mcp_server._engine = None       # pas d'Engine charge -- le pont doit s'en passer
mcp_server._last_applied_events = None


def _save(mode: str, name: str):
    """Une save synthetique avec la partition projetee, au mode donne."""
    app_dir = TMP / name
    lib = mcp_server.Library(app_dir)
    slug = lib.saves.create(f"Test I-17 {name}", premise="Une clairière.",
                            mode=mode)
    (lib.saves.dir(slug) / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    projection.derive(partition_dir, app_dir, slug, corpus_dir=TMP / f"corpus-{name}")
    return lib.store(slug), slug


section("1) save au jeu ACTIF : la fiche + le socle RPG arrivent a la photo")
store_rpg, slug_rpg = _save("rpg", "rpg")
assert store_rpg.rpg_enabled(), "la save devrait avoir rpg.enabled=true"
rpg = store_rpg.rpg_state()
rpg.setdefault("player", {})["stats"] = {"strength": 3, "agility": 2}
rpg["player"]["level"], rpg["player"]["hp"], rpg["player"]["hp_max"] = 5, 18, 18
store_rpg.set_rpg_state(rpg)

mcp_server._store = store_rpg
mcp_server._slug = slug_rpg
result = mcp_server.assemble_context_to_file("J'observe la clairière.")
texte = Path(result["path"]).read_text(encoding="utf-8")
assert "Fiche de personnage" in texte, \
    f"section Fiche de personnage absente -> {texte[:4000]!r}"
assert "RPG MODULE (mechanics ON)" in texte, \
    f"section RPG MODULE absente -> {texte[:4000]!r}"
print("  OK : Fiche de personnage + RPG MODULE présentes, jeu actif")

section("1b) I-22 : la section Rôle (Director)/DIRECTOR_SYS n'atteint plus "
        "ce chemin (régime principal, Director déjà son propre rôle)")
from coderain.modules.trinity import DIRECTOR_SYS
role_prefix = DIRECTOR_SYS.split("%s")[0].strip()[:60]
assert role_prefix not in texte, \
    f"DIRECTOR_SYS ne devrait plus atteindre la photo du Director MCP " \
    f"(director_sys=False par défaut, I-22) -> {texte[:2000]!r}"
assert "Rôle (Director)" not in texte, \
    "le titre de section ne devrait plus apparaître non plus"
print("  OK : section Rôle (Director) absente (I-22)")

section("2) save au jeu INACTIF : ni fiche ni socle RPG, rien ne fuite")
store_off, slug_off = _save("simple", "simple")
assert not store_off.rpg_enabled(), "la save ne devrait pas avoir rpg.enabled"
mcp_server._store = store_off
mcp_server._slug = slug_off
result2 = mcp_server.assemble_context_to_file("J'observe la clairière.")
texte2 = Path(result2["path"]).read_text(encoding="utf-8")
assert "Fiche de personnage" not in texte2, \
    f"section Fiche de personnage ne devrait pas apparaître -> {texte2[:4000]!r}"
assert "RPG MODULE (mechanics ON)" not in texte2, \
    f"section RPG MODULE ne devrait pas apparaître -> {texte2[:4000]!r}"
print("  OK : aucune fiche ni socle RPG, jeu inactif")

section("3) paquet_narrateur (role_section=False) reste inchangé : "
        "toujours aucune fiche")
mcp_server._store = store_rpg
mcp_server._slug = slug_rpg
mcp_server._last_applied_events = mcp_server.apply_envelope(
    json.dumps({"v": 1}), rpg_on=False)
paquet = mcp_server.paquet_narrateur(
    "Angle : calme avant la tempête.", "J'observe la clairière.",
    sans_mecanique=False)
texte3 = Path(paquet["path"]).read_text(encoding="utf-8")
assert "Fiche de personnage" not in texte3, \
    f"paquet_narrateur ne doit jamais recevoir la fiche -> {texte3[:4000]!r}"
assert "RPG MODULE (mechanics ON)" not in texte3, \
    f"paquet_narrateur ne doit jamais recevoir le socle RPG -> {texte3[:4000]!r}"
print("  OK : paquet_narrateur toujours sans fiche ni socle RPG")

print(f"\nOK test-photo-fiche-personnage-i17 — {len(FAIT)} sections vertes")
