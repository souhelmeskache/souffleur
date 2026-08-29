"""D-260 lane (c) — Issue #131 : l'étage scénario de la mémoire du vécu.

Chaque fold de scène ACCUMULE dans l'étage OUVERT (memory/scenario-courant.md,
`SCENARIO_STAGE_FILE`) ; `summarizer.fermer_scenario()` le REFERME et PROMEUT
UNE entrée compacte vers memory/aventure.md (`ADVENTURE_FILE`) ; l'assembleur
par position (lane a, #125) sert l'étage OUVERT seul. Partition SYNTHÉTIQUE
(D-109 : zéro matériau réel versionné) — mêmes fixtures que
test-branchement-position-d260.py.

Couvre les 4 critères testables de l'Issue #131 (le 5e = suites existantes,
`run_tests.py`) :
  1. les folds alimentent l'étage ouvert ; fermer_scenario() ⇒ l'étage fermé
     n'apparaît plus dans AUCUN paquet de l'assembleur, la promotion existe
     dans memory/aventure.md
  2. le paquet de l'assembleur porte l'étage OUVERT (jamais les notes d'un
     scénario fermé)
  3. non-régression : save sans partition => repliement octet-identique à un
     cas figé (golden fixe)
  4. mesure imprimée : chars de l'étage ouvert au fil des folds
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
from coderain import summarizer as sm_mod
from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record
from coderain.memory import ADVENTURE_FILE, Library, SCENARIO_STAGE_FILE
from coderain.summarizer import Summarizer, fermer_scenario, scenario_stage_chars

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


# --------------------------------------------------------- fixture builders --
def _manifest():
    return Manifest(titre="module factice D-260 (c)", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="2" * 64,
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
    write_partition(_build_partition(), out_dir)
    (out_dir / "directeur.md").write_text(
        "## Brief de direction\n\nReste tendu, jamais expéditif.\n",
        encoding="utf-8")
    return out_dir


def _projected_save(root: Path, partition_dir: Path, titre: str):
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon oublié.")
    projection.derive(partition_dir, root, slug, corpus_dir=root / "corpus")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    return lib, slug


class FakeLLM:
    """Jamais de vrai modèle (D-109/hors-ligne) — un JSON de scène distinct par
    appel, pour que chaque note d'étage scénario porte un contenu différent."""
    def __init__(self):
        self.n = 0

    def complete(self, messages):
        self.n += 1
        return json.dumps({
            "scene_summary": f"Résumé de scène {self.n}.",
            "state_changes": [f"garde-brutal.alerte -> niveau-{self.n}"],
            "characters": ["garde-brutal"],
        })


class Cfg:
    memory = {"medium_fold_after": 2, "medium_fold_size": 2,
              "long_fold_after": 100, "long_fold_size": 100}
    generation = {}


# --------------------------------------------------------------------- run --
TMP = Path(tempfile.gettempdir()) / "se_etage_scenario_d260"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = _write_synthetic_partition(TMP / "partition")

section("1) les folds alimentent l'étage ouvert (save AVEC partition)")
lib, slug = _projected_save(TMP / "app-a", partition_dir, "Avec partition")
store = lib.store(slug)
llm = FakeLLM()
summ = Summarizer(Cfg(), store, llm)
assert store.entries(SCENARIO_STAGE_FILE) == [], "étage non vide au départ"
chars_over_folds = []
# medium_fold_after est clampé >= 2 (Summarizer.__init__) : un tour à la fois
# jusqu'à ce que 3 folds de scène soient passés (le compte exact de tours qui
# déclenche chaque fold est un détail d'implémentation du seuil, pas de cette
# lane — voir phase2_test.py pour le même motif).
role_cycle = ["player", "narrator"]
i = 0
while len(store.entries("memory/scenes.md")) < 3 and i < 20:
    store.append_turn(role_cycle[i % 2], f"tour {i}")
    summ.maybe_fold()
    n = scenario_stage_chars(store)
    if not chars_over_folds or n != chars_over_folds[-1]:
        chars_over_folds.append(n)
    i += 1
stage = store.entries(SCENARIO_STAGE_FILE)
assert len(stage) == 3, f"attendu 3 notes d'étage, obtenu {len(stage)}"
assert all("delta" not in e.render().lower() for e in stage), \
    "mot réservé 'delta' (D-118) trouvé dans une note d'étage"
print(f"  OK : {len(stage)} notes d'étage, chars au fil des folds : "
     f"{chars_over_folds}")

section("2) mesure imprimée : chars de l'étage ouvert au fil des folds")
assert chars_over_folds == sorted(chars_over_folds)  # croissance monotone
for i, n in enumerate(chars_over_folds, start=1):
    print(f"  fold {i} : étage ouvert = {n} chars")
assert chars_over_folds[-1] > chars_over_folds[0], "l'étage n'a pas accumulé"

