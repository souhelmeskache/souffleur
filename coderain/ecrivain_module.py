"""L'ORGANE D'ÉCRITURE de module — la chaîne cadre → régime → formes →
écriture → retour 2 (D-262, issue #143, dernière brique du chemin
`MRPG-D-262`).

Quand le joueur sort du prévu (cas 2 inflexion / cas 3 digression, D-117),
l'Auteur écrit un interstice. Thèse actée : il écrit un MODULE en prose
source — jamais une partition — qui emprunte ensuite le chemin du matériau
tiers (conversion P4, `coderain/converter/convert.py`, hors périmètre de
cette lane). Cette lane construit l'orchestrateur SEUL : LE CODE orchestre,
LE LLM écrit (même pattern que `selecteur.py`/`modules/trinity.py::_redirect`) :

    1. **Entrée** : `acte` (`coderain.acte.Acte`) · `regime` (pont |
       rattrapage | aiguillage — choisi par l'APPELANT sur les lectures du
       cadre, JAMAIS par ce module : le régime est un jugement d'Auteur/
       Souhel) · `store` (le vécu, `coderain.memory.MemoryStore`) · `llm`.
    2. **Le prompt d'écriture** assemble, dans cet ordre : `acte.bloc_cadre`
       (les trois lectures) + les exigences du régime choisi + le bloc de
       formes (`formes.bloc_prompt`, déclaration obligatoire) + les
       contraintes d'écriture transverses (états/potentiels jamais une
       séquence imposée · texte de module source tel que le convertisseur
       sait l'ingérer).
    3. **La sortie structurée** attendue du LLM :
       `{module_md, declaration_formes, note_intention_md}` — la note
       d'intention est écrite au PASSÉ et à l'INTENTION (pourquoi ces
       choix), jamais au futur événementiel (contrainte de PROMPT ; ce
       module ne peut pas vérifier le temps grammatical d'un texte libre).
    4. **Les gardes en cascade (code)** : `formes.valider_declaration` →
       `retour2.retour2` sur les objectifs du régime (formulés en TEXTE par
       CE module depuis l'acte, jamais un champ structuré inventé) → UNE
       re-demande corrective max sur rejet (formes OU retour2 — même
       budget, pattern `modules/trinity.py::_redirect`), sinon échec
       rapporté avec les rejets (jamais silencieux).
    5. **Le rapport** : `RapportEcriture` — `statut` "pret" signifie prêt
       POUR LA CONVERSION, pas converti (l'appel de conversion est l'étape
       d'APRÈS, hors périmètre de cette lane).

Module autonome (D-262 §5, critère d'ordre) : n'importe ni `engine.py` ni le
convertisseur — le futur appel de conversion (humain ou lane future) est son
appelant nommé, pas l'inverse."""
from __future__ import annotations

import json
from dataclasses import dataclass

from .acte import Acte, bloc_cadre
from .formes import Forme, bloc_prompt, charger_vocabulaire, valider_declaration
from .llm import emit_json_ex
from .memory import MemoryStore
from .retour2 import Objectif, RapportConformite, retour2

# Vocabulaire fermé des régimes (D-262) — un jugement d'Auteur/Souhel sur les
# lectures du cadre, jamais déduit par ce module.
REGIMES = ("pont", "rattrapage", "aiguillage")

# Les exigences propres à chaque régime (D-262 §2), telles qu'injectées dans
# le prompt — texte, jamais un champ structuré côté LLM.
_EXIGENCES_REGIME = {
    "pont": (
        "PONT : écris le MINIMUM nécessaire pour rendre le raccord "
        "atteignable — pas de matière superflue, chaque scène sert "
        "explicitement le passage vers le module/l'acte suivant."),
    "rattrapage": (
        "RATTRAPAGE : fais VIVRE, dans ce module, chacun des jalons "
        "pas-vécus listés ci-dessous — un jalon rattrapé doit se jouer "
        "réellement, jamais être mentionné en passant."),
    "aiguillage": (
        "AIGUILLAGE : propose des situations à VRAIS enjeux qui "
        "discriminent réellement entre plusieurs agendas de personnages/"
        "factions — on aiguille les AGENDAS, jamais les révélations "
        "(aucun secret ne doit dépendre du choix du joueur pour exister ou "
        "non)."),
}

# Contraintes d'écriture transverses aux trois régimes (D-262 §2).
_CONTRAINTES_TRANSVERSES = (
    "CONTRAINTES D'ÉCRITURE TRANSVERSALES :\n"
    "- Écris des ÉTATS et des POTENTIELS, JAMAIS une séquence d'événements "
    "imposée au joueur : ce que tu écris doit rester jouable dans "
    "n'importe quel ordre que le joueur choisit.\n"
    "- Écris du texte de MODULE SOURCE (scènes, lieux, PNJ avec objectifs "
    "et accroches) — de la prose telle que le convertisseur de ce dépôt "
    "sait l'ingérer, jamais une partition d'événements scriptés.")

