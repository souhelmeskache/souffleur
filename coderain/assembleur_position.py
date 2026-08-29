"""D-260 lane (a) — assembleur de contexte KEYÉ SUR LA POSITION (Issue #125).

Sert un Director depuis une Partition PROJETÉE (`state.location`, posé par
`coderain/converter/projection.py` §6) au lieu de la sélection par mots-clés
+ budget de `MemoryStore.assemble()`. Fonction NOUVELLE, pas une réécriture :
les saves SANS partition/position gardent `assemble()` inchangé — voir
`eligible()`, la frontière de cohabitation entre les deux chemins.

Paquet servi, DANS CET ORDRE (figé, voir docstring d'`assemble()`) :

  1. STABLE   — DIRECTOR_SYS (rôle, existant dans `modules/trinity.py`)
  2. STABLE   — brief de direction (`directeur.md`, D-177, déjà projeté entre
                les marqueurs P4-BRIEF-START/END de `custom-instructions.md`)
  3. STABLE   — le node courant : corps + objectif_md + ses débouchés/liens
                comme POTENTIELS (garde D-179 : jamais un menu ni un
                déclencheur automatique)
  4. STABLE   — records ancrés à ce node (`tokens_initial`) + secrets dont un
                porteur est présent (routage `hidden` conservé, D-019)
  5. VOLATILE — verdicts de règles DE CE TOUR (`triggers_all` évalué par code
                contre l'état courant) — jamais `event_rules_block()` entier
  6. VOLATILE — fiche perso, état monde compact, file de scène récente

Le hors-position ne se charge pas d'avance : le Director le demande via
`recall_queries` de son enveloppe (soupape déjà existante).

Stabilité de préfixe (exigence cache) : les sections 1-4 sont byte-stables
entre deux tours SANS transition de node — aucun timestamp, compteur, id de
requête, tri non déterministe. `stable_prefix()` isole ce sous-ensemble pour
le test de non-régression du cache.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .memory import Entry, MemoryStore, _context_render, trigger_hit
from .converter.aval import _split_front
from .modules.trinity import DIRECTOR_SYS, _ENV_RPG, _ENV_WORLD

_BRIEF_START = "<!-- P4-BRIEF-START -->"
_BRIEF_END = "<!-- P4-BRIEF-END -->"


@dataclass
class Section:
    marker: str      # "stable" | "volatile"
    title: str
    text: str

    def render(self) -> str:
        body = self.text.strip()
        return f"## {self.title}\n{body}" if body else ""


def eligible(store: MemoryStore, state: dict) -> bool:
    """D-260 : la frontière de cohabitation — ce chemin ne remplace
    `assemble()` que si la save porte À LA FOIS une position ET une
    partition projetée (au moins un node dans locations.md). Toute autre
    save retombe sur `assemble()`, inchangé (zéro régression)."""
    return bool(state.get("location")) and bool(store.entries("locations.md"))


def _read_json_front(path: Path) -> dict:
    if not path.exists():
        return {}
    front, _body = _split_front(path.read_text(encoding="utf-8"))
    try:
        return json.loads(front) if front else {}
    except json.JSONDecodeError:
        return {}


def _brief(store: MemoryStore) -> str:
    """Le brief de direction déjà projeté (D-177) entre ses marqueurs — lu
    depuis custom-instructions.md, jamais régénéré ici."""
    text = store.read("custom-instructions.md")
    i, j = text.find(_BRIEF_START), text.find(_BRIEF_END)
    if i < 0 or j <= i:
        return ""
    return text[i + len(_BRIEF_START):j].strip()


def _potentials_text(meta: dict) -> str:
    """D-179 : les débouchés/liens sont un DÉCOR de possibles perçus depuis
    la scène — jamais un menu, jamais un auto-déclencheur. Formulation au
    conditionnel, id technique gardé hors du texte narratif adressé au
    Director (il ne cite jamais l'id — voir DIRECTOR_SYS)."""
    lines = []
    for l in meta.get("liens", []) or []:
        cond = str(l.get("condition_textuelle", "")).strip()
        cible = str(l.get("cible_id", "")).strip()
        if not cible:
            continue
        lines.append(f"- pourrait mener vers « {cible} »"
                     + (f" ({cond})" if cond else ""))
    for d in meta.get("debouches", []) or []:
        cond = str(d.get("condition_textuelle", "")).strip()
        dest = str(d.get("cible_id") or d.get("ouvre_vers_md") or "").strip()
        if not dest:
            continue
        lines.append(f"- un débouché possible vers « {dest} »"
                     + (f" ({cond})" if cond else ""))
    return "\n".join(lines)


def _current_node_section(partition_dir: Path, store: MemoryStore,
                          location: str) -> Section:
    entry = next((e for e in store.entries("locations.md")
                 if e.slug == location), None)
    meta = _read_json_front(Path(partition_dir) / "nodes" / f"{location}.md")
    parts = []
    if entry is not None and entry.body.strip():
        parts.append(entry.body.strip())
    objectif = str(meta.get("objectif_md", "")).strip()
    if objectif:
        parts.append("Objectif de la scène (une trajectoire visée, jamais "
                     "une séquence à annoncer) :\n" + objectif)
    potentials = _potentials_text(meta)
    if potentials:
        parts.append("Possibles perçus depuis ici (décor — PAS un menu ni "
                     "un déclencheur automatique) :\n" + potentials)
    title = entry.title if entry is not None else location
    return Section("stable", f"Scène courante — {title}",
                   "\n\n".join(parts))


def _anchored_record_ids(partition_dir: Path, location: str) -> list[str]:
    """Ids de records dont une pose `tokens_initial` atterrit sur ce node."""
    out = []
    recs_dir = Path(partition_dir) / "records"
    if not recs_dir.exists():
        return out
    for f in sorted(recs_dir.glob("*.md")):
        meta = _read_json_front(f)
        poses = meta.get("tokens_initial") or []
        if any(str(p.get("node_id")) == location for p in poses):
            out.append(str(meta.get("id", f.stem)))
    return out


def _presence_section(partition_dir: Path, store: MemoryStore,
                      location: str) -> Section:
    anchored = _anchored_record_ids(partition_dir, location)
    by_slug = {e.slug: e for e in store.entries("characters.md")}
    parts = [_context_render(by_slug[rid]) for rid in anchored
             if rid in by_slug]

    secret_lines = []
    secrets_dir = Path(partition_dir) / "secrets"
    if secrets_dir.exists():
        anchored_set = set(anchored)
        for f in sorted(secrets_dir.glob("*.md")):
            meta = _read_json_front(f)
            porteurs = {str(p) for p in (meta.get("porteurs") or [])}
            if not (anchored_set & porteurs):
                continue
            sid = str(meta.get("id", f.stem))
            e = by_slug.get(sid)
            if e is not None:
                # Entry.render() (not _context_render): même framing que
                # le Secrets de assemble() — un porteur présent laisse
                # entrevoir ce qu'il SAIT, jamais énoncé (D-019).
                secret_lines.append(e.render())
    body = "\n\n".join(parts)
    if secret_lines:
        body += ("\n\n### Secrets connus (NON révélés au joueur — à "
                "foreshadow, jamais énoncés) :\n\n"
                + "\n\n".join(secret_lines))
    return Section("stable", "Présences (records ancrés + secrets portés)",
                   body.strip())


def _rule_verdicts_section(store: MemoryStore, history: list[dict],
                           player_input: str) -> Section:
    """VOLATILE : les conditions/trajectoire projetées (locations.md,
    weight=heavy — les nodes, eux, sont weight=light, la distinction posée
    par projection.py ; l'attr RAW, pas `Entry.weight()`, qui normalise tout
    ce qui n'est pas un des cinq paliers du lorebook vers "standard") sont
    évaluées PAR CODE contre le haystack du tour. Seules les règles dont
    triggers_all matche intégralement passent — jamais `event_rules_block()`
    entier (D-260 §5)."""
    haystack = (" ".join(t.get("text", "") for t in history)
               + " " + player_input).lower()
    fired = []
    for e in store.entries("locations.md"):
        if e.attrs.get("weight", "").strip().lower() != "heavy":
            continue
        reqs = e.triggers_all()
        if reqs and all(trigger_hit(tok, haystack) for tok in reqs):
            fired.append(e)
    text = ("\n\n".join(_context_render(e) for e in fired) if fired
           else "(aucune règle déclenchée ce tour)")
    return Section("volatile",
                   "Verdicts de règles CE TOUR (jamais l'ensemble des "
                   "règles du scénario)", text)


def _world_and_queue_section(store: MemoryStore, scenes_tail: int) -> Section:
    lines = []
    clock = store.clock_str()
    if clock:
        lines.append(f"Horloge : {clock}")
    flags = store.world_state().get("flags") or {}
    if flags:
        lines.append("Drapeaux : "
                     + ", ".join(f"{k}={v}" for k, v in flags.items()))
    scenes = store.entries("memory/scenes.md")
    if scenes:
        lines.append("\nDernières scènes :\n" + "\n\n".join(
            e.render().strip() for e in scenes[-scenes_tail:]))
    return Section("volatile", "État du monde (compact) + file de scène",
                   "\n".join(lines))


def build_sections(partition_dir: str | Path, store: MemoryStore,
                   location: str, history: list[dict], player_input: str,
                   scenes_tail: int = 4, char_sheet: str = "",
                   rpg_on: bool = False) -> list[Section]:
    """Construit le paquet ordonné (voir docstring de module). `char_sheet`
    est fourni par l'appelant (`rpg_mod.context_block`, hors périmètre de ce
    module) — chaîne vide = section omise."""
    partition_dir = Path(partition_dir)
    sections = [Section("stable", "Rôle (Director)",
                        DIRECTOR_SYS % (_ENV_RPG if rpg_on else _ENV_WORLD))]
    brief = _brief(store)
    if brief:
        sections.append(Section("stable",
                                "Brief de direction (directeur.md)", brief))
    sections.append(_current_node_section(partition_dir, store, location))
    sections.append(_presence_section(partition_dir, store, location))
    sections.append(_rule_verdicts_section(store, history, player_input))
    sections.append(_world_and_queue_section(store, scenes_tail))
    if char_sheet.strip():
        sections.append(Section("volatile", "Fiche de personnage",
                                char_sheet.strip()))
    return sections


def stable_prefix(sections: list[Section]) -> str:
    """Le sous-ensemble byte-stable du paquet (sections 1-4) — inchangé
    entre deux tours tant que la position ne bouge pas. Le test de
    non-régression du cache compare ce texte, pas le paquet entier."""
    return "\n\n".join(s.render() for s in sections if s.marker == "stable")


def to_messages(sections: list[Section], history: list[dict],
                player_input: str) -> list[dict]:
    """Rend le paquet dans la même forme que `MemoryStore.assemble()` — une
    liste de messages — pour que `modules/trinity.py::_direct` puisse la
    consommer sans changer son contrat (D-260 §Branchement)."""
    system = "\n\n".join(s.render() for s in sections if s.render())
    messages = [{"role": "system", "content": system}]
    for t in history:
        messages.append({"role": "user" if t["role"] == "player"
                         else "assistant", "content": t["text"]})
    messages.append({"role": "user", "content": player_input})
    return messages


def assemble(partition_dir: str | Path, store: MemoryStore, state: dict,
            history: list[dict], player_input: str,
            scenes_tail: int = 4, char_sheet: str = "",
            rpg_on: bool = False) -> list[dict]:
    """Point d'entrée : assemblage keyé position pour une save AVEC
    partition projetée (voir `eligible()`). Même forme de sortie que
    `MemoryStore.assemble()` — le point d'appel choisit l'un ou l'autre
    selon `eligible()`, sans toucher au contrat du Director."""
    location = str(state.get("location", ""))
    sections = build_sections(partition_dir, store, location, history,
                              player_input, scenes_tail, char_sheet, rpg_on)
    return to_messages(sections, history, player_input)
