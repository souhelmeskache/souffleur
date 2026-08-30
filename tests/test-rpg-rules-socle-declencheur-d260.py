"""D-260 post-mesure (a) — Issue #162 (suite de l'arbitrage #144) : découpe de
`rpg-rules.md` en SOCLE toujours servi + section « Level-ups and grants »
servie seulement sur déclencheur d'état vérifiable par le moteur
(`rpg.pending_grant > 0`, même info que "LEVEL-UP PENDING" dans
`modules/rpg.py::context_block`). Aucune autre section n'a de déclencheur
identifiable — garde-fou explicite de l'arbitrage : au doute, elle reste au
socle (`templates.split_rpg_rules` ne retire QUE cette section nommée, et
retombe sur "texte entier au socle" si le marqueur disparaît).

Partition SYNTHÉTIQUE (D-109 : zéro matériau réel versionné), mêmes fixtures
que `test-branchement-position-d260.py`/`test-prefixe-rpg-longueur-unique-d260.py`.

Couvre :
  1. `templates.split_rpg_rules` : le socle shippé ne porte plus l'en-tête
     Level-ups, la section extraite le porte ; un fichier édité sans l'en-tête
     retombe sur "texte entier au socle" (aucune perte silencieuse).
  2. Golden sans partition (non-régression) : RPG ON, pas de grant en attente
     -> la section Level-ups est ABSENTE du system prompt ; grant en attente
     -> elle apparaît, EXACTEMENT une fois.
  3. Chemin partition : même garde (absente/présente selon `pending_grant`),
     et stabilité de préfixe octet pour octet sur deux tours sans transition,
     dans les deux configurations (pending_grant=0 et >0 constants).
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
from coderain import templates
from coderain.config import load_config
from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record
from coderain.engine import Engine
from coderain.memory import Library

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
    return Manifest(titre="module factice #162 socle rpg", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="1" * 64,
                    date_conversion="2026-08-30T00:00:00+00:00",
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
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon oublié.")
    projection.derive(partition_dir, root, slug, corpus_dir=root / "corpus")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    return lib, slug


LEVELUP_HEADER = "## Level-ups and grants"

# --------------------------------------------------------------------- run --
TMP = Path(tempfile.gettempdir()) / "se_rpg_rules_socle_declencheur_d260"
if TMP.exists():
    shutil.rmtree(TMP)

cfg = load_config()
cfg.generation["trinity_brain"] = False   # single-brain : chemin par défaut

section("1) templates.split_rpg_rules : socle vs section, garde-fou sans marqueur")
socle, levelup = templates.split_rpg_rules(templates.RPG_RULES)
assert LEVELUP_HEADER not in socle, "le socle ne doit plus porter la section Level-ups"
assert socle.strip(), "le socle ne doit jamais être vide"
assert levelup.startswith(LEVELUP_HEADER)
assert "ability_add" in levelup and "title_add" in levelup
# le reste du contenu (schéma d'enveloppe, attributs, barème DC) reste au socle
for needle in ("# RPG rules", "## The sidecar (envelope v1)",
              "## Rules", "Attributes: **Strength"):
    assert needle in socle, f"{needle!r} attendu au socle"
edited = templates.RPG_RULES.replace(LEVELUP_HEADER, "## Renamed section")
socle_edited, levelup_edited = templates.split_rpg_rules(edited)
assert levelup_edited == "" and socle_edited == edited, (
    "sans l'en-tête attendu, tout doit rester au socle (garde-fou : aucune "
    "section retirée sans déclencheur identifiable)")
print("  OK : socle/section correctement découpés, garde-fou sans marqueur vérifié")

section("2) golden sans partition (non-régression) : absent puis présent")
lib0 = Library(TMP / "app-simple")
slug0 = lib0.create_story("Sans partition", "Une taverne ordinaire.")
store0 = lib0.store(slug0)
rpg0 = store0.rpg_state()
rpg0["enabled"] = True
store0.set_rpg_state(rpg0)
engine0 = Engine(cfg, store0)
sys_no_grant = engine0._messages([], "J'observe la salle.")[0]["content"]
assert "RPG MODULE (mechanics ON)" in sys_no_grant
assert LEVELUP_HEADER not in sys_no_grant, \
    "pas de grant en attente -> la section Level-ups doit être absente"
assert "Attributes: **Strength" in sys_no_grant, "le socle reste servi"

rpg0["pending_grant"] = 1
store0.set_rpg_state(rpg0)
sys_with_grant = engine0._messages([], "J'observe la salle.")[0]["content"]
assert sys_with_grant.count(LEVELUP_HEADER) == 1, \
    "grant en attente -> la section Level-ups apparaît EXACTEMENT une fois"
print("  OK : section Level-ups absente/présente selon pending_grant, "
     "socle toujours servi (chemin non-partition)")

section("3) chemin partition : même garde + stabilité de préfixe (2 configs)")
partition_dir = _write_synthetic_partition(TMP / "partition")
for label, pending in (("pending_grant=0", 0), ("pending_grant=2", 2)):
    lib, slug = _projected_save(TMP / f"app-{pending}", partition_dir,
                                f"Socle rpg {label}")
    store = lib.store(slug)
    rpg = store.rpg_state()
    rpg["enabled"] = True
    rpg["pending_grant"] = pending
    store.set_rpg_state(rpg)
    engine = Engine(cfg, store)
    h1 = [{"role": "player", "text": "J'observe la porte."}]
    h2 = [{"role": "player", "text": "J'inspecte les gonds."},
         {"role": "player", "text": "Je tends l'oreille."}]
    msgs_1 = engine._messages(h1, "Je pousse la porte.")
    msgs_2 = engine._messages(h2, "Je fouille la pièce.")
    sys_1, sys_2 = msgs_1[0]["content"], msgs_2[0]["content"]

    state = store.world_state()
    loc = state["location"]
    rpg_rules = engine._rpg_rules_served()
    prefix_1 = ap.stable_prefix(ap.build_sections(
        partition_dir, store, loc, h1, "Je pousse la porte.", rpg_on=True,
        rpg_rules=rpg_rules))
    prefix_2 = ap.stable_prefix(ap.build_sections(
        partition_dir, store, loc, h2, "Je fouille la pièce.", rpg_on=True,
        rpg_rules=rpg_rules))
    assert prefix_1 == prefix_2, \
        f"[{label}] préfixe stable divergent sans transition de node"
    assert sys_1.startswith(prefix_1) and sys_2.startswith(prefix_2)

    expected_count = 1 if pending > 0 else 0
    for tour, sys_text in (("tour 1", sys_1), ("tour 2", sys_2)):
        n = sys_text.count(LEVELUP_HEADER)
        assert n == expected_count, (
            f"[{label}] {tour} : section Level-ups comptée {n} fois "
            f"(attendu {expected_count})")
    print(f"  OK [{label}] : préfixe stable identique octet pour octet "
         f"({len(prefix_1)} chars), section Level-ups comptée {expected_count} "
         "fois par tour")

print("\nALL RPG RULES SOCLE/DÉCLENCHEUR (#162) CHECKS PASSED: " + ", ".join(FAIT))