ECRITURE_SYS = """\
You are the AUTEUR writing a module-episode in SOURCE PROSE (never a \
scripted partition) for a tabletop campaign. You are given the ACTE frame \
(three readings: remplissage, divergence, raccord), the RÉGIME requirements \
for this write, a STOCK OF FORMS you must choose from and declare, and \
transversal writing constraints.

Return ONLY a JSON object with exactly these fields:
{"module_md": "...", "declaration_formes": [{"id": "...", "justification": "..."}],
 "note_intention_md": "..."}

"module_md" is the module-episode itself: scenes, places, NPCs with \
objectives and hooks — states and potentials, never a forced sequence.

"declaration_formes" declares every narrative form from the stock you used \
(id exactly as given, plus a justification linking it to the character's \
drive) — never a form used implicitly.

"note_intention_md" is a short note written in the PAST TENSE, about \
INTENTION — why you made these choices, what they serve — NEVER a preview \
of what will happen in play (it documents a decision already made, not an \
upcoming event).
"""


@dataclass(frozen=True)
class ModuleEcrit:
    """La sortie structurée validée d'un tour d'écriture (D-262 §3) — jamais
    accepté sur la seule parole du LLM : `declaration_formes` a déjà passé
    `formes.valider_declaration` quand cet objet existe."""
    module_md: str
    declaration_formes: tuple[dict, ...]
    note_intention_md: str

    def to_dict(self) -> dict:
        return {"module_md": self.module_md,
                "declaration_formes": list(self.declaration_formes),
                "note_intention_md": self.note_intention_md}


@dataclass(frozen=True)
class RapportEcriture:
    """Le rapport final (D-262 §5). `statut` "pret" signifie prêt POUR LA
    CONVERSION, pas converti — la conversion reste un appel séparé, hors
    périmètre de cette lane. `rejets` porte les motifs du dernier tour
    quand `statut == "echec"` — jamais silencieux."""
    module_md: str
    note_intention_md: str
    formes: tuple[dict, ...]
    rapport_conformite: RapportConformite | None
    statut: str
    rejets: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "module_md": self.module_md,
            "note_intention_md": self.note_intention_md,
            "formes": list(self.formes),
            "rapport_conformite": (self.rapport_conformite.to_dict()
                                   if self.rapport_conformite is not None else None),
            "statut": self.statut,
            "rejets": list(self.rejets),
        }


def _bloc_regime(acte: Acte, regime: str) -> str:
    """Le bloc de prompt propre au régime choisi — exigences fixes + les
    jalons pas-vécus concrets pour le rattrapage (jamais une re-déduction :
    la liste vient directement de l'acte transmis)."""
    lignes = [f"## Régime d'écriture : {regime}", "", _EXIGENCES_REGIME[regime]]
    if regime == "rattrapage":
        cibles = [j for j in acte.jalons if j.statut == "pas-vécu"]
        lignes.append("")
        lignes.append("Jalons pas-vécus à faire vivre :")
        if cibles:
            for j in cibles:
                lignes.append(f"- [{j.id}] {j.intention_md}")
        else:
            lignes.append("(aucun jalon pas-vécu — vérifier le cadre avant "
                          "d'écrire en régime rattrapage)")
    return "\n".join(lignes)


def _objectifs_regime(acte: Acte, regime: str) -> list[Objectif]:
    """Les objectifs du retour 2 (D-262 §4) — formulés en TEXTE par CE
    module depuis l'acte, jamais un champ structuré inventé par le LLM."""
    if regime == "pont":
        raccord = acte.raccord
        return [Objectif(
            id="raccord",
            texte="Le module rend atteignable le raccord vers "
                 f"{raccord.module_id or '(module suivant pas encore choisi)'} "
                 "— conditions d'entrée : "
                 f"{raccord.conditions_entree_md.strip() or '(aucune condition posée)'}")]
    if regime == "rattrapage":
        cibles = [j for j in acte.jalons if j.statut == "pas-vécu"]
        return [Objectif(id=f"jalon-{j.id}",
                         texte=f"Le module fait vivre le jalon '{j.id}' : "
                               f"{j.intention_md}")
               for j in cibles]
    if regime == "aiguillage":
        return [Objectif(
            id="aiguillage",
            texte="Le module propose des situations qui discriminent "
                 "réellement entre plusieurs agendas de personnages/"
                 "factions (jamais les révélations) — objectif de l'acte : "
                 f"{acte.objectif_md.strip()}")]
    raise ValueError(f"régime inconnu : {regime!r} (attendu {REGIMES})")


