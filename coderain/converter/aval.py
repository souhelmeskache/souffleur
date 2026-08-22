"""DC check extraction + ability mapping (SPEC-P4 §6, versioned tables).

Deterministic: finds every "DC N <Ability> saving throw/check" in node bodies
and writes them as structured facts (mapping-regles.json) — the prose stays
verbatim; this index only tells the Director what the engine must roll.

Mapping philosophy (measured decision): the save is CREATED with the six 5e
abilities AS its stats, so "DC 10 Wisdom saving throw" maps 1:1 onto the
engine's native d20+stat vs DC — identity conversion again, zero judgement.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ABILITIES_5E = ("strength", "dexterity", "constitution",
                "intelligence", "wisdom", "charisma")

CHECK_RE = re.compile(
    r"(?:make|attempt|succeed)[^\n]{0,40}?DC (\d{1,2}) "
    r"(strength|dexterity|constitution|intelligence|wisdom|charisma)"
    r"(?: \((\w+)\))? (saving throw|check)", re.I)

# Régimes de jet (MRPG-D-089, actée): SILENCIEUX / OPAQUE / TRANSPARENT.
# Le choix est SITUATIONNEL (facteurs A-F de D-89) — jamais catégoriel;
# ce que le convertisseur émet est un régime PROPOSÉ par des facteurs
# déterministes (posture passive, estimabilité), que le Director peut
# dévier pour raisons dramaturgiques documentées. Le secret n'est JAMAIS
# un facteur (non-facteur 12) et le veto tient: enjeu lourd = transparence.
PASSIF = {"perception", "ecoute", "memoire", "surprise", "reperage"}


def _regime(kind: str, ability: str, skill: str | None) -> str:
    hay = f"{ability} {skill or ''}".lower()
    if any(k in hay for k in PASSIF):
        return "SILENCIEUX"          # capacité qui s'exerce seule (facteur A1)
    if kind == "saving_throw":
        return "OPAQUE"              # subi: difficulté non estimable (A2)
    return "OPAQUE"                  # délibéré mais DC rarement estimable


def extract_checks(text: str, units) -> dict[str, list[dict]]:
    """{node_id: [{dc, ability, skill?, kind, regime_propose}]} — facts only."""
    out: dict[str, list[dict]] = {}
    for u in units:
        found = []
        for m in CHECK_RE.finditer(text[u.start:u.end]):
            skill = (m.group(3) or "").lower() or None
            kind = m.group(4).lower().replace(" ", "_")
            found.append({
                "dc": int(m.group(1)),
                "ability": m.group(2).lower(),
                "skill": skill,
                "kind": kind,
                "regime_propose": _regime(kind, m.group(2).lower(), skill),
            })
        if found:
            out[u.uid] = found
    return out


def write_checks(partition_dir: Path, checks: dict) -> Path:
    payload = {
        "note": ("jets extraits mécaniquement; le save porteur porte les six "
                 "caractéristiques 5e comme stats → jet natif d20+mod vs DC"),
        "abilities": list(ABILITIES_5E),
        "checks": checks,
    }
    path = Path(partition_dir) / "mapping-regles.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


# -- aval: what the Director reads at the table -------------------------------

def load_partition(partition_dir: Path) -> dict:
    """Index of a Partition directory (nodes/records/tables/secrets)."""
    p = Path(partition_dir)
    return json.loads((p / "index.json").read_text(encoding="utf-8"))


def _split_front(raw: str) -> tuple[str, str]:
    """'---\\n{json}\\n---\\nbody' -> ({json}, body)"""
    if raw.startswith("---"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
    front, _, body = raw.partition("\n---\n")
    return front.strip(), body.strip()


def get_node(partition_dir: Path, node_id: str) -> dict:
    """Front matter (parsed JSON) + body of one node file."""
    front, body = _split_front(
        (Path(partition_dir) / "nodes" / f"{node_id}.md").read_text(
            encoding="utf-8"))
    try:
        meta = json.loads(front) if front else {}
    except json.JSONDecodeError:
        meta = {}
    return {"meta": meta, "body": body}


def get_record(partition_dir: Path, record_id: str) -> dict:
    front, body = _split_front(
        (Path(partition_dir) / "records" / f"{record_id}.md").read_text(
            encoding="utf-8"))
    try:
        meta = json.loads(front) if front else {}
    except json.JSONDecodeError:
        meta = {}
    stats = json.loads(body) if body.startswith("{") else body
    return {"meta": meta, "stats": stats}


def roll_table(partition_dir: Path, table_id: str,
               die_result: int | None = None) -> dict:
    """Table data (+ the row for `die_result` if given; rolling is the
    engine's job, never ours)."""
    entries = _read_table_entries(Path(partition_dir), table_id)
    row = None
    if die_result is not None:
        for e in entries:
            if e["plage_debut"] <= die_result <= e["plage_fin"]:
                row = e
                break
    raw = (Path(partition_dir) / "tables" / f"{table_id}.md").read_text(
        encoding="utf-8")
    import re as _re
    de = (_re.search(r'"de":\s*"([^"]+)"', raw).group(1)
          if '"de"' in raw else None)
    return {"id": table_id, "de": de, "entrees": entries, "resultat": row}


def _read_table_entries(partition_dir: Path, table_id: str) -> list[dict]:
    import re
    raw = (partition_dir / "tables" / f"{table_id}.md").read_text(
        encoding="utf-8")
    out = []
    for line in raw.splitlines():
        m = re.match(r"^-\s*(\d+(?:-\d+)?):\s*(.*)$", line.strip())
        if not m:
            continue
        plage, res = m.group(1), m.group(2)
        if "-" in plage:
            a, b = plage.split("-")
        else:
            a = b = plage
        lien = None
        if "→ [" in res or "-> [" in res:
            res, _, lien = res.replace("->", "→").partition("→ [")
            lien = lien.rstrip("]")
        out.append({"plage_debut": int(a), "plage_fin": int(b),
                    "resultat_md": res.strip(), "lien_optionnel": lien})
    return out
