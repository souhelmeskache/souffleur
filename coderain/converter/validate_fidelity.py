"""Fidelity validator (SPEC-P4 §7, level 2) — the anti-hallucination net.

1. Coverage: the union of every produced anchor must equal [0, len(source))
   with no gap and no overlap — nothing lost, nothing invented.
2. Mass check: words per source unit vs words of its nodes (parametrized
   tolerance); a unit that shrank or grew past tolerance is a nominal alarm.
3. Sampling: N % of nodes re-translated by an independent pass (different
   prompt temperature/model), diffed automatically; deltas go to the report.

All findings are measurable facts (offsets, counts, ratios) — never module
prose. This is what makes 'done' checkable without anyone reading the module.
"""
from __future__ import annotations

import re


def _word_count(s: str) -> int:
    return len(re.findall(r"\S+", s))


def _content_words(s: str) -> int:
    """Words that carry content: dice tokens (1d6), numeric ranges (2-6:),
    lone numbers and heading markers don't count on either side of the mass
    comparison — otherwise table units always look 'shrunk'."""
    tokens = re.findall(r"\S+", s)
    keep = []
    for t in tokens:
        bare = t.strip("():;,.")
        if re.match(r"^\d+d\d+$", bare):          # dice
            continue
        if re.match(r"^\d+(-\d+)?[:.]?$", bare):  # ranges / entries
            continue
        if re.match(r"^#+$", t):                  # markdown headings
            continue
        keep.append(t)
    return len(keep)


def coverage_report(units, anchors, text_len: int) -> dict:
    """units: list[Unit]; anchors: flat list of (start, end) actually claimed."""
    spans = sorted((u.start, u.end) for u in units)
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    gaps = []
    cursor = 0
    for a, b in merged:
        if a > cursor:
            gaps.append([cursor, a])
        cursor = b
    if cursor < text_len:
        gaps.append([cursor, text_len])
    # overlaps in the RAW (unmerged) spans — double coverage is invention too
    raw_sorted = sorted(spans)
    overlaps = [[raw_sorted[i + 1][0], min(raw_sorted[i][1], raw_sorted[i + 1][1])]
                for i in range(len(raw_sorted) - 1)
                if raw_sorted[i + 1][0] < raw_sorted[i][1]]
    unanchored = [list(a) for a in sorted(anchors) if not any(
        ua <= a[0] and a[1] <= ub for ua, ub in spans)]
    return {"text_len": text_len, "gaps": gaps, "overlaps": overlaps,
            "unanchored_claims": unanchored}


def mass_report(source_text: str, units, partition,
                tolerance: float = 0.25,
                tolerance_by_structure: dict | None = None) -> list[str]:
    """Nominal alarms only: '<unit>: ratio 0.42' — no content quoted.

    tolerance_by_structure: parametrized per input structure (SPEC-P4 §3).
    S3 table units legitimately compress (the header becomes structure, dice
    notation collapses ranges), so their default band is wider."""
    tol_for = {"S1": tolerance, "S2": tolerance, "S3": 0.5}
    if tolerance_by_structure:
        tol_for.update(tolerance_by_structure)
    pieces = [(n.corps_md, n.anchors) for n in partition.nodes] \
        + [(" ".join(e["resultat_md"] for e in t.entrees), t.anchors)
           for t in partition.tables]
    by_anchor: dict[str, int] = {}
    for text, anchors in pieces:
        w = _content_words(text)
        if not w:
            continue
        best = max(anchors, key=lambda ab: ab[1] - ab[0])
        for u in units:
            if u.start <= best[0] and best[1] <= u.end:
                by_anchor[u.uid] = by_anchor.get(u.uid, 0) + w
                break
    alarms = []
    for u in units:
        src_words = _content_words(source_text[u.start:u.end])
        if src_words == 0:
            continue
        out_words = by_anchor.get(u.uid, 0)
        if out_words == 0:
            alarms.append(f"{u.uid}: 0 output words for {src_words} source words")
            continue
        ratio = out_words / src_words
        tol = tol_for.get(u.structure, tolerance)
        if not (1 - tol <= ratio <= 1 + tol):
            alarms.append(f"{u.uid}: ratio {ratio:.2f} "
                          f"({out_words}/{src_words} words)")
    return alarms


def sample_recheck(llm, source_text: str, units, partition, sampler_n: float,
                   convert_unit_fn) -> tuple[list[str], int]:
    """Re-translate ceil(N% * units) units with the given (different) llm and
    diff against the primary conversion. Returns (alarms, samples_taken)."""
    import math
    targets = [u for u in units
               if any(n.anchors[0][0] >= u.start and n.anchors[0][1] <= u.end
                      for n in partition.nodes)]
    k = min(len(targets), math.ceil(len(targets) * sampler_n)) or (
        1 if targets else 0)
    picked = targets[:k]
    alarms: list[str] = []
    for u in picked:
        fresh, err = convert_unit_fn(llm, source_text[u.start:u.end], u)
        if err or fresh is None:
            alarms.append(f"{u.uid}: recheck pass failed ({err})")
            continue
        prim = sorted(n.id for n in partition.nodes
                      if u.start <= n.anchors[0][0] and n.anchors[0][1] <= u.end)
        sec = sorted((n["id"] if isinstance(n, dict) else n.id)
                     for n in fresh.get("nodes", []))
        if prim != sec:
            alarms.append(f"{u.uid}: recheck diff — primary {len(prim)} nodes "
                          f"({','.join(prim)}) vs recheck {len(sec)} nodes "
                          f"({','.join(sec)})")
    return alarms, k