def _prompt_ecriture(acte: Acte, regime: str, store: MemoryStore | None,
                     vocabulaire: dict[str, Forme]) -> str:
    """Assemble le prompt complet (D-262 §2) : cadre + régime + formes +
    contraintes transverses, dans cet ordre, zéro appel LLM ici."""
    return "\n\n".join([
        bloc_cadre(acte, store),
        _bloc_regime(acte, regime),
        bloc_prompt(vocabulaire),
        _CONTRAINTES_TRANSVERSES,
    ])


def _payload_redemande(prompt_original: str, rejets: list[dict]) -> str:
    """Pattern `modules/trinity.py::_redirect` : montre les rejets au LLM et
    redemande la sortie complète — jamais un diff partiel."""
    return (prompt_original
            + "\n\n---\nTA PROPOSITION PRÉCÉDENTE A ÉTÉ REJETÉE, motifs :\n"
            + json.dumps(rejets, ensure_ascii=False)
            + "\n\nCorrige ta proposition en tenant compte de CHACUN de ces "
              "motifs. Retourne à nouveau le JSON complet {module_md, "
              "declaration_formes, note_intention_md}.")


def _valider_sortie(obj: dict, vocabulaire: dict[str, Forme]
                    ) -> tuple[ModuleEcrit | None, list[dict]]:
    """Garde de forme sur la sortie brute du LLM (D-262 §4) — jamais
    acceptée sur parole. Retourne (module, []) si valide, sinon
    (None, rejets) motivés."""
    if not isinstance(obj, dict):
        return None, [{"champ": None, "raison": "sortie LLM n'est pas un objet"}]

    module_md = str(obj.get("module_md", "")).strip()
    note_intention_md = str(obj.get("note_intention_md", "")).strip()
    declaration = obj.get("declaration_formes")
    if not isinstance(declaration, list):
        declaration = []

    rejets: list[dict] = []
    if not module_md:
        rejets.append({"champ": "module_md", "raison": "module_md absent ou vide"})
    if not note_intention_md:
        rejets.append({"champ": "note_intention_md",
                       "raison": "note_intention_md absente ou vide"})

    validees, rejets_formes = valider_declaration(declaration, vocabulaire)
    for r in rejets_formes:
        rejets.append({"champ": "declaration_formes", **r})

    if rejets:
        return None, rejets
    return ModuleEcrit(module_md, tuple(validees), note_intention_md), []


def ecrire_module(acte: Acte, regime: str, store: MemoryStore | None, llm,
                  *, vocabulaire: dict[str, Forme] | None = None,
                  retry: int = 1) -> RapportEcriture:
    """La chaîne complète cadre → régime → formes → écriture → retour 2
    (D-262, issue #143). UNE re-demande corrective max, sur rejet de forme
    OU sur non-conformité au retour 2 — même budget (pattern
    `modules/trinity.py::_redirect`) : jamais de boucle."""
    if regime not in REGIMES:
        return RapportEcriture(
            "", "", (), None, "echec",
            ({"champ": "regime", "raison": f"régime inconnu : {regime!r} "
             f"(attendu {REGIMES})"},))

    vocabulaire = vocabulaire if vocabulaire is not None else charger_vocabulaire()
    objectifs = _objectifs_regime(acte, regime)
    prompt = _prompt_ecriture(acte, regime, store, vocabulaire)

    rejets: list[dict] = []
    for tour in range(2):  # 1 tentative + 1 re-demande corrective max
        payload = prompt if tour == 0 else _payload_redemande(prompt, rejets)
        obj, err = emit_json_ex(llm, ECRITURE_SYS, payload, retry=retry)
        if obj is None:
            return RapportEcriture(
                "", "", (), None, "echec",
                ({"champ": None, "raison": f"appel LLM échoué : {err}"},))

        module, rejets_forme = _valider_sortie(obj, vocabulaire)
        if module is None:
            rejets = rejets_forme
            if tour == 0:
                continue
            return RapportEcriture(
                str(obj.get("module_md", "") or "").strip(),
                str(obj.get("note_intention_md", "") or "").strip(),
                (), None, "echec", tuple(rejets))

        rapport_conf = retour2(objectifs, module.module_md, llm,
                               formes_declarees=list(module.declaration_formes),
                               retry=retry)
        if rapport_conf.conforme_total:
            return RapportEcriture(module.module_md, module.note_intention_md,
                                   module.declaration_formes, rapport_conf,
                                   "pret", ())

        rejets = list(rapport_conf.ecarts) + [dict(r) for r in rapport_conf.rejets]
        if tour == 0:
            continue
        return RapportEcriture(module.module_md, module.note_intention_md,
                               module.declaration_formes, rapport_conf,
                               "echec", tuple(rejets))

    # Théoriquement inatteignable (la boucle retourne toujours dans ses deux
    # tours) — filet de sécurité pour ne jamais laisser passer un None.
    return RapportEcriture("", "", (), None, "echec", tuple(rejets))
