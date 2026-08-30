"""Deterministic local handling for rigid module structures.

Two routes live here, both zero-hallucination: code segments, node bodies are
VERBATIM copies of their source spans (fidèle au contenu, libre sur l'ordre).
The LLM pipeline stays the general path; these are the special cases that
don't need it.

- segment_s1 / node_for_unit: numbered-paragraph modules (#N markers +
  "go to N." renvois), measured on the specimen.
- scan_gamebook / build_gamebook_partition: gamebooks à ENTRÉES NOMMÉES
  (CAPS heads + "go to entry X" renvois + spatial pointer pages), measured
  on the first real pass (D-216: GENERIC shapes, parameterized by
  GamebookFormat — never a per-module hack).
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from .schemas import Node, RollTable, Unit

MARKER = re.compile(r"^#(\d{1,3})[ \t]*$", re.M)
RENVIS = re.compile(r"^\s*(.*?)[ \t]*,?[Gg]o to (\d{1,3})\.[ \t]*$", re.M)

# D-102/I-111 (Issue #182, EXTRACTION) : caractérisation du ton pour le
# matériau tiers sans directive `rendu_md` explicite (véhicule commun,
# voir cli.py § scenario-auteur.json + Node.attach_scenario). Chaque
# registre est repéré par un lexique FERMÉ, insensible à la casse ; on
# CARACTÉRISE ce qui est là, on n'invente jamais un ton absent — aucun
# lexique repéré ⇒ rendu_md vide + avertissement signalé (même contrat que
# objectif_md absent, cf. tests/converter_test.py:317). Les consignes
# associées évitent volontairement tout marqueur de
# RENDU_MD_INTERDITS_SEQUENCE (garde anti-rail D-065, schemas.py).
REGISTRES_RENDU = (
    ("tension", ("combat", "attaque", "arme", "sang", "menace", "danger",
                 "grogne", "hurle", "griffe", "crie"),
     "registre tendu ; fais peser la menace, laisse deviner le danger"),
    ("mystere", ("mystérieux", "mysterieux", "étrange", "etrange", "ombre",
                 "silence", "murmure", "secret", "inconnu", "sombre"),
     "registre mystérieux ; entretiens le doute, ne révèle rien de trop"),
    ("chaleureux", ("accueil", "chaleureux", "sourire", "rire", "paisible",
                    "calme", "repos", "confortable"),
     "registre chaleureux ; installe le confort avant de le troubler"),
    ("urgence", ("urgent", "vite", "précipite", "precipite", "panique",
                 "fuit", "pressé", "presse", "alarme"),
     "registre urgent ; presse le rythme, laisse peu de répit"),
)


def characterise_rendu(corps_md: str, owner: str) -> tuple[str, str | None]:
    """Caractérise le ton/rythme depuis la prose source (D-102/I-111,
    Issue #182) — jamais un ton improvisé. Compte les occurrences de chaque
    lexique de REGISTRES_RENDU (insensible à la casse) ; le registre au
    compte le plus haut (> 0) l'emporte, ex-aequo tranché par l'ordre de la
    table. Aucun lexique repéré ⇒ ("", avertissement) : rubrique vide,
    signalée, jamais un ton improvisé."""
    bas = (corps_md or "").lower()
    best_nom, best_count, best_consigne = None, 0, ""
    for nom, mots, consigne in REGISTRES_RENDU:
        count = sum(bas.count(m) for m in mots)
        if count > best_count:
            best_nom, best_count, best_consigne = nom, count, consigne
    if best_nom is None:
        return "", (f"{owner}: rendu_md — ton non identifiable, aucun "
                    "lexique reconnu dans la source (vide + exception, "
                    "D-102/I-111)")
    return best_consigne, None


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


def node_for_unit(unit: Unit, text: str, id_by_num: dict[int, str],
                  rendu_md: str | None = None) -> tuple[Node, str | None]:
    """Verbatim-copy node: corps_md IS the source span (minus edge blanks);
    renvois become typed links when their target paragraph exists.

    rendu_md (Issue #182) : directive explicite fournie par l'appelant (le
    véhicule commun — voir cli.py § scenario-auteur.json) ; absente
    (`None`, matériau tiers sans directive) ⇒ caractérisée depuis corps_md
    (`characterise_rendu`). Retourne (Node, avertissement | None) — le
    second élément non-None seulement quand le ton n'a pas pu être
    caractérisé (D-102/I-111)."""
    corps = text[unit.start:unit.end].strip("\n")
    liens = []
    for r in unit.renvois:
        target = id_by_num.get(int(r["cible"]))
        if target:
            liens.append({"cible_id": target,
                          "condition_textuelle": r["condition"] or "(inconditionnel)"})
    warning = None
    if rendu_md is None:
        rendu_md, warning = characterise_rendu(corps, f"node {unit.uid}")
    node = Node(unit.uid, "section", f"{unit.titre}", corps, "scene",
                liens=liens, anchors=[(unit.start, unit.end)],
                rendu_md=rendu_md)
    return node, warning


# ---------------------------------------------------------------------------
# Gamebook route: named entries (CAPS heads) wired by "go to entry X".
#
# Layout physics this route relies on (measured on the first real pass):
#   - an entry HEAD is a caps-line block separated from prose by blank lines;
#     PDF breaks split heads mid-word ("CULTISTCOMBA"/"T") or across tokens
#     ("SEARCH CAVE"), so consecutive SINGLE-TOKEN caps lines MERGE;
#   - a renvoi TARGET can be glued under its verb as bare caps line(s): such
#     glued blocks are target material, never heads — unless another renvoi,
#     located on ANOTHER page, references them (cross-page promotion);
#   - targets get truncated at line ends ("BLES SING", "DUKEITOU T"):
#     recollage joins captured tokens, then falls back to a unique prefix,
#     then to a unique near-name (source typos) — flagged, never silent.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GamebookFormat:
    """Structural knobs of one gamebook family (D-216: generic shapes)."""
    caps_line: str = (r"^(?:[A-Z][A-Z0-9]{0,29})(?:[ \t]+"
                      r"(?:[A-Z][A-Z0-9]{0,29}))*[ \t]*[?!]?[ \t]*$")
    cont_line: str = r"^[A-Z][A-Z0-9]{0,29}[?!]?$"
    pointer: str = r"^(TILEPAGE|SUB-?[ \t]?MAP|SUBMAP)[ \t]+(\d{1,2})[ \t]*$"
    pointer_kinds: tuple = (("TILEPAGE", "tilepage"), ("SUBMAP", "submap"))
    renvoi: str = (r"(?:[Gg]o to|[Rr]eturn to|[Rr]ejoin|[Bb]ack to)\s+"
                   r"(?:entry\s+)?((?:[A-Z][A-Z0-9]{1,29})"
                   r"(?:\s+[A-Z][A-Z0-9]{1,29}){0,3})")
    stat_next: str = r"\d+\s*\(\s*[-+]?\d+\s*\)"
    skip_tokens: frozenset = frozenset(
        {"STR", "DEX", "CON", "INT", "WIS", "CHA", "ATTACKS"})
    min_name: int = 3           # shortest viable entry name (RIP, RUN)
    max_name: int = 45          # longest plausible merged name
    promote_min: int = 5        # glued blocks shorter than this never promote
    prefix_min: int = 4         # min length of a prefix-recovery base
    lev_dist: int = 2           # near-name recollage (source typos), flagged
    lev_min_len: int = 8        # ...only for long-enough captured targets
    cross_page_chars: int = 1500   # distance proxy when page offsets unknown


GAMEBOOK = GamebookFormat()


def assemble_pages(pages_dir, first: int, last: int,
                   encoding: str = "utf-8") -> tuple[str, list[int]]:
    """Join per-page text files (page-NNN.txt) into one conversion source;
    also returns page-start offsets so the scan knows where pages begin."""
    from pathlib import Path
    page_dir = Path(pages_dir)
    parts, starts, pos = [], [], 0
    for n in range(first, last + 1):
        t = (page_dir / f"page-{n:03d}.txt").read_text(encoding=encoding)
        starts.append(pos)
        parts.append(t)
        pos += len(t) + 2                     # "\n\n" separator
    return "\n\n".join(parts), starts


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Whitespace-normalized text + norm-pos -> raw-offset map."""
    out, idx, last_sp = [], [], True
    for i, ch in enumerate(text):
        if ch.isspace():
            if not last_sp:
                out.append(" ")
                idx.append(i)
                last_sp = True
        else:
            out.append(ch)
            idx.append(i)
            last_sp = False
    return "".join(out), idx


def _lev(a: str, b: str, cap: int) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for ia, ca in enumerate(a, 1):
        cur = [ia]
        for ib, cb in enumerate(b, 1):
            cur.append(min(prev[ib] + 1, cur[ib - 1] + 1,
                           prev[ib - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def scan_gamebook(text: str, fmt: GamebookFormat = GAMEBOOK,
                  page_starts: list[int] | None = None) -> dict:
    """Detect entry heads, pointer pages and the renvoi graph. Returns a scan
    record: tiled Units (+ node_of_uid map) + resolutions + measures."""
    caps_re = re.compile(fmt.caps_line)
    cont_re = re.compile(fmt.cont_line)
    ptr_re = re.compile(fmt.pointer, re.IGNORECASE)
    renv_re = re.compile(fmt.renvoi)
    stat_re = re.compile(fmt.stat_next)
    kinds = dict(fmt.pointer_kinds)

    lines = text.splitlines()
    offs, pos = [], 0
    for ln in lines:
        offs.append(pos)
        pos += len(ln) + 1

    def _caps_ok(s: str) -> bool:
        return bool(caps_re.fullmatch(s)) and not (
            set(s.rstrip("?!").split()) & set(fmt.skip_tokens))

    def _page_of(off: int) -> int:
        if page_starts:
            return bisect.bisect_right(page_starts, off) - 1
        return off // fmt.cross_page_chars

    def _merge_ok(prev: list[tuple[int, str]], t: str) -> bool:
        if not prev:
            return True
        merged = "".join(x[1] for x in prev).rstrip("?!") + t.rstrip("?!")
        return bool(cont_re.fullmatch(t)) and len(merged) <= fmt.max_name

    # -- caps-line groups ------------------------------------------------------
    groups: list[dict] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        pm = ptr_re.fullmatch(s) if s else None
        if pm:
            label = re.sub(r"[^A-Z]", "", pm.group(1).upper())
            kind_name = kinds[label]
            groups.append({"kind": "pointer",
                           "lines": [(offs[i], s)],
                           "end": offs[i] + len(s),
                           "uid": f"{kind_name}-{int(pm.group(2))}",
                           "titre": s.upper()})
            i += 1
            continue
        if s and _caps_ok(s):
            glines = [(offs[i], s)]
            j = i + 1
            while j < len(lines):
                t = lines[j].strip()
                if t and not ptr_re.fullmatch(t) and _caps_ok(t) \
                        and _merge_ok(glines, t):
                    glines.append((offs[j], t))
                    j += 1
                else:
                    break
            full = "".join("".join(t.rstrip("?!").split())
                           for _, t in glines)[:fmt.max_name].lower()
            blank_above = (i == 0) or (not lines[i - 1].strip())
            nxt = next((lines[m].strip() for m in range(j, len(lines))
                        if lines[m].strip()), "")
            stat_guard = bool(nxt) and bool(stat_re.fullmatch(nxt))
            if len(full) < fmt.min_name or not full.isalpha() or stat_guard:
                kind = "junk"
            elif not blank_above:
                kind = "suspect"
            else:
                kind = "core"
            groups.append({"kind": kind, "lines": glines,
                           "end": glines[-1][0] + len(glines[-1][1]),
                           "uid": full,
                           "titre": " ".join(t.strip() for _, t in glines)})
            i = j
            continue
        i += 1

    defined = {g["uid"] for g in groups if g["kind"] == "core"}
    suspects = [g for g in groups if g["kind"] == "suspect"]

    # -- renvoi captures -------------------------------------------------------
    norm, idx = _norm_map(text)
    captures: list[dict] = []
    for m in renv_re.finditer(norm):
        cond = norm[max(0, m.start() - 70):m.start()].strip()
        cut = cond.find(" ")
        if 0 <= cut < len(cond) - 1:
            cond = cond[cut + 1:]
        captures.append({"raw": idx[m.start()],
                         "toks": m.group(1).split(),
                         "cond": cond[-120:].strip()})

    def resolve(toks: list[str], dset: set[str], with_lev: bool = False):
        # progressive candidates (longest join -> bare first token): each
        # fallback net applies to every candidate, not just the longest.
        cands = ["".join(toks[:k]).lower() for k in range(len(toks), 0, -1)]
        for cand in cands:
            if cand in dset:
                return cand
        for cand in cands:
            if len(cand) >= fmt.prefix_min:
                pref = sorted(e for e in dset if e.startswith(cand))
                if len(pref) == 1:
                    return pref[0]
        if with_lev:
            for cand in cands:
                if len(cand) >= fmt.lev_min_len:
                    near = [e for e in dset
                            if _lev(cand, e, fmt.lev_dist) <= fmt.lev_dist]
                    if len(near) == 1:
                        return near[0]
        return None

    # -- promotion of glued blocks referenced from another page ----------------
    def _cands(g: dict) -> list[tuple[str, int, str]]:
        leads, singles = [], []
        for k in range(len(g["lines"]), 0, -1):
            nm = "".join("".join(t.rstrip("?!").split())
                         for _, t in g["lines"][:k]).lower()[:fmt.max_name]
            leads.append((nm, g["lines"][0][0],
                          " ".join(t.strip() for _, t in g["lines"][:k])))
        for o, t in g["lines"]:
            singles.append(("".join(t.rstrip("?!").split()).lower(), o,
                            t.strip()))
        allc = leads + singles
        out, seen = [], set()
        for nm, o, titre in sorted(allc, key=lambda x: -len(x[0])):
            if len(nm) < fmt.promote_min or not nm.isalpha():
                continue
            if any(o2 != nm and len(o2) > len(nm) and o2.startswith(nm)
                   for o2, _, _ in allc):
                continue                      # not maximal within its group
            if nm not in seen:
                seen.add(nm)
                out.append((nm, o, titre))
        return out

    promoted: list[str] = []
    for _round in range(3):
        changed = False
        for g in suspects:
            for nm, loff, titre in _cands(g):
                if nm in defined:
                    continue
                if any(d.startswith(nm) and d != nm for d in defined):
                    continue                  # fragment of a known entry
                hit = False
                for c in captures:
                    for k in range(len(c["toks"]), 0, -1):
                        cand = "".join(c["toks"][:k]).lower()
                        if cand == nm or (len(cand) >= fmt.prefix_min
                                          and cand.startswith(nm)):
                            if _page_of(c["raw"]) != _page_of(loff):
                                hit = True
                        if hit:
                            break
                    if hit:
                        break
                if hit:
                    defined.add(nm)
                    g["promote"] = (nm, loff, titre)
                    promoted.append(nm)
                    changed = True
                    break
        if not changed:
            break

    # -- resolution ------------------------------------------------------------
    resolved, unresolved, flagged = [], [], []
    for c in captures:
        h = resolve(c["toks"], defined)
        if h is None:
            h = resolve(c["toks"], defined, with_lev=True)
            if h is not None:
                flagged.append({"capture": " ".join(c["toks"]), "target": h})
        if h is None:
            unresolved.append(" ".join(c["toks"]))
        else:
            resolved.append({**c, "target": h})

    # -- tile [0, len(text)) exactly once ---------------------------------------
    blocks: list[tuple[int, str, str, str]] = []   # (start, uid, titre, struct)
    for g in groups:
        if g["kind"] == "junk":
            continue                              # absorbed by previous unit
        if g["kind"] == "pointer":
            blocks.append((g["lines"][0][0], g["uid"], g["titre"], "S2"))
        elif g["kind"] == "core":
            blocks.append((g["lines"][0][0], g["uid"], g["titre"], "S1"))
        else:
            pr = g.get("promote")
            if pr is None:
                continue                          # glued material: absorbed
            blocks.append((pr[1], pr[0], pr[2], "S1"))
    blocks.sort(key=lambda b: b[0])

    used: dict[str, int] = {}
    node_of_uid: dict[str, str] = {}
    units: list[Unit] = []

    def add_unit(start: int, end: int, slug: str, titre: str,
                 structure: str) -> None:
        n = used.get(slug, 0)
        uid = slug if n == 0 else f"{slug}-{n + 1}"
        used[slug] = n + 1
        node_of_uid[uid] = slug
        units.append(Unit(uid, structure, start, end, titre=titre))

    if not blocks:
        add_unit(0, len(text), "ouverture", "Ouverture", "S1")
    else:
        if blocks[0][0] > 0:
            add_unit(0, blocks[0][0], "ouverture", "Ouverture", "S1")
        for k, (start, slug, titre, structure) in enumerate(blocks):
            end = blocks[k + 1][0] if k + 1 < len(blocks) else len(text)
            add_unit(start, end, slug, titre, structure)

    return {"units": units, "node_of_uid": node_of_uid,
            "defined": sorted(defined), "resolved": resolved,
            "unresolved": unresolved, "flagged": flagged,
            "promoted": promoted, "suspect_blocks": len(suspects),
            "pointers": sum(1 for g in groups if g["kind"] == "pointer")}


def build_gamebook_partition(scan: dict, text: str, partition,
                             fmt: GamebookFormat = GAMEBOOK) -> dict:
    """Nodes (verbatim bodies + typed links) and inline d100 tables from a
    scan_gamebook record. Returns mechanical measures (no judgement here)."""
    units = scan["units"]
    node_of = scan["node_of_uid"]

    def owner(off: int) -> Unit:
        for u in units:
            if u.start <= off < u.end:
                return u
        return units[-1]

    spans: dict[str, list[tuple[int, int]]] = {}
    titres: dict[str, str] = {}
    order: list[str] = []
    for u in units:
        nid = node_of[u.uid]
        if nid not in spans:
            order.append(nid)
            titres[nid] = u.titre
        spans.setdefault(nid, []).append((u.start, u.end))

    liens_by_unit: dict[str, list[dict]] = {}
    for c in scan["resolved"]:
        liens_by_unit.setdefault(owner(c["raw"]).uid, []).append(
            {"cible_id": c["target"],
             "condition_textuelle": c["cond"] or "(inconditionnel)"})

    nodes = []
    for nid in order:
        sp = spans[nid]
        a = sp[0][0]
        u0 = next(u for u in units if node_of[u.uid] == nid)
        corps = text[a:sp[0][1]].strip()
        if len(sp) > 1:                       # repeated heading: keep every
            corps = "\n\n".join(text[x:y].strip() for x, y in sp)
        nodes.append(Node(nid,
                          "chapitre" if nid == "ouverture" else "scene",
                          titres[nid], corps, "scene",
                          liens=liens_by_unit.get(u0.uid, []),
                          anchors=sp))
    partition.nodes.extend(nodes)

    tables = extract_d100_tables(scan, text, partition, fmt)
    n_open = sum(1 for u in units if u.uid == "ouverture")
    return {"entries": sum(1 for u in units
                           if u.structure == "S1" and u.uid != "ouverture"),
            "ouvertures": n_open,
            "pointers": sum(1 for u in units if u.structure == "S2"),
            "nodes": len(nodes),
            "tables_d100": tables,
            "renvois_total": len(scan["resolved"]) + len(scan["unresolved"]),
            "renvois_resolus": len(scan["resolved"]),
            "renvois_non_resolus": scan["unresolved"],
            "recollage_tolere": scan["flagged"],
            "promotions": scan["promoted"],
            "blocs_colles_exclus": scan["suspect_blocks"]}


def extract_d100_tables(scan: dict, text: str, partition,
                        fmt: GamebookFormat = GAMEBOOK) -> list[str]:
    """Inline roll tables -> RollTable primitives. Two source shapes:
    score-bullets ("♦ If you score 34-65, go to PHANTASM") and range-lines
    ("01-40: nothing happens"). Only contiguous runs become tables; anything
    else stays verbatim prose in its node body (measured, not improvised)."""
    made: list[str] = []
    score = re.compile(r"score\s+(\d{1,3})\s*[-–]\s*(\d{1,3}|00)", re.I)
    go_to = re.compile(r"go to(?: entry)?\s+[A-Z]", re.I)
    rng_line = re.compile(
        r"^[ \t]*(\d{1,3})\s*[-–]\s*(\d{1,3}|00)\s*[:.]?\s*(\S.*)$", re.M)

    def _plage(a: str, b: str) -> tuple[int, int]:
        return int(a), (100 if b == "00" else int(b))

    for u in scan["units"]:
        body = text[u.start:u.end]
        runs: list[list[dict]] = []

        def _flush(run: list[dict]) -> None:
            if len(run) >= 2:
                runs.append(run)

        # style A: contiguous score-bullet runs
        run: list[dict] = []
        for m in re.finditer(r"♦([^♦]*)", body):
            sm = score.search(m.group(1))
            if not sm:
                _flush(run)
                run = []
                continue
            a, b = _plage(sm.group(1), sm.group(2))
            if go_to.search(m.group(1)) \
                    and (not run or a == run[-1]["fin"] + 1):
                run.append({"debut": a, "fin": b,
                            "md": re.sub(r"\s+", " ", m.group(1).strip()),
                            "at": m.start(1)})
            else:
                _flush(run)
                run = []
        _flush(run)

        # style B: contiguous range-lines
        run = []
        for m in rng_line.finditer(body):
            a, b = _plage(m.group(1), m.group(2))
            if not run or a == run[-1]["fin"] + 1:
                run.append({"debut": a, "fin": b,
                            "md": re.sub(r"\s+", " ", m.group(3).strip()),
                            "at": m.start()})
            else:
                _flush(run)
                run = [{"debut": a, "fin": b,
                        "md": re.sub(r"\s+", " ", m.group(3).strip()),
                        "at": m.start()}]
        _flush(run)

        for k, rows in enumerate(runs, 1):
            tid = _slug(f"d100-{u.uid}") + (f"-{k}" if len(runs) > 1 else "")
            try:
                partition.tables.append(RollTable(
                    tid, "1d100",
                    [{"plage_debut": r["debut"], "plage_fin": r["fin"],
                      "resultat_md": r["md"]} for r in rows],
                    [(u.start + rows[0]["at"],
                      u.start + rows[-1]["at"] + len(rows[-1]["md"]))]))
                made.append(tid)
            except ValueError:
                pass                                # stays verbatim prose
    return made


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
