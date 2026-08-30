"""Default contents for a new story's memory files.

Markdown is the source of truth. `seed_story()` writes these into a story folder.
Registry entries follow a light, parseable format:

    ## Display Name  {#slug}
    aliases: Alt Name, nickname
    importance: 4
    status: one-line current state

    Freeform body. Reference other entities by name or [[slug]]; keep each
    entity's full detail only in its own file (see memory-rules.md).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from . import sidecar

WRITER_RULES = """\
# Writer rules & tone

These rules govern how the story is narrated. They are injected into the
narrator's system prompt every turn. Edit freely.

## Voice
- Second person ("you"), present tense.
- Immersive, concrete prose with sensory detail. Show, don't summarize.

## Turn structure
- Narrate the outcome of the player's action, then hand control back.
- Never decide the player's own choices, dialogue, or feelings for them.
- Let the world react; introduce consequences, not just description.
- End on a beat that invites the next action. Don't ask "What do you do?"
  every time — vary it or leave a charged pause.

## Length
- Roughly 2-4 paragraphs, unless the moment calls for less.

## Continuity
- Stay consistent with everything in the story context: premise, world bible,
  characters, locations, canon events, and open threads. Never contradict them.

## Content boundaries
- (Set any tone or content limits here.)
"""

MEMORY_RULES = """\
# Memory rules (policy)

This file is injected into the *summarizer/triage* prompt. It tells the model how
to maintain memory when folding the transcript. Edit to change memory behavior.

## Tiers
- **Short-term** = the raw tail of `transcript.md` (verbatim recent turns).
- **Medium-term** = `memory/scenes.md`: concise scene summaries. When the
  short-term window overflows, fold the oldest turns into one scene summary.
- **Long-term** = `memory/arc.md`: a terse running synopsis of the whole story.
  When enough scene summaries accumulate, fold the oldest into the arc.

## Reference, don't duplicate  (the core rule)
Every entity has ONE home file where its full details live:
- characters -> `characters.md`     - locations -> `locations.md`
- factions   -> `factions.md`       - items     -> `items.md`
- canon events -> `canon-events.md` - open threads -> `threads.md`

Everywhere else (scene summaries, the arc synopsis, and other entities' entries)
refer to an entity **by name or [[slug]] only** — never restate its details.
When you need the detail, resolve the reference to its home file.

Examples:
- The arc says: "the murder at [[event:kings-death]] still hangs over the city."
  The full account of that event lives only in `canon-events.md`.
- A scene says: "you promise [[char:mara]] to return the ledger (see
  [[thread:the-ledger-debt]])." The thread's details live only in `threads.md`.

## Triage (promotion)
When folding, before compressing, extract anything durable and write it to its
home file:
- a new/changed character or location -> update its entry (identity is stable;
  status is mutable).
- a story-critical event -> add a `canon-events.md` entry.
- a new obligation, mystery, or dangling hook -> add a `threads.md` entry;
  when resolved, mark it done rather than deleting.
Rate each entry's `importance` 1-5. Then compress the rest; ephemeral color may
fade.

## Rewrite, don't append
When you update an existing entity you will be shown its CURRENT entry. Return the
entity's FULL rewritten detail — the stable identity plus every still-true fact
plus the change — not just the new delta. The rewrite replaces the old body.

## Relationships
Record a character's relationships on that character's own entry via a
`relationships:` line, referencing the other party by slug, e.g.
`relationships: mara: trusts you; kael: bitter rival`. Keep the detail on the
character; other entries refer by slug only.

## Lorebook attributes (activation control — all optional)
Any entry may carry these header lines; absent means normal behavior:
- `weight: minor|supplementary|standard|important|critical` — how strongly it
  competes for context. `critical` is ALWAYS in context.
- `pinned: true` — always in context regardless of weight.
- `triggers: word, phrase` — extra activation keywords beyond the entry's
  name/aliases (the entry is injected when a recent turn mentions one).
- `hidden: true` — the storyteller knows this, the player must NOT: twists,
  secrets, hidden agendas. Foreshadow it; never state it outright. It stays
  hidden until the story reveals it.
- `links: slug, slug` — related pieces to surface (as one-liners) whenever this
  entry activates.

