"""Deterministic S1 handling for rigid numbered-paragraph modules.

Measured on the specimen: its structure (#N markers + "go to N." renvois)
is mechanically detectable, so code does the segmentation — zero
hallucination surface — and node bodies are VERBATIM copies of their source
span (fidèle au contenu, libre sur l'ordre). The LLM pipeline stays the
general path; this module is the special case that doesn't need it.
"""
from __future__ import annotations

import re

from .schemas import Node, Unit

MARKER = re.compile(r"^#(\d{1,3})[ \t]*$", re.M)
RENVIS = re.compile(r"^\s*(.*?)[ \t]*,?[Gg]o to (\d{1,3})\.[ \t]*$", re.M)


def segment_s1(text: str) -> list[Unit]:
    """Tile [0, len(text)) exactly once with units cut at #N markers.
    Anything before the first marker / after the last is one unit each."""
    marks = [(m.start(), int(m.group(1))) for m in MARKER.finditer(text)]
    spans: list[tuple[int, int, str]] = []
    if marks and marks[0][0] > 0:
        spans.append((0, marks[0][0], "avant-propos"))
    for k, (pos, num) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
        spans.append((pos, end, f"para-{num}"))
    if not marks:
        return [Unit("avant-propos", "S1", 0, len(text), titre="entier")]
    if marks[-1][0] < len(text) - 1 and not spans[-1][1] == len(text):
        pass  # last para-N unit already ends at len(text)

    units = []
    for start, end, uid in spans:
        body = text[start:end]
        renvois = [{"condition": c.strip(" \t\n-").rstrip(","), "cible": n}
                   for c, n in RENVIS.findall(body)]
        units.append(Unit(uid, "S1", start, end,
                          titre=uid.replace("para-", "#"), renvois=renvois))
    return units


def node_for_unit(unit: Unit, text: str, id_by_num: dict[int, str]) -> Node:
    """Verbatim-copy node: corps_md IS the source span (minus edge blanks);
    renvois become typed links when their target paragraph exists."""
    corps = text[unit.start:unit.end].strip("\n")
    liens = []
    for r in unit.renvois:
        target = id_by_num.get(int(r["cible"]))
        if target:
            liens.append({"cible_id": target,
                          "condition_textuelle": r["condition"] or "(inconditionnel)"})
    return Node(unit.uid, "section", f"{unit.titre}", corps, "scene",
                liens=liens, anchors=[(unit.start, unit.end)])
