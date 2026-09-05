"""Issue #287 : étanchéité de `.turn/` entre deux parties SIMULTANÉES.

Constat #282 (README `tools/banc/README.md` § « Limite connue ») : `.turn/`
(`context.md` de `assemble_context_to_file`, `paquet-narrateur.md` de
`paquet_narrateur`) vivait sous `mcp_server.ROOT` — un seul dossier pour tout
le worktree, quel que soit le nombre de parties/Directors en vol. Deux
Directors concurrents pouvaient donc lire le paquet l'un de l'autre.

`mcp_server._turn_dir()` (Issue #287) est désormais l'UNIQUE point de
résolution : il dérive de la save CHARGÉE (`store.dir`), jamais de `ROOT`.
Ce test simule deux parties synthétiques (D-109 : zéro matériau réel)
partageant le MÊME process (le pont MCP ne porte qu'une save chargée à la
fois, `mcp_server._store`) et vérifie que le fichier écrit pour l'une
n'apparaît jamais sous le dossier `.turn/` de l'autre, avec un contenu
distinct sur disque — la preuve demandée par l'Issue : « deux parties
simulées écrivant leur contexte en même temps, contenus distincts sur
disque »."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.memory import Library

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


TMP = Path(tempfile.gettempdir()) / "se_turn_dir_etancheite_i287"
if TMP.exists():
    shutil.rmtree(TMP)

lib = Library(TMP / "app")
slug1 = lib.saves.create("Partie 01 — synthétique #287", mode="rpg",
                          premise="Prémisse UNIQUE-P1, 100% synthétique, jamais de matériau réel.")
slug2 = lib.saves.create("Partie 02 — synthétique #287", mode="rpg",
                          premise="Prémisse UNIQUE-P2, 100% synthétique, jamais de matériau réel.")
store1 = lib.saves.store(slug1)
store2 = lib.saves.store(slug2)
assert store1.dir != store2.dir, "les deux saves doivent vivre dans des dossiers distincts"

mcp_server._engine = None

# ── 1) le scratch se résout bien SOUS la save chargée, jamais ROOT ─────────
section("1) _turn_dir() dérive de store.dir, jamais de mcp_server.ROOT")
mcp_server._store = store1
d1 = mcp_server._turn_dir()
assert d1 == store1.dir / ".turn", d1
assert str(mcp_server.ROOT) != str(d1.parent), (
    f".turn/ ne doit plus vivre sous ROOT ({mcp_server.ROOT}), reçu {d1}")

mcp_server._store = store2
d2 = mcp_server._turn_dir()
assert d2 == store2.dir / ".turn", d2
assert d1 != d2, "deux saves distinctes doivent recevoir deux .turn/ distincts"
print(f"  OK : partie 1 -> {d1}\n  OK : partie 2 -> {d2}")

# ── 2) écriture réelle, en alternance (simule deux Directors concurrents) ──
section("2) assemble_context_to_file : contenus distincts, aucun croisement")
mcp_server._store = store1
r1 = mcp_server.assemble_context_to_file("Action neutre.")
mcp_server._store = store2
r2 = mcp_server.assemble_context_to_file("Action neutre.")

assert Path(r1["path"]) == store1.dir / ".turn" / "context.md", r1["path"]
assert Path(r2["path"]) == store2.dir / ".turn" / "context.md", r2["path"]
assert Path(r1["path"]) != Path(r2["path"])

texte1 = Path(r1["path"]).read_text(encoding="utf-8")
texte2 = Path(r2["path"]).read_text(encoding="utf-8")
assert "UNIQUE-P1" in texte1 and "UNIQUE-P2" not in texte1, texte1
assert "UNIQUE-P2" in texte2 and "UNIQUE-P1" not in texte2, texte2
print("  OK : context.md de chaque partie ne porte que sa propre prémisse "
      "(donc son propre monde), aucun croisement")

# ── 3) paquet_narrateur : même étanchéité, sur l'autre outil du péage ──────
section("3) paquet_narrateur : même étanchéité")
mcp_server._store = store1
p1 = mcp_server.paquet_narrateur("Visée-P1-UNIQUE.", "Action P1.", sans_mecanique=True)
mcp_server._store = store2
p2 = mcp_server.paquet_narrateur("Visée-P2-UNIQUE.", "Action P2.", sans_mecanique=True)

assert Path(p1["path"]) == store1.dir / ".turn" / "paquet-narrateur.md", p1["path"]
assert Path(p2["path"]) == store2.dir / ".turn" / "paquet-narrateur.md", p2["path"]

paquet1 = Path(p1["path"]).read_text(encoding="utf-8")
paquet2 = Path(p2["path"]).read_text(encoding="utf-8")
assert "Visée-P1-UNIQUE" in paquet1 and "Visée-P2-UNIQUE" not in paquet1, paquet1
assert "Visée-P2-UNIQUE" in paquet2 and "Visée-P1-UNIQUE" not in paquet2, paquet2
print("  OK : paquet-narrateur.md de chaque partie ne porte que sa propre directive")

# ── 4) rejouer la partie 01 après la 02 ne voit pas la trace de la 02 ──────
section("4) ré-écriture de la partie 01 : toujours son propre dossier, jamais celui de la 02")
mcp_server._store = store1
r1b = mcp_server.assemble_context_to_file("Nouvelle action P1.")
assert Path(r1b["path"]) == store1.dir / ".turn" / "context.md"
texte1b = Path(r1b["path"]).read_text(encoding="utf-8")
assert "UNIQUE-P1" in texte1b and "UNIQUE-P2" not in texte1b, texte1b
print("  OK : aucune contamination, même après une écriture croisée dans le temps")

print(f"\n{len(FAIT)} sections passées : {FAIT}")
print("\nALL TURN_DIR_ETANCHEITE TESTS PASSED")
shutil.rmtree(TMP, ignore_errors=True)
