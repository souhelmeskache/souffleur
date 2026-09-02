"""L'organe de bouchage — logique PURE (D-275, Issue #253).

Un PETIT trou de règle en partie ne stoppe pas la partie : il se bouche
provisoirement, tracé, et l'Auteur de l'entre-deux (#97) l'entérine ou le
rejette à l'inter-scénario. Ce module ne porte QUE la logique lisible sans
harnais : normalisation des noms de champ, lecture de `rpg.provisoire`,
table de repli du save, extrait du vocabulaire fermé de règles, résumé
mécanique de la scène.

Deux invariants tenus ici :
  * aucun appel réseau, aucun import de `coderain/llm.py` (D-263) — la
    valeur provisoire est JUGÉE ailleurs, par un sous-agent du harnais ;
  * aucune écriture : ce module lit, il ne mute rien. L'écriture de
    `rpg.provisoire` vit dans `coderain/mcp/bouchage.py`, par le chemin
    d'application de `state.json` (`set_rpg_state` → `set_world_state` →
    `validator.guard_world_state`, D-141/I-94).

Les outils MCP (`demander_bouchage`, `enregistrer_bouchage`) sont dans
`coderain/mcp/bouchage.py` ; les lecteurs de nombres de fiche (`attack`,
`derived_combat`/`player_combat`, `roll_check`) appellent d'ici
`valeur_provisoire` / `appliquer_fiche` / `appliquer_stats`.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# --- constantes de doctrine (D-275 §5) --------------------------------------

#: Plafond de bouchages par scénario. Chiffre PROVISOIRE (D-275) : au-delà,
#: le trou n'est plus petit, c'est l'amont (converter/partition) qu'il faut
#: réparer. Le compteur se remet à zéro à l'inter-scénario (#97, hors
#: périmètre de cette lane).
SEUIL_SCENARIO = 3

#: Clé réservée dans `rpg.provisoire` — le compteur y cohabite avec les
#: entrées, jamais un id de trou ne peut la prendre (voir `id_trou`).
CLE_COMPTEUR = "nb_scenario"

#: Le texte FIXE remis au sous-agent juge. Ni le Director ni cet outil ne le
#: reformulent : le dossier est le prompt entier du juge.
CONSIGNE = ("rends UNE valeur ou UNE micro-règle d'une phrase, justifiée en "
            "deux lignes, rien d'autre")

#: Types de trou acceptés.
TYPES = ("nombre", "regle")

#: Ce qu'un trou de règle n'a PAS le droit de demander (D-275 §5) : le
#: dossier le DIT explicitement (champ `modifie`), la garde ne juge pas le
#: fond — elle lit la déclaration et refuse.
PORTEES_INTERDITES = ("fiche", "record", "moteur", "regle", "règle")

#: Combien d'entrées de repli / de lignes de vocabulaire au plus dans un
#: dossier — un dossier reste court, c'est le prompt d'un juge.
REPLI_MAX = 20
REGLES_MAX = 8

# --- normalisation des noms de champ ----------------------------------------

#: champ canonique -> alias acceptés. Le canonique est le nom FR de la fiche
#: (celui que `attack` cite dans ses refus : « missing ca on ... ») ; les
#: alias couvrent le nom anglais interne de la fiche de combat.
_ALIAS: dict[str, tuple[str, ...]] = {
    "ca": ("ac", "classe_armure", "armor_class"),
    "attaque_bonus": ("attack_bonus", "bonus_attaque", "bonus_d_attaque"),
    "degats": ("damage", "des_degats", "de_degats"),
    "pv": ("hp", "hp_max", "pv_max", "points_de_vie"),
}

#: champ canonique -> clé de la fiche de combat (`mcp_server._attack_fiche`).
CHAMPS_FICHE: dict[str, str] = {
    "ca": "ac", "attaque_bonus": "attack_bonus",
    "degats": "damage", "pv": "hp_max",
}

_CANON = {a: canon for canon, alias in _ALIAS.items() for a in alias}
_CANON.update({c: c for c in _ALIAS})


def normaliser(texte: object) -> str:
    """Minuscules, sans accent, séparateurs unifiés en `_` — la forme sous
    laquelle deux écritures d'un même champ (« Dégâts », "degats", "DEGATS")
    se reconnaissent."""
    s = unicodedata.normalize("NFKD", str(texte or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s.lower())
    return s.strip("_")


def champ_canon(champ: object) -> str:
    """Le nom canonique d'un champ de fiche, ou sa forme normalisée telle
    quelle quand il n'est pas connu (une stat, par exemple)."""
    n = normaliser(champ)
    return _CANON.get(n, n)


def fiche_canon(fiche: object) -> str:
    """Le slug de fiche visé — "player" pour le joueur (et ses synonymes),
    sinon le slug en kebab-case (la forme qu'ont les slugs de
    `characters.md`). Vide pour un trou sans fiche : il porte sur la scène,
    et se range alors sous `monde` (voir `id_trou`)."""
    n = normaliser(fiche)
    if n in ("player", "you", "joueur"):
        return "player"
    return n.replace("_", "-")


