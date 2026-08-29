"""D-260 lane (Issue #146) : le pont MCP passe au chemin par position pour
`assemble_context_to_file` — même sélection que `engine._messages()`
(`assembleur_position`, PR #130), jamais l'ancien assemblage par mots-clés +
budget. Partition SYNTHÉTIQUE (D-109 : zéro matériau réel versionné).

Couvre les critères testables de l'Issue #146 (le 4e = suites existantes,
`run_tests.py`) :
  1. save AVEC position+partition -> le fichier de contexte MCP porte les
     sections par position (jamais le lorebook entier, jamais
     event_rules_block() entier), et honore le contrat
     event_rules=False/secrets=False (compteur secrets_suppressed)
  2. mesure imprimée : chars du fichier servi AVANT (ancien chemin,
     `_assemble_text` appelé directement sur la même save) / APRÈS (nouveau
     chemin, `assemble_context_to_file`) — la symétrie avec la mesure
     pipeline (docs/mesure-d260-boucle-neuve.md) se constate
  3. save SANS partition -> comportement inchangé (même sortie qu'un appel
     direct de `_assemble_text`, golden octet-identique)
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


# --------------------------------------------------------- fixture builders --
def _manifest():
    return Manifest(titre="module factice D-260 pont MCP", corpus_source="5e",
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
    partition = _build_partition()
    write_partition(partition, out_dir)
    (out_dir / "directeur.md").write_text(
        "## Brief de direction\n\nReste tendu, jamais expéditif.\n",
        encoding="utf-8")
    return out_dir


def _projected_save(root: Path, partition_dir: Path, titre: str) -> tuple[Library, str]:
    """Même contrat que `converter/install.py` pose à l'installation
    (`module.json`), écrit à la main ici — hors périmètre du convertisseur."""
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon oublié.")
    projection.derive(partition_dir, root, slug, corpus_dir=root / "corpus")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    return lib, slug


# --------------------------------------------------------------------- run --
TMP = Path(tempfile.gettempdir()) / "se_pont_mcp_position_d260"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = _write_synthetic_partition(TMP / "partition")

mcp_server._engine = None  # pas d'Engine chargé -- le pont doit s'en passer

section("1) save AVEC position+partition -> assemble_context_to_file bascule")
lib_a, slug_a = _projected_save(TMP / "app-a", partition_dir, "Avec partition")
store_a = lib_a.store(slug_a)
# Règle d'événement toujours candidate (aucun triggers_all -> permanente) —
# pour vérifier qu'elle reste ABSENTE par défaut (event_rules=False) et que
# get_event_rules() la sert encore, elle, intacte (legacy/debug).
store_a.upsert_entry("events.md", Entry(
    title="Vigilance constante", slug="event-vigilance",
    attrs={}, body="Le donjon reste sur ses gardes."))
mcp_server._store = store_a
mcp_server._slug = slug_a

assert mcp_server._partition_dir(store_a) == partition_dir
state_a = store_a.world_state()
from coderain import assembleur_position as ap
assert ap.eligible(store_a, state_a)

# "avant" -- l'ancien chemin, toujours joignable directement (non branché).
before_text, _before_info = mcp_server._assemble_text(
    "Je pousse la porte.", 120000, event_rules=False, secrets=False)

result = mcp_server.assemble_context_to_file("Je pousse la porte.")
after_text = Path(result["path"]).read_text(encoding="utf-8")
assert "Scène courante" in after_text                  # section assembleur_position
assert "Le seuil" in after_text                        # node courant présent
assert "SCENARIO EVENT RULES" not in after_text, \
    "event_rules=False doit garder les verdicts hors du fichier"
assert "Vigilance constante" not in after_text, \
    "la règle d'événement ne doit pas fuiter sans event_rules=True"
assert "### Secrets connus" not in after_text, \
    "secrets=False doit garder la sous-section Secrets hors du fichier"
assert result["secrets_suppressed"] is True
print(f"  AVANT (ancien chemin, même save) : {len(before_text)} chars")
print(f"  APRÈS (chemin position)          : {len(after_text)} chars")

section("1b) get_event_rules reste joignable (legacy/debug) sur cette save")
rules_text = mcp_server.get_event_rules()
assert "Vigilance constante" in rules_text, \
    "get_event_rules() doit encore servir le bloc entier à la demande"

section("1c) event_rules=True -> verdicts du tour, jamais le bloc entier")
result_ev = mcp_server.assemble_context_to_file(
    "Je pousse la porte.", event_rules=True)
after_ev = Path(result_ev["path"]).read_text(encoding="utf-8")
assert "Vigilance constante" in after_ev, \
    "règle permanente (sans triggers_all) doit rester candidate ce tour"
assert after_ev.count("SCENARIO EVENT RULES") == 1
print("  OK : verdicts du tour présents une seule fois, pas de doublon")

section("2) save SANS partition -> _assemble_text inchangé (golden)")
lib_b = Library(TMP / "app-b")
slug_b = lib_b.create_story("Sans partition", "Une taverne ordinaire.")
store_b = lib_b.store(slug_b)
mcp_server._store = store_b
mcp_server._slug = slug_b
assert mcp_server._partition_dir(store_b) is None

direct_text, direct_info = mcp_server._assemble_text(
    "Je m'assois.", 120000, event_rules=False, secrets=False)
result_b = mcp_server.assemble_context_to_file("Je m'assois.")
bridged_text = Path(result_b["path"]).read_text(encoding="utf-8")
assert bridged_text == direct_text, \
    "le chemin non-partition a divergé de _assemble_text (régression)"
for k in ("degraded", "reason", "lore_blocks", "secrets", "secrets_suppressed",
         "hidden_total", "echoes", "secrets_window", "lore_selected"):
    assert result_b[k] == direct_info[k], f"info[{k!r}] a divergé"
print("  OK : fichier octet-identique à un appel direct de _assemble_text")

print("\nALL D-260 PONT MCP POSITION (#146) CHECKS PASSED: " + ", ".join(FAIT))
