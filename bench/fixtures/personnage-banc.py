"""Fixture de banc — un personnage synthétique de niveau 1 installé par script
dans un save (Issue #257, prérequis du banc de nuit #201).

Pourquoi (arbitrage Souhel du 02/09, cité dans l'Issue) : le save du banc
`beyond-the-vale-of-madness` n'a jamais eu de personnage — `player.md` au
gabarit vierge, `state.json` aux défauts du module (stats au vocabulaire 5e
générique `strength/dexterity/constitution/intelligence/wisdom/charisma`, pas
celui que lit le moteur), `items.md` vide. Aucun outil de création de
personnage n'existe encore (chantier #102, D-219 — reste le vrai chemin,
cette fixture ne le remplace pas). Principe I-226 (#120) : des FIXTURES, pas
un éditeur de save — ce script installe, il ne s'ouvre jamais en édition
manuelle.

Personnage 100% inventé (D-109) : nom, visuel, mentalité, buts génériques et
neutres, sans lien avec quelque module que ce soit. Un seul profil pour
l'instant : `guerrier`.

Vocabulaire du moteur (cf. `coderain/modules/rpg.py::derived_combat`,
`sidecar.DEFAULT_CFG["stats"]`) : les stats sont déjà des MODIFICATEURS, pas
des scores 5e bruts — `agility` fait office de DEX, `strength` de FOR. Ce
script écrit aussi `constitution` (citée dans l'Issue au titre du vocabulaire
attendu) même si `derived_combat` ne la lit pas aujourd'hui — ni erreur ni
gain, une clé de plus dans le dict `stats`.

Le script écrit `player.md` ET `state.json` de façon cohérente en un seul
passage (au lieu des deux sources désynchronisées constatées sur #102) :
- `player.md` : l'entrée `## <nom>  {#player}` avec `stats:` dans le
  vocabulaire moteur, un `status:` non vide, et les champs prose remplis ;
- `items.md` : une arme et une armure, avec les champs que lit
  `derived_combat` (`degats:`/`stat:` pour l'arme, `armure:`/`dex_max:` pour
  l'armure — cf. docs/combat-derive-i463.md) ;
- `state.json` (`rpg.player.stats/hp/hp_max/level/conditions` et
  `rpg.inventory`) — même forme que produirait `inventory_add`/
  `inventory_equip` ({slug: {qty, equipped}}), écrite par l'unique point
  d'écriture `MemoryStore.set_world_state` (D-141, guard_world_state inclus).

Refuse d'écraser un save dont `player.md` n'est plus au gabarit vierge, sauf
`--force`. Idempotent : rejoué sur un save déjà installé par CE script (même
profil), il ne change rien (sortie 0, message) — ni un troisième état
« modifié autrement » ni un gabarit vierge.

Usage :
    python bench/fixtures/personnage-banc.py <chemin-du-save> [--profil guerrier] [--force]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.memory import Entry, MemoryStore  # noqa: E402
from coderain.templates import slugify  # noqa: E402

# --- profil "guerrier" (D-109 : 100% inventé, générique, neutre) -----------
_PROSE_FIELDS = ("Visual", "Mentality", "Voice", "Skills")
_BODY_FIELDS = ("Identity", "Goals", "Inventory")

WEAPON_SLUG = "epee-courte-de-banc"
ARMOR_SLUG = "cotte-de-mailles-de-banc"

PROFILES: dict[str, dict] = {
    "guerrier": {
        "name": "Mika Thorne",
        "status": "prête au combat, armée et armurée",
        "skills": "mêlée (strength)",
        "stats": {
            "strength": 3, "agility": 1, "constitution": 2,
            "intelligence": 0, "knowledge": 0, "willpower": 1, "charisma": 0,
        },
        "hp_max": 20,
        "visual": "Silhouette trapue, cuir clouté sous la cotte, cheveux ras.",
        "mentality": "Directe, protège le groupe avant tout, méfiante des ruses.",
        "voice": "Phrases courtes. « On avance, ou on recule — pas de milieu. »",
        "skills_prose": "Combat rapproché, résistance à la fatigue.",
        "identity": "Combattante itinérante sans attache connue — personnage "
                    "de fixture (D-109), sans lien avec un module joué.",
        "goals": "Tenir la ligne, ramener le groupe entier.",
        "inventory_prose": "Épée courte, cotte de mailles.",
        "items": {
            WEAPON_SLUG: {
                "title": "Épée courte de banc",
                "attrs": {"degats": "1d8+2", "stat": "strength",
                          "status": "held by you"},
                "body": "Objet synthétique de fixture de banc (Issue #257) — "
                        "aucun lien avec un module joué.",
            },
            ARMOR_SLUG: {
                "title": "Cotte de mailles de banc",
                "attrs": {"armure": "14", "dex_max": "2",
                          "status": "held by you"},
                "body": "Objet synthétique de fixture de banc (Issue #257) — "
                        "aucun lien avec un module joué.",
            },
        },
    },
}


def _player_entry(store: MemoryStore):
    """La (première) entrée de `player.md`, ou None si le fichier est absent
    ou malformé."""
    try:
        entries = store.entries("player.md")
    except Exception:  # noqa: BLE001 — fichier illisible = pas d'entrée
        return None
    return entries[0] if entries else None


def _is_vierge(entry) -> bool:
    """Le gabarit vierge (`templates.FILE_SKELETONS["player.md"]`) : `status`
    vide et tous les champs prose (Visual/Mentality/Voice/Skills/Identity/
    Goals/Inventory) vides. `stats`/`skills` ne comptent pas : `_sync_player_stats`
    peut avoir rempli `stats` aux défauts du module sans que ce soit un
    personnage installé."""
    if entry is None:
        return False
    if str(entry.attrs.get("status", "")).strip():
        return False
    body = entry.body
    for label in _PROSE_FIELDS:
        m = re.search(rf"^\*\*{label}:\*\*[ \t]*(.*)$", body, re.MULTILINE)
        if m and m.group(1).strip():
            return False
    for label in _BODY_FIELDS:
        m = re.search(rf"^{label}:[ \t]*(.*)$", body, re.MULTILINE)
        if m and m.group(1).strip():
            return False
    return True


def _is_installed(entry, rpg: dict, profile: dict) -> bool:
    """Ce PROFIL, déjà installé tel quel (idempotence)."""
    if entry is None or entry.title != profile["name"]:
        return False
    if str(entry.attrs.get("status", "")).strip() != profile["status"]:
        return False
    p_stats = (rpg.get("player") or {}).get("stats") or {}
    if {k: int(v) for k, v in p_stats.items()} != dict(profile["stats"]):
        return False
    inv = rpg.get("inventory") or {}
    for slug in profile["items"]:
        held = inv.get(slug)
        if not isinstance(held, dict) or not held.get("equipped") \
                or int(held.get("qty", 0)) < 1:
            return False
    return True


def _render_player_body(profile: dict) -> str:
    return (
        f"**Visual:** {profile['visual']}\n"
        f"**Mentality:** {profile['mentality']}\n"
        f"**Voice:** {profile['voice']}\n"
        f"**Skills:** {profile['skills_prose']}\n\n"
        f"Identity: {profile['identity']}\n"
        f"Goals: {profile['goals']}\n"
        f"Inventory: {profile['inventory_prose']}\n"
    )


def install(save_path: Path, profil: str = "guerrier",
           force: bool = False) -> dict:
    """Installe le profil `profil` dans le save à `save_path`. Rend
    {"status": "installed"|"unchanged"|"refused", "message": str}."""
    if profil not in PROFILES:
        return {"status": "refused",
                "message": f"profil inconnu '{profil}' (disponibles : "
                           f"{', '.join(sorted(PROFILES))})"}
    profile = PROFILES[profil]
    if not (save_path / "player.md").exists() or not (save_path / "state.json").exists():
        return {"status": "refused",
                "message": f"'{save_path}' ne ressemble pas à un save "
                           f"(player.md/state.json absents)"}

    store = MemoryStore(save_path)
    entry = _player_entry(store)
    rpg = store.rpg_state()

    if _is_installed(entry, rpg, profile):
        return {"status": "unchanged",
                "message": f"déjà installé (profil '{profil}') — rien à faire"}
    if not _is_vierge(entry) and not force:
        return {"status": "refused",
                "message": "player.md n'est plus au gabarit vierge (un "
                           "personnage ou une partie jouée l'occupe déjà) — "
                           "relance avec --force pour écraser"}

    # --- player.md ----------------------------------------------------
    stats_line = ", ".join(f"{k} {v}" for k, v in profile["stats"].items())
    player_entry = Entry(
        title=profile["name"], slug="player", importance=5,
        attrs={"status": profile["status"], "skills": profile["skills"],
              "stats": stats_line},
        body=_render_player_body(profile))
    store.upsert_entry("player.md", player_entry)

    # --- items.md -------------------------------------------------------
    for slug, spec in profile["items"].items():
        store.upsert_entry("items.md", Entry(
            title=spec["title"], slug=slug, importance=2,
            attrs=dict(spec["attrs"]), body=spec["body"]))

    # --- state.json (rpg.player + rpg.inventory, D-141 seul point d'écriture) --
    rpg = store.rpg_state()
    player = rpg.setdefault("player", {})
    player["stats"] = dict(profile["stats"])
    player["level"] = 1
    player["hp"] = player["hp_max"] = profile["hp_max"]
    player.setdefault("mana", 5)
    player.setdefault("mana_max", 5)
    player.setdefault("xp", 0)
    player["conditions"] = []
    player.setdefault("abilities", [])
    player.setdefault("titles", [])
    inv = rpg.setdefault("inventory", {})
    for slug in profile["items"]:
        inv[slug] = {"qty": 1, "equipped": True}
    store.set_rpg_state(rpg)

    return {"status": "installed",
            "message": f"personnage de banc installé (profil '{profil}') "
                       f"sur '{save_path}'"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Installe un personnage synthétique de niveau 1 dans un "
                    "save (fixture de banc, Issue #257 — pas la brique #102).")
    parser.add_argument("chemin_du_save", type=Path,
                        help="Dossier du save (ex. saves/mon-save)")
    parser.add_argument("--profil", default="guerrier", choices=sorted(PROFILES),
                        help="Profil de personnage à installer (défaut : guerrier)")
    parser.add_argument("--force", action="store_true",
                        help="Écrase un player.md qui n'est plus au gabarit vierge")
    args = parser.parse_args(argv)

    result = install(args.chemin_du_save, args.profil, args.force)
    try:
        print(result["message"])
    except UnicodeEncodeError:  # console non-UTF8 (cmd.exe par défaut) — ASCII de secours
        print(result["message"].encode("ascii", "replace").decode("ascii"))
    return 0 if result["status"] in ("installed", "unchanged") else 2


if __name__ == "__main__":
    raise SystemExit(main())
