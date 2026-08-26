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
from coderain.converter.validate_form import adventure_exceptions  # noqa: E402


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pymupdf
        return "\n\n".join(p.get_text() for p in pymupdf.open(str(path)))
    return path.read_text(encoding="utf-8")


# Structure detection: numbered-branching modules (S1 pur) are the MINORITY
# case for this tool (D-152: choice-enumerated material is the exception).
# Most ingested material is free-form — its route is the LLM pipeline
# (SPEC-P4 §3), which requires an approved model route (MRPG-D-176).
def _segment(text: str, mode: str, llm=None):
    has_markers = len(s1_local.MARKER.findall(text)) >= 3
    if mode == "s1" or (mode == "auto" and has_markers):
        return s1_local.segment_s1(text), None
    if mode == "gamebook":
        return s1_local.scan_gamebook(text)["units"], None
    if llm is None:
        raise SystemExit(
            "matériau libre détecté (pas de marqueurs #N en nombre): la "
            "segmentation exige la pipeline LLM (SPEC-P4 §3) — fournir un "
            "modèle approuvé (feu vert MRPG-D-176) ou --segmenter s1")
    from . import segmentation
    return segmentation.segment_chunked(llm, text)


def cmd_convert(src: Path, out_dir: Path, titre: str | None = None,
                mode: str = "auto", llm=None) -> dict:
    text = _extract_text(src)
    scan = None
    if mode == "gamebook":
        scan = s1_local.scan_gamebook(text)
        units, seg_errors = scan["units"], None
    else:
        units, seg_errors = _segment(text, mode, llm)
    if seg_errors:
        raise SystemExit(f"segmentation: {seg_errors}")
    cov0 = validate_fidelity.coverage_report(units, [], len(text))
    assert not cov0["gaps"] and not cov0["overlaps"], cov0
    manifest = Manifest(
        titre=titre or src.stem.replace("_", "-").replace("-", " ").strip().title(),
        corpus_source="5e", corpus_cible="5e",
        structures=["S1", "S2"] if mode == "gamebook" else ["S1"],
        hash_source=__import__("hashlib").sha256(
            text.encode("utf-8")).hexdigest(),
        date_conversion=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        version_convertisseur=("0.4.0+gamebook-local" if mode == "gamebook"
                               else "0.3.0+local"))  # D-178: étage aventure

    partition = Partition(manifest)
    gamebook_mesures: dict | None = None
    if scan is not None:
        gamebook_mesures = s1_local.build_gamebook_partition(scan, text,
                                                             partition)
    else:
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
                    transverse=raw.get("transverse"),
                    fonctions_aval=raw.get("fonctions_aval")))
            break

    checks = extract_checks(text, units)

    # adventure stage (D-178): judgment supplied as aventure-auteur.json in
    # the corpus home — trajectoire + perturbations structurées, world
    # conditions with their triggers, and the exit converted into a hinge
    # (never an end). Inherited shapes convert WITH SIGNALLED LOSS: every
    # missing field lands in the exceptions report (fiche §6).
    adventure_rule_exceptions: list[str] = []
    for candidate in (CORPUS / "aventure-auteur.json",
                      src.parent / "aventure-auteur.json"):
        if candidate.exists():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            from .schemas import Aventure
            partition.aventure = Aventure(
                raw.get("trajectoire", []), raw.get("conditions", []),
                raw.get("charniere_md", ""))
            adventure_rule_exceptions = list(partition.aventure.warnings)
            # charnières de sortie portées par des nodes terminaux
            # (fiche D-178 §4) — judgement auteur, application déterministe
            for cs in raw.get("charniere_sorties", []):
                nid = str(cs.get("node_id", ""))
                match = next((n for n in partition.nodes if n.id == nid),
                             None)
                if match is None:
                    adventure_rule_exceptions.append(
                        f"charniere_sortie: node cible inconnu {nid}")
                    continue
                try:
                    match.charniere_sortie = {
                        "ouvre_vers_md": str(cs["ouvre_vers_md"]),
                        "prerequis_etat": str(cs["prerequis_etat"])}
                except KeyError as ke:
                    adventure_rule_exceptions.append(
                        f"charniere_sortie {nid}: champ manquant {ke}")
            break

    # scenario stage (fiche méta 2026-08-23): the three rubrics written en
    # bloc, à froid, from scenario-auteur.json in the corpus home — CONVERTED
    # from source material, never invented (I-111); validation happens at
    # attachment (schemas) and at report time (validate_form.scenario_report)
    for candidate in (CORPUS / "scenario-auteur.json",
                      src.parent / "scenario-auteur.json"):
        if candidate.exists():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            by_id = {n.id: n for n in partition.nodes}
            for entry in raw.get("scenarios", []):
                nid = str(entry.get("node_id", ""))
                node = by_id.get(nid)
                if node is None:
                    adventure_rule_exceptions.append(
                        f"scenario: node cible inconnu {nid}")
                    continue
                try:
                    node.attach_scenario(
                        entry.get("objectif_md", ""),
                        entry.get("debouches") or None,
                        entry.get("heritage") or None)
                except (KeyError, ValueError, TypeError) as e:
                    adventure_rule_exceptions.append(f"scenario {nid}: {e}")
            break

    write_partition(partition, out_dir)
    write_checks(out_dir, checks)
    from .directeur import generate as gen_director
    gen_director(out_dir)

    # dédoublonnage en préservant l'ordre: adventure_exceptions(partition)
    # ré-inclut déjà av.warnings
    seen: set[str] = set()
    merged_adventure_exceptions = []
    for line in (adventure_rule_exceptions
                 + adventure_exceptions(partition)):
        if line not in seen:
            seen.add(line)
            merged_adventure_exceptions.append(line)
    # étage SCÉNARIO (fiche méta 2026-08-23 §5): erreurs structurelles ⇒
    # rouge; absences non fournies par la source ⇒ lignes d'exception
    # signalée (non bloquantes); comptages testables ⊥ textuels ⇒ mesures
    scen = validate_form.scenario_report(partition)
    report = build(manifest.to_dict(),
                   validate_form.validate_form(partition, out_dir)
                   + scen["erreurs"],
                   coverage := validate_fidelity.coverage_report(
                       units, [], len(text)),
                   validate_fidelity.mass_report(text, units, partition),
                   [], merged_adventure_exceptions, 0,
                   infos=scen["exceptions"],
                   mesures_scenario=scen["mesures"])
    rp = write_report(report, out_dir / "rapport-conversion.json")
    (out_dir / "rapport-conversion.md").write_text(render_md(report),
                                                   encoding="utf-8")
    res = {"verdict": report["verdict"], "nodes": len(partition.nodes),
           "scenarios": scen["mesures"]["noeuds_scenario"],
           "records": len(partition.records), "checks": sum(len(v) for v in
                                                            checks.values()),
           "tables": len(partition.tables),
           "out": str(out_dir)}
    if gamebook_mesures is not None:
        res["route_gamebook"] = gamebook_mesures
    return res


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
        p.add_argument("--segmenter", default="auto",
                       choices=("auto", "s1", "gamebook"),
                       help="route de segmentation (gamebook = entrées "
                            "nommées déterministes, zéro LLM)")
    sub.add_parser("install").add_argument("partition")
    d = sub.add_parser("doctor")
    d.add_argument("partition")
    d.add_argument("--root", default=str(ROOT))
    pj = sub.add_parser("project",
                        help="dérive la vue moteur dans le save (D-179)")
    pj.add_argument("partition")
    pj.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)

    if a.cmd in ("convert", "all"):
        src = Path(a.source)
        titre = a.titre
        out = Path(a.out) if a.out else (
            CORPUS / f"partition-{_slug(titre or src.stem)}")
        res = cmd_convert(src, out, titre, mode=a.segmenter)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if res["verdict"] != "VERT":
            return 1
        if a.cmd == "convert":
            return 0
        a.partition = res["out"]

    if a.cmd in ("install", "project", "all") or a.cmd == "project":
        if a.cmd in ("install", "all"):
            from .install import install as do_install
            res = do_install(Path(a.partition), ROOT)
            print(json.dumps(res, ensure_ascii=False, indent=1))
        if a.cmd == "project" or (a.cmd == "all"):
            from .install import doctor as _d  # kit.json -> save slug
            from .projection import derive
            pdir = Path(a.partition)
            kit_p = pdir / "kit.json"
            if not kit_p.exists():
                print("pas de kit.json — lance 'install' d'abord")
                return 1
            kit = json.loads(kit_p.read_text(encoding="utf-8"))
            counts = derive(pdir, ROOT, kit["save_slug"], None)
            print(json.dumps({"projection": counts,
                              "save_slug": kit["save_slug"]},
                             ensure_ascii=False, indent=1))
        if a.cmd == "install":
            return 0

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
