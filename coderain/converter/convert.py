"""Pipeline driver (SPEC-P4 §1/§3): source text -> Partition + exceptions
report. Deterministic code owns extraction accounting, rule tables and both
validators; the LLM owns segmentation, bucketing and semantic conversion.

Every stage failure lands in the exceptions report — nominal alarms, never
silent correction. Nothing here requires a human to read module content.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path

from .schemas import Manifest, Partition, Unit
from .ruletables import RuleTables, ConversionException
from .semantic import absorb_aventure
from . import segmentation, buckets, semantic
from . import validate_form, validate_fidelity, exceptions as exc_report
from .emit import write_partition

VERSION_CONVERTISSEUR = "0.3.0"   # D-178: étage aventure


class TokenMeter:
    """Measured, not estimated (I-145): counts every payload handed to the
    model. Chars are exact; provider usage numbers attach later if the
    backend reports them (v0 records what is knowable without guessing)."""

    def __init__(self):
        self.calls: list[dict] = []

    def wrap(self, llm, stage: str):
        meter = self

        class _Metered:
            def complete(self, messages, **kw):
                chars = sum(len(str(m.get("content") or "")) for m in messages)
                meter.calls.append({"stage": stage, "chars_in": chars})
                return llm.complete(messages, **kw)

        return _Metered()

    def summary(self) -> dict:
        by_stage: dict[str, int] = {}
        for c in self.calls:
            by_stage[c["stage"]] = by_stage.get(c["stage"], 0) + c["chars_in"]
        return {"calls": len(self.calls), "chars_in_by_stage": by_stage,
                "chars_in_total": sum(c["chars_in"] for c in self.calls)}


def convert_module(source_text: str, titre: str, structures: list[str],
                   corpus_source: str, target_version: str,
                   llm_main, out_dir: Path,
                   llm_recheck=None, sampler_pct: float = 0.25,
                   mass_tolerance: float = 0.25) -> tuple[Partition | None, dict]:
    meter = TokenMeter()
    rule_exceptions: list[str] = []
    stage_errors: list[str] = []
    hash_source = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    manifest = Manifest(
        titre=titre, corpus_source=corpus_source, corpus_cible="5e",
        structures=structures, hash_source=hash_source,
        date_conversion=datetime.now().isoformat(timespec="seconds"),
        version_convertisseur=VERSION_CONVERTISSEUR)
    tables = RuleTables(corpus_source, target_version)

    # -- stage 1: segmentation (chunked — measured reliability) -------------
    units, seg_errors = segmentation.segment_chunked(
        meter.wrap(llm_main, "segmentation"), source_text)
    for e in seg_errors:
        stage_errors.append(f"segmentation {e}")
    if not units and not seg_errors:
        stage_errors.append("segmentation returned no units")

    partition = Partition(manifest)
    nodes_by_unit: dict[str, list] = {}

    # -- stages 2+3: buckets then semantic conversion ----------------------
    if units:
        rows, err = buckets.classify(
            meter.wrap(llm_main, "buckets"),
            str([{"id": u.uid, "titre": u.titre, "structure": u.structure}
                 for u in units]),
            [u.uid for u in units])
        if err:
            stage_errors.append(err)
            rows = [{"id": u.uid, "bucket": "consulte-a-froid", "detail": []}
                    for u in units]

        # semantic conversion in batches (measured: one call per paragraph
        # made the specimen cost hours); a failed batch falls back to
        # per-unit calls so one bad chunk can't sink 8 units.
        def absorb(res: dict):
            partition.nodes += res["nodes"]
            partition.records += res["records"]
            partition.tables += res["tables"]
            partition.secrets += res["secrets"]
            partition.patches += res["patches"]
            if res.get("evenements"):
                absorb_aventure(partition, res["evenements"])
            rule_exceptions.extend(res.get("exceptions", []))

        for i in range(0, len(units), semantic.BATCH_SIZE):
            chunk = [(u, source_text[u.start:u.end])
                     for u in units[i:i + semantic.BATCH_SIZE]]
            metered = meter.wrap(llm_main, "semantic")
            results, errs = semantic.convert_batch(metered, chunk, tables)
            stage_errors += errs
            missing = [u for u, _t in chunk if u.uid not in results]
            for uid in list(results):
                try:
                    absorb(results[uid])
                    nodes_by_unit[uid] = results[uid]["nodes"]
                except ConversionException as e:
                    rule_exceptions.append(f"{uid}: {e}")
            for u in missing:      # fallback: one call, precise error
                res, err = semantic.convert_unit(metered, source_text[u.start:u.end],
                                                 u, partition, tables)
                if err or res is None:
                    stage_errors.append(err or f"{u.uid}: empty conversion")
                    continue
                try:
                    absorb(res)
                    nodes_by_unit[u.uid] = res["nodes"]
                except ConversionException as e:
                    rule_exceptions.append(f"{u.uid}: {e}")

    # -- validators ---------------------------------------------------------
    form_errors = validate_form.validate_form(partition)
    anchors = [ab for n in partition.nodes for ab in n.anchors] \
        + [ab for r in partition.records for ab in r.anchors] \
        + [ab for t in partition.tables for ab in t.anchors]
    coverage = validate_fidelity.coverage_report(units, anchors,
                                                 len(source_text))
    mass_alarms = validate_fidelity.mass_report(
        source_text, units, partition, mass_tolerance)

    recheck_alarms: list[str] = []
    samples = 0
    if llm_recheck is not None and units:
        recheck_alarms, samples = validate_fidelity.sample_recheck(
            llm_recheck, source_text, units, partition, sampler_pct,
            lambda l, txt, unit: semantic.convert_unit(l, txt, unit, partition,
                                                       tables))

    report = exc_report.build(manifest.to_dict(), form_errors + stage_errors,
                              coverage, mass_alarms, recheck_alarms,
                              rule_exceptions, samples)
    report["tokens"] = meter.summary()
    write_partition(partition, Path(out_dir))
    exc_report.write_report(report, Path(out_dir).parent /
                            f"rapport-exceptions-{date.today().isoformat()}.json")
    return partition, report
