"""DC check extraction + ability mapping (SPEC-P4 §6, versioned tables).

Deterministic: finds every "DC N <Ability> saving throw/check" in node bodies
and writes them as structured facts (mapping-regles.json) — the prose stays
verbatim; this index only tells the Director what the engine must roll.

Mapping philosophy (measured decision): the save is CREATED with the six 5e
abilities AS its stats, so "DC 10 Wisdom saving throw" maps 1:1 onto the
engine's native d20+stat vs DC — identity conversion again, zero judgement.

D-254 (I-328/Issue-77, mesure pconv1-3): certains modules du corpus phrasent
le jet dans l'ordre inverse — compétence/caractéristique D'ABORD, DC ensuite
(« Make a perception check, DC 12 », « roll survival, DC 15 », « wisdom
save, DC 10 ») — au lieu de « DC 12 wisdom (perception) check ». REVERSE_
CHECK_RE couvre cette forme générique EN PLUS de CHECK_RE, sans le modifier :
les deux formes coexistent, aucune des deux ne régresse. Le nom de
compétence est routé vers sa caractéristique via SKILL_TO_ABILITY_5E (table
versionnée, complétude SRD) — jamais improvisé.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ABILITIES_5E = ("strength", "dexterity", "constitution",
                "intelligence", "wisdom", "charisma")

# Table compétence -> caractéristique 5e (SRD, complète — 18 compétences +
# "thieves' tools" qui n'est pas une compétence SRD mais un outil dont le
# module source route explicitement le jet, mesuré au même titre : D-254).
# Versionnée comme le reste de ruletables.py : une correction future est une
# révision de table, jamais une édition de l'historique.
SKILL_TO_ABILITY_5E = {
    "athletics": "strength",
    "acrobatics": "dexterity",
    "sleight of hand": "dexterity",
    "stealth": "dexterity",
    "thieves' tools": "dexterity",
    "thieves tools": "dexterity",
    "arcana": "intelligence",
    "history": "intelligence",
    "investigation": "intelligence",
    "nature": "intelligence",
    "religion": "intelligence",
    "animal handling": "wisdom",
    "insight": "wisdom",
    "medicine": "wisdom",
    "perception": "wisdom",
    "survival": "wisdom",
    "deception": "charisma",
    "intimidation": "charisma",
    "performance": "charisma",
    "persuasion": "charisma",
}

CHECK_RE = re.compile(
    r"(?:make|attempt|succeed)[^\n]{0,40}?DC (\d{1,2}) "
    r"(strength|dexterity|constitution|intelligence|wisdom|charisma)"
    r"(?: \((\w+)\))? (saving throw|check)", re.I)

# Ordre inverse (D-254) : compétence-ou-caractéristique [mot-clé] , DC N
# [mot-clé] — le mot-clé (check/save/saving throw/roll) peut précéder ou
# suivre le DC selon le phrasé mesuré ; au moins une occurrence est requise
# pour éviter de capturer un simple DC de statblock sans jet associé.
_SKILL_OR_ABILITY = "|".join(sorted(
    list(ABILITIES_5E) + list(SKILL_TO_ABILITY_5E.keys()),
    key=len, reverse=True))  # plus long d'abord (ex. "sleight of hand" avant rien)
_KEYWORD = r"check|saving throw|save|roll"

REVERSE_CHECK_RE = re.compile(
    r"(?:(?P<kind0>make|attempt|roll)\s+(?:an?\s+)?)?"
    rf"\b(?P<skill>{_SKILL_OR_ABILITY})\b"
    rf"(?:\s+(?P<kind1>{_KEYWORD}))?"
    r",?\s*DC\s*(?P<dc>\d{1,2})"
    rf"(?:\s*(?:[—-]|,)?\s*(?P<kind2>{_KEYWORD}))?",
    re.I)

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


def _kind_from_keyword(word: str | None) -> str:
    if word and word.lower().replace(" ", "_") in ("save", "saving_throw"):
        return "saving_throw"
    return "check"                   # check/roll, ou mot-clé absent (skill)


def extract_checks(text: str, units) -> dict[str, list[dict]]:
    """{node_id: [{dc, ability, skill?, kind, regime_propose}]} — facts only."""
    out: dict[str, list[dict]] = {}
    for u in units:
        found = []
        spans: list[tuple[int, int]] = []

        for m in CHECK_RE.finditer(text[u.start:u.end]):
            skill = (m.group(3) or "").lower() or None
            ability = m.group(2).lower()
            kind = m.group(4).lower().replace(" ", "_")
            spans.append(m.span())
            found.append({
                "dc": int(m.group(1)),
                "ability": ability,
                "skill": skill,
                "kind": kind,
                "regime_propose": _regime(kind, ability, skill),
            })

        # Ordre inverse (D-254) : compétence/caractéristique avant le DC.
        # Au moins un mot-clé (check/save/saving throw/roll) est requis —
        # sinon "Strength DC 15" d'un statblock serait pris pour un jet.
        # Les correspondances qui chevauchent une trouvaille CHECK_RE (forme
        # existante) sont écartées pour ne jamais compter deux fois le même
        # jet.
        for m in REVERSE_CHECK_RE.finditer(text[u.start:u.end]):
            kind0, kind1, kind2 = (m.group("kind0"), m.group("kind1"),
                                   m.group("kind2"))
            if not kind0 and not kind1 and not kind2:
                continue
            if any(a < m.end() and m.start() < b for a, b in spans):
                continue
            raw_skill = m.group("skill").lower()
            if raw_skill in ABILITIES_5E:
                ability, skill = raw_skill, None
            else:
                ability, skill = SKILL_TO_ABILITY_5E[raw_skill], raw_skill
            kind = _kind_from_keyword(kind2 or kind1 or kind0)
            spans.append(m.span())
            found.append({
                "dc": int(m.group("dc")),
                "ability": ability,
                "skill": skill,
                "kind": kind,
                "regime_propose": _regime(kind, ability, skill),
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


class TableConsultationError(Exception):
    """D-252.4 : clé de consultation inconnue, ou table interrogée dans le
    mauvais mode — échec explicite, jamais une invention (même esprit que
    l'absence de table : exception signalée, jamais improvisation)."""


def _table_meta(partition_dir: Path, table_id: str) -> dict:
    front, _ = _split_front(
        (Path(partition_dir) / "tables" / f"{table_id}.md").read_text(
            encoding="utf-8"))
    try:
        return json.loads(front) if front else {}
    except json.JSONDecodeError:
        return {}


def roll_table(partition_dir: Path, table_id: str,
               die_result: int | None = None) -> dict:
    """Table data (+ the row for `die_result` if given; rolling is the
    engine's job, never ours). Réservé au mode aleatoire (D-252.4) — une
    table consultation n'a pas de dé, voir consulter_table()."""
    partition_dir = Path(partition_dir)
    meta = _table_meta(partition_dir, table_id)
    mode = meta.get("mode", "aleatoire")
    if mode != "aleatoire":
        raise TableConsultationError(
            f"table {table_id}: mode {mode!r} — pas de dé, la lecture se "
            "fait par consulter_table() (D-252.4)")
    entries = _read_table_entries(partition_dir, table_id, mode)
    row = None
    if die_result is not None:
        for e in entries:
            if e["plage_debut"] <= die_result <= e["plage_fin"]:
                row = e
                break
    return {"id": table_id, "de": meta.get("de"), "entrees": entries,
            "resultat": row}


def consulter_table(partition_dir: Path, table_id: str, cle: str) -> dict:
    """Lecture ciblée d'une table consultation (D-252.4) — le documentaliste
    interroge la bibliothèque indexée : donner la clé rend l'entrée, clé
    inconnue rend un échec explicite (TableConsultationError), jamais une
    invention."""
    partition_dir = Path(partition_dir)
    meta = _table_meta(partition_dir, table_id)
    mode = meta.get("mode", "aleatoire")
    if mode != "consultation":
        raise TableConsultationError(
            f"table {table_id}: mode {mode!r} — pas de clé de consultation, "
            "voir roll_table() (D-252.4)")
    entries = _read_table_entries(partition_dir, table_id, mode)
    for e in entries:
        if e["cle"] == cle:
            return {"id": table_id, "cle": cle, "resultat_md": e["resultat_md"]}
    raise TableConsultationError(
        f"table {table_id}: clé de consultation inconnue {cle!r} — échec "
        "explicite, jamais d'invention (D-252.4)")


def _read_table_entries(partition_dir: Path, table_id: str,
                        mode: str = "aleatoire") -> list[dict]:
    import re
    raw = (partition_dir / "tables" / f"{table_id}.md").read_text(
        encoding="utf-8")
    out = []
    if mode == "consultation":
        for line in raw.splitlines():
            m = re.match(r"^-\s*(.+?):\s*(.*)$", line.strip())
            if not m:
                continue
            out.append({"cle": m.group(1).strip(),
                        "resultat_md": m.group(2).strip()})
        return out
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