def entier(v: object) -> int | None:
    """Un entier lisible ('16', '+4', 16), sinon None. Local ON PURPOSE :
    ce module ne dépend d'aucun module pro (`coderain.modules.rpg` peut
    manquer sur une install libre)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"^\s*([+-]?\d+)\s*$", str(v))
    return int(m.group(1)) if m else None


# --- lecture de `rpg.provisoire` --------------------------------------------

def bloc(rpg: dict | None) -> dict:
    """Le bloc `rpg.provisoire` tel qu'il est écrit, ou un bloc vide."""
    p = (rpg or {}).get("provisoire")
    return p if isinstance(p, dict) else {}


def entrees(rpg: dict | None) -> dict[str, dict]:
    """Les bouchages enregistrés, {id: entrée} — le compteur exclu."""
    return {k: v for k, v in bloc(rpg).items()
            if k != CLE_COMPTEUR and isinstance(v, dict)}


def nb_scenario(rpg: dict | None) -> int:
    """Combien de bouchages ont été enregistrés dans le scénario courant."""
    return entier(bloc(rpg).get(CLE_COMPTEUR)) or 0


def id_trou(trou: dict) -> str:
    """L'identifiant DÉTERMINISTE d'un trou : même fiche + même champ = même
    id, d'un appel à l'autre. C'est ce qui fait qu'un trou ne se demande pas
    deux fois — le second appel voit l'entrée déjà là."""
    fiche = fiche_canon(trou.get("fiche")) or "monde"
    champ = champ_canon(trou.get("champ"))
    prefixe = "regle" if normaliser(trou.get("type")) == "regle" else fiche
    ident = f"{prefixe}.{champ}"
    # Jamais la clé réservée du compteur : un champ nommé « nb scenario »
    # écraserait sinon le compteur lui-même.
    return f"{ident}_" if ident == CLE_COMPTEUR else ident


def valeur_provisoire(rpg: dict | None, fiche: object,
                      champ: object) -> tuple[str | None, object]:
    """La valeur provisoire enregistrée pour ce champ de cette fiche, s'il
    y en a une : `(id, valeur)`, sinon `(None, None)`.

    Consultée APRÈS la fiche et AVANT le refus — jamais à la place de la
    fiche : un nombre réellement écrit l'emporte toujours."""
    cible_f, cible_c = fiche_canon(fiche), champ_canon(champ)
    for ident, e in entrees(rpg).items():
        t = e.get("trou") if isinstance(e.get("trou"), dict) else {}
        if (fiche_canon(t.get("fiche")) == cible_f
                and champ_canon(t.get("champ")) == cible_c):
            return ident, e.get("valeur")
    return None, None


def appliquer_fiche(rpg: dict | None, slug: object,
                    fiche: dict) -> list[str]:
    """Comble les nombres ABSENTS d'une fiche de combat avec les valeurs
    provisoires de cette fiche. Mute `fiche` en place et rend les ids
    appliqués (vide = la fiche se suffisait, rien n'a été emprunté).

    Un champ déjà porté par la fiche n'est JAMAIS écrasé."""
    poses: list[str] = []
    for canon, cle in CHAMPS_FICHE.items():
        actuel = fiche.get(cle)
        if actuel is not None and actuel != "":
            continue
        ident, valeur = valeur_provisoire(rpg, slug, canon)
        if ident is None:
            continue
        if cle == "damage":
            texte = str(valeur).strip()
            if not texte:
                continue
            fiche[cle] = texte
        else:
            n = entier(valeur)
            if n is None:
                continue        # valeur illisible : on refuse comme avant
            fiche[cle] = n
        poses.append(ident)
    return poses


def appliquer_stats(rpg: dict | None, slug: object,
                    stats: dict | None) -> tuple[dict, list[str]]:
    """Une COPIE des stats de la fiche, complétée des modificateurs
    provisoires enregistrés pour elle. Rend `(stats, ids appliqués)`.

    Copie et non mutation : une valeur provisoire n'entre jamais dans
    `rpg.player.stats` — elle ne vit que dans `rpg.provisoire`, où
    l'entre-deux (#97) la relira pour l'entériner ou la rejeter."""
    copie = dict(stats) if isinstance(stats, dict) else {}
    poses: list[str] = []
    for ident, e in entrees(rpg).items():
        t = e.get("trou") if isinstance(e.get("trou"), dict) else {}
        if fiche_canon(t.get("fiche")) != fiche_canon(slug):
            continue
        champ = champ_canon(t.get("champ"))
        if champ in CHAMPS_FICHE or champ in copie:
            continue            # un champ de combat, ou déjà sur la fiche
        n = entier(e.get("valeur"))
        if n is None:
            continue
        copie[champ] = n
        poses.append(ident)
    return copie, poses


# --- matière du dossier ------------------------------------------------------

