"""Markdown-as-source-of-truth memory store + queryable index.

A story is a folder of .md files (see templates.py). This module reads/writes
those files, parses registry entries, manages the transcript, builds an in-memory
index for smart retrieval, and assembles the per-turn context for the narrator.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import time
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import templates
from .config import saves_dir
from .macros import expand_macros

# Registry files whose entries are recall-gated by alias/name match.
GATED_REGISTRIES = [
    "characters.md", "locations.md", "factions.md", "items.md", "canon-events.md",
]
# All files that hold indexable entries.
INDEX_FILES = [
    "player.md", "characters.md", "locations.md", "factions.md", "items.md",
    "canon-events.md", "threads.md",
]
# Lorebook weight tiers (Wave 2): rank multiplier for activation. `critical`
# (like `pinned:`) is always in context; the rest activate on trigger match and
# compete for the lore budget ranked by weight x importance.
WEIGHTS = {"minor": 0.5, "supplementary": 0.75, "standard": 1.0,
           "important": 1.5, "critical": 2.0}
# The "Secrets you know" section title assemble() renders below, hoisted to a
# named constant so trinity.py's Writer-side retrait (Issue #108) matches this
# text by name instead of a second hand-copied literal. mcp_server.py carries
# its own independent copy (`_SECRETS_TITLE`) for its own leak guard — this
# constant is NOT that one and the two are not meant to merge (separate
# modules, separate contracts).
SECRETS_SECTION_TITLE = ("Secrets you know (NOT yet revealed to the player — "
                          "foreshadow, hint, let them discover; never state "
                          "outright)")


def _attr_true(v) -> bool:
    return str(v or "").strip().lower() in ("true", "yes", "1", "on")


def _safe_child(root: Path, name: str) -> bool:
    """True iff `root / name` is a DIRECT child of root — blocks a slug like
    '..\\..\\Windows\\Temp' from escaping the library root (arbitrary rmtree)."""
    if not name or name in (".", ".."):
        return False
    try:
        return (root / name).resolve().parent == root.resolve()
    except OSError:
        return False


# A quantified group that itself contains a quantifier — (a+)+, (\w+\s*)+, (.*a){25}.
_NESTED_QUANT = re.compile(r"\([^)]*[+*][^)]*\)[+*{]")
# A quantified group containing an alternation — (a|a)+$, (a|ab)+ — the other
# classic backtracking bomb, which _NESTED_QUANT misses (no inner quantifier).
# Output-scrub rules almost never quantify an alternation, so the false-positive
# cost is acceptable for the gain of closing this ReDoS class.
_QUANT_ALT = re.compile(r"\([^)]*\|[^)]*\)[+*{]")


def safe_output_regex(pattern: str) -> bool:
    """ST-31 guard: reject a user/imported regex likely to catastrophically
    backtrack (ReDoS) — too long, or a quantified group that itself contains a
    quantifier or an alternation: (a+)+, (\\w+\\s*)+, (.*a){25}, (a|a)+. A cheap
    heuristic (not a full ReDoS solver) that blocks the practical bombs while
    passing ordinary patterns (\\bword\\b, colou?r). Critical because rules ride
    inside shared/imported worlds and run while the app-wide generation lock is
    held."""
    if not pattern or len(pattern) > 200:
        return False
    if _NESTED_QUANT.search(pattern) or _QUANT_ALT.search(pattern):
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _safe_zip_member(dst: Path, name: str) -> bool:
    """True iff extracting archive entry `name` stays under `dst`. Blocks `..`
    segments AND absolute/drive/UNC entries (an absolute join silently drops dst,
    so a `C:/...` or `/etc/...` entry would otherwise write anywhere) — Zip-Slip."""
    if not name or name.endswith("/"):
        return False
    p = Path(name)
    if p.is_absolute() or p.drive or p.anchor:
        return False
    try:
        return (dst / name).resolve().is_relative_to(dst.resolve())
    except OSError:
        return False
# Governing rule files: global masters resolved save -> scenario -> global (Phase 5).
RULE_FILES = templates.RULE_FILES
# Map a promotion "kind" to its home file.
KIND_FILE = {
    "character": "characters.md", "location": "locations.md",
    "faction": "factions.md", "item": "items.md",
    "canon-event": "canon-events.md", "thread": "threads.md",
}
# D-260 lane (c) — Issue #131 : l'étage scénario de la mémoire du vécu
# (D-129). Accumule un fold de scène à la fois (`summarizer._fold_scene`),
# se referme vers ADVENTURE_FILE (`summarizer.fermer_scenario`), et sert de
# lecteur unique à l'assembleur par position
# (`assembleur_position._world_and_queue_section`) — les deux modules
# partagent le nom depuis ici : `summarizer` importe `assembleur_position`
# (pas l'inverse), donc ce module neutre évite de faire dépendre
# `assembleur_position` de `summarizer` pour ce seul nom de fichier.
SCENARIO_STAGE_FILE = "memory/scenario-courant.md"
ADVENTURE_FILE = "memory/aventure.md"
# Files a custom lore type may NEVER shadow: built-in registries, rules, and
# the non-registry story files (declaring "events" as a lore type would turn
# unfired event rules into Writer-visible lorebook entries).
_RESERVED_MD = set(INDEX_FILES) | set(templates.RULE_FILES) | {
    ".md", "events.md", "premise.md", "world-bible.md", "transcript.md",
    "custom-instructions.md",
}
# Files exposed in the GUI Memory editor, in display order.
EDITABLE_FILES = [
    "premise.md", "world-bible.md", "writer-rules.md", "memory-rules.md",
    "rpg-rules.md",
    "player.md", "characters.md", "locations.md", "factions.md", "items.md",
    "canon-events.md", "threads.md", "events.md", "custom-instructions.md",
    "memory/scenes.md", "memory/arc.md", "memory/timeline.md",
    "memory/facts.md", "memory/companion-chat.md",
    SCENARIO_STAGE_FILE, ADVENTURE_FILE,
    "transcript.md", "state.json",
]

_TURN_RE = re.compile(r"<!--\s*@(player|narrator)\s*-->\s*\n(.*?)(?=\n<!--\s*@|\Z)",
                      re.DOTALL)
_HEADING_RE = re.compile(r"^##\s+(.*?)\s*(?:\{#([a-z0-9-]+)\})?\s*$")
# An attribute header line = a lowercase single-token key, so prose such as
# "She said: hello" is never mistaken for an attribute (bug: body-text loss).
_ATTR_RE = re.compile(r"^([a-z][a-z0-9_-]{0,20}):\s?(.*)$")
_LINK_RE = re.compile(r"\[\[(?:[a-z-]+:)?([a-z0-9-]+)\]\]")
_ZW = "​"  # zero-width space used to neutralize turn delimiters in stored text
# A timeline line's source-turn tag, e.g. "[T6-10]" -> (6, 10).
_TL_RANGE_RE = re.compile(r"\[T(\d+)-(\d+)\]")
# An explicit range in a recall reference: "T6-10", "6 - 10", "6 to 10".
_REF_RANGE_RE = re.compile(r"T?(\d+)\s*(?:-|–|to)\s*T?(\d+)", re.IGNORECASE)


def _turns_block(turns: list[dict]) -> str:
    """Render turns verbatim, labeled by speaker (for recall output)."""
    out = []
    for t in turns:
        who = "PLAYER" if t["role"] == "player" else "NARRATOR"
        out.append(f"[{who}] {t['text']}")
    return "\n\n".join(out)


def _range_from_ref(ref: str, timeline_text: str,
                    scenes: list["Entry"]) -> tuple[int, int] | None:
    """Resolve a recall reference to a 1-based inclusive turn range, trying in order:
    an explicit range, a timeline line matching the reference text, then a scene
    slug's `turns:` attr. Returns None if nothing resolves."""
    m = _REF_RANGE_RE.search(ref)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (min(a, b), max(a, b))
    needle = ref.lower().strip()
    slug = templates.slugify(ref)
    for line in timeline_text.splitlines():
        if needle and needle in line.lower():
            rm = _TL_RANGE_RE.search(line)
            if rm:
                return (int(rm.group(1)), int(rm.group(2)))
    for e in scenes:
        if e.slug == slug or (needle and needle in (e.title + " " + e.body).lower()):
            tm = re.match(r"\s*(\d+)-(\d+)", e.attrs.get("turns", ""))
            if tm:
                return (int(tm.group(1)), int(tm.group(2)))
    return None


def _strip_comments(text: str) -> str:
    """Blank out HTML-comment regions, preserving newlines so line indices stay
    aligned. An unterminated '<!--' hides to end of text. Used by BOTH parse_entries
    and heading location so the two can never disagree (bug: duplicate entries)."""
    out = []
    i, n, in_c = 0, len(text), False
    while i < n:
        if not in_c:
            if text.startswith("<!--", i):
                in_c, i = True, i + 4
            else:
                out.append(text[i])
                i += 1
        else:
            if text.startswith("-->", i):
                in_c, i = False, i + 3
            else:
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
    return "".join(out)