### Advanced activation (Tier 2 — all optional, absent = normal)
- `triggers_all: word, word` — secondary keys that must ALSO all be present for
  the entry to activate (AND). `triggers_not: word, word` — any of these present
  SUPPRESSES it (NOT). Great for context-specific variants.
- `chance: 0-100` — activation probability; rolled reproducibly per turn (a
  retry keeps the same result). Use for rare flavor that shouldn't fire always.
- `group: name` — only ONE activated entry of a group is kept, chosen weighted +
  reproducibly. Perfect for mutually-exclusive rumor/event variants.
- `delay: N` — dormant until at least N messages have passed. `sticky: N` — once
  triggered, stays active for the next N messages (even after it scrolls out of
  context). `cooldown: N` — after firing, stays quiet for N messages unless
  re-mentioned. Timed effects are derived from the transcript (replay-safe).
- `semantic: true` — activate by meaning (embedding similarity) instead of
  keywords; needs the vector recall module enabled.
- `recurse: true` — this entry's body may trigger further entries (one extra
  pass only; the entries it pulls in do not themselves recurse).
Preserve these lines when rewriting an entry; set them on new entries when the
fiction warrants it (a twist you invent should usually be `hidden: true`).

## Quests and companions (Wave 3)
A thread that is a QUEST may carry `type: quest` and an `objectives:` line
(semicolon-separated). Its live state (inactive/active/completed/failed) is
tracked by the engine, not in this file — do not restate quest status in
summaries beyond referencing the thread. A character who travels with the
player may carry `companion: true`; their trust/mood live in the engine state.
Private companion side-chat is NOT story canon — never promote from it unless
the story itself later confirms it.

