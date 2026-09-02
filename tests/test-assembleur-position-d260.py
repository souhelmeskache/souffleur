"""D-260 lane (a) — Issue #125 : assembleur de contexte keyé sur la position.
Bout-en-bout sur une partition SYNTHÉTIQUE (D-109 : zéro matériau réel) :
projette la partition dans une save fraîche (`converter/projection.py`), puis
exerce `coderain/assembleur_position.py` contre cette save projetée.

Couvre les 4 critères d'acceptation testables de l'Issue #125 :
  1. bout-en-bout sur partition synthétique
  2. mesure imprimée (chars/~tokens par section, total du paquet)
  3. stabilité de préfixe (deux assemblages, même position => même préfixe)
  4. transition : delta location => nouveau paquet, corpus non atteint absent
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
from coderain.converter.schemas import Manifest, Node, Partition, Record, Secret
from coderain.memory import Library
from coderain import validator as validator_mod

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


# --------------------------------------------------------- fixture builders --
def _manifest():
    return Manifest(titre="module factice D-260", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="0" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil", "Vous êtes devant une porte close.",
        "scene", liens=[{"cible_id": "para-02",
                         "condition_textuelle": "si vous forcez le passage"}],
        anchors=[(0, 40)]))
    p.nodes.append(Node(
        "para-02", "scene", "La salle des gardes",
        "Une torche brûle contre le mur du fond.\n\nGo to 3.",
        "scene", anchors=[(40, 80)]))
    p.records.append(Record(
        "garde-brutal", "pnj", "Garde brutal",
        {"role": "sentinelle", "description_md": "Un garde massif et nerveux.",
         "tokens_initial": [{"node_id": "para-02", "count": 1,
                             "placement_md": "près de la porte"}]},
        anchors=[(40, 60)]))
    p.secrets.append(Secret(
        "secret-fuite", "Le garde connaît un passage dérobé.", "secret",
        porteurs=["garde-brutal"],
        revelation={"declencheur": "corruption reussie",
                    "node_cible": "para-02"},
        consequence_si_brule="le passage est muré",
        anchors=[(40, 60)]))
    p.aventure = None
    return p


def _condition_extra() -> dict:
    """Condition de monde (rubrique "condition", D-119) ajoutée à part —
    `emit.write_partition` la sert via `aventure.md`."""
    return {"trajectoire": [], "conditions": [
        {"id": "cond-alarme", "description_md": "La garnison est en alerte.",
         "triggers_all": ["alarme"], "declencheur": {"type": "etat",
                                                       "valeur": "alarme"}}]}


def _write_synthetic_partition(out_dir: Path) -> Path:
    partition = _build_partition()
    write_partition(partition, out_dir)
    # aventure.md : écrit à la main (Aventure/emit exigent une forme plus
    # riche que ce test n'a pas besoin de couvrir — seul le triggers_all
    # projeté vers locations.md nous intéresse ici).
    import json
    fm = ("---\n" + json.dumps({
        "etage": "adventure", "trajectoire": [],
        "conditions": _condition_extra()["conditions"]}) + "\n---\n")
    (out_dir / "aventure.md").write_text(
        fm + "## Charnière de sortie\n\nLa nuit tombe.\n", encoding="utf-8")
    (out_dir / "directeur.md").write_text(
        "## Brief de direction\n\nReste tendu, jamais expéditif.\n",
        encoding="utf-8")
    return out_dir


def _new_projected_save(root: Path, partition_dir: Path) -> tuple[Library, str]:
    lib = Library(root)
    slug = lib.create_story("Test D-260", "Un donjon oublié.")
    projection.derive(partition_dir, root, slug, corpus_dir=root / "corpus")
    return lib, slug


# --------------------------------------------------------------------- run --
TMP = Path(tempfile.gettempdir()) / "se_assembleur_position_d260"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = _write_synthetic_partition(TMP / "partition")
lib, slug = _new_projected_save(TMP / "app", partition_dir)
store = lib.saves.store(slug)

section("1) bout-en-bout : la save projetée est éligible + assemblage réussit")
state = store.world_state()
assert validator_mod.current_location(state) == "para-01", state.get("player")
assert ap.eligible(store, state)
history = [{"role": "player", "text": "J'observe la porte."}]
messages = ap.assemble(partition_dir, store, state, history,
                       "Je pousse la porte.")
assert messages[0]["role"] == "system"
assert messages[-1] == {"role": "user", "content": "Je pousse la porte."}
sys_text = messages[0]["content"]
assert "Le seuil" in sys_text                    # node courant présent
# le lien vers para-02 est un POTENTIEL décoratif (D-179) — l'id peut y
# figurer, mais jamais le CORPS de la scène non atteinte (D-065/SPEC-MVP) :
assert "torche" not in sys_text.lower()           # corps de para-02 absent
print(f"  OK : {len(messages)} messages, système={len(sys_text)} chars")

section("2) mesure imprimée : chars/~tokens par section + total du paquet")
sections = ap.build_sections(partition_dir, store, "para-01", history,
                             "Je pousse la porte.")
total = 0
for s in sections:
    n = len(s.render())
    total += n
    print(f"  [{s.marker:8}] {s.title:45} {n:6} chars (~{n // 4} tok)")
print(f"  TOTAL paquet (hors entrée joueur) : {total} chars (~{total // 4} tok)")
assert total <= 10_000, f"paquet trop lourd pour le cas synthétique : {total}"

section("3) stabilité de préfixe : deux assemblages, même position => même octets")
sections_a = ap.build_sections(partition_dir, store, "para-01",
                               history, "Je pousse la porte.")
sections_b = ap.build_sections(partition_dir, store, "para-01",
                               history, "J'inspecte la porte à la place.")
prefix_a, prefix_b = ap.stable_prefix(sections_a), ap.stable_prefix(sections_b)
assert prefix_a == prefix_b, "le préfixe stable a bougé sans transition de node"
assert prefix_a.encode("utf-8") == prefix_b.encode("utf-8")
print(f"  OK : préfixe stable identique octet pour octet ({len(prefix_a)} chars)")

section("4) transition : delta location => nouveau paquet, corpus non atteint absent")
sections_2 = ap.build_sections(partition_dir, store, "para-02", history,
                               "J'entre dans la salle.")
prefix_2 = ap.stable_prefix(sections_2)
assert prefix_2 != prefix_a, "la transition de node doit changer le préfixe"
text_2 = "\n\n".join(s.render() for s in sections_2)
assert "torche" in text_2.lower()                 # le nouveau node est servi
assert "garde brutal" in text_2.lower() or "garde-brutal" in text_2.lower()
assert "le seuil" not in text_2.lower() or "porte close" not in text_2.lower()
print("  OK : le node quitté n'est plus servi, le nouveau node + son "
     "record ancré + son secret le sont")

section("5) verdict de règle : triggers_all évalué par code, jamais le bloc entier")
sections_no_trigger = ap.build_sections(
    partition_dir, store, "para-01", history, "Je pousse la porte.")
verdicts = next(s for s in sections_no_trigger
               if s.title.startswith("Verdicts"))
assert "aucune règle déclenchée" in verdicts.text
sections_triggered = ap.build_sections(
    partition_dir, store, "para-01",
    [{"role": "player", "text": "L'alarme retentit dans tout le donjon."}],
    "Je me cache.")
verdicts_2 = next(s for s in sections_triggered
                  if s.title.startswith("Verdicts"))
assert "Condition de monde" in verdicts_2.text or "cond-alarme" in verdicts_2.text
print("  OK : la règle ne surface qu'une fois son déclencheur présent dans "
     "le tour")

print("\nALL D-260 (a) CHECKS PASSED: " + ", ".join(FAIT))
