"""Issue #197 : le schisme de position — `validator.apply_world` n'écrivait
que `player.location`, tandis que l'assembleur par position et le pont MCP
lisent `state["location"]` racine (seedée une fois par la projection,
D-180). Le joueur se déplaçait sans que la scène servie suive.

Correctif : le guichet (`apply_world`) écrit désormais les DEUX champs —
compat minimale, aucun lecteur de position touché. Ce test rejoue le
scénario du banc de fumée D-264 sur une partition SYNTHÉTIQUE (D-109) :
save positionnée au node A, `apply_envelope` déplace vers B, puis
`assemble_context_to_file` ET `paquet_narrateur` doivent servir B — jamais
A. Régime dégradé (pas d'Engine chargé, comme test-paquet-narrateur-i192) :
l'application passe par `validator.apply_world` directement, la fonction du
schisme."""
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
from coderain.memory import Library

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


RENDU_A = "registre A : calme plat avant l'orage, rien ne bouge"
RENDU_B = "registre B : la tension éclate, tout s'accélère"


def _manifest():
    return Manifest(titre="module factice I-197", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="4" * 64,
                    date_conversion="2026-08-31T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-a", "scene", "Le vestibule", "Un vestibule poussiéreux.",
        "scene", anchors=[(0, 30)], rendu_md=RENDU_A))
    p.nodes.append(Node(
        "para-b", "scene", "La salle du trône", "Le trône se dresse, vide.",
        "scene", anchors=[(0, 30)], rendu_md=RENDU_B))
    p.records.append(Record(
        "sentinelle", "pnj", "Sentinelle",
        {"role": "garde", "description_md": "Une sentinelle immobile.",
         "tokens_initial": [{"node_id": "para-b", "count": 1,
                             "placement_md": "devant le trône"}]},
        anchors=[(0, 30)]))
    p.aventure = None
    return p


TMP = Path(tempfile.gettempdir()) / "se_schisme_position_i197"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)
(partition_dir / "directeur.md").write_text(
    "## Brief de direction\n\nJamais expéditif.\n", encoding="utf-8")

lib = Library(TMP / "app")
slug = lib.create_story("Test I-197", "Un donjon oublié.")
projection.derive(partition_dir, TMP / "app", slug, corpus_dir=TMP / "corpus")
sdir = lib.saves.dir(slug)
(sdir / "module.json").write_text(
    json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
store = lib.store(slug)

# Save synthétique positionnée EXPLICITEMENT au node A (au lieu du premier
# node "para-" que la projection aurait seedé) — c'est ce point de départ
# que le banc de fumée D-264 constatait figé après déplacement.
state_p = sdir / "state.json"
state = json.loads(state_p.read_text(encoding="utf-8"))
state["location"] = "para-a"
state.setdefault("player", {})["location"] = "para-a"
state_p.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                   encoding="utf-8")

mcp_server._engine = None       # régime dégradé, comme I-192
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None

section("1) départ : les deux champs pointent sur A")
st0 = store.world_state()
assert st0.get("location") == "para-a", st0.get("location")
assert st0.get("player", {}).get("location") == "para-a", st0.get("player")

section("2) apply_envelope déplace vers B (guichet validator.apply_world)")
events = mcp_server.apply_envelope(
    json.dumps({"v": 1, "deltas": {"location": "para-b"}}), rpg_on=False)
assert any("para-b" in e for e in events), events
print("  OK : événement location -> para-b journalisé")

section("3) get_world_state confirme B sur LES DEUX champs")
st1 = store.world_state()
assert st1.get("player", {}).get("location") == "para-b", st1.get("player")
assert st1.get("location") == "para-b", (
    "state racine encore figé sur A -- le schisme I-197 n'est pas corrigé : "
    f"{st1.get('location')!r}")
print("  OK : player.location ET state.location racine s'accordent sur B")

section("4) assemble_context_to_file sert la scène B, jamais A")
result = mcp_server.assemble_context_to_file("J'avance vers le trône.")
texte = Path(result["path"]).read_text(encoding="utf-8")
assert RENDU_B in texte or "La salle du trône" in texte, (
    "le paquet assemble_context_to_file reste sur le node A")
assert RENDU_A not in texte
assert "Le vestibule" not in texte
print("  OK : assemble_context_to_file suit le joueur jusqu'à B")

section("5) paquet_narrateur sert la scène B, jamais A")
result2 = mcp_server.paquet_narrateur(
    "Angle : le silence de la salle du trône.", "J'avance vers le trône.")
texte2 = Path(result2["path"]).read_text(encoding="utf-8")
assert RENDU_B in texte2, "paquet_narrateur ne sert pas la DIRECTION DE RENDU de B"
assert RENDU_A not in texte2
assert "Le vestibule" not in texte2
print("  OK : paquet_narrateur suit le joueur jusqu'à B")

print(f"\nOK test-schisme-position-i197 — {len(FAIT)} sections vertes")