@dataclass
class Entry:
    title: str
    slug: str
    aliases: list[str] = field(default_factory=list)
    importance: int = 3
    attrs: dict[str, str] = field(default_factory=dict)
    body: str = ""

    def triggers(self) -> list[str]:
        """Activation keywords: title + slug + aliases + the optional `triggers:`
        attr (extra lorebook keywords beyond names, Wave 2)."""
        extra = [t.strip() for t in self.attrs.get("triggers", "").split(",")
                 if t.strip()]
        return [x for x in ([self.title, self.slug] + self.aliases + extra) if x]

    # --- lorebook attributes (Wave 2; all optional, absent = old behavior) ---
    def weight(self) -> str:
        w = self.attrs.get("weight", "").strip().lower()
        return w if w in WEIGHTS else "standard"

    def weight_factor(self) -> float:
        return WEIGHTS[self.weight()]

    def pinned(self) -> bool:
        return _attr_true(self.attrs.get("pinned"))

    def hidden(self) -> bool:
        return _attr_true(self.attrs.get("hidden"))

    def persistent_attrs(self) -> list[str]:
        """Attributes the author marked MUTABLE IN SESSION (D-216 §3) — names
        from the optional `persistent:` header line, comma-separated:

            ## The Death Knight  {#death-knight}
            persistent: hp, morale
            hp: 120

        Only these may be written by the engine-tracked `persist` delta (the
        rest of the attribute vocabulary stays closed); the value lives at the
        top level of state.json under "persistent", so it survives scene and
        combat boundaries by construction. Until the first in-session write,
        the entry's own `attr: value` line IS the baseline. assemble() serves
        the current value + the mutation history on every render of this entry.
        """
        return [p.strip().lower()
                for p in self.attrs.get("persistent", "").split(",") if p.strip()]

    def links(self) -> list[str]:
        """Slugs of explicitly linked pieces (`links: slug, slug`)."""
        return [templates.slugify(p) for p in self.attrs.get("links", "").split(",")
                if p.strip()]

    # --- Tier 2 lorebook activation refinements (all optional) ---
    def _csv(self, key: str) -> list[str]:
        return [t.strip() for t in self.attrs.get(key, "").split(",") if t.strip()]

    def triggers_all(self) -> list[str]:
        """ST-13: extra keys that must ALL be present too (AND). Empty = no gate."""
        return self._csv("triggers_all")

    def triggers_not(self) -> list[str]:
        """ST-13: keys that SUPPRESS the entry if any is present (NOT)."""
        return self._csv("triggers_not")

    def chance(self) -> int | None:
        """ST-11: activation probability 0-100, or None if unset/unparseable.
        `isascii` guard: Python int() accepts Unicode digits (e.g. '٣'), which a
        human never meant as a percentage — treat those as unset, not 3."""
        raw = self.attrs.get("chance", "").strip().rstrip("%")
        if not raw or not raw.isascii():
            return None
        try:
            return max(0, min(100, int(raw)))
        except ValueError:
            return None

    def group(self) -> str:
        """ST-12: inclusion-group name; only one activated member of a group is
        kept (weighted). Empty = ungrouped (always kept if activated)."""
        return self.attrs.get("group", "").strip()

    def _int_attr(self, key: str) -> int | None:
        raw = self.attrs.get(key, "").strip()
        if not raw or not raw.isascii():   # ignore Unicode-digit junk, not "3"
            return None
        try:
            return max(0, int(raw))
        except ValueError:
            return None

    def delay(self) -> int | None:
        """ST-10: entry stays dormant until at least N messages have happened."""
        return self._int_attr("delay")

    def sticky(self) -> int | None:
        """ST-10: once triggered, stays active for the next N messages even after
        it leaves the immediate context window."""
        return self._int_attr("sticky")

    def cooldown(self) -> int | None:
        """ST-10: after firing, stays quiet for N messages unless re-mentioned."""
        return self._int_attr("cooldown")

    def semantic(self) -> bool:
        """ST-17: activate by embedding similarity (the retriever) rather than
        keywords. Author with `semantic: true` (or `trigger: semantic`)."""
        return (_attr_true(self.attrs.get("semantic"))
                or self.attrs.get("trigger", "").strip().lower() == "semantic")

    def recurse(self) -> bool:
        """ST-14: this entry's body may trigger further entries (one extra pass,
        depth-capped). Opt-in with `recurse: true`."""
        return _attr_true(self.attrs.get("recurse"))

    def render(self) -> str:
        lines = [f"## {self.title}  {{#{self.slug}}}"]
        if self.aliases:
            lines.append("aliases: " + ", ".join(self.aliases))
        lines.append(f"importance: {self.importance}")
        for k, v in self.attrs.items():
            if v:
                lines.append(f"{k}: {v}")
        # A '## ' line inside a body would re-parse as a NEW entry and truncate
        # this one (registry sections are ## headings) — demote to '###' so
        # user markdown sub-headers survive the save/parse round-trip.
        body = re.sub(r"(?m)^##(?=\s)", "###", self.body.strip())
        return "\n".join(lines) + "\n\n" + body + "\n"

    def oneline(self) -> str:
        status = self.attrs.get("status", "")
        first = self.body.strip().splitlines()[0] if self.body.strip() else ""
        return f"{self.title} — {status or first}".strip(" —")

    def relationships(self) -> list[tuple[str, str]]:
        """Parse the optional `relationships:` attr ("slug: note; slug: note")."""
        out = []
        for part in self.attrs.get("relationships", "").split(";"):
            part = part.strip()
            if not part:
                continue
            sep = ":" if ":" in part else ("=" if "=" in part else None)
            if sep:
                a, b = part.split(sep, 1)
                out.append((a.strip(), b.strip()))
            else:
                out.append((part, ""))
        return out

    def stats(self) -> dict[str, int]:
        """Parse the optional `stats:` attr ("strength 3, agility 1" — `name value`
        or `name: value`, comma-separated). Markdown is the authoritative BASELINE
        for attributes; the mutable pools (hp/xp/...) stay in state.json."""
        out: dict[str, int] = {}
        for part in self.attrs.get("stats", "").split(","):
            part = part.strip().rstrip(".")
            if not part:
                continue
            m = re.match(r"^([a-z][a-z_-]*)\s*:?\s*([+-]?\d+)$", part.lower())
            if m:
                out[m.group(1)] = int(m.group(2))
        return out

    def skills(self) -> list[tuple[str, str | None]]:
        """Parse the optional `skills:` attr ("name (stat), name (stat), name").
        Returns (skill_name, governing_stat|None). Feeds the RPG module's tiered
        skill bonus (see rpg.skill_mod); purely descriptive when RPG is off."""
        return self._name_stat_list("skills")

    def abilities(self) -> list[tuple[str, str | None]]:
        """Parse the optional `abilities:` attr (Wave 3 level-up grants) — same
        `name (stat)` shape as skills; an ability counts as a trained skill."""
        return self._name_stat_list("abilities")

    def titles(self) -> list[str]:
        return [t.strip() for t in self.attrs.get("titles", "").split(",")
                if t.strip()]

    def _name_stat_list(self, key: str) -> list[tuple[str, str | None]]:
        out: list[tuple[str, str | None]] = []
        for part in self.attrs.get(key, "").split(","):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", part)
            if m:
                out.append((m.group(1).strip(), m.group(2).strip().lower() or None))
            else:
                out.append((part, None))
        return out


def parse_entries(text: str) -> list[Entry]:
    """Parse '## Name {#slug}' sections with key: value headers + body.
    HTML comments (skeleton examples) are ignored."""
    text = _strip_comments(text)
    entries: list[Entry] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _HEADING_RE.match(lines[i])
        if not m:
            i += 1
            continue
        title = m.group(1).strip()
        slug = m.group(2) or templates.slugify(title)
        aliases: list[str] = []
        importance = 3
        attrs: dict[str, str] = {}
        i += 1
        # header block: only lowercase-token key:value lines, until the first line
        # that isn't one (blank line or start of body).
        while i < len(lines) and lines[i].strip():
            am = _ATTR_RE.match(lines[i])
            if not am:
                break
            key, val = am.group(1), am.group(2).strip()
            if key == "aliases":
                aliases = [a.strip() for a in val.split(",") if a.strip()]
            elif key == "importance":
                try:
                    importance = int(val)
                except ValueError:
                    pass
            else:
                attrs[key] = val
            i += 1
        body_lines: list[str] = []
        while i < len(lines) and not _HEADING_RE.match(lines[i]):
            body_lines.append(lines[i])
            i += 1
        entries.append(Entry(title, slug, aliases, importance, attrs,
                             "\n".join(body_lines).strip()))
    return entries


def _real_headings(text: str) -> list[tuple[int, str]]:
    """Heading positions (line index, slug), ignoring headings inside HTML
    comments. Uses the same comment stripping as parse_entries so the two agree."""
    heads = []
    for idx, line in enumerate(_strip_comments(text).splitlines()):
        m = _HEADING_RE.match(line)
        if m:
            heads.append((idx, m.group(2) or templates.slugify(m.group(1).strip())))
    return heads


def _replace_or_append(text: str, entry: Entry) -> str:
    """Textually upsert an entry by slug, preserving everything else. Replaces the
    first matching section AND deletes any duplicate sections of the same slug, and
    keeps a blank line before the following heading so entries can't weld together."""
    lines = text.splitlines()
    heads = _real_headings(text)
    matches = [j for j, (_, slug) in enumerate(heads) if slug == entry.slug]
    if not matches:
        return text.rstrip("\n") + "\n\n" + entry.render().rstrip("\n") + "\n"
    covered: set[int] = set()
    for j in matches:
        start = heads[j][0]
        end = heads[j + 1][0] if j + 1 < len(heads) else len(lines)
        covered.update(range(start, end))
    first_start = heads[matches[0]][0]
    rendered = entry.render().rstrip("\n").splitlines() + [""]  # trailing blank line
    out: list[str] = []
    for idx, line in enumerate(lines):
        if idx == first_start:
            out.extend(rendered)
        if idx in covered:
            continue
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def _remove_section(text: str, slug: str) -> tuple[str, bool]:
    """Delete every '## ... {#slug}' section by slug. Returns (new_text, removed?)."""
    lines = text.splitlines()
    heads = _real_headings(text)
    matches = [j for j, (_, s) in enumerate(heads) if s == slug]
    if not matches:
        return text, False
    covered: set[int] = set()
    for j in matches:
        start = heads[j][0]
        end = heads[j + 1][0] if j + 1 < len(heads) else len(lines)
        covered.update(range(start, end))
    kept = [ln for idx, ln in enumerate(lines) if idx not in covered]
    return "\n".join(kept).rstrip("\n") + "\n", True


def _world_defaults(data: dict) -> dict:
    """Fill the Wave-1 state.json shape on read (SPEC-V2 A.4) so pre-W1 saves
    migrate lazily on first open: time gains weather; player (location/gold),
    quests and flags appear. Existing values are never touched."""
    tm = data.get("time")
    if not isinstance(tm, dict):
        tm = data["time"] = {"day": 1, "phase": "", "note": ""}
    tm.setdefault("weather", "")
    player = data.get("player")
    if not isinstance(player, dict):
        player = data["player"] = {}
    player.setdefault("location", "")
    player.setdefault("gold", 0)
    if not isinstance(data.get("quests"), dict):
        data["quests"] = {}
    if not isinstance(data.get("flags"), dict):
        data["flags"] = {}
    return data


