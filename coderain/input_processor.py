"""Le processeur d'entrée v-min (I-373) — l'organe qui TRIE et PROPOSE entre le
texte brut du joueur et les réceptacles, sans jamais juger.

La table de routage (D-092) :
    - guillemets doubles ou chevrons « » = parole
    - parenthèses ( )                    = intériorité
    - texte nu                           = action
    - ligne entière préfixée d'un tiret cadratin « — »
      = parole aussi — la "ligne PAROLE qui n'a jamais existé" (trou N4).
      ASSUMPTION NON CONFIRMÉE (vault MVP2 inaccessible depuis ce repo, schéma
      des chaînes §6) : convention française du dialogue en prose sans
      guillemets. Voir BLOQUÉ posté sur l'Issue #34 — à corriger si le vault
      dit autre chose.
    - commande méta (I-237) : l'entrée ENTIÈRE (une fois dépouillée de sa
      ponctuation finale) est "annuler"/"undo" ou "rejouer"/"retry"/"redo" ->
      routée seule, propriétaire déclaré = la méthode Engine qui la traite
      (undo_last / swipe_generate). Aucune autre lecture n'est tentée sur une
      commande : elle ne se mélange pas aux 3 registres.

Tout ce que la table n'a pas su router (guillemet/parenthèse non apparié,
entrée ambiguë) monte dans LE PACK : chaque pièce y porte une PROPOSITION de
lecture, jamais une décision — router ne juge pas, il propose. Le Director
tranche.

Ce module est pur (aucun accès disque/LLM) sauf `extraire_interiorite`, qui
écrit dans le store fourni — voir sa docstring pour le réceptacle stub D-233b.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

QUOTE_RE = re.compile(r'"([^"\n]+)"|«([^»\n]+)»')
PAREN_RE = re.compile(r'\(([^()\n]+)\)')
EMDASH_RE = re.compile(r'^\s*[—–]\s*(.+)$')

# I-237 : vocabulaire des commandes méta reconnues, et la méthode Engine
# propriétaire de chacune (jamais dupliquée ici — le routeur appelle,
# il ne réimplémente pas undo/retry).
COMMANDES: dict[str, str] = {
    "annuler": "undo_last",
    "undo": "undo_last",
    "rejouer": "swipe_generate",
    "retry": "swipe_generate",
    "redo": "swipe_generate",
}


@dataclass
class RoutedSegment:
    """Un morceau d'entrée que la table a su ranger sans passage Director."""
    registre: str                      # "parole" | "interiorite" | "action" | "commande"
    text: str
    proprietaire: str | None = None    # commande uniquement : méthode Engine déclarée


@dataclass
class PackItem:
    """Une pièce non routée, avec sa proposition de lecture — jamais un fait."""
    text: str
    proposition: str


@dataclass
class ProcessedInput:
    segments: list[RoutedSegment] = field(default_factory=list)
    pack: list[PackItem] = field(default_factory=list)
    pack_ratio: float = 0.0             # métrique native : part brute -> Director
    commande: RoutedSegment | None = None


def classify_pack_ratio(ratio: float) -> str:
    """Lecture qualitative de la métrique native (I-373), dans les mots mêmes
    du ticket : >=80% = le processeur "ne trie pas" (quasi tout part brut) ;
    <=5% = il "triche" (prétend tout router sans jamais admettre l'ambiguïté).
    Entre les deux : plage saine, non nommée par le ticket."""
    if ratio >= 0.80:
        return "ne trie pas"
    if ratio <= 0.05:
        return "triche"
    return "sain"


def _detect_commande(raw: str) -> RoutedSegment | None:
    stripped = raw.strip().rstrip(".!?").strip().lower()
    owner = COMMANDES.get(stripped)
    if owner is None:
        return None
    return RoutedSegment("commande", raw.strip(), owner)