def resume_scene(store) -> dict:
    """Le résumé MÉCANIQUE de la scène courante — chiffres et slugs, aucune
    prose : le juge tranche sur des nombres, pas sur une ambiance (et le
    dossier ne fuit pas la fiction hors de la partie)."""
    from . import validator as validator_mod
    state = store.world_state()
    rpg = state.get("rpg") if isinstance(state.get("rpg"), dict) else {}
    joueur = rpg.get("player") if isinstance(rpg.get("player"), dict) else {}
    temps = state.get("time") if isinstance(state.get("time"), dict) else {}
    ennemis = rpg.get("enemies") if isinstance(rpg.get("enemies"), dict) else {}
    return {
        "tour": len(store.turns()),
        "lieu": validator_mod.current_location(state),
        "temps": {"day": temps.get("day"), "phase": temps.get("phase")},
        "joueur": {"hp": joueur.get("hp"), "hp_max": joueur.get("hp_max"),
                   "level": joueur.get("level"),
                   "conditions": list(joueur.get("conditions") or [])},
        "ennemis": {slug: {"hp": (e or {}).get("hp"),
                           "hp_max": (e or {}).get("hp_max")}
                    for slug, e in ennemis.items() if isinstance(e, dict)},
        "dernier_jet": rpg.get("last_check"),
    }


def table_repli(store, trou: dict | None = None) -> list[dict]:
    """Les entrées de la table de repli livrée avec la partition, lues sur
    `repli.md` du save (une entrée par slug, champs `valeur:` et `source:`).

    Pas de `repli.md`, ou aucune entrée portant `valeur:` → `[]`. Le
    converter qui peuple ce fichier est hors périmètre (#105). Les entrées
    qui parlent du trou passent devant ; le reste suit, borné à
    `REPLI_MAX`."""
    try:
        brutes = store.entries("repli.md")
    except Exception:  # noqa: BLE001 — un repli.md illisible n'arrête pas la partie
        return []
    lues = []
    for e in brutes:
        attrs = {normaliser(k): v for k, v in (e.attrs or {}).items()}
        if not str(attrs.get("valeur") or "").strip():
            continue
        lues.append({"slug": e.slug, "titre": e.title,
                     "valeur": str(attrs["valeur"]).strip(),
                     "source": str(attrs.get("source") or "").strip()})
    cible = {normaliser(champ_canon((trou or {}).get("champ"))),
             normaliser(fiche_canon((trou or {}).get("fiche"))),
             normaliser(id_trou(trou)) if trou else ""} - {""}

    def _parle_du_trou(entree: dict) -> int:
        mots = set(normaliser(entree["slug"]).split("_"))
        mots.add(normaliser(entree["slug"]))
        return 0 if mots & cible else 1

    lues.sort(key=_parle_du_trou)
    return lues[:REPLI_MAX]


_LIGNE_VOCAB = re.compile(r"^\|\s*`([^`]+)`\s*\|([^|]*)\|([^|]*)\|")

#: Ce que sollicite mécaniquement chaque champ de fiche, en slugs du
#: vocabulaire fermé de `docs/couverture-moteur.md` §4.
_REGLES_PAR_CHAMP: dict[str, tuple[str, ...]] = {
    "ca": ("combat.attack.legacy",),
    "attaque_bonus": ("combat.attack.legacy",),
    "degats": ("combat.damage.legacy", "combat.attack.legacy"),
    "pv": ("combat.attack.legacy", "condition.downed"),
}


def _chemin_couverture() -> Path:
    return (Path(__file__).resolve().parents[1] / "docs"
            / "couverture-moteur.md")


def vocabulaire(chemin: Path | None = None) -> list[dict]:
    """Le vocabulaire fermé de règles sollicitées de
    `docs/couverture-moteur.md` §4, lu ligne à ligne : [{slug, statut,
    reference}]. Document absent → `[]` (le dossier reste valide, il porte
    juste une section vide)."""
    p = chemin or _chemin_couverture()
    try:
        texte = p.read_text(encoding="utf-8")
    except OSError:
        return []
    _debut = texte.find("## 4.")
    if _debut < 0:
        return []
    corps = texte[_debut:]
    fin = corps.find("\n## ", 3)
    corps = corps if fin < 0 else corps[:fin]
    out = []
    for ligne in corps.splitlines():
        m = _LIGNE_VOCAB.match(ligne.strip())
        if not m:
            continue
        out.append({"slug": m.group(1).strip(),
                    "statut": m.group(2).strip(),
                    "reference": m.group(3).strip()})
    return out


def regles_concernees(trou: dict, chemin: Path | None = None) -> list[dict]:
    """L'extrait du vocabulaire fermé que ce trou sollicite : les slugs liés
    au champ visé, plus ceux dont un segment est nommé par le champ ou le
    contexte. Borné à `REGLES_MAX` — un dossier n'embarque pas la carte
    entière."""
    champ = champ_canon(trou.get("champ"))
    mots = set(normaliser(f"{trou.get('champ')} {trou.get('contexte')}").split("_"))
    mots.discard("")
    vises = set(_REGLES_PAR_CHAMP.get(champ, ()))
    if normaliser(trou.get("type")) == "nombre":
        vises.add("check.legacy")
    out = []
    for regle in vocabulaire(chemin):
        segments = set(normaliser(regle["slug"]).split("_"))
        if regle["slug"] in vises or (segments & mots):
            out.append(regle)
        if len(out) >= REGLES_MAX:
            break
    return out