class MemoryStore:
    """A single playthrough (save). Reads are layered for the governing rule files
    (writer/memory/rpg): save override -> scenario override -> global instructions.
    Everything else is save-local. Writes to a rule file target its effective layer
    (global by default) so editing a rule updates all saves; make_override() forks a
    save-local copy. All play state (transcript, registries, memory tiers, state.json)
    is written to the save folder."""

    def __init__(self, story_dir: str | Path,
                 instructions_dir: str | Path | None = None,
                 scenario_dir: str | Path | None = None):
        self.dir = Path(story_dir)
        self.instructions_dir = Path(instructions_dir) if instructions_dir else None
        self.scenario_dir = Path(scenario_dir) if scenario_dir else None

    # --- generic file access ---
    def path(self, rel: str) -> Path:
        """The save-local path (used for play-state writes and existence checks)."""
        return self.dir / rel

    def _layer_dirs(self, rel: str) -> list[tuple[str, Path]]:
        """Search order for a file, most specific first."""
        dirs = [("save", self.dir)]
        if rel in RULE_FILES:
            if self.scenario_dir is not None:
                dirs.append(("scenario", self.scenario_dir))
            if self.instructions_dir is not None:
                dirs.append(("global", self.instructions_dir))
        return dirs

    def resolve_read_path(self, rel: str) -> Path:
        for _, d in self._layer_dirs(rel):
            if (d / rel).exists():
                return d / rel
        return self.dir / rel

    def resolve_write_path(self, rel: str) -> Path:
        """Where an edit lands. Non-rule files: the save. Rule files: the layer they
        currently resolve from (existing override wins; else the global master)."""
        if rel in RULE_FILES:
            for _, d in self._layer_dirs(rel):
                if (d / rel).exists():
                    return d / rel
            if self.instructions_dir is not None:
                return self.instructions_dir / rel
        return self.dir / rel

    def layer_of(self, rel: str) -> str:
        for name, d in self._layer_dirs(rel):
            if (d / rel).exists():
                return name
        # Nothing exists yet: report the layer a write would actually target, so the
        # UI label can't disagree with resolve_write_path (only "global" when there
        # really is a global masters dir to write to).
        if rel in RULE_FILES and self.instructions_dir is not None:
            return "global"
        return "save"

    def read(self, rel: str) -> str:
        p = self.resolve_read_path(rel)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write(self, rel: str, text: str) -> None:
        """Atomic write (temp then os.replace) to the file's effective layer.
        The temp name is per-write unique so two concurrent writers to the same
        file can't clobber each other's in-progress `.tmp` (they still serialize
        at the final os.replace, which is atomic)."""
        p = self.resolve_write_path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f".{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            # os.replace is atomic, but on Windows it raises a sharing violation
            # (WinError 5) if an AV scanner/indexer — or a concurrent writer —
            # has the target momentarily open. Retry briefly before giving up.
            for attempt in range(10):
                try:
                    os.replace(tmp, p)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.02)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def make_override(self, rel: str) -> bool:
        """Fork a save-local copy of an inherited rule file so edits affect only this
        save. Returns False if not a rule file or an override already exists."""
        if rel not in RULE_FILES or (self.dir / rel).exists():
            return False
        (self.dir / rel).write_text(self.read(rel), encoding="utf-8")
        return True

    def remove_override(self, rel: str) -> bool:
        """Drop a save-local rule override, reverting to the inherited version."""
        p = self.dir / rel
        if rel in RULE_FILES and p.exists():
            p.unlink()
            return True
        return False

    def reset_rule(self, rel: str) -> bool:
        """Restore a rule file to its current shipped default, at its effective layer
        (an existing save/scenario override is reset in place; otherwise the global
        master). The escape hatch for a rule that drifted stale. Non-rule -> False."""
        if rel not in RULE_FILES:
            return False
        self.write(rel, templates.default_rule(rel))
        return True

    @property
    def title(self) -> str:
        try:
            data = json.loads(self.read("meta.json"))
        except json.JSONDecodeError:
            return self.dir.name
        return data.get("title", self.dir.name) if isinstance(data, dict) \
            else self.dir.name

    # --- custom lore types (Wave 2) ---------------------------------------
    def custom_files(self) -> list[str]:
        """Extra typed registry files this save (meta.json) and/or its scenario
        (scenario.json) declare — e.g. races.md, rules.md. Names are sanitized:
        bare .md filenames only, never paths, never a built-in file."""
        names: list[str] = []
        for path in (self.dir / "meta.json",
                     (self.scenario_dir / "scenario.json")
                     if self.scenario_dir else None):
            if path is None or not path.exists():
                continue
            try:
                declared = json.loads(path.read_text(encoding="utf-8")) \
                    .get("custom_files", [])
            except (json.JSONDecodeError, AttributeError):
                continue
            for raw in declared if isinstance(declared, list) else []:
                base = str(raw).removesuffix(".md")
                if not re.search(r"[A-Za-z0-9]", base):
                    continue                      # slugify would invent a name
                name = templates.slugify(base) + ".md"
                if name not in names and name not in _RESERVED_MD:
                    names.append(name)
        return names

    def gated_registries(self) -> list[str]:
        return GATED_REGISTRIES + self.custom_files()

    def index_files(self) -> list[str]:
        return INDEX_FILES + self.custom_files()

    def add_custom_file(self, name: str, description: str = "") -> str:
        """Declare (and seed) a new typed lore file on this save. Returns the
        sanitized filename."""
        base = str(name).removesuffix(".md")
        if not re.search(r"[A-Za-z0-9]", base):
            raise ValueError(f"not a usable lore file name: {name!r}")
        name = templates.slugify(base) + ".md"
        if name in _RESERVED_MD:
            raise ValueError(f"not a usable lore file name: {name!r}")
        try:
            meta = json.loads(self.read("meta.json"))
        except json.JSONDecodeError:
            meta = {}
        declared = meta.setdefault("custom_files", [])
        if name not in declared:
            declared.append(name)
            self.write("meta.json", json.dumps(meta, indent=2))
        if not self.path(name).exists():
            label = name.removesuffix(".md").replace("-", " ").title()
            self.write(name, f"# {label}\n\n"
                             f"{description or f'{label} — custom lore registry.'}\n")
        return name

    # --- timeless facts (Wave 2 semantic memory) ---------------------------
    def facts(self) -> list[str]:
        return [ln[2:].strip() for ln in self.read("memory/facts.md").splitlines()
                if ln.startswith("- ")]

    def add_facts(self, new: list[str]) -> int:
        """Append timeless world facts as bullets, deduped case-insensitively.
        Returns how many were actually added."""
        have = {f.lower() for f in self.facts()}
        added: list[str] = []
        for f in new:
            # Collapse whitespace INCLUDING newlines — an embedded "\n- " would
            # write extra bullets and break the dedupe round-trip.
            t = " ".join(str(f).split()) if f else ""
            if t and t.lower() not in have:
                have.add(t.lower())      # also dedupes within the batch itself
                added.append(t)
        if added:
            text = self.read("memory/facts.md").rstrip("\n")
            self.write("memory/facts.md",
                       text + "\n" + "\n".join(f"- {f}" for f in added) + "\n")
        return len(added)

    # --- story mode + beats (Wave 3) ---------------------------------------
    def mode(self) -> str:
        """Save-level story mode: 'simple' (tap-and-play, no mechanics, Logic
        Agent skipped) or 'rpg' (full campaign). Falls back to the RPG toggle
        for saves that predate the mode field."""
        try:
            m = json.loads(self.read("meta.json")).get("mode", "")
        except json.JSONDecodeError:
            m = ""
        if m in ("simple", "rpg"):
            return m
        return "rpg" if self.rpg_enabled() else "simple"

    def beats(self) -> list[str]:
        """The optional Acts/Arcs/Beats pacing list: '- ' bullets under a
        '## Beats' heading in memory/arc.md. The Logic Agent is steered by the
        current one and advances via the beat_advance delta."""
        out: list[str] = []
        in_beats = False
        for ln in self.read("memory/arc.md").splitlines():
            if ln.strip().lower().startswith("## beats"):
                in_beats = True
            elif ln.startswith("## "):
                in_beats = False
            elif in_beats and ln.strip().startswith("- "):
                out.append(ln.strip()[2:].strip())
        return out

    # --- companion side-chat log (Wave 3; NOT the transcript) ---------------
    def append_companion_chat(self, slug: str, user_text: str,
                              reply: str) -> None:
        """Log one side-chat exchange to memory/companion-chat.md — out-of-band
        by design: no turn counter, no folds, no timeline impact."""
        text = self.read("memory/companion-chat.md").rstrip("\n")
        block = (f"\n\n**You → {slug}:** {user_text.strip()}\n"
                 f"**{slug}:** {reply.strip()}")
        self.write("memory/companion-chat.md", text + block + "\n")

    def companion_chat_tail(self, slug: str = "", lines: int = 10) -> str:
        """The recent side-chat lines (optionally one companion's) — the short
        digest the Memory Manager gets so the story can react to private talk."""
        out = [ln for ln in self.read("memory/companion-chat.md").splitlines()
               if ln.startswith("**")
               and (not slug or f"{slug}:**" in ln or f"→ {slug}:" in ln)]
        return "\n".join(out[-lines:])

    # --- scenario event rules + opening override (Wave 4) -------------------
    def event_rules(self, include_consumed: bool = False) -> list[Entry]:
        """Authored "when X, then Y" rules from events.md — Logic Agent input,
        never the Writer's (unfired events must not leak into prose)."""
        out = []
        for e in self.entries("events.md"):
            if include_consumed or not _attr_true(e.attrs.get("consumed")):
                out.append(e)
        return out

    def event_rules_block(self) -> str:
        rules = self.event_rules()
        if not rules:
            return ""
        return ("# SCENARIO EVENT RULES (enforce these when their condition "
                "occurs; report fired rules via event_fired)\n\n"
                + "\n\n".join(e.render().strip() for e in rules))

    def event_rule_verdicts_block(self, history: list[dict],
                                  player_input: str) -> str:
        """D-260 lane (b) (Issue #127) : le bloc CANDIDAT du tour — jamais
        `event_rules_block()` entier (20 060 chars constants mesurés, I-158,
        `docs/mesure-i158-director-deux-corps.md`). Une règle avec
        `triggers_all` ne devient candidate que si son déclencheur machine
        matche le haystack du tour (même assiette que `haystack` ci-dessus
        dans `assemble()` : historique récent + entrée joueur) ; `triggers_not`
        l'écarte ; une règle SANS déclencheur machine (titre en langage
        naturel seul, cas des saves existantes) reste un candidat PERMANENT —
        la sélection par code n'improvise jamais depuis la prose (D-119), le
        jugement (une règle candidate n'est pas une règle tirée) reste au
        Director (D-078/I-111). Même framing Director-only que
        `event_rules_block()`."""
        haystack = (" ".join(t.get("text", "") for t in history)
                   + " " + player_input).lower()
        rules = [e for e in self.event_rules()
                if trigger_gate(e, haystack, permanent_if_no_triggers=True)]
        if not rules:
            return ""
        return ("# SCENARIO EVENT RULES (enforce these when their condition "
                "occurs; report fired rules via event_fired)\n\n"
                + "\n\n".join(e.render().strip() for e in rules))

    def mark_event_consumed(self, slug: str, consumed: bool = True) -> bool:
        """Flip a once-rule's consumed flag (undo flips it back)."""
        for e in self.entries("events.md"):
            if e.slug == slug:
                e.attrs["consumed"] = "true" if consumed else "false"
                self.upsert_entry("events.md", e)
                return True
        return False

    def opening_override(self) -> str:
        """A verbatim opening: the text under a '## Opening' heading in
        premise.md. When present, the engine uses it AS the opening scene
        instead of generating one (FictionLab's greeting message)."""
        lines = _strip_comments(self.read("premise.md")).splitlines()
        out: list[str] = []
        in_open = False
        for ln in lines:
            if ln.strip().lower().startswith("## opening"):
                in_open = True
            elif ln.startswith("## ") or ln.startswith("# "):
                if in_open:
                    break
                in_open = False
            elif in_open:
                out.append(ln)
        return "\n".join(out).strip()

    # --- response style (Wave 4) --------------------------------------------
    def custom_instructions(self) -> str:
        """The user-authored per-save style directives: everything below the
        `---` divider in custom-instructions.md."""
        text = self.read("custom-instructions.md")
        if "---" in text:
            text = text.split("---", 1)[1]
        return text.strip()

    # --- hidden lore reveal (Wave 2; the one sanctioned md mutation) --------
    def set_hidden(self, slug: str, hidden: bool) -> Entry | None:
        """Flip an entry's hidden flag across all registries (threads included —
        a hidden quest must be revealable too). Returns the entry (post-flip) or
        None when the slug doesn't exist. Reversible by design — undo re-hides
        via the same call."""
        for rel in self.gated_registries() + ["threads.md"]:
            for e in self.entries(rel):
                if e.slug == slug:
                    e.attrs["hidden"] = "true" if hidden else "false"
                    self.upsert_entry(rel, e)
                    return e
        return None

    # --- fold state (app metadata; derived, not memory) ---
    def state(self) -> dict:
        try:
            return json.loads(self.read(".fold_state.json"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {"folded_turns": 0, "folded_scenes": 0}

    def write_state(self, state: dict) -> None:
        self.write(".fold_state.json", json.dumps(state, indent=2))

    # --- snapshots (pre-fold safety / undo) ---
    def snapshot(self, keep: int = 5) -> Path:
        snaps = self.dir / ".snapshots"
        snaps.mkdir(exist_ok=True)
        base = time.strftime("%Y%m%d-%H%M%S")
        dest, n = snaps / base, 1
        while dest.exists():  # two folds in the same second must not collide
            dest, n = snaps / f"{base}-{n}", n + 1
        dest.mkdir(parents=True)
        extra = [self.path(".fold_state.json"), self.path("state.json"),
                 self.path("meta.json")]
        for src in list(self.dir.rglob("*.md")) + extra:
            if not src.exists() or ".snapshots" in src.parts:
                continue
            rel = src.relative_to(self.dir)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
        existing = sorted(p for p in snaps.iterdir() if p.is_dir())
        for old in existing[:-keep]:
            shutil.rmtree(old, ignore_errors=True)
        return dest

    # --- transcript (short-term source) ---
    @staticmethod
    def _render_turn(role: str, text: str) -> str:
        text = text.strip()
        if role == "player":
            block = "\n".join("> " + ln for ln in text.splitlines())
        else:
            block = text
        # Neutralize any '<!--' in the content so narration can't forge a turn
        # delimiter and split itself into bogus turns. Reversed in turns().
        block = block.replace("<!--", "<" + _ZW + "!--")
        return f"\n<!-- @{role} -->\n{block}\n"

    def append_turn(self, role: str, text: str) -> None:
        with self.path("transcript.md").open("a", encoding="utf-8") as f:
            f.write(self._render_turn(role, text))

    def drop_last_turns(self, k: int = 1) -> None:
        raw = self.read("transcript.md")
        idx = raw.find("<!-- @")
        header = raw[:idx] if idx != -1 else raw
        kept = self.turns()[:-k] if k else self.turns()
        body = "".join(self._render_turn(t["role"], t["text"]) for t in kept)
        self.write("transcript.md", header + body)

    def update_turn(self, i: int, text: str) -> bool:
        """Replace one turn's text in place (0-based over the full transcript).
        The in-place message editor (ST-03): rewriting Markdown is clean + honest.
        Folded summaries aren't retro-edited — same limitation ST has."""
        raw = self.read("transcript.md")
        idx = raw.find("<!-- @")
        header = raw[:idx] if idx != -1 else raw
        turns = self.turns()
        if not 0 <= i < len(turns):
            return False
        turns[i]["text"] = text.strip()
        body = "".join(self._render_turn(t["role"], t["text"]) for t in turns)
        self.write("transcript.md", header + body)
        return True

    def turns(self) -> list[dict]:
        out = []
        for role, block in _TURN_RE.findall(self.read("transcript.md")):
            body = block.strip().replace("<" + _ZW + "!--", "<!--")
            if role == "player":
                body = "\n".join(ln[2:] if ln.startswith("> ") else ln
                                 for ln in body.splitlines()).strip()
            out.append({"role": role, "text": body})
        return out

    def recent_turns(self, n: int) -> list[dict]:
        return self.turns()[-n:]

    def turns_range(self, start: int, end: int) -> list[dict]:
        """Verbatim turns in the 1-based inclusive range [start, end] (the pointer a
        timeline line records). Clamps out-of-range bounds and returns [] if empty."""
        turns = self.turns()
        lo = max(1, int(start))
        hi = min(len(turns), int(end))
        return turns[lo - 1:hi] if lo <= hi else []

    def recall_turns(self, reference: str, max_turns: int = 12) -> str:
        """Resolve a reference to a turn range and return those turns verbatim — the
        on-demand detail lookup behind a timeline shorthand. `reference` may be an
        explicit range ("T6-10"/"6-10"), a scene slug ("scene-2"), or free text that
        matches a timeline line (e.g. an event name). Returns a not-found note if
        nothing resolves."""
        ref = (reference or "").strip()
        if not ref:
            return "Provide a reference: an event/keyword, a scene, or a range like T6-10."
        rng = _range_from_ref(ref, self.read("memory/timeline.md"),
                              self.entries("memory/scenes.md"))
        if rng is None:
            return f"No timeline entry matches '{reference}'."
        turns = self.turns_range(*rng)
        if not turns:
            return f"Turn range T{rng[0]}-{rng[1]} is empty."
        head = f"Source turns T{rng[0]}-{rng[1]} (verbatim):"
        body = _turns_block(turns[:max_turns])
        return head + "\n\n" + body

    def _scenes_touching(self, slug: str, meta_keys: tuple[str, ...]) -> list[Entry]:
        """Episodes whose Wave-2 metadata attrs name `slug`."""
        out = []
        for sc in self.entries("memory/scenes.md"):
            meta = ",".join(sc.attrs.get(k, "") for k in meta_keys)
            if slug in {templates.slugify(p) for p in meta.split(",") if p.strip()}:
                out.append(sc)
        return out

    def recall_entity(self, name: str, max_scenes: int = 5) -> str:
        """Entity index lookup ("what happened with the innkeeper?"): the entry
        itself + every episode whose metadata names it, with turn pointers for
        verbatim drill-down via recall_turns."""
        slug = templates.slugify((name or "").strip())
        if not slug:
            return "Provide an entity name or slug."
        hit = self.index().resolve(slug)
        scenes = self._scenes_touching(slug, ("characters", "locations"))
        if hit is None and not scenes:
            return f"No entity or episode matches '{name}'."
        parts = []
        if hit is not None:
            parts.append(_masked_render(hit).strip())
        if scenes:
            parts.append("Episodes involving it (recall a T range for detail):")
            parts += [f"- [T{sc.attrs.get('turns', '?')}] {sc.title}: "
                      f"{sc.body.strip().splitlines()[0] if sc.body.strip() else ''}"
                      for sc in scenes[-max_scenes:]]
        return "\n".join(parts)

    def recall_quest(self, name: str, max_scenes: int = 5) -> str:
        """Quest/causal index lookup ("what advanced this quest?"): the thread
        entry + its live status + every episode whose metadata names it."""
        slug = templates.slugify((name or "").strip())
        if not slug:
            return "Provide a quest/thread name or slug."
        thread = next((e for e in self.entries("threads.md") if e.slug == slug),
                      None)
        status = self.world_state().get("quests", {}).get(slug, "")
        scenes = self._scenes_touching(slug, ("quests",))
        if thread is None and not scenes and not status:
            return f"No quest or episode matches '{name}'."
        parts = []
        if thread is not None:
            parts.append(_masked_render(thread).strip())
        if status:
            parts.append(f"Current status: {status}")
        if scenes:
            parts.append("Episodes that touched it (recall a T range for detail):")
            parts += [f"- [T{sc.attrs.get('turns', '?')}] {sc.title}: "
                      f"{sc.body.strip().splitlines()[0] if sc.body.strip() else ''}"
                      for sc in scenes[-max_scenes:]]
        return "\n".join(parts)

    def has_turns(self) -> bool:
        return bool(_TURN_RE.search(self.read("transcript.md")))

    # --- registry helpers ---
    def entries(self, rel: str) -> list[Entry]:
        return parse_entries(self.read(rel))

    def upsert_entry(self, rel: str, entry: Entry) -> None:
        self.write(rel, _replace_or_append(self.read(rel), entry))

    def remove_entry(self, rel: str, slug: str) -> bool:
        """Delete an entry by slug (used by RPG inventory_remove). Returns True if
        anything was removed."""
        text, removed = _remove_section(self.read(rel), slug)
        if removed:
            self.write(rel, text)
        return removed

    def merge_entry(self, rel: str, new: Entry, rewrite: bool = False) -> None:
        """Fold a promotion into an existing entry without clobbering identity.

        rewrite=False (Phase 2 default): append genuinely new detail to the body.
        rewrite=True (Phase 3): the summarizer was shown the current entry and
        returns the FULL rewritten body, so replace the body with it. Either way we
        union aliases, keep the highest importance, and update attrs (status/when/
        relationships), so nothing durable is silently lost."""
        existing = {e.slug: e for e in self.entries(rel)}.get(new.slug)
        if existing is None:
            self.upsert_entry(rel, new)
            return
        aliases = list(dict.fromkeys(existing.aliases + new.aliases))
        importance = max(existing.importance, new.importance)
        if rewrite:
            body = new.body.strip() or existing.body
            # Managed keys are authoritative from the rewrite: the model was shown
            # the current entry and restates what is still true, so a dropped
            # relationship / when / status is an intentional clear, not a loss.
            managed = {"status", "when", "relationships"}
            attrs = {k: v for k, v in existing.attrs.items() if k not in managed}
            attrs.update(new.attrs)
        else:
            attrs = {**existing.attrs, **new.attrs}
            body = existing.body
            addition = new.body.strip()
            if addition and addition not in body:
                body = (body + "\n\n" + addition).strip() if body else addition
        merged = Entry(existing.title or new.title, new.slug, aliases, importance,
                       attrs, body)
        self.upsert_entry(rel, merged)

    # --- in-world clock + world mutables (Phase 3, expanded Wave 1) ---
    def world_state(self) -> dict:
        try:
            data = json.loads(self.read("state.json"))
        except (json.JSONDecodeError, FileNotFoundError):
            data = None
        # Guard valid-but-wrong-shape JSON (e.g. a hand edit to {"time":"evening"}
        # or []) — degrade to the default rather than crashing every turn.
        if not isinstance(data, dict):
            data = {}
        return _world_defaults(data)

    def set_world_state(self, state: dict) -> None:
        self.write("state.json", json.dumps(state, indent=2))

    def clock_str(self) -> str:
        t = self.world_state().get("time", {})
        if not isinstance(t, dict):
            t = {}
        parts = []
        if t.get("day") is not None:
            parts.append(f"Day {t['day']}")
        if t.get("phase"):
            parts.append(str(t["phase"]))
        if t.get("weather"):
            parts.append(str(t["weather"]))
        s = ", ".join(parts)
        if t.get("note"):
            s = f"{s} — {t['note']}".strip(" —")
        return s

    # --- events log (Wave 1; SPEC-V2 §1.4) ---
    def append_event_log(self, record: dict) -> None:
        """Append one JSONL record to memory/events.jsonl — the per-turn validated
        envelope. Replay from the save's baseline reproduces the state exactly
        (rolls are seed+nonce deterministic), which is what W4 branching builds on."""
        path = self.dir / "memory" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def truncate_event_log(self, max_turn: int) -> None:
        """Drop records logged past the transcript's current end. Undo/retry
        truncate the transcript — a stale envelope surviving here would be
        double-applied by the next branch replay."""
        path = self.dir / "memory" / "events.jsonl"
        if not path.exists():
            return
        kept = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("turn", 0) <= max_turn:
                kept.append(rec)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                for r in kept), encoding="utf-8")

    # --- fold log (forensics; separate file ON PURPOSE) ---
    def append_fold_log(self, record: dict) -> None:
        """Append one JSONL record to memory/fold-log.jsonl — what each fold saw
        before it truncated, and what it rewrote.

        Its own file, not events.jsonl: that log is REPLAYED by save_branch (it
        rebuilds state from it) and pruned by truncate_event_log, so a foreign
        record shape there is a correctness risk for branching. This one is
        write-only forensics — nothing reads it to rebuild anything.

        Not a snapshot either: snapshot() copies *.md + the two json state files
        and keeps only `snapshot_keep` of them, so the evidence would age out
        after a handful of folds. This file lives in the save and only grows."""
        path = self.dir / "memory" / "fold-log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --- RPG module state (Phase 4; lives in state.json under "rpg") ---
    def rpg_state(self) -> dict:
        rpg = self.world_state().get("rpg")
        return rpg if isinstance(rpg, dict) else {}

    def set_rpg_state(self, rpg: dict) -> None:
        state = self.world_state()
        state["rpg"] = rpg
        self.set_world_state(state)

    def rpg_enabled(self) -> bool:
        return bool(self.rpg_state().get("enabled"))

    def index(self) -> "MemoryIndex":
        return MemoryIndex(self)

    def lookup(self, query: str, limit: int = 4) -> str:
        """Free-text search over all entries (used by the LLM lookup tool).
        Hidden entries come back MASKED — the recall tools feed the Writer, so
        a full render here would bypass the Secrets foreshadow framing."""
        hits = self.index().find(query)[:limit]
        if not hits:
            return f"No memory entries match '{query}'."
        return "\n\n".join(_masked_render(e) for _, e in hits)

    # --- context assembly (narrator prompt) ---
    def _entry_activates(self, e: "Entry", haystack: str, seed: int,
                         turn_index: int, recent: list[str],
                         player_now: str) -> bool:
        """A non-forced entry's trigger decision, incl. the Tier-2 gates.
        (pinned/critical entries bypass this — they're always in.)

        Timed effects (ST-10) are derived purely from the transcript — no mutable
        counters — so they stay replay-safe and survive retries. `recent` is the
        list of committed turn texts (lowercased); `player_now` is the pending
        action; `turn_index` is the committed message count."""
        toks = e.triggers()
        # ST-10 delay: dormant until at least N messages exist.
        delay = e.delay()
        if delay is not None and turn_index < delay:
            return False
        # primary: title / slug / aliases / `triggers:` (any hit in context)
        primary = any(trigger_hit(tok, haystack) for tok in toks)
        # ST-10 sticky: keep active if triggered within the last N messages, even
        # once it has scrolled out of the immediate context window.
        from_sticky = False
        sticky = e.sticky()
        if not primary and sticky:
            window = " ".join(recent[-sticky:])
            if any(trigger_hit(tok, window) for tok in toks):
                primary, from_sticky = True, True
        if not primary:
            return False
        # ST-13 secondary keys: ALL of triggers_all must also hit...
        reqs = e.triggers_all()
        if reqs and not all(trigger_hit(tok, haystack) for tok in reqs):
            return False
        # ...and NONE of triggers_not may be present.
        if any(trigger_hit(tok, haystack) for tok in e.triggers_not()):
            return False
        # ST-10 cooldown: after firing, stay quiet for N messages unless the
        # player re-mentions it in the current action.
        cooldown = e.cooldown()
        if cooldown and not any(trigger_hit(tok, player_now) for tok in toks):
            prior = " ".join(recent[-cooldown:])
            if any(trigger_hit(tok, prior) for tok in toks):
                return False
        # ST-11 probability: reproducible per (story seed, turn, entry) so a
        # retry of the same turn keeps the same activations. chance>=100 → always.
        # A sticky continuation skips the roll — `chance` gates the INITIAL fire
        # only; otherwise a stuck entry would flicker as the per-turn roll re-rolls.
        chance = e.chance()
        if not from_sticky and chance is not None and chance < 100:
            rng = random.Random(f"{seed}-{turn_index}-{e.slug}-chance")
            if rng.randint(1, 100) > chance:
                return False
        return True

    def _collapse_groups(self, candidates: list, seed: int, turn_index: int) -> list:
        """ST-12: for each inclusion group among the activated candidates, keep a
        single winner chosen by seeded weighted random (weight = weight_factor x
        importance). Ungrouped candidates pass through untouched. Seeded by
        (seed, turn, group) so a retry of the same turn keeps the same winner."""
        groups: dict[str, list] = {}
        out = []
        for c in candidates:
            e = c[2]
            # pinned/critical are ALWAYS in — they never enter the group lottery,
            # or an "always present" entry could lose it and vanish.
            g = "" if (e.pinned() or e.weight() == "critical") else e.group()
            (groups.setdefault(g, []) if g else out).append(c)
        for name, members in groups.items():
            if len(members) == 1:
                out.append(members[0])
                continue
            weights = [max(0.0, m[2].weight_factor() * m[2].importance)
                       for m in members]
            rng = random.Random(f"{seed}-{turn_index}-{name}-group")
            out.append(rng.choices(members, weights=weights, k=1)[0]
                       if sum(weights) > 0 else members[0])
        return out

    def _recursion_pass(self, picked: dict, matched_slugs: set, by_slug: dict,
                        seed: int, turn_index: int, recent: list[str],
                        player_now: str, used_lore: int, lore_budget: int) -> int:
        """ST-14: entries flagged `recurse: true` let their body activate further
        entries — exactly one extra pass. The newly-activated entries do NOT
        recurse (depth cap 1). Hidden/pinned/critical stay out of the pass. Extras
        respect the remaining lore budget. Returns the updated used_lore."""
        fuel = " ".join(e.body for group in picked.values() for e in group
                        if e.recurse()).lower()
        if not fuel.strip():
            return used_lore
        extra: list[tuple[float, str, Entry]] = []
        for slug, (rel, e) in by_slug.items():
            if slug in matched_slugs or e.hidden() or e.pinned() \
                    or e.weight() == "critical":
                continue
            if self._entry_activates(e, fuel, seed, turn_index, recent, player_now):
                extra.append((e.weight_factor() * e.importance, rel, e))
        extra.sort(key=lambda c: c[0], reverse=True)
        # ST-12 still holds through recursion: at most one member per inclusion
        # group survives (counting any group already represented in the first pass).
        picked_groups = {e.group() for grp in picked.values() for e in grp
                         if e.group()}
        for _score, rel, e in extra:
            g = e.group()
            if g and g in picked_groups:
                continue
            block = len(e.render())
            if used_lore + block > lore_budget:
                break
            picked.setdefault(rel, []).append(e)
            matched_slugs.add(e.slug)
            used_lore += block
            if g:
                picked_groups.add(g)
        return used_lore

    def _activate_lore(self, haystack: str, player_now: str,
                       recent_texts: list[str], turn_index: int, seed: int,
                       retriever, budget_tokens: int,
                       lore_include: set[str] | None = None):
        """The lorebook half of assemble(): scan every gated entry against the
        haystack, collapse inclusion groups, compete for the lore budget, run
        the one recursion pass. Returns (picked, hidden_hits, matched_slugs,
        linked_wanted, ordered) — `ordered` is the surviving visible entries in
        score order, the raw material of a selection report.

        `lore_include` is the CAMERA's tranche (the Director's judgment on which
        activated entries serve THIS scene): when given, an activated entry that
        is not named and not forced (pinned/critical) is dropped BEFORE the
        budget competition. Forced entries stay unfilterable — "always in
        context" is an authored contract, and a tranche that could silence one
        would let a selection mistake masquerade as an authoring choice."""
        matched_slugs = set()
        candidates: list[tuple[float, str, Entry]] = []   # (score, rel, entry)
        hidden_hits: list[Entry] = []
        by_slug: dict[str, tuple[str, Entry]] = {}
        for rel in self.gated_registries():
            for e in self.entries(rel):
                by_slug.setdefault(e.slug, (rel, e))
                always = e.pinned() or e.weight() == "critical"
                hit = always or self._entry_activates(
                    e, haystack, seed, turn_index, recent_texts, player_now)
                if not hit:
                    continue
                if e.hidden():
                    hidden_hits.append(e)
                    continue
                score = e.weight_factor() * e.importance + (100 if always else 0)
                candidates.append((score, rel, e))
        # ST-17: semantic-triggered lore. Only when at least one entry opts into
        # `semantic: true` do we spend an extra retriever pass here — kept separate
        # from the "Recalled" pass below so the common case stays a single call and
        # the Recalled top-K isn't diluted by already-activated slugs. Promotion
        # honors the HARD gates (hidden stays hidden, `triggers_not` suppresses,
        # `chance:0` never fires, `delay` holds) but not the keyword gate itself —
        # activating without keywords is the whole point of semantic triggering.
        if retriever is not None and any(e.semantic()
                                         for _s, (_r, e) in by_slug.items()):
            already = {c[2].slug for c in candidates}
            exclude = {e.slug for e in self.entries("player.md")} | already
            for e in retriever(haystack, exclude):
                if not (e.semantic() and not e.hidden() and e.slug in by_slug):
                    continue
                if e.slug in already or e.chance() == 0:
                    continue
                dly = e.delay()
                if dly is not None and turn_index < dly:
                    continue
                if any(trigger_hit(tok, haystack) for tok in e.triggers_not()):
                    continue
                rel = by_slug[e.slug][0]
                candidates.append((e.weight_factor() * e.importance, rel, e))
                already.add(e.slug)
        # ST-12: mutually-exclusive inclusion groups collapse to one winner each
        # (weighted) before the budget competition.
        candidates = self._collapse_groups(candidates, seed, turn_index)
        candidates.sort(key=lambda c: c[0], reverse=True)
        lore_budget = budget_tokens * 4 * 0.45   # chars; lore may use just under half
        picked: dict[str, list[Entry]] = {}
        linked_wanted: list[str] = []
        used_lore = 0
        ordered: list[tuple[float, str, Entry]] = []
        for score, rel, e in candidates:
            if lore_include is not None and e.slug not in lore_include \
                    and not (e.pinned() or e.weight() == "critical"):
                continue          # the tranche: not selected for this scene
            block = len(e.render())
            if score < 100 and used_lore + block > lore_budget:
                continue          # budget cutoff hits activated entries, never pinned
            picked.setdefault(rel, []).append(e)
            matched_slugs.add(e.slug)
            used_lore += block
            linked_wanted += [s for s in e.links() if s in by_slug]
            ordered.append((score, rel, e))
        # ST-14: one recursion pass — bodies of `recurse: true` entries can trigger
        # further entries (hard depth cap of 1; the extras never recurse again).
        used_lore = self._recursion_pass(
            picked, matched_slugs, by_slug, seed, turn_index,
            recent_texts, player_now, used_lore, lore_budget)
        return picked, hidden_hits, matched_slugs, linked_wanted, ordered

    def lore_candidates(self, history: list[dict], player_input: str,
                        budget_tokens: int = 8000, retriever=None) -> list[dict]:
        """The documentaliste's report: WHAT the activation WOULD serve, before
        anyone judges whether it serves THIS scene. Same scan, same groups, same
        budget as assemble() — metadata only, no bodies, no assembly. Cheap
        (CPU only), deterministic, off the latency path.

        Hidden entries that activated are reported too, flagged `hidden: true`:
        this report feeds the Director, who holds the secrets. It must never be
        shown to the player or handed to the narrator."""
        all_turns = self.turns()
        turn_index = len(all_turns)
        recent_texts = [t.get("text", "").lower() for t in all_turns]
        haystack = (" ".join(t["text"] for t in history) + " " + player_input).lower()
        rpg_block = self.world_state().get("rpg")
        try:
            seed = int(rpg_block.get("seed", 0)) if isinstance(rpg_block, dict) else 0
        except (TypeError, ValueError):
            seed = 0
        picked, hidden_hits, _ms, _lw, ordered = self._activate_lore(
            haystack, player_input.lower(), recent_texts, turn_index, seed,
            retriever, budget_tokens)
        rows = [{"slug": e.slug, "registry": rel, "title": e.title,
                 "chars": len(e.render()),
                 "forced": bool(e.pinned() or e.weight() == "critical")}
                for _score, rel, e in ordered]
        rows += [{"slug": e.slug, "registry": "", "title": e.title,
                  "chars": len(e.render()), "hidden": True}
                 for e in hidden_hits]
        return rows

    def assemble(self, history: list[dict], player_input: str,
                 scenes_tail: int = 4, budget_tokens: int = 8000,
                 retriever=None, lore_include: set[str] | None = None) -> list[dict]:
        idx = self.index()
        writer_rules = self.read("writer-rules.md").strip()
        haystack = (" ".join(t["text"] for t in history) + " " + player_input).lower()

        # sections: (priority, title, body). priority 0 = always keep.
        sections: list[tuple[int, str, str]] = []
        premise = _premise_prose(self.read("premise.md"))
        if premise:
            sections.append((0, "Premise", premise))
        # D-216 §3: persistent attributes are read ONCE per assembly and served
        # on every rendered entry that declares them (current value + history).
        pstate = self.world_state().get("persistent")
        player = self.entries("player.md")
        if player:
            sections.append(
                (0, "You",
                 "\n\n".join(_context_render(e) + _persistent_suffix(e, pstate)
                             for e in player)))
        clock = self.clock_str()
        loc = self.world_state().get("player", {}).get("location", "")
        if clock or loc:
            now = ("Current in-world time: " + clock) if clock else ""
            if loc:
                now = (now + "\n" if now else "") + "Current location: " + loc
            sections.append((1, "Time", now))
        world = _strip_h1(self.read("world-bible.md"))
        if world:
            sections.append((1, "World", world))
        open_threads = [e for e in self.entries("threads.md")
                        if e.attrs.get("status", "open").lower() != "resolved"
                        and not e.hidden()]
        if open_threads:
            sections.append(
                (1, "Open threads",
                 "\n\n".join(_context_render(e) + _persistent_suffix(e, pstate)
                             for e in open_threads)))
        arc = _strip_h1(self.read("memory/arc.md"))
        if arc:
            sections.append((1, "Story so far (arc)", arc))
        # Newest 50 facts only: the file is append-only, and an unbounded list
        # would slowly squeeze the lorebook out of the budget.
        facts = self.facts()[-50:]
        if facts:
            sections.append((1, "Established facts (timeless truths)",
                             "\n".join(f"- {f}" for f in facts)))
        beats = self.beats()
        if beats:
            cur = self.world_state().get("beat")
            cur = cur if isinstance(cur, int) and 0 <= cur < len(beats) else 0
            sections.append((1, "Story beat (pacing)",
                             f"Beat {cur + 1}/{len(beats)}: {beats[cur]}\n"
                             "(advance with the beat_advance delta once its "
                             "goal lands — never skip ahead in prose)"))
        chat_tail = self.companion_chat_tail()
        if chat_tail:
            sections.append((3, "Companion side-chat (recent, private)",
                             chat_tail))
        # Last N SCENES (entries), not paragraphs — an entry renders as two
        # paragraphs, so the paragraph count showed half the intended tail and
        # desynced from the related-scenes exclusion below.
        scene_entries = self.entries("memory/scenes.md")
        if scene_entries:
            scenes = "\n\n".join(e.render().strip()
                                 for e in scene_entries[-scenes_tail:])
        else:
            scenes = _recent_paragraphs(self.read("memory/scenes.md"),
                                        scenes_tail)
        if scenes:
            sections.append((2, "Recent scenes", scenes))
        tl_lines = [ln for ln in self.read("memory/timeline.md").splitlines()
                    if ln.lstrip().startswith("- [T")]
        if tl_lines:
            sections.append((2, "Timeline (shorthand; recall a [T..] range for detail)",
                             "\n".join(tl_lines)))

        # --- lorebook activation (Wave 2 + Tier 2) ------------------------
        # pinned/critical entries are ALWAYS in; the rest activate on a trigger
        # match (title/slug/aliases + the `triggers:` attr), refined by the
        # optional Tier-2 gates (secondary keys ST-13, probability ST-11), and
        # compete for a lore budget ranked by weight x importance. Hidden entries
        # never join the normal sections — they get their own foreshadow block.
        # turn_index + seed make the probability roll reproducible across a retry
        # of the same turn (replay-safe, like the RPG dice).
        all_turns = self.turns()
        turn_index = len(all_turns)
        recent_texts = [t.get("text", "").lower() for t in all_turns]
        player_now = player_input.lower()
        # A hand-edited state.json may carry a malformed rpg block (null, a list,
        # a non-int seed) — degrade to seed 0 (still deterministic) rather than
        # crashing every turn.
        rpg_block = self.world_state().get("rpg")
        try:
            seed = int(rpg_block.get("seed", 0)) if isinstance(rpg_block, dict) else 0
        except (TypeError, ValueError):
            seed = 0
        picked, hidden_hits, matched_slugs, linked_wanted, _ordered = \
            self._activate_lore(haystack, player_now, recent_texts, turn_index,
                                seed, retriever, budget_tokens,
                                lore_include=lore_include)
        for rel in self.gated_registries():
            if rel in picked:
                label = rel.replace(".md", "").replace("-", " ").title()
                # A section carrying pinned/critical lore outranks the bulky
                # scene/timeline sections in the outer salience budget — the
                # "always in context" contract must survive a tight budget.
                pr = 1 if any(e.pinned() or e.weight() == "critical"
                              for e in picked[rel]) else 2
                sections.append((pr, label,
                                 "\n\n".join(_context_render(e)
                                             + _persistent_suffix(e, pstate)
                                             for e in picked[rel])))
        if hidden_hits:
            # NOTE: this section keeps Entry.render() (not _context_render)
            # deliberately -- mcp_server.py's secret-splice/leak guard
            # (`_splice_secrets`/`_hidden_exposure`) matches hidden entries by
            # locating this EXACT rendered text inside the assembled prefix;
            # changing it here would desync that matching (I-376 review).
            sections.append((
                2, SECRETS_SECTION_TITLE,
                "\n\n".join(e.render() + _persistent_suffix(e, pstate)
                            for e in hidden_hits)))

        # related past episodes (Wave 2 hybrid retrieval): folds whose metadata
        # names an entity that just activated, plus their chronological
        # neighbors — old scenes about the people/places now in play.
        all_scenes = self.entries("memory/scenes.md")
        if matched_slugs and len(all_scenes) > scenes_tail:
            tail_slugs = {e.slug for e in all_scenes[-scenes_tail:]}
            wanted: list[int] = []
            for i, sc in enumerate(all_scenes):
                meta = ",".join(sc.attrs.get(k, "") for k in
                                ("characters", "locations", "quests"))
                touched = {templates.slugify(p) for p in meta.split(",")
                           if p.strip()}
                if touched & matched_slugs:
                    wanted += [j for j in (i - 1, i, i + 1)
                               if 0 <= j < len(all_scenes)
                               and all_scenes[j].slug not in tail_slugs]
            if wanted:
                keep = sorted(dict.fromkeys(wanted))[:4]
                sections.append((3, "Related past scenes (entities now present)",
                                 "\n\n".join(all_scenes[j].render()
                                             for j in keep)))

        # reference resolution: one-liners for [[slug]] referenced anywhere in the
        # gathered context, plus `links:` of activated lore — never hidden ones.
        corpus = haystack + " " + scenes + " " + arc \
            + " ".join(e.body for e in open_threads)
        ref_slugs = [s for s in _LINK_RE.findall(corpus) + linked_wanted
                     if s in idx.entries and s not in matched_slugs
                     and not idx.entries[s][1].hidden()]
        if ref_slugs:
            lines = [idx.entries[s][1].oneline() for s in dict.fromkeys(ref_slugs)]
            sections.append((3, "Referenced (by name)", "\n".join(lines)))

        # semantic recall (Phase 5, optional): salient entries related to the current
        # context that alias-gating and reference resolution didn't already surface.
        # Full exclude BEFORE the retriever's top-K slice so the K slots go to fresh
        # recalls; hidden entries never surface here (they belong only in Secrets).
        if retriever is not None:
            exclude = set(matched_slugs) | set(ref_slugs) | {e.slug for e in player}
            recalled = [e for e in retriever(haystack, exclude)
                        if e.slug not in exclude and not e.hidden()]
            if recalled:
                sections.append((3, "Recalled (semantically related)",
                                 "\n\n".join(e.render() for e in recalled)))

        # index of canon events so unreferenced ones stay discoverable by name.
        canon = [e for e in self.entries("canon-events.md") if not e.hidden()]
        if canon:
            names = ", ".join(f"{e.title} [[event:{e.slug}]]" for e in canon)
            sections.append((4, "Known canon events", names))

        # salience budget: keep priority-0 always; fill the rest until budget.
        # No single section may exceed the whole budget, so even an always-on
        # premise/player can't blow past the context window.
        budget = budget_tokens * 4
        used = 0
        chosen = []
        for pr, title, body in sorted(sections, key=lambda s: s[0]):
            seg = f"## {title}\n{body}"
            if len(seg) > budget:
                seg = seg[:budget] + "\n…(truncated)"
            if pr == 0 or used + len(seg) <= budget:
                chosen.append(seg)
                used += len(seg)

        system = writer_rules
        if chosen:
            # ST-20: one macro pass over the whole authored context ({{user}},
            # {{roll::2d6}}, {{random::a::b}}, {{day}}, {{clock}}). Seeded by
            # (seed, turn) so a retry of the same turn expands identically.
            tm = self.world_state().get("time")
            ctx = expand_macros(
                "\n\n".join(chosen),
                player=(player[0].title if player else "you"),
                clock=clock,
                day=(str(tm.get("day", "")) if isinstance(tm, dict) else ""),
                seed=seed, turn=turn_index)
            system += "\n\n# STORY & MEMORY CONTEXT\n\n" + ctx

        messages = [{"role": "system", "content": system}]
        for t in history:
            messages.append({"role": "user" if t["role"] == "player" else "assistant",
                             "content": t["text"]})
        messages.append({"role": "user", "content": player_input})
        return messages

    def strip_secrets_section(self, content: str) -> str:
        """Remove the "Secrets you know" section `assemble()` may have appended
        above, if present. A no-op when it never activated (no pinned/critical
        hidden entry fired this turn — the common case, I-159).

        Exists so a caller sharing ONE `assemble()` result between a
        Director-like reader and a Writer-like reader can hand the Writer its
        own copy with the Director-only section explicitly retiré, instead of
        relying on the Writer simply never being handed that copy (director-
        pipeline's `trinity.py::_writer_messages`, Issue #108) — the same
        retrait mcp_server.py names `secrets=False` on the director-de-table
        side (`assemble_context_to_file`), same section, same intent, applied
        after the fact here because `assemble()` itself has no such toggle."""
        header = "## " + SECRETS_SECTION_TITLE + "\n"
        start = content.find(header)
        if start == -1:
            return content
        # Runs to the next top-level heading (assemble()'s own "## " sections,
        # or a later "# " block an engine-side augment step appended) or EOF.
        end = content.find("\n\n#", start + len(header))
        end = end if end != -1 else len(content)
        prefix = content[:start]
        if prefix.endswith("\n\n"):
            prefix = prefix[:-2]
        return prefix + content[end:]


