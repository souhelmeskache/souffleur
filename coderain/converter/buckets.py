"""LLM stage 2 — bucket each unit: change-en-jeu vs consulté-à-froid (D-141).

The founding triage of SPEC-P4 §4: what changes in play becomes engine data
(records/tables/secrets), what is consulted cold stays readable text (nodes).
Criteria are coded INTO the prompt so the judgement is repeatable.
"""
from __future__ import annotations

from ..llm import emit_json_ex

SYSTEM = """You classify parts of a converted RPG module. For each unit id,
decide its bucket using ONLY these criteria:

- "change-en-jeu": the content can CHANGE during play or is consumed by play —
  creatures/NPC stats, rollable tables, hidden information that can be burned,
  placed encounters that resolve once.
- "consulte-a-froid": static reference prose read on demand — descriptions,
  read-aloud text, lore, history.

When a unit contains both, answer "mixte" and list which sub-parts belong to
which bucket in "detail".

Return ONLY:
{"buckets": [{"id": "<unit id>",
              "bucket": "change-en-jeu"|"consulte-a-froid"|"mixte",
              "detail": ["..."]}]}"""


def _validate(obj: dict, unit_ids: list[str]) -> list[dict]:
    rows = obj.get("buckets")
    if not isinstance(rows, list):
        raise ValueError("no buckets list")
    seen = {}
    for r in rows:
        uid, b = str(r["id"]), str(r["bucket"])
        if b not in ("change-en-jeu", "consulte-a-froid", "mixte"):
            raise ValueError(f"unit {uid}: bad bucket {b!r}")
        seen[uid] = {"id": uid, "bucket": b, "detail": r.get("detail", [])}
    missing = [u for u in unit_ids if u not in seen]
    if missing:
        raise ValueError(f"units never classified: {missing}")
    return [seen[u] for u in unit_ids]


def classify(llm, units_summary: str, unit_ids: list[str]) -> tuple[list[dict], str | None]:
    """units_summary: compact JSON of {id, titre, structure} per unit."""
    obj, err = emit_json_ex(llm, SYSTEM, units_summary, retry=1, temperature=0.0)
    if obj is None:
        return [], f"bucketing failed: {err}"
    try:
        return _validate(obj, unit_ids), None
    except (KeyError, ValueError, TypeError) as e:
        return [], f"bucket grammar violated: {e}"