section("3) lecteur : le paquet porte l'étage OUVERT (assembleur_position)")
history = [{"role": "player", "text": "J'observe la porte."}]
sections_before = ap.build_sections(partition_dir, store, "para-01", history,
                                    "Je pousse la porte.")
world_section = next(s for s in sections_before
                     if s.title.startswith("État du monde"))
assert "Étage scénario" in world_section.text
for note in stage:
    assert note.body.strip() in world_section.text, \
        f"note d'étage absente du paquet : {note.body!r}"
assert "Dernières scènes" not in world_section.text, \
    "la file de scène brute n'a pas été remplacée par l'étage scénario"
print("  OK : les 3 notes de l'étage ouvert sont servies, jamais la file de "
     "scène brute")

section("4) fermer_scenario() : promotion + étage fermé physiquement inerte")
old_notes_text = [n.body.strip() for n in stage]
events = fermer_scenario(store)
assert any("clos" in e and ADVENTURE_FILE in e for e in events), events
assert store.entries(SCENARIO_STAGE_FILE) == [], \
    "l'étage doit être vide juste après la fermeture"
promoted = store.entries(ADVENTURE_FILE)
assert len(promoted) == 1, f"attendu 1 promotion, obtenu {len(promoted)}"
for txt in old_notes_text:
    assert txt in promoted[0].body, f"note perdue à la promotion : {txt!r}"
# aucun paquet de l'assembleur ne sert plus l'étage fermé :
sections_after = ap.build_sections(partition_dir, store, "para-01", history,
                                   "Je pousse la porte.")
rendered_after = "\n\n".join(s.render() for s in sections_after)
for txt in old_notes_text:
    assert txt not in rendered_after, \
        f"une note du scénario fermé fuite encore dans le paquet : {txt!r}"
world_after = next(s for s in sections_after
                   if s.title.startswith("État du monde"))
assert "aucune scène close" in world_after.text
print(f"  OK : promotion unique vers {ADVENTURE_FILE}, étage fermé absent de "
     "tout paquet de l'assembleur")

section("5) l'étage rouvre avec le fold suivant, jamais les notes closes")
store.append_turn("player", "action 3")
store.append_turn("narrator", "narration 3")
summ.maybe_fold()
reopened = store.entries(SCENARIO_STAGE_FILE)
assert len(reopened) == 1, f"attendu 1 nouvelle note, obtenu {len(reopened)}"
for txt in old_notes_text:
    assert txt not in reopened[0].body, "une note close a refait surface"
sections_reopened = ap.build_sections(partition_dir, store, "para-01",
                                      history, "Je pousse la porte.")
world_reopened = next(s for s in sections_reopened
                      if s.title.startswith("État du monde"))
assert reopened[0].body.strip() in world_reopened.text
print("  OK : la nouvelle note (post-fermeture) est servie, aucune ancienne "
     "note du scénario clos")

section("6) non-régression : save SANS partition, repliement octet-identique")
lib_b = Library(TMP / "app-b")
slug_b = lib_b.create_story("Sans partition", "Une taverne ordinaire.")
store_b = lib_b.store(slug_b)
assert not ap.eligible(store_b, store_b.world_state())
llm_b = FakeLLM()
summ_b = Summarizer(Cfg(), store_b, llm_b)
for i in range(3):
    store_b.append_turn("player", f"action {i}")
    store_b.append_turn("narrator", f"narration {i}")
    events_b = summ_b.maybe_fold()
    assert not any("étage scénario" in e for e in events_b), events_b
assert store_b.entries(SCENARIO_STAGE_FILE) == [], \
    "l'étage scénario ne doit jamais s'alimenter sans partition/position"
assert store_b.read(SCENARIO_STAGE_FILE) == "", \
    "aucune écriture ne doit toucher scenario-courant.md sans partition"
assert store_b.entries(ADVENTURE_FILE) == []
GOLDEN_SCENES = (
    "# Scene summaries (medium-term)\n\n"
    "Filled by the summarizer as scenes close. Reference entities by "
    "name/slug only.\n\n"
    "## Scene 1  {#scene-1}\nimportance: 3\nturns: 1-2\n"
    "when: Day 1, morning\ncharacters: garde-brutal\n"
    "state_changes: garde-brutal.alerte -> niveau-1\nday: 1\n\n"
    "Résumé de scène 1.\n\n"
    "## Scene 2  {#scene-2}\nimportance: 3\nturns: 3-4\n"
    "when: Day 1, morning\ncharacters: garde-brutal\n"
    "state_changes: garde-brutal.alerte -> niveau-2\nday: 1\n\n"
    "Résumé de scène 2.\n")
assert store_b.read("memory/scenes.md") == GOLDEN_SCENES, \
    store_b.read("memory/scenes.md")
print("  OK : étage scénario intouché, memory/scenes.md octet-identique au "
     "cas figé")

print("\nALL D-260 (c) CHECKS PASSED: " + ", ".join(FAIT))
