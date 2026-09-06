"""I-469 §F0.4 (Issue #332) — journalisation de la taille du paquet servi,
par tour, dans `events.jsonl` : `mcp_server._log_paquet`, appelé par les deux
outils qui écrivent le paquet du narrateur/Director dans un FICHIER plutôt
que dans une fenêtre (`assemble_context_to_file`, `paquet_narrateur`).

Tranche la contradiction « 83% au tour 1 » (Haiku, écran) ⊥ « 53k » (I-467) :
avec cette lane, `events.jsonl` porte un chiffre LU (`chars`/`tokens_est`),
jamais une hypothèse — voir `docs/mesure-i158-director-deux-corps.md`
(mesure hors ligne, ≈ 19 300 jetons, qui a précédé cette instrumentation en
ligne).

Convention `tokens_est` : 1 jeton ≈ 4 caractères (déjà en usage,
`coderain/memory.py`, budgets jetons -> caractères), ici inversée
(caractères -> jetons), division entière — jamais un vrai compte de
tokenizer.

Partition SYNTHÉTIQUE (D-109), même fixture que
`test-pont-mcp-position-d260.py` (chemin par position, D-260/#146) + une save
sans partition (chemin `_assemble_text`, legacy) pour couvrir les deux
chemins d'`assemble_context_to_file`.
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


def _manifest():
    return Manifest(titre="module factice I-469 paquet", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="3" * 64,
                    date_conversion="2026-09-06T00:00:00+00:00",
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


def _projected_save(root: Path, partition_dir: Path, titre: str):
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon oublié.")
    projection.derive(partition_dir, root, slug, corpus_dir=root / "corpus")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    return lib, slug


def _events(store) -> list[dict]:
    path = store.dir / "memory" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


TMP = Path(tempfile.gettempdir()) / "se_mesure_paquet_i469"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = _write_synthetic_partition(TMP / "partition")

mcp_server._engine = None

section("1) save AVEC position+partition — assemble_context_to_file journalise un paquet")
lib_a, slug_a = _projected_save(TMP / "app-a", partition_dir, "Avec partition")
store_a = lib_a.store(slug_a)
mcp_server._store = store_a
mcp_server._slug = slug_a

result = mcp_server.assemble_context_to_file("Je pousse la porte.")
after_text = Path(result["path"]).read_text(encoding="utf-8")
events = _events(store_a)
paquets = [e for e in events if e.get("type") == "paquet"]
assert len(paquets) == 1, paquets
p0 = paquets[0]
assert p0["outil"] == "assemble_context_to_file", p0
assert p0["turn"] == 1, p0                      # aucun tour encore enregistré
assert p0["chars"] == len(after_text), p0
assert p0["tokens_est"] == len(after_text) // 4, p0
assert p0["sections"] == {}, p0                 # ce chemin ne distingue pas les sections
print(f"  paquet journalisé : {p0['chars']} chars / {p0['tokens_est']} jetons estimés")

section("1b) un second appel journalise un second événement, jamais un écrasement")
mcp_server.assemble_context_to_file("Je frappe à la porte.")
events2 = _events(store_a)
paquets2 = [e for e in events2 if e.get("type") == "paquet"]
assert len(paquets2) == 2, paquets2
print("  OK : events.jsonl s'append (deux tours -> deux entrées paquet)")

section("2) save SANS partition — même journalisation (chemin _assemble_text)")
lib_b = Library(TMP / "app-b")
slug_b = lib_b.create_story("Sans partition", "Une taverne ordinaire.")
store_b = lib_b.store(slug_b)
mcp_server._store = store_b
mcp_server._slug = slug_b
assert mcp_server._partition_dir(store_b) is None

result_b = mcp_server.assemble_context_to_file("Je m'assois.")
text_b = Path(result_b["path"]).read_text(encoding="utf-8")
events_b = [e for e in _events(store_b) if e.get("type") == "paquet"]
assert len(events_b) == 1, events_b
assert events_b[0]["chars"] == len(text_b)
assert events_b[0]["tokens_est"] == len(text_b) // 4
print("  OK : chemin legacy journalise aussi (même helper _log_paquet)")

section("3) paquet_narrateur journalise avec un détail par section")
lib_c = Library(TMP / "app-c")
slug_c = lib_c.create_story("Narrateur", "Un couloir sombre.")
store_c = lib_c.store(slug_c)
mcp_server._store = store_c
mcp_server._slug = slug_c
mcp_server._last_applied_events = ["engine: hp -1"]   # R1 satisfait

result_c = mcp_server.paquet_narrateur("Le garde s'avance.", "Je recule.")
full_c = Path(result_c["path"]).read_text(encoding="utf-8")
events_c = [e for e in _events(store_c) if e.get("type") == "paquet"]
assert len(events_c) == 1, events_c
p_c = events_c[0]
assert p_c["outil"] == "paquet_narrateur", p_c
assert p_c["chars"] == len(full_c), p_c
assert p_c["tokens_est"] == len(full_c) // 4, p_c
assert isinstance(p_c["sections"], dict) and p_c["sections"], p_c
assert sum(p_c["sections"].values()) <= p_c["chars"], p_c   # sections + séparateurs "\n\n" = full
print(f"  sections journalisées : {list(p_c['sections'].keys())}")

print("\nALL I-469 PAQUET (#332) CHECKS PASSED: " + ", ".join(FAIT))