class MemoryIndex:
    """In-memory query layer over the story's entries. Rebuilt cheaply each turn;
    Phase 4 will back this with a persisted embeddings index."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self.entries: dict[str, tuple[str, Entry]] = {}
        self.duplicate_slugs: list[str] = []
        for rel in store.index_files():
            for e in store.entries(rel):
                if e.slug in self.entries:
                    self.duplicate_slugs.append(e.slug)
                self.entries[e.slug] = (rel, e)
        corpus = " ".join(e.body for _, e in self.entries.values())
        corpus += " " + store.read("memory/scenes.md") + " " + store.read("memory/arc.md")
        self.ref_counts = Counter(_LINK_RE.findall(corpus))

    def resolve(self, slug: str) -> Entry | None:
        hit = self.entries.get(slug)
        return hit[1] if hit else None

    def relationships(self) -> dict[str, list[tuple[str, str]]]:
        """Derived relationship graph: slug -> [(other_slug, note), ...]."""
        graph = {}
        for slug, (_, e) in self.entries.items():
            rels = e.relationships()
            if rels:
                graph[slug] = rels
        return graph

    def dangling_refs(self) -> list[str]:
        corpus = self.store.read("memory/scenes.md") + " " \
            + self.store.read("memory/arc.md") \
            + " ".join(e.body for _, e in self.entries.values())
        return sorted({s for s in _LINK_RE.findall(corpus) if s not in self.entries})

    def find(self, query: str) -> list[tuple[str, Entry]]:
        q = query.lower().strip()
        scored = []
        for slug, (rel, e) in self.entries.items():
            hay = (e.title + " " + slug + " " + " ".join(e.aliases) + " "
                   + e.body).lower()
            if q in hay:
                # rank: exact trigger match first, then importance + references.
                exact = any(q == t.lower() for t in e.triggers())
                score = (2 if exact else 0) + e.importance + self.ref_counts[slug]
                scored.append((score, rel, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(rel, e) for _, rel, e in scored]


def _persistent_suffix(e: Entry, pstate: dict | None) -> str:
    """The live persistent-attribute block for one entry (D-216 §3): every
    attribute declared `persistent:` is served with its CURRENT engine-tracked
    value (state.json "persistent" block) followed by the recent mutation
    history (who / when / value). Before the first in-session write the
    entry's own baseline line is shown. '' when nothing live applies, so
    entries without persistent state render exactly as before."""
    decls = e.persistent_attrs()
    if not decls:
        return ""
    recs = pstate.get(e.slug) if isinstance(pstate, dict) else None
    recs = recs if isinstance(recs, dict) else {}
    lines: list[str] = []
    for attr in decls:
        rec = recs.get(attr)
        hist = None
        if isinstance(rec, dict) and "value" in rec:
            cur = rec["value"]
            hist = rec.get("history") \
                if isinstance(rec.get("history"), list) else []
        elif str(e.attrs.get(attr, "")).strip():
            cur = e.attrs[attr]
        else:
            continue
        lines.append(f"- {attr}: {cur}")
        for m in (hist or [])[-5:]:
            lines.append(f"  - {m.get('when', '?')}: set to {m.get('value')} "
                         f"(by {m.get('who', '?')})")
    if not lines:
        return ""
    return ("\n\nPersistent state (live values tracked by the engine):\n"
            + "\n".join(lines))


# Attribute keys that are purely internal bookkeeping (activation/authoring
# machinery or raw ids) and never carry narrative content -- I-376 (D-82 the
# narrator must never see an explicit "hidden"/secret-status marker; D-219
# internal ids are invisible to narrator and player alike). Entry.render()
# itself must keep dumping every attr verbatim (memory.py:447/454 round-trip
# entries back to the authored Markdown file byte-for-byte), so the filter
# lives in this narrator-facing sibling instead, used only at assemble()'s
# context-building call sites -- never for file persistence.
_INTERNAL_ATTRS = {
    "hidden", "pinned", "weight", "chance", "delay", "sticky", "cooldown",
    "triggers", "triggers_all", "triggers_not", "group", "semantic",
    "recurse", "persistent", "origin", "resolved_origin",
}


def _context_render(e: Entry) -> str:
    """Entry.render(), minus internal-only attrs (_INTERNAL_ATTRS) and any
    attr whose KEY looks like a raw internal id (`node_id`, `tension_id`, a
    bare `id`, or anything ending in `_id`/`_uuid`) -- narrator-facing text
    should read as natural authored prose, never framework bookkeeping."""
    lines = [f"## {e.title}  {{#{e.slug}}}"]
    if e.aliases:
        lines.append("aliases: " + ", ".join(e.aliases))
    lines.append(f"importance: {e.importance}")
    for k, v in e.attrs.items():
        key = k.strip().lower()
        if not v or key in _INTERNAL_ATTRS or key == "id" \
                or key.endswith(("_id", "_uuid")):
            continue
        lines.append(f"{k}: {v}")
    body = re.sub(r"(?m)^##(?=\s)", "###", e.body.strip())
    return "\n".join(lines) + "\n\n" + body + "\n"


def _masked_render(e: Entry) -> str:
    """A hidden entry seen through a recall tool: name only, framed as an
    unrevealed secret — never the body (the Secrets section in assemble() is
    the one sanctioned channel, with its foreshadow framing)."""
    if not e.hidden():
        return _context_render(e)
    return (f"## {e.title}  {{#{e.slug}}}\n\n(SECRET — known to you but not "
            "yet revealed to the player. Foreshadow only; never state its "
            "details until it is revealed.)")


def trigger_hit(tok: str, haystack: str) -> bool:
    """Word-boundary trigger match against an already-lowercased haystack:
    'Ash' must not activate inside 'washed', nor 'Ana' inside 'banana'."""
    tok = tok.strip().lower()
    if not tok:
        return False
    return re.search(r"(?<!\w)" + re.escape(tok) + r"(?!\w)", haystack) \
        is not None


def trigger_gate(e: Entry, haystack: str, *,
                  permanent_if_no_triggers: bool = False) -> bool:
    """D-260 : le geste commun de sélection par déclencheur machine — partagé
    par l'assembleur position (`assembleur_position._rule_verdicts_section`,
    lane a, Issue #125) et l'évaluateur de règles d'événement (lane b, Issue
    #127). `triggers_not` écarte toujours l'entrée si présent. Sans
    `triggers_all`, `permanent_if_no_triggers` tranche : False (lane a) exige
    un déclencheur explicite ; True (lane b) traite l'absence de déclencheur
    comme un candidat PERMANENT (titre en langage naturel seul — on ne devine
    jamais depuis la prose, D-119)."""
    if any(trigger_hit(tok, haystack) for tok in e.triggers_not()):
        return False
    reqs = e.triggers_all()
    if not reqs:
        return permanent_if_no_triggers
    return all(trigger_hit(tok, haystack) for tok in reqs)


def _strip_h1(text: str) -> str:
    text = _strip_comments(text).strip()
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _premise_prose(text: str) -> str:
    """The premise PROSE only: minus the H1 header AND the verbatim `## Opening`
    greeting (which is turn 1 of the transcript, not standing world context — it
    shouldn't also ride in the premise section every turn)."""
    out: list[str] = []
    for ln in _strip_comments(text).splitlines():
        if ln.startswith("# "):
            continue
        if ln.strip().lower().startswith("## opening"):
            break
        out.append(ln)
    return "\n".join(out).strip()


def _recent_paragraphs(text: str, n: int) -> str:
    body = _strip_h1(text)
    if not body:
        return ""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return "\n\n".join(paras[-n:])


def _unique_slug(root: Path, base: str) -> str:
    slug, n = base, 2
    while (root / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return {}


class ScenarioLibrary:
    """Reusable authored worlds under scenarios/. A scenario is the template a save
    is instantiated from (premise + world bible + starting cast + optional rule
    overrides)."""

    def __init__(self, root: str | Path, instructions_dir=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.instructions_dir = Path(instructions_dir) if instructions_dir \
            else None

    def dir(self, slug: str) -> Path:
        return self.root / slug

    def exists(self, slug: str) -> bool:
        return bool(slug) and (self.root / slug / "scenario.json").exists()

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and (d / "scenario.json").exists():
                data = _read_json(d / "scenario.json")
                out.append({"slug": d.name, "title": data.get("title", d.name),
                            "created": data.get("created", 0),
                            "description": data.get("description", "")})
        out.sort(key=lambda s: s["created"], reverse=True)
        return out

    def create(self, title: str, premise: str, world: str = "",
               description: str = "", introduction: str = "") -> str:
        slug = _unique_slug(self.root, templates.slugify(title))
        templates.seed_scenario(self.root / slug, title, premise, world,
                                description, introduction=introduction,
                                instructions_dir=self.instructions_dir)
        return slug

    def update_meta(self, slug: str, title: str = "",
                    description: str | None = None) -> bool:
        """Rename / re-describe a world (the builder's main-details save)."""
        path = self.root / slug / "scenario.json"
        if not path.exists():
            return False
        data = _read_json(path)
        if title.strip():
            data["title"] = title.strip()
        if description is not None:
            data["description"] = str(description).strip()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True

    def export(self, slug: str, dest: str | Path) -> str:
        """Zip a scenario's files to `dest` (a .zip path), excluding stray temp
        files — the mirror of SaveLibrary.export. Returns the archive path."""
        src = self.root / slug
        if not (src / "scenario.json").exists():
            raise FileNotFoundError(f"no such scenario: {slug}")
        dest = Path(dest)
        if dest.suffix.lower() != ".zip":
            dest = dest.with_suffix(".zip")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(src.rglob("*")):
                if p.is_dir() or p.suffix in (".tmp", ".db"):
                    continue
                z.write(p, p.relative_to(src).as_posix())
        return str(dest)

    def import_(self, zip_path: str | Path, title: str | None = None) -> str:
        """Load a world exported by export() into a new scenario folder. Mirror of
        SaveLibrary.import_, keyed on scenario.json. Returns the new slug."""
        zip_path = Path(zip_path)
        base_title = title or zip_path.stem
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            marks = [n for n in names if n.rsplit("/", 1)[-1] == "scenario.json"]
            if not marks:
                raise ValueError(
                    "archive has no scenario.json — not a Coderain world export")
            mark = min(marks, key=lambda n: n.count("/"))
            prefix = mark[:-len("scenario.json")]          # "" or "inner/"
            slug = _unique_slug(self.root, templates.slugify(base_title))
            dst = self.root / slug
            dst.mkdir(parents=True)
            for n in names:
                if prefix and not n.startswith(prefix):
                    continue
                rel = n[len(prefix):]
                if not _safe_zip_member(dst, rel):     # guard traversal + absolute
                    continue
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as srcf, open(target, "wb") as outf:
                    shutil.copyfileobj(srcf, outf)
        if title:
            self.rename(slug, title)
        return slug

    def rename(self, slug: str, title: str) -> bool:
        p = self.root / slug / "scenario.json"
        if not p.exists():
            return False
        data = _read_json(p)
        data["title"] = title
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True

    def delete(self, slug: str) -> bool:
        if not _safe_child(self.root, slug):    # never rmtree outside the root
            return False
        d = self.root / slug
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False

    def ensure_default(self) -> None:
        """Seed the bundled showcase world on a fresh install. Only when the
        library is empty, so a user who deletes it isn't force-fed it again."""
        if not self.list():
            from . import default_scenario
            default_scenario.seed(self.root / default_scenario.SLUG)


class SaveLibrary:
    """Playthroughs under saves/. Each save is instantiated from a scenario (its
    authored world is copied in) and then evolves independently; rule files are
    inherited live from the scenario / global instructions unless overridden."""

    def __init__(self, root: str | Path, scenarios: ScenarioLibrary,
                 instructions_dir: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.scenarios = scenarios
        self.instructions_dir = Path(instructions_dir)

    def dir(self, slug: str) -> Path:
        return self.root / slug

    def meta(self, slug: str) -> dict:
        return _read_json(self.root / slug / "meta.json")

    def _write_meta(self, slug: str, meta: dict) -> None:
        (self.root / slug / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and (d / "meta.json").exists():
                data = _read_json(d / "meta.json")
                out.append({"slug": d.name, "title": data.get("title", d.name),
                            "created": data.get("created", 0),
                            "updated": data.get("updated", data.get("created", 0)),
                            "scenario": data.get("scenario", ""),
                            "mode": data.get("mode", "")})
        out.sort(key=lambda s: s["updated"], reverse=True)
        return out

    def create(self, title: str, scenario_slug: str = "",
               rpg_enabled: bool = False, premise: str = "",
               mode: str = "", rpg_cfg: dict | None = None,
               start_time: dict | None = None) -> str:
        """Create a save. From a scenario (its world is copied in) or, when no
        scenario is given, directly from an inline `premise` (no scenario is
        registered — avoids scenario proliferation for one-off stories).
        `mode` = 'simple' | 'rpg' (Wave 3); 'rpg' also enables mechanics."""
        if mode == "rpg":
            rpg_enabled = True
        slug = _unique_slug(self.root, templates.slugify(title))
        scen_dir = (self.scenarios.dir(scenario_slug)
                    if self.scenarios.exists(scenario_slug) else None)
        templates.new_save(self.root / slug, scen_dir, title,
                           scenario_slug if scen_dir else "", rpg_enabled,
                           premise=premise, mode=mode, rpg_cfg=rpg_cfg,
                           instructions_dir=self.instructions_dir,
                           start_time=start_time)
        # Genesis record: proves the event log reaches back to the save's very
        # beginning, so a branch may rebuild state from scratch by replay. A
        # save without it (pre-sweep) can't be told apart from one that lost
        # records — those branches keep their state and warn instead.
        store = MemoryStore(self.root / slug, self.instructions_dir, scen_dir)
        store.append_event_log({"turn": 0, "env": {}})
        return slug

    def store(self, slug: str) -> MemoryStore:
        # A missing save must RAISE, not materialize: the migration below
        # seeds play files, so opening a bad slug used to conjure a phantom
        # save folder (found via a literal saves/undefined directory).
        if not (self.root / slug / "meta.json").exists():
            raise FileNotFoundError(f"no such save: {slug}")
        scen = self.meta(slug).get("scenario", "")
        scen_dir = self.scenarios.dir(scen) if self.scenarios.exists(scen) else None
        store = MemoryStore(self.root / slug, self.instructions_dir, scen_dir)
        # Migration: seed any play-state file this save predates (e.g. timeline.md on
        # a save created before that feature). Idempotent; only writes what's missing.
        for rel in templates.PLAY_FILES:
            if not store.path(rel).exists():
                store.write(rel, templates.user_default(
                    rel, self.instructions_dir)
                    if rel in templates.USER_DEFAULTABLE
                    else templates.FILE_SKELETONS[rel])
        # Wave 2: custom lore files declared by the scenario materialize in the
        # save on first open (copied from the scenario when authored there).
        for name in store.custom_files():
            if not store.path(name).exists():
                src = (scen_dir / name) if scen_dir else None
                if src is not None and src.exists():
                    store.write(name, src.read_text(encoding="utf-8"))
                else:
                    label = name.removesuffix(".md").replace("-", " ").title()
                    store.write(name, f"# {label}\n\n{label} — custom lore registry.\n")
        _sync_player_stats(store)
        return store

    def open(self, slug: str, keep: int = 5) -> MemoryStore:
        """`store(slug)` plus a versioning snapshot (I-148/ESC-4, Issue #110): a
        dated, rotating copy of the save's play state taken at the moment a
        frontend actually opens it for play — the same `.snapshots/` mechanism
        already used pre-fold (`MemoryStore.snapshot`), just triggered on open
        too. Zero save-format change, zero lock: a plain filesystem copy next
        to the save, never on the read/write path of play itself.

        Every frontend's session-open call site (play.py `_open`, server.py
        `_engine`, gui.py `_open_story`, mcp_server.py `load_save`) goes
        through here instead of bare `store()` — `store()` itself stays
        snapshot-free since it also backs ancillary mid-session lookups (world
        editing, character application) that are not a fresh "session start"
        and would otherwise spam `.snapshots/` on every touch.

        A snapshot failure (disk full, permissions, …) must never prevent the
        game from opening — it's a best-effort filet layered on top of, not a
        gate in front of, the existing save system."""
        store = self.store(slug)
        try:
            store.snapshot(keep=keep)
        except Exception:  # noqa: BLE001 — a failed safety net must not block play
            pass
        return store

    def touch(self, slug: str) -> None:
        """Bump the save's updated timestamp (so recency sort reflects play)."""
        meta = self.meta(slug)
        if meta:
            meta["updated"] = time.time()
            self._write_meta(slug, meta)

    def branch(self, slug: str, turn_n: int,
               rpg_cfg: dict | None = None) -> tuple[str, list[str]]:
        """Fork a save at turn N (SPEC-V2 §4.2): copy the save, truncate the
        transcript to N, restore the Markdown memory from the nearest pre-fold
        snapshot ≤ N (avoiding "remembers the future" bleed), then rebuild the
        state by replaying the events log up to N (rolls are deterministic).
        Past snapshot retention the branch still works but keeps the current
        memory files — returned warnings say so. Returns (new_slug, warnings)."""
        from . import validator as validator_mod
        src = self.root / slug
        if not (src / "meta.json").exists():
            raise FileNotFoundError(f"no such save: {slug}")
        src_store = self.store(slug)
        turns = src_store.turns()
        turn_n = max(1, min(int(turn_n), len(turns)))
        warnings: list[str] = []
        title = f"(BRANCH) {src_store.title} @T{turn_n}"
        dst_slug = _unique_slug(self.root, templates.slugify(title))
        dst = self.root / dst_slug
        shutil.copytree(src, dst,
                        ignore=shutil.ignore_patterns(".snapshots", "*.tmp",
                                                      "*.db"))
        meta = _read_json(dst / "meta.json")
        meta.update({"title": title, "created": time.time(),
                     "updated": time.time()})
        (dst / "meta.json").write_text(json.dumps(meta, indent=2),
                                       encoding="utf-8")
        scen = meta.get("scenario", "")
        scen_dir = self.scenarios.dir(scen) if self.scenarios.exists(scen) \
            else None
        dst_store = MemoryStore(dst, self.instructions_dir, scen_dir)

        # 1) memory fidelity: nearest pre-fold snapshot with <= N turns.
        snap = _nearest_snapshot(src, turn_n)
        snap_turns = 0
        if snap is not None:
            for f in snap.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(snap)
                    if rel == Path("meta.json"):
                        # meta.json is now part of the snapshot (I-148/ESC-4)
                        # but a branch must keep ITS OWN meta (title/created
                        # already rewritten above) — never the source's.
                        continue
                    target = dst / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
            snap_turns = len(MemoryStore(snap).turns())
        else:
            warnings.append(
                "no snapshot old enough — memory files (characters, scenes, "
                "arc) may contain post-branch knowledge")

        # 2) transcript: exactly turns 1..N (verbatim, from the source).
        dst_store.write("transcript.md", templates.FILE_SKELETONS["transcript.md"])
        for t in turns[:turn_n]:
            dst_store.append_turn(t["role"], t["text"])

        # 3) state: replay the events log onto the restored base.
        records = _read_event_log(src_store)
        # A log is "complete" when it reaches back to the save's beginning: a
        # genesis record (turn 0, seeded at creation) or a first-exchange
        # record (opening logs turn 1, first exchange turn 2). Only then can
        # the state be rebuilt from scratch without a snapshot.
        complete = bool(records) and records[0].get("turn", 99) <= 2
        replay = True
        if snap is None:
            if complete:
                # No snapshot but a complete log: rebuild state from a fresh
                # block, preserving identity (seed keeps rolls deterministic).
                cur = dst_store.rpg_state()
                cur_full = dst_store.world_state()   # copied-from-source full state
                state = templates.initial_state(rpg_cfg)
                state["rpg"]["enabled"] = bool(cur.get("enabled"))
                state["rpg"]["seed"] = cur.get("seed", state["rpg"]["seed"])
                if isinstance(cur.get("player", {}).get("stats"), dict):
                    state["rpg"]["player"]["stats"] = dict(cur["player"]["stats"])
                # Carry forward top-level state that NO event delta can rebuild
                # (author's note, quick actions, output-regex rules) — else a
                # branch before the first fold silently loses them.
                for k in ("authors_note", "quick_actions", "regex_rules"):
                    if k in cur_full:
                        state[k] = cur_full[k]
                dst_store.set_world_state(state)
                snap_turns = 0
            else:
                # Replaying onto the source's CURRENT state would double-apply
                # every delta — keep the state as-is and say so loudly.
                replay = False
                warnings.append(
                    "event log doesn't reach the save's beginning — state kept "
                    f"as of the original save's latest turn, not T{turn_n}")
        if replay:
            replayable = [r for r in records
                          if snap_turns < r.get("turn", 0) <= turn_n]
            validator_mod.replay_records(dst_store, rpg_cfg or {}, replayable)
        # the branch's own log = everything up to the fork
        _write_event_log(dst_store,
                         [r for r in records if r.get("turn", 0) <= turn_n])

        # 4) drop folds/timeline lines that cover post-branch turns, then make
        # the fold counter agree with the scenes that actually remain — a
        # future-counting .fold_state.json would leave turns never folded.
        _filter_folds_after(dst_store, turn_n)
        _reconcile_fold_state(dst_store)
        return dst_slug, warnings

    def duplicate(self, slug: str, new_title: str | None = None) -> str:
        src = self.root / slug
        if not (src / "meta.json").exists():
            raise FileNotFoundError(f"no such save: {slug}")
        title = new_title or (self.meta(slug).get("title", slug) + " (copy)")
        dst_slug = _unique_slug(self.root, templates.slugify(title))
        # A branch starts clean: don't drag along the original's undo history or a
        # stray half-written temp file.
        shutil.copytree(src, self.root / dst_slug,
                        ignore=shutil.ignore_patterns(".snapshots", "*.tmp", "*.db"))
        meta = self.meta(dst_slug)
        meta.update({"title": title, "created": time.time(), "updated": time.time()})
        self._write_meta(dst_slug, meta)
        return dst_slug

    def rename(self, slug: str, title: str) -> bool:
        meta = self.meta(slug)
        if not meta:
            return False
        meta["title"] = title
        meta["updated"] = time.time()
        self._write_meta(slug, meta)
        return True

    def delete(self, slug: str) -> bool:
        if not _safe_child(self.root, slug):    # never rmtree outside the root
            return False
        d = self.root / slug
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False

    def export(self, slug: str, dest: str | Path) -> str:
        """Zip a save's live files to `dest` (a .zip path), excluding the undo
        snapshot history and any stray temp files. Returns the archive path."""
        src = self.root / slug
        if not (src / "meta.json").exists():
            raise FileNotFoundError(f"no such save: {slug}")
        dest = Path(dest)
        if dest.suffix.lower() != ".zip":
            dest = dest.with_suffix(".zip")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(src.rglob("*")):
                if p.is_dir():
                    continue
                rel = p.relative_to(src)
                if ".snapshots" in rel.parts or p.suffix in (".tmp", ".db"):
                    continue
                z.write(p, rel.as_posix())
        return str(dest)

    def import_(self, zip_path: str | Path, title: str | None = None) -> str:
        """Load a save exported by export() into a new save folder. Validates that
        the archive is actually a save (has a meta.json), tolerates a save nested one
        level deep, and never cross-moves files (so duplicate names can't clobber).
        Returns the new save's slug."""
        zip_path = Path(zip_path)
        base_title = title or zip_path.stem
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            metas = [n for n in names if n.rsplit("/", 1)[-1] == "meta.json"]
            if not metas:
                raise ValueError(
                    "archive has no meta.json — not a Coderain save export")
            # The save root = the folder holding the shallowest meta.json.
            meta_name = min(metas, key=lambda n: n.count("/"))
            prefix = meta_name[:-len("meta.json")]        # "" or "inner/"
            slug = _unique_slug(self.root, templates.slugify(base_title))
            dst = self.root / slug
            dst.mkdir(parents=True)
            for n in names:
                if prefix and not n.startswith(prefix):
                    continue                              # ignore files outside the save
                rel = n[len(prefix):]
                if not _safe_zip_member(dst, rel):        # guard traversal + absolute
                    continue
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as srcf, open(target, "wb") as outf:
                    shutil.copyfileobj(srcf, outf)
        meta = self.meta(slug)
        meta.setdefault("created", time.time())
        meta["title"] = title or meta.get("title", base_title)
        meta["updated"] = time.time()
        self._write_meta(slug, meta)
        return slug


def _nearest_snapshot(save_dir: Path, turn_n: int) -> Path | None:
    """The most recent pre-fold snapshot whose transcript has <= turn_n turns —
    the memory base a branch at turn_n restores from."""
    snaps = save_dir / ".snapshots"
    if not snaps.exists():
        return None
    best: tuple[int, Path] | None = None
    for d in sorted(p for p in snaps.iterdir() if p.is_dir()):
        try:
            count = len(MemoryStore(d).turns())
        except Exception:  # noqa: BLE001 — a corrupt snapshot never blocks
            continue
        if count <= turn_n and (best is None or count >= best[0]):
            best = (count, d)
    return best[1] if best else None


def _read_event_log(store: MemoryStore) -> list[dict]:
    out = []
    for line in store.read("memory/events.jsonl").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _write_event_log(store: MemoryStore, records: list[dict]) -> None:
    store.write("memory/events.jsonl",
                "".join(json.dumps(r, ensure_ascii=False) + "\n"
                        for r in records))


def _fold_end(attr: str) -> int:
    """The end turn of a fold's `turns:` attr — 'a-b' or a bare 'n'."""
    m = re.match(r"\s*(\d+)(?:\s*-\s*(\d+))?", attr or "")
    return int(m.group(2) or m.group(1)) if m else 0


def _filter_folds_after(store: MemoryStore, turn_n: int) -> None:
    """Remove scenes + timeline lines whose source-turn range reaches past the
    branch point (they summarize turns the branch no longer has)."""
    scenes = store.entries("memory/scenes.md")
    for sc in scenes:
        if _fold_end(sc.attrs.get("turns", "")) > turn_n:
            store.remove_entry("memory/scenes.md", sc.slug)
    kept = []
    for ln in store.read("memory/timeline.md").splitlines():
        tm = _TL_RANGE_RE.search(ln)
        if tm and int(tm.group(2)) > turn_n:
            continue
        kept.append(ln)
    store.write("memory/timeline.md", "\n".join(kept).rstrip("\n") + "\n")


def _reconcile_fold_state(store: MemoryStore) -> None:
    """Recompute .fold_state.json from the scenes actually present. After a
    branch restores an older snapshot (which may predate the fold counter) or
    filters folds away, an inherited counter would claim turns were folded
    that no scene covers — those turns would silently never fold again."""
    scenes = store.entries("memory/scenes.md")
    folded = 0
    for sc in scenes:
        folded = max(folded, _fold_end(sc.attrs.get("turns", "")))
    st = store.state()
    st["folded_turns"] = folded
    st["folded_scenes"] = len(scenes)
    store.write_state(st)


def _sync_player_stats(store: MemoryStore) -> None:
    """Keep the player's attribute BASELINES visible + authoritative in player.md.

    Markdown is the source of truth for authored numbers: a `stats:` line on the
    player entry overwrites the matching baselines in state.json's rpg block on
    every open (edit the file → the sheet follows). If player.md has no stats line
    yet but the rpg block does, the current numbers are written INTO player.md once
    so they stop being json-only. Mutables (hp/mana/xp/level/conditions) never sync
    — they live in state.json alone. NOTE: nothing in rpg.apply mutates attribute
    baselines today; if a stat-increase mechanic is ever added it must write the new
    value back to player.md (md wins here on every open). Best-effort: a malformed
    file never blocks opening a save."""
    try:
        rpg = store.rpg_state()
        p_stats = rpg.get("player", {}).get("stats")
        if not isinstance(p_stats, dict):
            return
        players = store.entries("player.md")
        player = next((e for e in players if e.slug == "player"),
                      players[0] if players else None)
        if player is None:
            return
        changed_state = False
        changed_md = False
        md_stats = player.stats()
        if md_stats:
            merged = {**p_stats, **md_stats}      # md wins for the stats it lists
            if merged != p_stats:
                rpg["player"]["stats"] = merged
                changed_state = True
        elif p_stats:
            player.attrs["stats"] = ", ".join(f"{k} {v}" for k, v in p_stats.items())
            changed_md = True
        # Wave 3: abilities/titles follow the same pattern — the md line wins in
        # full when present; a json-only list is written INTO player.md once.
        # (Grants also write back to md at apply time, so this is the safety net.)
        for key in ("abilities", "titles"):
            md_line = player.attrs.get(key, "").strip()
            json_list = rpg.get("player", {}).get(key)
            if md_line:
                parsed = [p.strip() for p in md_line.split(",") if p.strip()]
                if parsed != (json_list or []):
                    rpg["player"][key] = parsed
                    changed_state = True
            elif isinstance(json_list, list) and json_list:
                player.attrs[key] = ", ".join(json_list)
                changed_md = True
        if changed_state:
            store.set_rpg_state(rpg)
        if changed_md:
            store.upsert_entry("player.md", player)
    except Exception:  # noqa: BLE001
        pass


class Library:
    """Top-level app storage: global instructions + scenarios + saves under one root.
    Wires the three layers together and seeds the global rule masters on first use."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.instructions_dir = self.root / "instructions"
        # Seed + migrate the global rule masters. `outdated_rules` = user-edited
        # masters that now differ from the shipped default (an update was withheld to
        # protect the edit); the UI/CLI can offer a reset. Unedited masters are
        # upgraded automatically so app updates actually reach installed rules.
        self.outdated_rules = templates.seed_instructions(self.instructions_dir)
        self.scenarios = ScenarioLibrary(self.root / "scenarios",
                                         self.instructions_dir)
        # Saves resolve through config.saves_dir(self.root): for the production
        # root this consults SAVES_DIR env / config.yaml `saves_dir:` (real play
        # data can live outside this repo, D-224, while scenarios/instructions
        # stay put) ; for any other root (every test harness opens one against a
        # throwaway tmp dir) it's exactly self.root/"saves", unchanged.
        self.saves = SaveLibrary(saves_dir(self.root), self.scenarios,
                                 self.instructions_dir)

    def reset_all_rules(self) -> list[str]:
        """Force-restore every global master to its current shipped default (the
        nuclear 'reset rules to default' action). Save/scenario overrides are left
        alone. Returns the files reset and refreshes the version ledger."""
        for name in templates.RULE_FILES:
            (self.instructions_dir / name).write_text(
                templates.default_rule(name), encoding="utf-8")
        self.outdated_rules = templates.seed_instructions(self.instructions_dir)
        return list(templates.RULE_FILES)

    # --- convenience / backward-compatible helpers ---
    def create_story(self, title: str, premise: str) -> str:
        """Simple 'new story from a premise' flow (+ tests): create a save directly
        from the inline premise. Does NOT register a scenario — one-off stories must
        not litter the reusable-world library (author a scenario explicitly for
        reuse)."""
        return self.saves.create(title, premise=premise)

    def list_stories(self) -> list[dict]:
        return self.saves.list()

    def store(self, slug: str) -> MemoryStore:
        return self.saves.store(slug)

    def open(self, slug: str, keep: int = 5) -> MemoryStore:
        return self.saves.open(slug, keep=keep)