def _extract_spans(text: str, regex: re.Pattern, registre: str
                    ) -> tuple[list[RoutedSegment], str]:
    """Retire chaque occurrence de `regex` et la route vers `registre`. Le
    texte restant garde un espace à la place de chaque morceau retiré (pour
    ne pas recoller deux mots qui ne l'étaient pas) — v-min : l'ordre relatif
    entre segments routés et texte nu n'est pas préservé, seule la
    classification l'est."""
    segments = []
    out = []
    last = 0
    for m in regex.finditer(text):
        out.append(text[last:m.start()])
        content = next(g for g in m.groups() if g is not None)
        segments.append(RoutedSegment(registre, content.strip()))
        out.append(" ")
        last = m.end()
    out.append(text[last:])
    return segments, "".join(out)


def process(raw: str) -> ProcessedInput:
    """Route `raw` : voir le docstring du module pour la table complète.
    Ne stocke rien, n'appelle rien — fonction pure, à l'appelant d'agir sur
    le résultat (Engine.route_input)."""
    if not raw or not raw.strip():
        return ProcessedInput()

    commande = _detect_commande(raw)
    if commande is not None:
        return ProcessedInput(segments=[commande], commande=commande)

    parole_segs, rest = _extract_spans(raw, QUOTE_RE, "parole")
    interior_segs, rest = _extract_spans(rest, PAREN_RE, "interiorite")
    segments: list[RoutedSegment] = [*parole_segs, *interior_segs]
    pack: list[PackItem] = []

    # Ce qui reste (hors spans déjà routés) est examiné ligne par ligne :
    # ligne tiret cadratin -> parole (trou N4) ; guillemet/parenthèse
    # orphelin (non apparié) -> LE PACK avec proposition, jamais tranché de
    # force ; sinon -> action.
    for line in rest.split("\n"):
        line = line.strip()
        if not line:
            continue
        if '"' in line or "«" in line or "»" in line:
            pack.append(PackItem(line, "guillemet non apparié — peut-être "
                                       "parole, non tranché"))
            continue
        if "(" in line or ")" in line:
            pack.append(PackItem(line, "parenthèse non appariée — peut-être "
                                       "intériorité, non tranché"))
            continue
        m = EMDASH_RE.match(line)
        if m:
            segments.append(RoutedSegment("parole", m.group(1).strip()))
            continue
        segments.append(RoutedSegment("action", line))

    total = len(raw)
    pack_len = sum(len(p.text) for p in pack)
    ratio = (pack_len / total) if total else 0.0
    return ProcessedInput(segments=segments, pack=pack, pack_ratio=ratio)


# --- l'extracteur des parenthèses (D-233b) ---------------------------------

# D-233b (le support biographique, colonne "dit") n'existe pas encore côté
# repo — réceptacle stub clairement nommé, en attendant. À rebrancher sur le
# vrai support dès qu'il existe ; le nom du fichier suffit à retrouver tous
# les appelants à corriger.
STUB_INTERIORITE = "memory/interiorite-stub.md"


def extraire_interiorite(store, segments: list[RoutedSegment], turn_index: int
                          ) -> list[str]:
    """Écrit chaque segment 'interiorite' vers la colonne 'dit' du support
    biographique (D-233b) — ici le réceptacle stub STUB_INTERIORITE tant que
    le vrai support n'existe pas. Une Entry par segment, upsert (un retry du
    même tour_index réécrit plutôt que d'accumuler des doublons). Retourne
    les textes écrits, pour les tests/logs — n'écrit jamais dans un registre
    de faits géré (characters/locations/...) : l'intériorité n'est pas un
    fait de scénario."""
    from .memory import Entry
    written = []
    for i, seg in enumerate(segments):
        if seg.registre != "interiorite":
            continue
        slug = f"interiorite-t{turn_index}-{i}"
        store.upsert_entry(STUB_INTERIORITE, Entry(
            title=f"Intériorité — tour {turn_index}", slug=slug,
            attrs={"dit": seg.text, "tour": str(turn_index)}, body=seg.text))
        written.append(seg.text)
    return written