## Established facts (semantic memory)
`memory/facts.md` holds timeless world truths as short bullets ("The capital is
Asterhold"), NOT events. When folding, report durable truths in the `facts`
field; events belong in canon-events, not facts.

## Episode metadata
Every scene fold reports which `characters`, `locations`, and `quests` the turns
touched (slugs) plus terse `state_changes` — these build the entity/quest
indexes ("what happened with X?"). Best effort: never block a fold on them.

## Character facets (visual, mentality, voice, skills)
When you promote or rewrite a character, keep these four labeled facets in the body
(rewrite in full — never drop one that is still true):
- **Visual:** how they look at a glance.
- **Mentality:** how they act and decide.
- **Voice:** how they talk — include a short sample line when you can.
- **Skills:** notable competencies.
When a skill maps to a governing stat, also keep the structured `skills:` line
(`name (stat), ...`); the RPG module reads it for trained-skill bonuses. Likewise
preserve a `stats:` line (`strength 3, agility 2, ...`) when present — it is the
authoritative attribute baseline the RPG module rolls with.

## In-world time
Track the passage of in-world time. When a scene moves time forward, report the
new time (day + phase). Stamp events with `when:` so the chronology stays
consistent.
"""

RPG_RULES = """\
# RPG rules (mechanics module)

Injected into the narrator's prompt ONLY when RPG mechanics are enabled for this
story (a per-story toggle; off by default). Edit freely to reskin the system.

## The core rule: you never roll dice
The engine rolls, not you. When the outcome of the player's action is uncertain and
worth resolving, PROPOSE a check; the engine rolls d20 + the relevant stat, applies
the result, and tells you the outcome on the *next* turn (see "Last check" in your
sheet). Narrate the attempt this turn; narrate the verdict once the engine reports it.

## The sidecar (envelope v1)
After your prose, you MAY append a single fenced block (omit it entirely when nothing
mechanical happens). A code validator checks every field and DROPS anything invalid
or unknown — stick to this exact schema:

```rpg
{"v": 1,
 "check": {"stat": "strength", "dc": 14, "skill": "blade"},
 "deltas": {"hp_delta": -3, "mana_delta": 0, "xp_delta": 10,
            "inventory_add": ["torch"], "inventory_remove": [],
            "status_add": ["bleeding"], "status_remove": [],
            "trust": {"mara": 1},
            "enemies": {"goblin": {"hp_max": 8, "hp_delta": -5}},
            "time_advance": {"days": 0, "phase": "evening", "weather": "rain"},
            "flag_set": {"bridge_destroyed": true},
            "location": "blackwood-tavern"}}
```

## World deltas (work even when nothing else mechanical happens)
- `time_advance` — move the in-world clock when the fiction does: set `phase`
  (morning/evening/night...) and `weather` freely; `days` is capped at 1 per turn
  unless you also set top-level `"scene_break": true` for an explicit time skip.
  The clock never runs backward.
- `flag_set` — durable true/false (or number/text) world facts a rule may depend on
  ("bridge_destroyed": true). Once set, a flag keeps its type forever.
- `location` — where the player now is (a short name; it becomes a slug).
- `reveal` — a list of hidden lore slugs the story just brought to light
  (`"reveal": ["thornes-secret"]`). Only when the player genuinely discovers it in
  the fiction; the engine makes the entry public and logs a canon event. The
  validator rejects slugs that don't exist or aren't hidden.
- The `check.stat` must be one of the configured attributes — an invented stat
  name is rejected.
- `gold_delta` — coin gained/spent. Spending more than the player holds is
  rejected; propose a smaller purchase or none.
- `quest_update` — `{"thread-slug": "active|completed|failed"}`. Quests are
  threads; the ONLY legal path is inactive → active → completed|failed. The
  engine logs completions as canon events.
- `beat_advance: true` — move to the next story beat (only when the current
  beat's goal has genuinely landed; requires a `## Beats` list in memory/arc.md).
- `npc_state` — a companion's `mood`/`disposition` strings when they shift.
- `event_fired` — a list of event-rule slugs from your SCENARIO EVENT RULES that
  fired THIS turn (`"event_fired": ["chest-trap"]`). Required for `once: true`
  rules so they never fire twice; the validator rejects unknown or already
  consumed slugs.

## Inventory, equipment, rarity
- `inventory_add`/`inventory_remove` take names or `{"slug": "iron-sword",
  "qty": 1}`; quantities are tracked. `inventory_equip`/`inventory_unequip`
  only work on items actually held (the validator checks).
- An item entry on items.md may carry `rarity: common|uncommon|rare|epic|
  legendary` — respect it: legendary things are once-a-story finds, not loot.

## Level-ups and grants
Each level-up banks ONE grant. When the sheet says "LEVEL-UP PENDING", propose
exactly one `ability_add: ["name (stat)"]` (a learnable technique tied to how
the character has been played) or `title_add: ["name"]` (an earned epithet).
Abilities count as trained skills for checks. Grants are rejected when nothing
is pending — never hand them out otherwise.

## Rules
- Attributes: **Strength, Agility, Intelligence, Knowledge, Willpower, Charisma**.
  Pick the one that governs the action. **The world bible has the final say** on what
  governs what — follow it when it speaks. When it is silent, use these defaults:
    - Strength — melee force, lifting, breaking, grappling, brute endurance
    - Agility — stealth, dodging, acrobatics, aim, sleight of hand, reflexes
    - Intelligence — spell accuracy, quick reasoning, deduction, deception
    - Knowledge — spell strength/potency, lore, alchemy, identifying the unknown
    - Willpower — resisting magic or fear, concentration, sustaining a spell
    - Charisma — persuasion, intimidation, bartering, leadership
- Set a DC from 5 (trivial) to 20 (near-impossible), ~12 average.
- Optional `"skill"`: name a trained skill the actor has (see their `skills:` line).
  If they're trained in it, the engine adds a flat proficiency bonus on top of the
  stat. Omit it for untrained actions.
- Optional `"actor"`: an NPC's slug when the check is THEIRS, not the player's
  (e.g. `{"stat": "agility", "dc": 12, "actor": "kaelen"}`) — the engine then uses
  that character's `stats:`/`skills:` lines from characters.md. Omit for the player.
- Character attribute baselines live on each entry's `stats:` line
  (`stats: strength 3, agility 2`) — Markdown is the source of truth for them.
- Every key is optional — include only what applies. No sidecar is fine.
- Deltas are for consequences that are **certain this turn** (drank a potion → mana,
  picked up a torch → inventory). For consequences that depend on a check, wait for
  the next turn once you see whether it succeeded.
- Do NOT state die results or exact numbers as fact in your prose — the engine owns
  them and clamps them. Describe fiction, not arithmetic.
"""

def split_rpg_rules(text: str) -> tuple[str, str]:
    """D-260 post-mesure (a) (Issue #162, suite de l'arbitrage #144) : découpe
    le texte RUNTIME de `rpg-rules.md` (celui lu depuis le disque — l'utilisateur
    peut l'avoir édité, jamais ce module `RPG_RULES` directement) en :

    - le SOCLE, toujours servi : schéma d'enveloppe, deltas, attributs, barème
      DC — la grammaire dont n'importe quel tour peut avoir besoin ;
    - la section « Level-ups and grants », servie seulement sur déclencheur
      d'état vérifiable par le moteur (`rpg.pending_grant > 0` — la même info
      que "LEVEL-UP PENDING" dans `modules/rpg.py::context_block`).

    Garde-fou explicite de l'arbitrage (#144/#162) : aucune AUTRE section n'a
    de déclencheur identifiable, donc aucune autre section n'est retirée — au
    doute, elle reste au socle. Si le fichier édité par l'utilisateur ne porte
    plus l'en-tête `## Level-ups and grants`, la fonction retombe sur "texte
    entier au socle" (comportement d'avant ce découpage) plutôt que de
    perdre silencieusement la règle : retourne `(text, "")`.
    """
    marker = "## Level-ups and grants"
    i = text.find(marker)
    if i < 0:
        return text, ""
    j = text.find("\n## ", i + len(marker))
    end = j + 1 if j >= 0 else len(text)
    section = text[i:end].rstrip("\n")
    socle = text[:i] + text[end:]
    socle = re.sub(r"\n{3,}", "\n\n", socle).rstrip("\n") + "\n"
    return socle, section


PREMISE_HEADER = "# Premise\n\n"

FILE_SKELETONS = {
    "world-bible.md": (
        "# World bible\n\n"
        "Setting rules, history, geography, factions overview, magic/technology, "
        "and the world's overall tone. Referenced (relevance-gated) during play.\n"
    ),
    "player.md": (
        "# Player character\n\n"
        "The protagonist (you). Always in context. Keep identity stable; update "
        "status/inventory/goals as the story moves.\n\n"
        "The `skills:` line is a structured, comma-separated list of `name (stat)` "
        "the RPG module reads for trained-skill bonuses; the **Skills** paragraph is "
        "the prose version. Both are optional.\n\n"
        "The `stats:` line holds your attribute baselines (`strength 2, agility 1, "
        "...`) — Markdown is authoritative: edit it and the sheet follows on next "
        "load. HP/mana/XP stay in state.json (mutable play state).\n\n"
        "## You  {#player}\n"
        "aliases:\n"
        "importance: 5\n"
        "status:\n"
        "skills:\n"
        "stats:\n\n"
        "**Visual:** \n"
        "**Mentality:** \n"
        "**Voice:** \n"
        "**Skills:** \n\n"
        "Identity: \nGoals: \nInventory: \n"
    ),
    "characters.md": (
        "# Characters\n\n"
        "One section per NPC. `aliases` become recall triggers. Optional "
        "`relationships:`, `skills:`, and `when:` lines. Describe each NPC with "
        "**Visual** (appearance), **Mentality** (how they act), **Voice** (how they "
        "talk — include a short sample line), and **Skills**.\n\n"
        "<!-- Example — copy this shape:\n"
        "## Kaelen  {#kaelen}\n"
        "aliases: Ser Kaelen, the knight\n"
        "importance: 4\n"
        "status: alive - wary of you\n"
        "skills: blade (strength), oath-sense (willpower)\n"
        "stats: strength 3, agility 2, willpower 3\n"
        "relationships: you: owes a debt; ash-guard: sworn member\n"
        "weight: important\n"
        "triggers: knight, pauldron\n"
        "links: ash-guard\n\n"
        "**Visual:** Grey-templed, chipped pauldron, a burn scar down one forearm.\n"
        "**Mentality:** Duty over feeling; tests newcomers before trusting them.\n"
        "**Voice:** Clipped, formal, no contractions. e.g. \"You will explain "
        "yourself, witch.\"\n"
        "**Skills:** Veteran swordsman; can sense a broken oath.\n\n"
        "Grim knight bound by a blood-oath. Owes you a debt from "
        "[[event:kings-death]].\n-->\n"
    ),
    "locations.md": (
        "# Locations\n\n"
        "One section per place. `aliases` become recall triggers.\n\n"
        "<!-- Example:\n"
        "## Ashford  {#ashford}\n"
        "aliases: the town, the frontier town\n"
        "importance: 3\n\n"
        "A rain-soaked frontier town on the edge of the haunted forest.\n-->\n"
    ),
    "factions.md": (
        "# Factions\n\n"
        "Groups, orders, kingdoms, cults. One section each.\n\n"
        "<!-- Example:\n"
        "## The Ash Guard  {#ash-guard}\n"
        "aliases: the Guard\n"
        "importance: 3\n\n"
        "A militia sworn to burn what the forest corrupts.\n-->\n"
    ),
    "items.md": (
        "# Items\n\n"
        "Plot-relevant objects/artifacts. One section each. Details live here; "
        "other files reference by name/slug.\n\n"
        "<!-- Example:\n"
        "## The Debt-Contract  {#debt-contract}\n"
        "aliases: the contract, the ledger\n"
        "importance: 4\n\n"
        "A blood-sealed page binding you to your patron.\n-->\n"
    ),
    "canon-events.md": (
        "# Canon events\n\n"
        "Story-critical events, in full. Other files reference these by name/slug "
        "only (see memory-rules.md). One section each.\n\n"
        "<!-- Example:\n"
        "## The King's Death  {#kings-death}\n"
        "turn: 47\n"
        "importance: 5\n\n"
        "The King was murdered in the cathedral; you witnessed the killer's ring.\n"
        "-->\n"
    ),
    "threads.md": (
        "# Open threads\n\n"
        "Unresolved hooks, obligations, mysteries, promises. Full details live "
        "here; reference by name/slug elsewhere. Mark resolved rather than "
        "deleting.\n\n"
        "<!-- Example:\n"
        "## The Ledger Debt  {#the-ledger-debt}\n"
        "status: open\n"
        "importance: 4\n\n"
        "You promised [[char:mara]] to return the stolen ledger by the new moon.\n"
        "-->\n"
    ),
    "memory/scenes.md": (
        "# Scene summaries (medium-term)\n\n"
        "Filled by the summarizer as scenes close. Reference entities by "
        "name/slug only.\n"
    ),
    "memory/arc.md": (
        "# Arc synopsis (long-term)\n\n"
        "A terse running synopsis of the whole story. Reference entities by "
        "name/slug only.\n"
    ),
    "memory/timeline.md": (
        "# Timeline (turn index)\n\n"
        "One shorthand line per folded turn-block, each tagged with its source turn "
        "range (e.g. T6-10), so the exact turns can be recalled on demand. Filled "
        "by the summarizer as turns age out of the verbatim window.\n"
    ),
    "memory/facts.md": (
        "# Established facts (semantic memory)\n\n"
        "Timeless world truths as short bullets — NOT events (those belong in "
        "canon-events.md). Maintained by the summarizer; always in context.\n"
    ),
    "memory/companion-chat.md": (
        "# Companion side-chat (private)\n\n"
        "Out-of-band conversations with companions — never part of the "
        "transcript; the story only sees a short recent digest.\n"
    ),
    "events.md": (
        "# Scenario event rules\n\n"
        "\"When X, then Y\" rules the Logic Agent enforces (the Writer never "
        "sees them — unfired events can't leak). One entry per rule; add "
        "`once: true` for a rule that fires a single time (the engine marks it "
        "`consumed: true` via the event_fired delta).\n\n"
        "<!-- Example:\n"
        "## When the chest is opened  {#chest-trap}\n"
        "once: true\n\n"
        "A poisoned needle trap fires (agility check, DC 14; 1d4 hp on fail). "
        "The map inside is genuine.\n"
        "-->\n"
    ),
    "custom-instructions.md": (
        "# Custom instructions (this save)\n\n"
        "Anything written below the line is appended to the narrator's style "
        "directives every turn. Keep it short and directive.\n\n---\n"
    ),
    "transcript.md": (
        "# Transcript\n\n"
        "Raw turns, verbatim. Short-term memory is the tail of this file.\n"
    ),
}


# --- three-layer file classification (see memory.py for the resolver) ---
# Governing rules: global masters in instructions/, resolved save -> scenario -> global.
RULE_FILES = ["writer-rules.md", "memory-rules.md", "rpg-rules.md"]
_RULE_CONTENT = {
    "writer-rules.md": WRITER_RULES,
    "memory-rules.md": MEMORY_RULES,
    "rpg-rules.md": RPG_RULES,
}
# Authored world content: lives in a scenario, COPIED into a save at creation.
SCENARIO_FILES = [
    "premise.md", "world-bible.md", "player.md", "characters.md", "locations.md",
    "factions.md", "items.md", "canon-events.md", "threads.md", "events.md",
]
# Play state: created fresh per save (never authored).
PLAY_FILES = ["transcript.md", "memory/scenes.md", "memory/arc.md",
              "memory/timeline.md", "memory/facts.md",
              "memory/companion-chat.md", "custom-instructions.md"]

DEFAULT_PREMISE = (
    "A rain-soaked frontier town on the edge of a haunted forest. Grim, grounded "
    "low fantasy. You are a wandering hedge-witch with a debt to a dangerous patron."
)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "story"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def initial_state(rpg_cfg: dict | None = None) -> dict:
    """The v2 state.json shape. Pass config.rpg so custom stats/base pools
    reach a new save's baseline (None = shipped defaults)."""
    return {"time": {"day": 1, "phase": "morning", "weather": "", "note": ""},
            "player": {"location": "", "gold": 0},
            "quests": {},
            "flags": {},
            "rpg": sidecar.default_block(rpg_cfg)}


# --- rule-master versioning / migration -------------------------------------
# Bump whenever any master's default text changes, and append the OUTGOING hash of
# each changed file to `_SHIPPED_RULE_HASHES` below. The version is informational
# (stored in the ledger for diagnostics); correctness is driven by the hashes.
RULES_VERSION = 7

# Every default rule text we have ever SHIPPED, per file (current defaults are added
# automatically). On an app update, an on-disk master whose content hashes to one of
# these is an *unmodified* prior default and is safe to replace with the new default;
# anything else is treated as a user edit and preserved. When you change a master,
# add its previous hash here so installs still on that version auto-update cleanly.
_SHIPPED_RULE_HASHES: dict[str, set[str]] = {
    "writer-rules.md": set(),
    # v1 superseded in v2 (character facets + skill-check `skill` field);
    # v2 superseded in v3 (stats: baselines in Markdown + NPC `actor` checks).
    # memory-rules: v5 added lorebook attrs + facts + episode metadata; v6 added
    # quests/companions guidance.
    "memory-rules.md": {
        "545e368ef7dd6a649e582528cb99390c480e8dd23c7b3a21211c4db618282c95",
        "920ea7d51cf1935daff23527dbcdcb8fa1569c7987e1e37771c63dba6e0b7459",
        "e355aa8ec948bced66849cf944ca4fbf25b0fdefeb0822281aa95816d84e9336",
        "9d7da2fafce2b686fb13577070fc4690e949dc1dbbe75969355f3f671aefb819"},
    # rpg-rules: v4 = envelope v1 (world deltas + validator); v5 = reveal +
    # stat-list validation; v6 = gold/inventory-mirror/quests/grants/beats.
    "rpg-rules.md": {
        "f1c8e462c1412a574ffa96aca5d0da3608a96d1ae582e5a2b4bef61f17e0a3ce",
        "d350015f10de875eea3d45f1d01874d2ca1d0254f81013e65628a41f40b490d4",
        "7f858989341aa1ec9897412972ab6df36cb0f4c408bf5e68e6159797fd8c17ba",
        "81dffbaea60dfae1f90813cf21196f8d01ee90f643a8bab231a13ac70c68c8c8",
        "1334897bdfd47911ad1139c8d1a31adc04ed6e9ae04a0d727003e8a5a3db218a",
        # v6 superseded in v7 (event_fired delta).
        "43c6b6c54a52eabdc0fcdf08909914bc3e316d9d9a186927d3fdd49c8464d100"},
}

# Ledger recording, per install, the hash of the default we last wrote to each
# master — so a later launch can tell "unchanged since we wrote it" (safe to update)
# from "the user edited it" (preserve).
RULES_LEDGER = ".rules-version.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_rule(name: str) -> str:
    """The current shipped default text for a rule file (for reset-to-default)."""
    return _RULE_CONTENT[name]


def _known_default_hashes(name: str) -> set[str]:
    """All hashes that count as an unmodified shipped default for `name` — the
    historical set plus the current default."""
    return _SHIPPED_RULE_HASHES.get(name, set()) | {_sha(_RULE_CONTENT[name])}


def _load_ledger(inst_dir: Path) -> dict:
    p = inst_dir / RULES_LEDGER
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("hashes"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 0, "hashes": {}}


def seed_instructions(inst_dir: Path) -> list[str]:
    """Seed + migrate the global master rule files.

    - Missing masters are written from the current defaults.
    - An existing master that is still an *unmodified* shipped default (matches the
      ledger's record of what we last wrote, or any known historical default hash)
      is upgraded in place when the shipped default has changed — so app updates
      propagate rule improvements.
    - An existing master the user has edited is left untouched.

    Returns the list of rule files that are user-edited AND now differ from the
    current shipped default (i.e. an update is available but was withheld to protect
    the edit), so a caller can surface a "your rules are outdated" hint.
    """
    inst_dir.mkdir(parents=True, exist_ok=True)
    ledger = _load_ledger(inst_dir)
    hashes: dict[str, str] = dict(ledger.get("hashes", {}))
    outdated: list[str] = []

    for name, content in _RULE_CONTENT.items():
        p = inst_dir / name
        cur_hash = _sha(content)
        if not p.exists():
            p.write_text(content, encoding="utf-8")
            hashes[name] = cur_hash
            continue
        disk = p.read_text(encoding="utf-8")
        disk_hash = _sha(disk)
        if disk_hash == cur_hash:
            hashes[name] = cur_hash          # up to date; self-heal the ledger
            continue
        recorded = ledger.get("hashes", {}).get(name)
        unmodified = disk_hash == recorded or disk_hash in _known_default_hashes(name)
        if unmodified:
            p.write_text(content, encoding="utf-8")   # upgrade unedited master
            hashes[name] = cur_hash
        else:
            outdated.append(name)            # user edit: preserve, don't record

    try:
        (inst_dir / RULES_LEDGER).write_text(
            json.dumps({"version": RULES_VERSION, "hashes": hashes}, indent=2),
            encoding="utf-8")
    except OSError:
        pass  # a read-only instructions dir shouldn't break app startup
    return outdated


# Skeletons a user may override as their own new-file defaults (Library "User
# defaults" section). Overrides live in instructions/defaults/<name> and seed
# every NEW scenario/save; rule masters have their own layered machinery.
USER_DEFAULTABLE = ["premise.md", "world-bible.md", "player.md", "events.md",
                    "custom-instructions.md"]


def user_default(rel: str, instructions_dir=None) -> str:
    """The skeleton used when seeding `rel` on a NEW scenario/save: the user's
    override if present, else the shipped skeleton."""
    if instructions_dir is not None:
        p = Path(instructions_dir) / "defaults" / rel
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                pass
    if rel == "premise.md":
        return PREMISE_HEADER + DEFAULT_PREMISE + "\n"
    return FILE_SKELETONS[rel]


def seed_scenario(scen_dir: Path, title: str, premise: str,
                  world: str = "", description: str = "",
                  introduction: str = "",
                  instructions_dir=None) -> None:
    """Author a reusable world: premise + world bible + starting cast skeletons.
    `introduction` (FictionLab shape) becomes the `## Opening` section — the
    verbatim first chat message of every story started from this scenario.
    Rules are NOT written here — a scenario inherits the global masters unless the
    author drops in an override rule file."""
    scen_dir.mkdir(parents=True, exist_ok=True)
    (scen_dir / "scenario.json").write_text(
        json.dumps({"title": title, "created": time.time(),
                    "description": description}, indent=2), encoding="utf-8")
    for rel in SCENARIO_FILES:
        if rel == "premise.md":
            text = PREMISE_HEADER + premise.strip() + "\n"
            if introduction.strip():
                text += "\n## Opening\n\n" + introduction.strip() + "\n"
            _write(scen_dir / rel, text)
        elif rel == "world-bible.md" and world.strip():
            _write(scen_dir / rel, "# World bible\n\n" + world.strip() + "\n")
        elif rel in USER_DEFAULTABLE:
            _write(scen_dir / rel, user_default(rel, instructions_dir))
        else:
            _write(scen_dir / rel, FILE_SKELETONS[rel])


def _seed_save_aids(save_dir: Path, scen_dir: Path | None, state: dict) -> None:
    """Copy a scenario's recommended play aids (aids.json) into a new save's state
    and custom-instructions. Scenarios have no state.json of their own, so this is
    how an authored world ships quick actions / an author's-note / output-regex
    with it. Shape-cleaned only; the engine re-validates regex at exec time."""
    if scen_dir is None:
        return
    try:
        aids = json.loads((scen_dir / "aids.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(aids, dict):
        return
    qa = aids.get("quick_actions")
    if isinstance(qa, list):
        state["quick_actions"] = [str(s).strip() for s in qa
                                  if isinstance(s, str) and s.strip()][:20]
    rr = aids.get("regex_rules")
    if isinstance(rr, list):
        rules = []
        for r in rr:
            if not isinstance(r, dict) or not isinstance(r.get("find"), str):
                continue
            rules.append({"find": r["find"],
                          "replace": str(r.get("replace", ""))[:1000],
                          "flags": "".join(c for c in str(r.get("flags", "")).lower()
                                           if c in "ims")})
            if len(rules) >= 30:
                break
        state["regex_rules"] = rules
    an = aids.get("authors_note")
    if isinstance(an, dict):
        depth = an.get("depth") if an.get("depth") in ("system", "tail") else "system"
        try:
            every = max(1, int(an.get("every", 1)))
        except (TypeError, ValueError):
            every = 1
        state["authors_note"] = {"depth": depth, "every": every}
        note = str(an.get("content", "") or "").strip()
        if note:
            _write(save_dir / "custom-instructions.md",
                   "# Custom instructions (this save)\n\n---\n" + note + "\n")


def new_save(save_dir: Path, scen_dir: Path | None, title: str,
             scenario_slug: str = "", rpg_enabled: bool = False,
             premise: str = "", mode: str = "",
             rpg_cfg: dict | None = None, instructions_dir=None,
             start_time: dict | None = None) -> None:
    """Instantiate a playthrough: copy the scenario's authored world into the save
    (or, with no scenario, seed from an inline `premise`), then create fresh
    play-state files. Rules stay global (inherited). `mode` (Wave 3) is
    'simple' (tap-and-play; Logic Agent skipped) or 'rpg'; defaults from the
    RPG toggle."""
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "memory").mkdir(exist_ok=True)
    for rel in SCENARIO_FILES:
        src = (scen_dir / rel) if scen_dir else None
        if src and src.exists():
            _write(save_dir / rel, src.read_text(encoding="utf-8"))
        elif rel == "premise.md":
            if premise.strip():
                _write(save_dir / rel, PREMISE_HEADER + premise.strip() + "\n")
            else:
                _write(save_dir / rel,
                       user_default("premise.md", instructions_dir))
        elif rel in USER_DEFAULTABLE:
            _write(save_dir / rel, user_default(rel, instructions_dir))
        else:
            _write(save_dir / rel, FILE_SKELETONS[rel])
    for rel in PLAY_FILES:
        if rel in USER_DEFAULTABLE:
            _write(save_dir / rel, user_default(rel, instructions_dir))
        else:
            _write(save_dir / rel, FILE_SKELETONS[rel])
    state = initial_state(rpg_cfg)
    state["rpg"]["enabled"] = bool(rpg_enabled)
    # Optional non-default start: the story may open on any day/phase, with a
    # free-text fictional calendar note. `time_advance` only moves forward from
    # here, so this simply seeds the baseline clock.
    if isinstance(start_time, dict):
        t = state["time"]
        if str(start_time.get("day", "")).strip():
            try:
                t["day"] = max(1, int(start_time["day"]))
            except (TypeError, ValueError):
                pass
        for key in ("phase", "weather", "note"):
            val = start_time.get(key)
            if isinstance(val, str) and val.strip():
                t[key] = val.strip()
    _seed_save_aids(save_dir, scen_dir, state)   # scenario's recommended play aids
    _write(save_dir / "state.json", json.dumps(state, indent=2))
    if mode not in ("simple", "rpg"):
        mode = "rpg" if rpg_enabled else "simple"
    (save_dir / "meta.json").write_text(
        json.dumps({"title": title, "created": time.time(), "updated": time.time(),
                    "scenario": scenario_slug, "mode": mode}, indent=2),
        encoding="utf-8")
