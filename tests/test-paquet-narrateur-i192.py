"""Issue #192 (D-269) : `paquet_narrateur`, le péage du tour côté pont MCP
(chemin PRODUIT). Bout-en-bout sur une partition SYNTHÉTIQUE (D-109 : zéro
matériau réel) : projette une partition portant un node avec `rendu_md`, une
entrée cachée non révélée et une règle d'événement, puis exerce :

  1. `rendu_md` sert dans le fichier écrit quand le node en porte, absent
     sinon, jamais dans le retour de l'outil (R3) ;
  2. R1 mord sans enveloppe appliquée, passe avec `sans_mecanique=True` ou
     après un `apply_envelope` ;
  3. R2 mord sur un slug/fragment caché ou de règle d'événement dans la
     directive, nomme la garde, et laisse passer une directive propre
     (verbatim préservé dans le paquet) ;
  4. le retour ne porte jamais le texte du paquet (R3) ;
  5. le paquet écrit ne contient aucune entrée cachée non révélée ni règle
     d'événement (garde D-019 déjà exercée par le chemin position, revérifiée
     ici sur CE fichier).
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

from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record
from coderain.memory import Entry, Library

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


COULEUR = ("registre feutré ; joue les silences et les regards, ne révèle "
           "rien, laisse le doute monter")


def _manifest():
    return Manifest(titre="module factice I-192", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="3" * 64,
                    date_conversion="2026-08-31T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil", "Vous êtes devant une porte close.",
        "scene", anchors=[(0, 40)], rendu_md=COULEUR))
    p.records.append(Record(
        "garde-brutal", "pnj", "Garde brutal",
        {"role": "sentinelle", "description_md": "Un garde massif et nerveux.",
         "tokens_initial": [{"node_id": "para-01", "count": 1,
                             "placement_md": "près de la porte"}]},
        anchors=[(0, 40)]))
    p.aventure = None
    return p


TMP = Path(tempfile.gettempdir()) / "se_paquet_narrateur_i192"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)
(partition_dir / "directeur.md").write_text(
    "## Brief de direction\n\nReste tendu, jamais expéditif.\n",
    encoding="utf-8")

lib = Library(TMP / "app")
slug = lib.create_story("Test I-192", "Un donjon oublié.")
projection.derive(partition_dir, TMP / "app", slug, corpus_dir=TMP / "corpus")
sdir = lib.saves.dir(slug)
(sdir / "module.json").write_text(
    json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
store = lib.store(slug)

# Une entrée cachée non révélée + une règle d'événement, pour R2/D-019.
store.upsert_entry("characters.md", Entry(
    title="La traîtresse", slug="la-traitresse",
    attrs={"hidden": "true"},
    body="Elle a vendu la porte au garde brutal contre de l'or."))
store.upsert_entry("events.md", Entry(
    title="Vigilance constante", slug="event-vigilance",
    attrs={}, body="Le donjon reste sur ses gardes."))

mcp_server._engine = None       # pas d'Engine chargé -- le pont doit s'en passer
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None

state = store.world_state()
assert state.get("location") == "para-01", state.get("location")

section("1) R1 mord sans enveloppe appliquée ce tour")
try:
    mcp_server.paquet_narrateur("Angle : tension.", "Je pousse la porte.")
    raise AssertionError("R1 aurait dû refuser")
except ValueError as exc:
    assert "R1" in str(exc)
print("  OK : refus nommé R1")

section("1b) sans_mecanique=True lève le refus R1")
result = mcp_server.paquet_narrateur(
    "Angle : tension palpable, personne ne parle.", "Je pousse la porte.",
    sans_mecanique=True)
assert "path" in result and "sections" in result
print("  OK : sans_mecanique=True passe le filet R1")

section("2) apply_envelope arme le signal R1, puis paquet_narrateur passe")
mcp_server._last_applied_events = None
events = mcp_server.apply_envelope(json.dumps({"v": 1}), rpg_on=False)
assert isinstance(events, list)
result2 = mcp_server.paquet_narrateur(
    "Angle : tension palpable.", "Je pousse la porte.")
assert "path" in result2
print("  OK : R1 passe après un apply_envelope, sans sans_mecanique")

section("3) rendu_md sert dans le fichier, jamais dans le retour (R3)")
texte = Path(result2["path"]).read_text(encoding="utf-8")
assert "DIRECTION DE RENDU" in texte
assert COULEUR in texte
assert "Direction de rendu" in result2["sections"]
for v in result2.values():
    if isinstance(v, str):
        assert COULEUR not in v, "rendu_md a fuité dans le retour de l'outil"
assert "rendu_md" not in result2
print("  OK : rendu_md dans le fichier, absent du retour")

section("4) le retour ne porte jamais le texte du paquet (R3)")
for k, v in result2.items():
    if isinstance(v, str) and k != "path":
        assert len(v) < 200, f"{k!r} ressemble à du contenu, pas à une métadonnée"
assert isinstance(result2["sections"], list)
assert all(isinstance(s, str) and len(s) < 80 for s in result2["sections"])
print("  OK : retour = chemin + métadonnées + noms de sections, jamais le texte")

section("5) le paquet écrit ne contient ni entrée cachée ni règle d'événement")
assert "traîtresse" not in texte
assert "vendu la porte" not in texte
assert "Vigilance constante" not in texte
assert "SCENARIO EVENT RULES" not in texte
print("  OK : garde D-019 tenue sur le fichier paquet_narrateur")

section("6) R2 mord sur un slug d'entrée cachée dans la directive")
mcp_server._last_applied_events = ["check: agility d20+1=9 vs DC12 -> success"]
try:
    mcp_server.paquet_narrateur("Angle sur la-traitresse.", "Je regarde autour.")
    raise AssertionError("R2 aurait dû refuser (slug caché)")
except ValueError as exc:
    assert "R2" in str(exc) and "la-traitresse" in str(exc)
print("  OK : refus R2 nomme la garde (slug d'entrée cachée)")

section("6b) R2 mord sur un fragment littéral du corps caché")
try:
    mcp_server.paquet_narrateur(
        "Angle : Elle a vendu la porte au garde brutal contre de l'or, "
        "joue la tension qui en découle.",
        "Je regarde autour.")
    raise AssertionError("R2 aurait dû refuser (fragment de corps caché)")
except ValueError as exc:
    assert "R2" in str(exc)
print("  OK : refus R2 mord aussi sur un fragment littéral, pas seulement le slug")

section("6c) R2 mord sur le slug d'une règle d'événement")
try:
    mcp_server.paquet_narrateur("Angle sur event-vigilance.", "J'observe.")
    raise AssertionError("R2 aurait dû refuser (slug de règle d'événement)")
except ValueError as exc:
    assert "R2" in str(exc) and "event-vigilance" in str(exc)
print("  OK : refus R2 nomme la garde (règle d'événement)")

section("7) directive propre -> verbatim préservé dans le paquet")
propre = "Angle : cadre la peur du joueur, jamais celle du garde."
result3 = mcp_server.paquet_narrateur(propre, "Je pousse la porte.")
texte3 = Path(result3["path"]).read_text(encoding="utf-8")
assert propre in texte3
assert "Directive du Director" in result3["sections"]
print("  OK : directive propre passe le filet R2, verbatim dans le paquet")

section("8) node sans rendu_md => section absente, aucun bruit")
store2_dir = TMP / "app2"
p2 = Partition(_manifest())
p2.nodes.append(Node(
    "para-02", "scene", "La salle des gardes",
    "Une torche brûle contre le mur du fond.", "scene",
    anchors=[(0, 40)]))                       # pas de rendu_md
p2.aventure = None
partition_dir2 = TMP / "partition2"
write_partition(p2, partition_dir2)
lib2 = Library(store2_dir)
slug2 = lib2.create_story("Test I-192 sans rendu_md", "Un couloir.")
projection.derive(partition_dir2, store2_dir, slug2, corpus_dir=TMP / "corpus2")
sdir2 = lib2.saves.dir(slug2)
(sdir2 / "module.json").write_text(
    json.dumps({"partition": str(partition_dir2)}), encoding="utf-8")
store2 = lib2.store(slug2)
mcp_server._store = store2
mcp_server._slug = slug2
mcp_server._last_applied_events = None
result4 = mcp_server.paquet_narrateur(
    "Angle neutre.", "J'avance.", sans_mecanique=True)
texte4 = Path(result4["path"]).read_text(encoding="utf-8")
assert "DIRECTION DE RENDU" not in texte4
assert "Direction de rendu" not in result4["sections"]
print("  OK : pas de rendu_md sur ce node => aucune section, aucun bruit")

section("9) le paquet narrateur ne porte jamais la section Rôle (Director) "
        "(Issue #198, point 3 : DIRECTOR_SYS décrit le Director, pas le "
        "narrateur qui lit ce fichier)")
assert "Rôle (Director)" not in result4["sections"]
assert "Rôle (Director)" not in texte4
from coderain.modules.trinity import DIRECTOR_SYS
assert DIRECTOR_SYS.split("%s")[0].strip()[:40] not in texte4
print("  OK : DIRECTOR_SYS absent du paquet narrateur")

print(f"\nOK test-paquet-narrateur-i192 — {len(FAIT)} sections vertes")
