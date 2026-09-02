"""D-260 branchement (Issue #128) : la bascule dans `engine._messages()` — une
save AVEC position + partition projetée passe par `assembleur_position`
(lane a, #125) ; toute autre save garde `store.assemble()` strictement
inchangé. Partition SYNTHÉTIQUE (D-109 : zéro matériau réel versionné).

Couvre les 3 critères testables de l'Issue #128 (le 4e = suites existantes,
`run_tests.py`) :
  1. bout-en-bout : save partition -> paquet assembleur_position ; save sans
     partition -> paquet `store.assemble()` identique (même appel direct)
  2. stabilité de préfixe : deux tours sans transition de node -> préfixe
     stable byte-identique, y compris avec des règles d'événement en queue
  3. pas de fiche perso en double sur le chemin partition
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
from coderain.config import load_config
from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record
from coderain.engine import Engine
from coderain.memory import Entry, Library
from coderain import validator as validator_mod

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


class Stub:
    """Jamais de vrai modèle (D-109/hors-ligne) : capture le dernier appel."""
    def __init__(self, prose: str = "Prose de test."):
        self.prose = prose
        self.calls: list[list[dict]] = []

    def stream(self, messages, **k):
        self.calls.append(messages)
        yield self.prose

    def complete_with_tools(self, messages, tools, dispatch, max_rounds=4):
        self.calls.append(messages)
        return self.prose


# --------------------------------------------------------- fixture builders --
def _manifest():
    return Manifest(titre="module factice D-260 branchement", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="1" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil", "Vous êtes devant une porte close.",
        "scene", anchors=[(0, 40)]))
    p.records.append(Record(
        "garde-brutal", "pnj", "Garde brutal",
        {"role": "sentinelle", "description_md": "Un garde massif et nerveux.",
         "tokens_initial": [{"node_id": "para-01", "count": 1,
                             "placement_md": "près de la porte"}]},
        anchors=[(0, 40)]))
    p.aventure = None
    return p


def _write_synthetic_partition(out_dir: Path) -> Path:
    partition = _build_partition()
    write_partition(partition, out_dir)
    (out_dir / "directeur.md").write_text(
        "## Brief de direction\n\nReste tendu, jamais expéditif.\n",
        encoding="utf-8")
    return out_dir


def _projected_save(root: Path, partition_dir: Path, titre: str) -> tuple[Library, str]:
    """Save projetée ET pointée sur sa partition (`module.json`, D-260 §1) —
    le pointeur que `converter/install.py` pose normalement à l'installation,
    ici écrit à la main (même contrat, hors périmètre du convertisseur)."""
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon oublié.")
    projection.derive(partition_dir, root, slug, corpus_dir=root / "corpus")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    return lib, slug


# --------------------------------------------------------------------- run --
TMP = Path(tempfile.gettempdir()) / "se_branchement_position_d260"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = _write_synthetic_partition(TMP / "partition")

cfg = load_config()
cfg.generation["trinity_brain"] = False   # single-brain : chemin par défaut

section("1a) save AVEC position+partition -> paquet via assembleur_position")
lib_a, slug_a = _projected_save(TMP / "app-a", partition_dir, "Avec partition")
store_a = lib_a.store(slug_a)
engine_a = Engine(cfg, store_a)
assert engine_a._partition_dir() == partition_dir
stub_a = Stub()
engine_a.llm = stub_a
visible = "".join(engine_a.turn("Je pousse la porte."))
assert visible == "Prose de test."
messages = stub_a.calls[-1]
sys_text = messages[0]["content"]
assert "Le seuil" in sys_text                      # node courant présent
assert "Scène courante" in sys_text                # section assembleur_position
assert engine_a._partition_active is True
print(f"  OK : paquet servi via assembleur_position ({len(sys_text)} chars)")

section("1b) save SANS partition -> store.assemble() strictement inchangé")
lib_b = Library(TMP / "app-b")
slug_b = lib_b.create_story("Sans partition", "Une taverne ordinaire.")
store_b = lib_b.store(slug_b)
engine_b = Engine(cfg, store_b)
assert engine_b._partition_dir() is None
history_b = [{"role": "player", "text": "J'observe la salle."}]
via_engine = engine_b._messages(history_b, "Je m'assois.")
direct = store_b.assemble(history_b, "Je m'assois.",
                          scenes_tail=engine_b.scenes_tail,
                          budget_tokens=engine_b.budget,
                          retriever=engine_b.retriever)
direct = engine_b._augment_pack(engine_b._augment_style(
    engine_b._augment_rpg(direct)))
assert via_engine == direct, "le chemin non-partition a divergé de assemble()"
assert engine_b._partition_active is False
assert "Scène courante" not in via_engine[0]["content"]
print("  OK : paquet octet-identique à un appel direct de store.assemble()")

section("2) stabilité de préfixe : deux tours sans transition, règles en queue")
lib_c, slug_c = _projected_save(TMP / "app-c", partition_dir, "Stabilité")
store_c = lib_c.store(slug_c)
# Règle d'événement toujours candidate (aucun triggers_all -> permanente,
# `trigger_gate(permanent_if_no_triggers=True)`, lane b #127) : présente aux
# DEUX tours, jamais entre DIRECTOR_SYS et le contexte (D-260 branchement).
store_c.upsert_entry("events.md", Entry(
    title="Vigilance constante", slug="event-vigilance",
    attrs={}, body="Le donjon reste sur ses gardes."))
engine_c = Engine(cfg, store_c)
h1 = [{"role": "player", "text": "J'observe la porte."}]
h2 = [{"role": "player", "text": "J'inspecte les gonds."},
     {"role": "player", "text": "Je tends l'oreille."}]
state_c = store_c.world_state()
loc = validator_mod.current_location(state_c)
prefix_1 = ap.stable_prefix(ap.build_sections(
    partition_dir, store_c, loc, h1, "Je pousse la porte."))
prefix_2 = ap.stable_prefix(ap.build_sections(
    partition_dir, store_c, loc, h2, "Je fouille la pièce."))
assert prefix_1 == prefix_2, "préfixe stable divergent sans transition de node"
msgs_1 = engine_c._messages(h1, "Je pousse la porte.")
msgs_2 = engine_c._messages(h2, "Je fouille la pièce.")
assert msgs_1[0]["content"].startswith(prefix_1)
assert msgs_2[0]["content"].startswith(prefix_2)
assert "Vigilance constante" in msgs_1[0]["content"][len(prefix_1):]
assert "Vigilance constante" in msgs_2[0]["content"][len(prefix_2):]
print(f"  OK : préfixe stable identique octet pour octet ({len(prefix_1)} chars), "
     "règle d'événement présente en queue aux deux tours")

section("3) pas de fiche perso en double sur le chemin partition (rpg ON)")
lib_d, slug_d = _projected_save(TMP / "app-d", partition_dir, "Fiche perso")
store_d = lib_d.store(slug_d)
rpg = store_d.rpg_state()
rpg["enabled"] = True
store_d.set_rpg_state(rpg)
engine_d = Engine(cfg, store_d)
messages_d = engine_d._messages([], "Je pousse la porte.")
sys_text_d = messages_d[0]["content"]
assert "RPG MODULE (mechanics ON)" in sys_text_d      # règles toujours servies
assert sys_text_d.count("Fiche de personnage") == 1, \
    "la fiche perso apparaît plus d'une fois sur le chemin partition"
assert "Your character sheet" not in sys_text_d, \
    "_augment_rpg a resservi la fiche malgré include_sheet=False"
print("  OK : fiche perso servie une seule fois (section volatile dédiée)")

print("\nALL D-260 BRANCHEMENT (#128) CHECKS PASSED: " + ", ".join(FAIT))
