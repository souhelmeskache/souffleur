"""Chantier 5 (chemin MCP du régime principal, sujet 3/4) : les outils
`module_*`, appelés par leur nom d'outil MCP — nommés par
`coderain/roles/director.md` d'abord (`module_get_node`, `module_get_record`,
`module_get_aventure`), puis `module_index`, `module_list_nodes`,
`module_roll_table`.

Mesuré avant d'écrire ce test (Grep `tests/`) :
  - `module_index` : couvert par `tests/test-pval-bout-en-bout.py`, mais par
    l'appel INTERNE `coderain.converter.aval.load_partition(tmp_dir)`,
    jamais par l'outil MCP `mcp_server.module_index()` lui-même (qui résout
    `_module_partition()`, c-à-d le `module.json` de la save CHARGÉE).
  - `module_list_nodes`, `module_get_node`, `module_get_record`,
    `module_roll_table`, `module_get_aventure` : AUCUNE couverture, à
    aucun niveau.
Ce fichier comble ces deux trous : chaque outil est appelé par
`mcp_server.<outil>(...)` (le même objet que `@mcp_server.mcp.tool()`
enregistre sous ce nom — revérifié au point 0 via `mcp.list_tools()`), sur
une save dont `module.json` pointe une partition 100 % synthétique (D-109).

Couvre :
  0. Les six outils existent au serveur MCP, sous ces noms exacts.
  1. `module_index`/`module_list_nodes` : la forme attendue (nodes/records/
     tables/secrets), le nœud et le record synthétiques y figurent.
  2. `module_get_node` : corps + liens du nœud, verbatim.
  3. `module_get_record` : stats 5e du record, verbatim.
  4. `module_roll_table` : la table + la ligne résolue pour un résultat de
     dé donné.
  5. `module_get_aventure` : la charnière de sortie, verbatim.
  6. Un identifiant inconnu, sur CHACUN des quatre outils paramétrés par id
     (`module_get_node`, `module_get_record`, `module_roll_table` — et,
     tenu pour mémoire, le cas sans save chargée pour `module_get_aventure`)
     rend un refus NOMMÉ (`{"error": ...}`), jamais une exception brute qui
     remonterait crue au Director.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter.emit import write_partition
from coderain.converter.schemas import (Aventure, Manifest, Node, Partition,
                                         Record, RollTable)
from coderain.memory import Library

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


DIRECTOR_MD = ROOT / "coderain" / "roles" / "director.md"
CHARNIERE = "Le seuil se referme derrière vous, sans retour possible."


def _manifest():
    return Manifest(titre="module factice chantier 5/3", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="8" * 64,
                    date_conversion="2026-10-11T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil", "Une porte de fer, close.",
        "scenario", liens=[{"cible_id": "para-02",
                           "condition_textuelle": "pousser la porte"}],
        anchors=[(0, 30)]))
    p.nodes.append(Node(
        "para-02", "scene", "Le couloir", "Un couloir de pierre humide.",
        "scene", anchors=[(30, 60)]))
    p.records.append(Record(
        "gobelin-sentinelle", "creature", "Gobelin sentinelle",
        {"ca": "14", "pv": "11", "vitesse": "30", "attaque_bonus": "3",
         "degats": "4 (1d6+1) slashing"},
        anchors=[(0, 30)]))
    p.tables.append(RollTable(
        "butin-coffre", "1d6",
        [{"plage_debut": 1, "plage_fin": 3, "resultat_md": "Rien d'utile."},
         {"plage_debut": 4, "plage_fin": 6, "resultat_md": "Une bourse de "
          "pièces d'argent."}],
        anchors=[(0, 10)]))
    p.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Le gardien rôde.",
          "declencheur": {"type": "etat", "valeur": "debut"},
          "ancres_sources": [[0, 10]]}],
        [], CHARNIERE)
    return p


TMP = Path(tempfile.gettempdir()) / "se_mcp_outils_module_chantier5"
if TMP.exists():
    shutil.rmtree(TMP)

_saves_root_avant = mcp_server._saves_root

try:
    partition_dir = TMP / "partition"
    write_partition(_build_partition(), partition_dir)

    lib = Library(TMP / "app")
    slug = lib.saves.create("Chantier5-3", premise="Un donjon muet.")
    (lib.saves.dir(slug) / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    store = lib.store(slug)

    mcp_server._store = store
    mcp_server._slug = slug
    # `_module_partition()` résout via `_saves_root / _slug / module.json` —
    # un chemin GLOBAL au serveur, jamais dérivé de `store.dir` (contraste
    # avec `_partition_dir`). Sur une fixture hors du vrai saves_root, il
    # faut pointer `_saves_root` vers la racine `saves/` de CETTE
    # bibliothèque synthétique, ou l'outil chercherait dans le dossier
    # `saves/` réel du dépôt.
    mcp_server._saves_root = lib.saves.root

    tool_names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    for outil in ("module_index", "module_list_nodes", "module_get_node",
                 "module_get_record", "module_roll_table",
                 "module_get_aventure"):
        assert outil in tool_names, f"{outil} absent du serveur MCP"
    section("0) les six outils module_* existent au serveur MCP")

    # --- 1) module_index / module_list_nodes -------------------------------
    idx = mcp_server.module_index()
    assert not idx.get("error"), idx
    ids_nodes = {n["id"] for n in idx["nodes"]}
    assert {"para-01", "para-02"} <= ids_nodes, idx["nodes"]
    ids_records = {r["id"] for r in idx["records"]}
    assert "gobelin-sentinelle" in ids_records, idx["records"]
    ids_tables = {t["id"] for t in idx["tables"]}
    assert "butin-coffre" in ids_tables, idx["tables"]
    section(f"1a) module_index() -> {len(idx['nodes'])} nœud(s), "
           f"{len(idx['records'])} record(s), {len(idx['tables'])} table(s)")

    nodes = mcp_server.module_list_nodes()
    assert {n["id"] for n in nodes} >= {"para-01", "para-02"}, nodes
    section(f"1b) module_list_nodes() -> {[n['id'] for n in nodes]}")

    # --- 2) module_get_node : corps + liens verbatim ------------------------
    node = mcp_server.module_get_node("para-01")
    assert not node.get("error"), node
    assert "Une porte de fer, close." in node["body"], node
    assert node["meta"]["liens"] == [
        {"cible_id": "para-02", "condition_textuelle": "pousser la porte"}], \
        node["meta"]
    section(f"2) module_get_node('para-01') -> corps + liens verbatim "
           f"({node['meta']['liens']})")

    # --- 3) module_get_record : stats 5e verbatim ---------------------------
    rec = mcp_server.module_get_record("gobelin-sentinelle")
    assert not rec.get("error"), rec
    assert rec["stats"]["ca"] == "14" and rec["stats"]["pv"] == "11", rec
    assert rec["stats"]["degats"] == "4 (1d6+1) slashing", rec
    section(f"3) module_get_record('gobelin-sentinelle') -> stats 5e "
           f"verbatim ({rec['stats']})")

    # --- 4) module_roll_table : table + ligne résolue -----------------------
    table_sans_de = mcp_server.module_roll_table("butin-coffre")
    assert not table_sans_de.get("error"), table_sans_de
    assert table_sans_de["de"] == "1d6", table_sans_de
    assert len(table_sans_de["entrees"]) == 2, table_sans_de
    assert table_sans_de["resultat"] is None, \
        "sans die_result, aucune ligne ne doit être résolue"
    section("4a) module_roll_table('butin-coffre') (sans dé) -> table "
           f"lue, {len(table_sans_de['entrees'])} ligne(s), resultat=None")

    table_avec_de = mcp_server.module_roll_table("butin-coffre", die_result=5)
    assert table_avec_de["resultat"]["resultat_md"] == \
        "Une bourse de pièces d'argent.", table_avec_de
    section(f"4b) module_roll_table('butin-coffre', die_result=5) -> ligne "
           f"résolue ({table_avec_de['resultat']['resultat_md']!r})")

    # --- 5) module_get_aventure : charnière verbatim ------------------------
    av = mcp_server.module_get_aventure()
    assert not av.get("error"), av
    assert av["charniere_md"] == CHARNIERE, av
    assert isinstance(av.get("trajectoire"), list) and av["trajectoire"], av
    section(f"5) module_get_aventure() -> charnière verbatim ({av['charniere_md']!r})")

    # --- 6) identifiant inconnu : refus NOMMÉ, jamais une exception brute --
    for outil, args in (
        ("module_get_node", ("id-inexistant",)),
        ("module_get_record", ("id-inexistant",)),
        ("module_roll_table", ("id-inexistant",)),
    ):
        fn = getattr(mcp_server, outil)
        try:
            res = fn(*args)
        except Exception as exc:  # noqa: BLE001 — précisément ce qui est interdit
            raise AssertionError(
                f"{outil}('id-inexistant') a laissé fuiter une exception "
                f"brute ({type(exc).__name__}: {exc}) au lieu d'un refus "
                f"nommé") from exc
        assert isinstance(res, dict) and res.get("error"), \
            f"{outil}('id-inexistant') devrait rendre {{'error': ...}} -> {res!r}"
    section("6) module_get_node/module_get_record/module_roll_table sur un "
           "identifiant inconnu : {'error': ...} nommé, jamais d'exception "
           "brute")

    # --- garde anti-dérive : chaque module_* cité par director.md existe --
    import re
    role_text = DIRECTOR_MD.read_text(encoding="utf-8")
    outils_role = set(re.findall(r"`(module_[A-Za-z_]+)\(", role_text))
    assert outils_role & {"module_get_node", "module_get_record",
                          "module_get_aventure"}, \
        ("coderain/roles/director.md devrait citer au moins module_get_node/"
         "module_get_record/module_get_aventure (ordre donné par la "
         f"consigne) -> {outils_role}")
    manquants = sorted(outils_role - tool_names)
    assert not manquants, \
        f"outil(s) module_* cité(s) par director.md absent(s) du serveur MCP : {manquants}"
    section(f"7) garde anti-dérive : chaque module_* cité par director.md "
           f"existe au serveur MCP ({sorted(outils_role)})")

    print(f"\nOK test-mcp-outils-module-par-nom-chantier5 — {len(FAIT)} "
         "sections vertes")
finally:
    mcp_server._saves_root = _saves_root_avant
    mcp_server._store = None
    mcp_server._slug = ""
    shutil.rmtree(TMP, ignore_errors=True)
