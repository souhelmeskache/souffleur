"""LLM stage 1 — detect S1/S2/S3 and segment the source into anchored units.

The LLM reads prose; the grammar of its output is imposed (JSON validated).
Offsets are the anti-hallucination backbone: every unit carries [start, end)
into the exact source text given, and validate_fidelity accounts for every
offset exactly once.
"""
from __future__ import annotations

from ..llm import emit_json_ex
from .schemas import Unit

SYSTEM = """You segment a tabletop RPG module text for conversion. You NEVER
invent content: you only report what is in the text, and you MUST give the
exact character offsets [start, end) of each unit inside the provided text.

Return ONLY a JSON object:
{"units": [{"id": "<kebab-slug>", "structure": "S1"|"S2"|"S3",
            "start": <int>, "end": <int>, "titre": "<short>",
            "renvois": [{"condition": "...", "cible": "<section number or id>"}],
            "mj_only": true|false}]}

Structure meanings:
- S1: numbered branching sections, conditional cross-references ("if X go to n").
- S2: spatial zones (rooms/areas/map locations, placed encounters).
- S3: rollable tables (encounters/treasure/oracle).
Mark "mj_only": true for DM-only sidebars/secrets blocks."""


def _validate(obj: dict, text_len: int) -> list[Unit]:
    if not isinstance(obj.get("units"), list) or not obj["units"]:
        raise ValueError("segmentation returned no units")
    units = []
    for u in obj["units"]:
        start, end = int(u["start"]), int(u["end"])
        if not (0 <= start <= end <= text_len):
            raise ValueError(f"unit {u.get('id')}: offsets [{start},{end}) "
                             f"outside source of length {text_len}")
        units.append(Unit(
            uid=str(u["id"]), structure=str(u["structure"]),
            start=start, end=end, titre=str(u.get("titre", "")),
            renvois=[{"condition": str(r.get("condition", "")),
                      "cible": str(r.get("cible", ""))}
                     for r in u.get("renvois", [])],
            mj_only=bool(u.get("mj_only", False)),
        ))
    return units


def segment(llm, source_text: str) -> tuple[list[Unit], str | None]:
    """Returns (units, error). On error, units is [] and the caller reports."""
    obj, err = emit_json_ex(llm, SYSTEM, source_text, retry=1,
                            temperature=0.0)
    if obj is None:
        return [], f"segmentation failed: {err}"
    try:
        return _validate(obj, len(source_text)), None
    except (KeyError, ValueError, TypeError) as e:
        return [], f"segmentation grammar violated: {e}"


# Measured on the first real pass: one 49.5k-char segmentation call returned
# EMPTY output twice (15-25 min each) — reasoning models burn their budget
# before writing. Small calls (~12k chars) succeed consistently, so the
# default path slices at paragraph boundaries and shifts offsets.
SEGMENT_CHUNK_CHARS = 12000


def _slice_chunks(source_text: str, chunk_chars: int) -> list[tuple[int, str]]:
    """[(offset, chunk)] cut near chunk_chars at line boundaries; coverage of
    the source is exact by construction (no overlap, no gap)."""
    chunks = []
    start = 0
    n = len(source_text)
    while start < n:
        end = min(start + chunk_chars, n)
        if end < n:
            nl = source_text.rfind("\n", start + int(chunk_chars * 0.7), end)
            if nl > start:
                end = nl + 1
        chunks.append((start, source_text[start:end]))
        start = end
    return chunks


def segment_chunked(llm, source_text: str,
                    chunk_chars: int = SEGMENT_CHUNK_CHARS
                    ) -> tuple[list[Unit], list[str]]:
    """Chunked segmentation; returns (units, errors) — partial success keeps
    the units it got and reports the failed chunks as nominal alarms."""
    units: list[Unit] = []
    errors: list[str] = []
    for offset, chunk in _slice_chunks(source_text, chunk_chars):
        part, err = segment(llm, chunk)
        if err:
            errors.append(f"chunk @{offset}: {err}")
            continue
        for u in part:
            u.start += offset
            u.end += offset
            units.append(u)
    return units, errors
