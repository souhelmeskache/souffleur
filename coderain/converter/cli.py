"""One integrated command: python -m coderain.converter <cmd>

  convert <pdf|txt> [--titre T]   extract -> convert -> validate -> emit
  install <partition_dir>         scenario + rpg save wired to the partition
  doctor  <partition_dir>         re-check everything; verdict PRÊT À JOUER
  all     <pdf|txt> [--titre T]   the whole kit in one shot

Every step writes its facts (manifest, rapport, kit.json) NEXT TO the module,
so campaigns never mix: one partition directory = one module = one save.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# data home: OUTSIDE the repo (no material ever enters git) — D-178 session
# decision 2026-08-22. Override with env CODERAIN_CORPUS if the vault moves.
import os
CORPUS = Path(os.environ.get(
    "CODERAIN_CORPUS",
    r"C:\Vaults\MVP2\Migration Coderain\kit-p4"))

from coderain.converter import s1_local                      # noqa: E402
from coderain.converter import validate_fidelity             # noqa: E402
from coderain.converter import validate_form                 # noqa: E402
from coderain.converter.aval import extract_checks, write_checks  # noqa: E402
from coderain.converter.emit import write_partition          # noqa: E402
from coderain.converter.exceptions import build, render_md, write_report  # noqa: E402
from coderain.converter.ruletables import RuleTables         # noqa: E402
from coderain.converter.schemas import Manifest, Partition, Record  # noqa: E402


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pymupdf
        return "\n\n".join(p.get_text() for p in pymupdf.open(str(path)))
    return path.read_text(encoding="utf-8")


def cmd_convert(src: Path, out_dir: Path, titre: str | None = None) -> dict:
    text = _extract_text(src)
    units = s1_local.segment_s1(text)
    cov0 = validate_fidelity.coverage_report(units, [], len(text))
    assert not cov0["gaps"] and not cov0["overlaps"], cov0
    manifest = Manifest(
        titre=titre or src.stem.replace("_", "-").replace("-", " ").strip().title(),
        corpus_source="5e", corpus_cible="5e", structures=["S1"],
        hash_source=__import__("hashlib").sha256(
            text.encode("utf-8")).hexdigest(),
        date_conversion=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        version_convertisseur="0.1.0+local")

    partition = Partition(manifest)
    tables_rule = RuleTables("5e")
    id_by_num = {int(u.titre[1:]): u.uid for u in units
                 if u.uid.startswith("para-")}
    for u in units:
        partition.nodes.append(s1_local.node_for_unit(u, text, id_by_num))

    # authored records: judgment supplied as records-auteur.json in the corpus
    # home (or next to the source); anchors computed here by locating the
    # name in the text — deterministic, and coverage already holds via nodes
    for candidate in (CORPUS / "records-auteur.json",
                      src.parent / "records-auteur.json"):
        if candidate.exists():
            for raw in json.loads(candidate.read_text(encoding="utf-8")):
                idx = text.find(raw["nom"])
                if idx < 0:
                    continue
                end = text.find("\n\n", idx)
                anchor = (idx, end if 0 < end <= idx + 4000
                          else idx + len(raw["nom"]))
                partition.records.append(Record(
                    raw["id"], raw["classe"], raw["nom"],
                    {**raw["stats"], "nom": raw["nom"]}, [anchor],
                    tags=raw.get("tags"),
                    transverse=raw.get("transverse")))
            break

    checks = extract_checks(text, units)

    # adventure stage (D-178): judgment supplied as aventure-auteur.json in
    # the corpus home — trajectoire + perturbations, world conditions with
    # their triggers, and the exit converted into a hinge (never an end)
    for candidate in (CORPUS / "aventure-auteur.json",
                      src.parent / "aventure-auteur.json"):
        if candidate.exists():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            from .schemas import Aventure
            partition.aventure = Aventure(
                raw.get("trajectoire", []), raw.get("conditions", []),
                raw.get("charniere_md", ""))
            break

    write_partition(partition, out_dir)
    write_checks(out_dir, checks)
    from .directeur import generate as gen_director
    gen_director(out_dir)

    report = build(manifest.to_dict(),
                   validate_form.validate_form(partition, out_dir),
                   coverage := validate_fidelity.coverage_report(
                       units, [], len(text)),
                   validate_fidelity.mass_report(text, units, partition),
                   [], [], 0)
    rp = write_report(report, out_dir / "rapport-conversion.json")
    (out_dir / "rapport-conversion.md").write_text(render_md(report),
                                                   encoding="utf-8")
    return {"verdict": report["verdict"], "nodes": len(partition.nodes),
            "records": len(partition.records), "checks": sum(len(v) for v in
                                                             checks.values()),
            "out": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="coderain.converter",
                                 description="Kit P4 : convertir un module et "
                                             "le rendre jouable.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("convert", "all"):
        p = sub.add_parser(name)
        p.add_argument("source")
        p.add_argument("--titre")
        p.add_argument("--out", default=None)
    sub.add_parser("install").add_argument("partition")
    d = sub.add_parser("doctor")
    d.add_argument("partition")
    d.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)

    if a.cmd in ("convert", "all"):
        src = Path(a.source)
        titre = a.titre
        out = Path(a.out) if a.out else (
            CORPUS / f"partition-{_slug(titre or src.stem)}")
        res = cmd_convert(src, out, titre)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if res["verdict"] != "VERT":
            return 1
        if a.cmd == "convert":
            return 0
        a.partition = res["out"]

    if a.cmd == "install" or a.cmd == "all":
        from .install import install as do_install
        res = do_install(Path(a.partition), ROOT)
        print(json.dumps(res, ensure_ascii=False, indent=1))

    if a.cmd == "doctor" or a.cmd == "all":
        from .install import doctor as do_doctor
        root = getattr(a, "root", None) or str(ROOT)
        res = do_doctor(Path(a.partition), root)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        print(f"\n>>> {res['verdict']}")
        return 0 if res["verdict"] == "PRÊT À JOUER" else 1
    return 0


def _slug(s: str) -> str:
    from .install import _slugify
    return _slugify(s)[:40]


if __name__ == "__main__":
    sys.exit(main())
