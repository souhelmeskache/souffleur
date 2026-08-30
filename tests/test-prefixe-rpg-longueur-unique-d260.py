"""Correctif post-refus PR #164 (Issue #165) : test bloquant manquant à la
revue de #144. Save partition SYNTHÉTIQUE (D-109), RPG ON, `response_length`
!= medium, DEUX tours SANS transition de node -> vérifie que
`rpg-rules.md`/`response_length` (D-260 post-mesure, Issue #144, arbitrage
(b)) sont bien portés par le préfixe STABLE de `assembleur_position`, une
seule fois chacun, sur tout le paquet servi par `engine._messages()` :

  (a) préfixe stable byte-identique entre les deux tours
  (b) le préfixe CONTIENT « RPG MODULE (mechanics ON) » ET la directive de
      longueur
  (c) chacune des deux comptée EXACTEMENT UNE FOIS dans le paquet entier

Anti-régression explicite (vérifié en écrivant ce test) : re-brancher
`_augment_rpg` sur le chemin partition (double service, comme avant le
correctif de la PR #164) ou remettre `include_length=True` dans l'appel à
`_augment_style` de `engine._messages()` fait ROUGIR ce test — la section
RPG ou la directive de longueur seraient alors comptées deux fois.
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
    return Manifest(titre="module factice #165 prefixe rpg/longueur",
                    corpus_source="5e", corpus_cible="5e", structures=["S1"],
                    hash_source="1" * 64,
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
    """Save projetée ET pointée sur sa partition (`module.json`, D-260 §1)."""
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon oublié.")
    projection.derive(partition_dir, root, slug, corpus_dir=root / "corpus")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    return lib, slug


# --------------------------------------------------------------------- run --
TMP = Path(tempfile.gettempdir()) / "se_prefixe_rpg_longueur_unique_d260"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = _write_synthetic_partition(TMP / "partition")

cfg = load_config()
cfg.generation["trinity_brain"] = False   # single-brain : chemin par défaut
cfg.generation["response_length"] = "short"   # != medium (medium = pas de directive)

section("0) save AVEC position+partition, RPG ON")
lib, slug = _projected_save(TMP / "app", partition_dir, "Prefixe rpg/longueur")
store = lib.store(slug)
rpg = store.rpg_state()
rpg["enabled"] = True
store.set_rpg_state(rpg)
engine = Engine(cfg, store)
assert engine._partition_dir() == partition_dir
length_directive = engine._response_length_directive()
assert length_directive, "response_length=short doit produire une directive non vide"

section("1) deux tours SANS transition de node, via engine._messages()")
h1 = [{"role": "player", "text": "J'observe la porte."}]
h2 = [{"role": "player", "text": "J'inspecte les gonds."},
     {"role": "player", "text": "Je tends l'oreille."}]
msgs_1 = engine._messages(h1, "Je pousse la porte.")
msgs_2 = engine._messages(h2, "Je fouille la pièce.")
sys_1, sys_2 = msgs_1[0]["content"], msgs_2[0]["content"]

state = store.world_state()
loc = state["location"]
# D-260 post-mesure (a) (Issue #162) : `rpg_rules` servi par le moteur est
# désormais le socle (+ section Level-ups sur déclencheur), pas le fichier
# brut — `_rpg_rules_served()` est la même fonction que `_messages()` appelle.
rpg_rules = engine._rpg_rules_served()
prefix_1 = ap.stable_prefix(ap.build_sections(
    partition_dir, store, loc, h1, "Je pousse la porte.", rpg_on=True,
    rpg_rules=rpg_rules, response_length=length_directive))
prefix_2 = ap.stable_prefix(ap.build_sections(
    partition_dir, store, loc, h2, "Je fouille la pièce.", rpg_on=True,
    rpg_rules=rpg_rules, response_length=length_directive))

section("(a) préfixe stable byte-identique entre les deux tours")
assert prefix_1 == prefix_2, "préfixe stable divergent sans transition de node"
assert sys_1.startswith(prefix_1), "le paquet servi ne commence pas par le préfixe stable"
assert sys_2.startswith(prefix_2), "le paquet servi ne commence pas par le préfixe stable"
print(f"  OK : préfixe stable identique octet pour octet ({len(prefix_1)} chars)")

section("(b) le préfixe CONTIENT « RPG MODULE (mechanics ON) » ET la directive de longueur")
assert "RPG MODULE (mechanics ON)" in prefix_1
assert length_directive in prefix_1
print("  OK : les deux sections attendues sont dans le préfixe stable")

section("(c) chacune comptée EXACTEMENT UNE FOIS dans le paquet entier")
for label, needle in (("RPG MODULE (mechanics ON)", "RPG MODULE (mechanics ON)"),
                      ("directive de longueur", length_directive)):
    for tour, sys_text in (("tour 1", sys_1), ("tour 2", sys_2)):
        n = sys_text.count(needle)
        assert n == 1, (f"{label} apparaît {n} fois au {tour} (attendu 1) — "
                        "double service (_augment_rpg/_augment_style) ?")
print("  OK : RPG MODULE et directive de longueur comptées une seule fois, "
     "chaque tour")

print("\nALL PREFIXE RPG/LONGUEUR UNIQUE (#165) CHECKS PASSED: " + ", ".join(FAIT))
