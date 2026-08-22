"""P4 module converter: raw module text -> Partition (SPEC-P4 v0).

Six primitives out (manifest, nodes, records, tables, secrets, patches),
three structures in (S1 branching sections, S2 spatial zones, S3 rollable
tables). The LLM stages judge; the code enforces conformance — every produced
object carries source anchors, and the validators check coverage without ever
requiring a human to read the module.
"""
from .schemas import (Partition, Manifest, Node, Record, RollTable, Secret,
                      Patch, Unit, Aventure)
from . import ruletables, annexe_a, segmentation, buckets, semantic
from . import emit, validate_form, validate_fidelity, exceptions
from .convert import convert_module

__all__ = [
    "Partition", "Manifest", "Node", "Record", "RollTable", "Secret", "Patch",
    "Unit",
    "ruletables", "annexe_a", "segmentation", "buckets", "semantic", "emit",
    "validate_form", "validate_fidelity", "exceptions", "convert_module",
]
