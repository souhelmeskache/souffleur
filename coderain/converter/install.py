"""Install + doctor: wire a converted Partition into a playable save.

Campaign isolation is structural: each module gets ONE scenario and ONE save,
both slugged from the module title, and the save carries `module.json`
pointing at its own partition directory. The kit never lists, reads or
touches any other scenario — the only global action is creating its own.
"""
from __future__ import annotations

import json
from pathlib import Path

from .aval import ABILITIES_5E, get_node, get_record, load_partition

KIT_FILE = "kit.json"


def _slugify(titre: str) -> str:
    import re
    s = titre.lower()
    s = re.sub(r"[àâä]", "a", s)
    s = re.sub(r"[éèêë]", "e", s)
    s = re.sub(r"[îï]", "i", s)
    s = re.sub(r"[ôö]", "o", s)
    s = re.sub(r"[ùûü]", "u", s)
    s = re.sub(r"ç", "c", s)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")


def install(partition_dir: Path, root_dir: Path) -> dict:
    """Create scenario + rpg save bound to this partition; idempotent-ish:
    refuses to duplicate an existing kit for a DIFFERENT partition."""
    partition_dir = Path(partition_dir).resolve()
    manifest = json.loads((partition_dir / "manifest.json").read_text(
        encoding="utf-8"))
    kit_path = partition_dir / KIT_FILE
    if kit_path.exists():
        kit = json.loads(kit_path.read_text(encoding="utf-8"))
        from coderain.memory import Library
        lib0 = Library(root_dir)
        wired = (kit.get("save_slug") in [s.get("slug")
                                          for s in lib0.saves.list()]
                 and kit.get("scenario_slug") in [s.get("slug")
                                                  for s in lib0.scenarios.list()])
        if wired:
            return {**kit, "already": True, "wiring_ok": True}
        # stale wiring (save/scenario deleted): rebuild below
        kit_path.unlink()

    from coderain.memory import Library
    lib = Library(root_dir)
    slug = _slugify(manifest["titre"])
    scen_slug = lib.scenarios.create(
        f"[module] {manifest['titre']}",
        premise=f"Module solo converti par le kit P4 : {manifest['titre']}.",
        description=f"Partition P4 v{manifest.get('version_convertisseur')}, "
                    f"hash source {manifest.get('hash_source', '')[:12]}.")
    save_slug = lib.saves.create(slug, scenario_slug=scen_slug,
                                 rpg_enabled=True, mode="rpg")
    sdir = lib.saves.dir(save_slug)

    # D&D-style stats: the six abilities ARE the save's stats (identity).
    player = (sdir / "player.md").read_text(encoding="utf-8")
    lines = []
    for line in player.splitlines():
        if line.startswith("stats:"):
            line = "stats: " + ", ".join(f"{a} 0" for a in ABILITIES_5E)
        lines.append(line)
    (sdir / "player.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # pointer: this save plays THIS partition — no cross-campaign ambiguity
    module_ptr = {"partition": str(partition_dir), "titre": manifest["titre"],
                  "hash_source": manifest.get("hash_source"),
                  "scenario_slug": scen_slug}
    (sdir / "module.json").write_text(json.dumps(module_ptr, indent=1),
                                      encoding="utf-8")

    kit = {"scenario_slug": scen_slug, "save_slug": save_slug,
           "titre": manifest["titre"],
           "hash_source": manifest.get("hash_source")}
    kit_path.write_text(json.dumps(kit, indent=1), encoding="utf-8")
    return {**kit, "save_dir": str(sdir)}


def doctor(partition_dir: Path, root_dir: Path) -> dict:
    """Re-run everything cheap and deterministic; verdict PRÊT or problems."""
    problems: list[str] = []
    partition_dir = Path(partition_dir).resolve()

    # 1) structure: manifest + index + one node file readable via aval
    try:
        idx = load_partition(partition_dir)
        if not idx.get("nodes"):
            problems.append("index.json: aucun node")
        first = sorted(idx["nodes"], key=lambda n: n["id"])[0]["id"]
        node = get_node(partition_dir, first)
        if len(node.get("body") or "") < 10:
            problems.append(f"node {first}: corps vide ou illisible")
    except Exception as e:  # noqa: BLE001
        problems.append(f"partition illisible: {e}")

    # 2) kit wiring: kit.json ↔ scenario/save existent, hash cohérent
    kit_path = partition_dir / KIT_FILE
    if not kit_path.exists():
        problems.append("pas de kit.json — lance d'abord 'install'")
    else:
        kit = json.loads(kit_path.read_text(encoding="utf-8"))
        from coderain.memory import Library
        lib = Library(root_dir)
        saves = [s.get("slug") for s in lib.saves.list()]
        scens = [s.get("slug") for s in lib.scenarios.list()]
        if kit.get("save_slug") not in saves:
            problems.append(f"save absente: {kit.get('save_slug')}")
        if kit.get("scenario_slug") not in scens:
            problems.append(f"scenario absent: {kit.get('scenario_slug')}")
        sdir = lib.saves.dir(kit["save_slug"]) if kit.get("save_slug") else None
        if sdir and Path(sdir).exists():
            ptr = sdir / "module.json"
            if not ptr.exists():
                problems.append("le save ne pointe vers aucune partition "
                                "(module.json manquant)")
            elif json.loads(ptr.read_text(encoding="utf-8")).get(
                    "partition") != str(partition_dir):
                problems.append("module.json ne pointe PAS sur cette partition")
        # records readable through aval
        recs = [r["id"] for r in idx.get("records", [])]
        for rid in recs[:3]:
            try:
                get_record(partition_dir, rid)
            except Exception as e:  # noqa: BLE001
                problems.append(f"record {rid} illisible: {e}")

    verdict = "PRÊT À JOUER" if not problems else "PAS PRÊT"
    return {"verdict": verdict, "problems": problems,
            "partition": str(partition_dir)}
