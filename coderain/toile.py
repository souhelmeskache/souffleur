"""L'étage toile (D-241 issue a, I-371a) — toile.md, objet propre.

La TOILE de secrets et de révélations, tissée par l'Auteur autour de la
pulsion du joueur, dévoilée module après module (arbitrage Souhel du 29/08:
objet propre, PAS dans campagne.md). Format Markdown lisible seul, même
convention d'entrées que campagne.md (voir docs/verification-campagne-md-
d186.md):

    # toile

    ## <id> {#<id>}
    ancre_module: <référence module/scène qui a posé le fil>
    condition_revelation: <condition — jamais improvisée au moment du dévoilement>
    etat: latent | revele | caduc
    rattachement: <id campagne.md — pulsion ou destinée du personnage>   (optionnel)
    revele_ancre: <référence tour/scène où la révélation a eu lieu>      (posé par set_etat)

    <secret_md — le fil lui-même>

TRACÉE (D-19): un fil se pose à l'avance (ancre_module + condition_revelation
obligatoires — refus sinon). VÉRIFIABLE (D-20): validate() relit et constate
la cohérence de forme. RÉVÉLATION NON DUE (D-63): un fil peut rester latent à
jamais; `caduc` couvre les fils que la campagne a rendus sans objet. Les
références sont UNIDIRECTIONNELLES: un fil peut pointer un id de campagne.md
via `rattachement`; campagne.md ne pointe JAMAIS la toile (pas de mécanisme
retour dans ce module). Rétro-création INTERDITE: une réadaptation ajoute des
fils ou fait progresser leur état, jamais ne réécrit un fil déjà tracé — ce
module n'expose aucune fonction d'édition du contenu posé, seulement
set_etat() pour les transitions. Archivage: un fil retiré passe `caduc`,
jamais supprimé. Ce module ne branche rien en séance: écrit par l'Auteur
seul, lu par l'Auteur et les gardes de secret, jamais chargé dans un contexte
de tour (même régime que campagne.md — D-186).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ETATS = ("latent", "revele", "caduc")
# Transitions légales — jamais de retour en arrière (rétro-création interdite):
# latent peut avancer vers révélé ou devenir caduc directement (D-63); révélé
# ne peut que devenir caduc; caduc est terminal (trace biographique).
_TRANSITIONS = {
    "latent": {"revele", "caduc"},
    "revele": {"caduc"},
    "caduc": set(),
}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Reuses the registry parser so toile.md round-trips exactly like campagne.md
# and every other md file the engine reads/writes.
from .memory import parse_entries  # noqa: E402


@dataclass
class FilToile:
    id: str
    ancre_module: str = ""
    condition_revelation: str = ""
    etat: str = "latent"
    rattachement: str = ""
    secret_md: str = ""
    attrs: dict[str, str] = field(default_factory=dict)

    def revele_ancre(self) -> str:
        return self.attrs.get("revele_ancre", "").strip()


@dataclass
class Toile:
    fil: list[FilToile] = field(default_factory=list)

    def by_id(self, fil_id: str) -> FilToile | None:
        return next((f for f in self.fil if f.id == fil_id), None)


def load(text: str) -> Toile:
    """Parse toile.md text — même convention d'entrées que campagne.md."""
    fils = []
    for e in parse_entries(text):
        ancre_module = e.attrs.pop("ancre_module", "").strip()
        condition = e.attrs.pop("condition_revelation", "").strip()
        etat = e.attrs.pop("etat", "").strip() or "latent"
        rattachement = e.attrs.pop("rattachement", "").strip()
        fils.append(FilToile(id=e.slug, ancre_module=ancre_module,
                             condition_revelation=condition, etat=etat,
                             rattachement=rattachement, secret_md=e.body,
                             attrs=e.attrs))
    return Toile(fil=fils)


def load_file(path: str | Path) -> Toile:
    p = Path(path)
    return load(p.read_text(encoding="utf-8") if p.exists() else "")


def render(toile: Toile) -> str:
    out = ["# toile", ""]
    for f in toile.fil:
        out.append(f"## {f.id}  {{#{f.id}}}")
        out.append(f"ancre_module: {f.ancre_module}")
        out.append(f"condition_revelation: {f.condition_revelation}")
        out.append(f"etat: {f.etat}")
        if f.rattachement:
            out.append(f"rattachement: {f.rattachement}")
        for k, v in f.attrs.items():
            if v:
                out.append(f"{k}: {v}")
        out.append("")
        out.append(f.secret_md.strip())
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def save_file(toile: Toile, path: str | Path) -> None:
    Path(path).write_text(render(toile), encoding="utf-8")


def set_etat(toile: Toile, fil_id: str, etat: str, *, ancre: str | None = None) -> bool:
    """Transition d'état — jamais de retour en arrière (rétro-création
    interdite, D-19/D-63). Une transition vers `revele` DOIT porter son ancre
    (D-241: « tracée avec son ancre ») — refusée sans elle. L'entrée reste
    dans le fichier quel que soit l'état (archivage biographique)."""
    if etat not in ETATS:
        return False
    f = toile.by_id(fil_id)
    if f is None:
        return False
    if etat not in _TRANSITIONS.get(f.etat, set()):
        return False
    if etat == "revele":
        if not (ancre or "").strip():
            return False
        f.attrs["revele_ancre"] = ancre.strip()
    f.etat = etat
    return True


def validate(toile: Toile, *, campagne_ids: set[str] | None = None,
             signales: set[str] | None = None) -> list[str]:
    """Validation de forme (livrable 1, D-241): tout fil a ancre_module et
    condition_revelation (sinon REFUSÉ) ; etat connu ; une révélation porte
    son ancre tracée ; rattachement, s'il existe, résout contre les ids
    connus de campagne.md ou est explicitement signalé. Retourne une liste
    d'erreurs — vide veut dire valide."""
    campagne_ids, signales = campagne_ids or set(), signales or set()
    errors: list[str] = []
    seen: set[str] = set()
    for f in toile.fil:
        tag = f"f[{f.id}]"
        if not _ID_RE.match(f.id):
            errors.append(f"{tag}: id non conforme au slug stable")
        if f.id in seen:
            errors.append(f"{tag}: id dupliqué")
        seen.add(f.id)
        if not f.ancre_module.strip():
            errors.append(f"{tag}: ancre_module absente")
        if not f.condition_revelation.strip():
            errors.append(f"{tag}: condition_revelation absente")
        if f.etat not in ETATS:
            errors.append(f"{tag}: etat '{f.etat}' hors {list(ETATS)}")
        elif f.etat == "revele" and not f.revele_ancre():
            errors.append(f"{tag}: transition revele sans ancre tracée")
        if f.rattachement:
            if not _ID_RE.match(f.rattachement):
                errors.append(f"{tag}: rattachement mal formé: {f.rattachement}")
            elif f.rattachement not in campagne_ids and f.rattachement not in signales:
                errors.append(f"{tag}: rattachement inconnu: {f.rattachement}")
    return errors
