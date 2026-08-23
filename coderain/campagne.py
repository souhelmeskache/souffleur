"""L'étage campagne (D-186, candidate) — campagne.md, fichier autoportant.

La couche qu'aucun module ne porte jamais (D-122): ce que la table a construit
et qu'aucune conversion ne réécrira. Le format est du Markdown lisible seul:

    # campagne

    ambition_finale: <md libre>

    ## <id> {#<id>}
    registre: monde | interieur          (I-200 — les deux obligatoires)
    statut: actif | promu | scelle       (critère de sortie D-183)
    ancre_source: <référence tour/scène/état>
    aventure_debut: <n>                  (optionnel — alimente l'ancienneté)
    porte: rec-x, flag:y, quete_etat:z:etat

    <fait_md — UN fait extrait, jamais une synthèse>

Sémantique des statuts (D-186): `promu` = la matière a sédimenté dans une
structure permanente (flag, champ de record, état de quête); `scelle` = ne
rend rien non portable, ne structure aucun héritage. Les entrées retirées
restent dans le fichier avec leur statut — JAMAIS supprimées (trace
biographique). Ce module ne branche rien en séance: lecture, validation de
forme et rapport hors séance pour l'Auteur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REGISTRES = ("monde", "interieur")
STATUTS = ("actif", "promu", "scelle")
# I-186: un fil actif sans promotion ni scellement après N aventures est un
# signal (pas une erreur) remonté dans le rapport de lecture.
SEUIL_AVENTURES = 3

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_AMBITION_RE = re.compile(r"^ambition_finale:\s?(.*)$", re.IGNORECASE)
_PORTE_RE = re.compile(
    r"^(?:[a-z0-9][a-z0-9-]*"          # record_id (slug de registre)
    r"|flag:[a-z0-9][a-z0-9-]*"        # flag:<nom>
    r"|quete_etat:[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*)$")  # quete_etat:<id>:<etat>

# Reuses the registry parser so campagne.md round-trips exactly like every
# other md file the engine reads/writes (comment stripping, attr headers,
# body preservation).
from .memory import Entry, parse_entries  # noqa: E402


@dataclass
class FilRouge:
    id: str
    registre: str = ""
    fait_md: str = ""
    ancre_source: str = ""
    porte: list[str] = field(default_factory=list)
    statut: str = "actif"
    attrs: dict[str, str] = field(default_factory=dict)

    def aventure_debut(self) -> int | None:
        raw = self.attrs.get("aventure_debut", "").strip()
        if not raw or not raw.isascii():
            return None
        try:
            return int(raw)
        except ValueError:
            return None


@dataclass
class Campagne:
    ambition_finale: str = ""
    fil_rouge: list[FilRouge] = field(default_factory=list)

    def by_id(self, fil_id: str) -> FilRouge | None:
        return next((f for f in self.fil_rouge if f.id == fil_id), None)


def load(text: str) -> Campagne:
    """Parse campagne.md text. Everything above the first entry heading is the
    preamble; only the `ambition_finale:` line is meaningful there."""
    ambition = ""
    for line in text.splitlines():
        m = _AMBITION_RE.match(line)
        if m:
            ambition = m.group(1).strip()
            break
    fils = []
    for e in parse_entries(text):
        porte = [p.strip() for p in e.attrs.pop("porte", "").split(",")
                 if p.strip()]
        registre = e.attrs.pop("registre", "").strip()
        statut = e.attrs.pop("statut", "").strip() or "actif"
        ancre = e.attrs.pop("ancre_source", "").strip()
        fils.append(FilRouge(id=e.slug, registre=registre, fait_md=e.body,
                             ancre_source=ancre, porte=porte, statut=statut,
                             attrs=e.attrs))
    return Campagne(ambition_finale=ambition, fil_rouge=fils)


def load_file(path: str | Path) -> Campagne:
    p = Path(path)
    return load(p.read_text(encoding="utf-8") if p.exists() else "")


def render(camp: Campagne) -> str:
    out = ["# campagne", ""]
    out.append(f"ambition_finale: {camp.ambition_finale.strip()}")
    out.append("")
    for f in camp.fil_rouge:
        out.append(f"## {f.id}  {{#{f.id}}}")
        out.append(f"registre: {f.registre}")
        out.append(f"statut: {f.statut}")
        out.append(f"ancre_source: {f.ancre_source}")
        for k, v in f.attrs.items():
            if v:
                out.append(f"{k}: {v}")
        if f.porte:
            out.append("porte: " + ", ".join(f.porte))
        out.append("")
        out.append(f.fait_md.strip())
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def save_file(camp: Campagne, path: str | Path) -> None:
    Path(path).write_text(render(camp), encoding="utf-8")


def set_statut(camp: Campagne, fil_id: str, statut: str) -> bool:
    """Transition actif -> promu|scelle. The entry STAYS in the file either way
    (trace biographique, D-186); nothing is ever removed."""
    if statut not in STATUTS:
        return False
    f = camp.by_id(fil_id)
    if f is None:
        return False
    f.statut = statut
    return True


def _porte_cible(tok: str, records: set[str], flags: set[str],
                 quests: dict[str, str], signales: set[str]) -> str | None:
    """Resolve one porte token against what the save knows. Returns None when it
    resolves (or was signaled), else an error message."""
    if tok in signales:
        return None
    if tok.startswith("flag:"):
        return None if tok[5:] in flags else f"flag inconnu: {tok}"
    if tok.startswith("quete_etat:"):
        _, qid, etat = tok.split(":", 2)
        known = quests.get(qid)
        if qid not in quests:
            return f"quête inconnue: {tok}"
        if known and known != etat:
            return f"état de quête incohérent: {tok} (save: {known})"
        return None
    return None if tok in records else f"record inconnu: {tok}"


def validate(camp: Campagne, *, records: set[str] | None = None,
             flags: set[str] | None = None, quests: dict[str, str] | None = None,
             signales: set[str] | None = None) -> list[str]:
    """Form validation (livrable 1): every entry has id/registre/fait/ancre/
    statut; every porte is well-formed AND resolves against the save's known
    records/flags/quests — or was explicitly signaled (`signales`), per D-186.
    Returns a list of error strings; empty means valid."""
    records, flags = records or set(), flags or set()
    quests, signales = quests or {}, signales or set()
    errors: list[str] = []
    seen: set[str] = set()
    if not camp.ambition_finale.strip():
        errors.append("ambition_finale absente")
    for f in camp.fil_rouge:
        tag = f"f[{f.id}]"
        if not _ID_RE.match(f.id):
            errors.append(f"{tag}: id non conforme au slug stable")
        if f.id in seen:
            errors.append(f"{tag}: id dupliqué")
        seen.add(f.id)
        if f.registre not in REGISTRES:
            errors.append(f"{tag}: registre '{f.registre}' hors {list(REGISTRES)}")
        if not f.fait_md.strip():
            errors.append(f"{tag}: fait_md vide")
        if not f.ancre_source.strip():
            errors.append(f"{tag}: ancre_source absente")
        if f.statut not in STATUTS:
            errors.append(f"{tag}: statut '{f.statut}' hors {list(STATUTS)}")
        for tok in f.porte:
            if not _PORTE_RE.match(tok):
                errors.append(f"{tag}: porte mal formée: {tok}")
                continue
            err = _porte_cible(tok, records, flags, quests, signales)
            if err:
                errors.append(f"{tag}: {err}")
    return errors


def rapport(camp: Campagne, *, aventure_actuelle: int | None = None,
            seuil: int = SEUIL_AVENTURES) -> dict:
    """Reading report for the Auteur (out-of-session, livrable 2): active
    entries per registre, age of the actives, and the counter of actives with
    neither promotion nor scellement after N adventures. The counter is a
    SIGNAL feeding I-186 — never an error."""
    actifs = [f for f in camp.fil_rouge if f.statut == "actif"]
    par_registre = {r: sum(1 for f in actifs if f.registre == r)
                    for r in REGISTRES}
    ages: list[dict] = []
    ages_inconnues: list[str] = []
    for f in actifs:
        debut = f.aventure_debut()
        if debut is None or aventure_actuelle is None:
            ages_inconnues.append(f.id)
        else:
            ages.append({"id": f.id, "aventures": aventure_actuelle - debut})
    depasses = [a for a in ages if a["aventures"] > seuil]
    return {
        "total": len(camp.fil_rouge),
        "par_statut": {s: sum(1 for f in camp.fil_rouge if f.statut == s)
                       for s in STATUTS},
        "actifs_par_registre": par_registre,
        "anciennete_actifs": sorted(ages, key=lambda a: -a["aventures"]),
        "anciennete_inconnue": ages_inconnues,
        "signal_stagnation": {"seuil_aventures": seuil, "entrees": depasses},
    }
