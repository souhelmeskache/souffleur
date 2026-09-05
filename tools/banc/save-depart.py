"""tools/banc/save-depart.py — fabrique la save de DÉPART gelée du banc de
nuit (Issue #275, I-465).

Constat fermé (03/09) : `nuit.sh` copiait jusqu'ici `beyond-the-vale-of-
madness` telle qu'elle est dans `saves_dir()` — une partie JOUÉE (tour 28,
mort du personnage, prolongée en post-mortem). Chaque « nuit » démarrait donc
APRÈS la fin du module au lieu du début : la mesure « tours sans craquement »
ne mesurait pas un début de module, et le module DKS source était spoilé par
la seule lecture de la save.

Ce script construit une fois une save FRAÎCHE (tour 0, scène d'ouverture,
transcript.md vierge) depuis le SCÉNARIO déjà enregistré (celui dont a été
instanciée la save jouée — `coderain/converter/install.py`), au moyen de
`coderain/templates.py::new_save` (jamais réécrit — appelé via
`SaveLibrary`/`Library`, l'API de production). La fixture personnage (#257,
`bench/fixtures/personnage-banc.py`) y est ensuite appliquée : le personnage
créé (Mika Thorne, arme + armure) existe dès le tour 0, mais aucun tour n'a
encore été joué. Rangée hors dépôt, sous `saves_dir()`, comme n'importe quelle
autre save (D-224) — jamais commitée.

Idempotent en apparence trompeuse : ce script REFUSE d'écraser une save déjà
présente au slug cible, sauf `--force` (une save de départ n'est fabriquée
qu'une fois ; si elle a été jouée par erreur, `--force` la reconstruit à
neuf plutôt que de continuer sur une save entamée).

Usage :
    python tools/banc/save-depart.py
        [--slug banc-depart-beyond-the-vale-of-madness]
        [--from-save beyond-the-vale-of-madness]
        [--scenario <slug scénario, déduit de --from-save par défaut>]
        [--profil guerrier] [--force]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# Force UTF-8 sur stdout/stderr quel que soit le terminal (Issue #279) : sous
# Windows, sys.stdout/stderr sont en cp1252 hors terminal UTF-8 explicite.
# `reconfigure` peut lever si le flux n'en dispose pas (ex. capturé par un
# test) — sans conséquence, le flux garde alors son encodage d'origine.
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain import config, templates  # noqa: E402
from coderain.memory import Library, MemoryStore  # noqa: E402

DEFAULT_SLUG = "banc-depart-beyond-the-vale-of-madness"
DEFAULT_FROM_SAVE = "beyond-the-vale-of-madness"
DEFAULT_PROFIL = "guerrier"

# Le nom de fichier de la fixture porte un tiret : pas un module importable
# tel quel (même convention que tests/test-fixture-personnage-banc-i257.py).
_FIXTURE_PATH = ROOT / "bench" / "fixtures" / "personnage-banc.py"
_spec = importlib.util.spec_from_file_location("personnage_banc", _FIXTURE_PATH)
personnage_banc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(personnage_banc)


def _scenario_slug_depuis(save_slug: str, root: Path) -> str | None:
    """Le slug de scénario enregistré dans meta.json de la save `save_slug`
    (celle dont la save de départ doit reprendre le monde), ou None si cette
    save ou son meta.json est introuvable."""
    meta_path = config.saves_dir(root) / save_slug / "meta.json"
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — meta.json illisible = pas de scénario
        return None
    scenario = data.get("scenario") or ""
    return scenario or None


def fabriquer(slug: str = DEFAULT_SLUG, from_save: str = DEFAULT_FROM_SAVE,
              scenario: str | None = None, profil: str = DEFAULT_PROFIL,
              force: bool = False, root: Path | None = None) -> dict:
    """Fabrique la save de départ `slug`. `root` est la racine `Library`
    (défaut : la racine de production `coderain.config.ROOT` — un test passe
    un dossier temporaire, D-109/D-178). Rend
    {"status": "created"|"refused", "message": str, "save_dir": str}."""
    root = Path(root) if root is not None else config.ROOT
    lib = Library(root)
    dest_dir = lib.saves.dir(slug)
    if dest_dir.exists() and not force:
        return {"status": "refused", "save_dir": str(dest_dir),
                "message": f"REFUS : la save '{slug}' existe déjà "
                           f"({dest_dir}) — relance avec --force pour la "
                           f"reconstruire à neuf."}

    scenario_slug = scenario or _scenario_slug_depuis(from_save, root)
    if not scenario_slug:
        return {"status": "refused", "save_dir": str(dest_dir),
                "message": f"REFUS : scénario introuvable — ni --scenario "
                           f"fourni, ni de save '{from_save}' avec un "
                           f"meta.json exploitable."}
    if not lib.scenarios.exists(scenario_slug):
        return {"status": "refused", "save_dir": str(dest_dir),
                "message": f"REFUS : le scénario '{scenario_slug}' est "
                           f"introuvable dans {lib.scenarios.root}."}

    if dest_dir.exists():   # --force sur une save déjà présente
        import shutil
        shutil.rmtree(dest_dir)

    scen_dir = lib.scenarios.dir(scenario_slug)
    templates.new_save(dest_dir, scen_dir, slug, scenario_slug,
                       rpg_enabled=True, mode="rpg",
                       instructions_dir=lib.instructions_dir)
    # Genesis record (même geste que SaveLibrary.create, memory.py) : l'event
    # log doit remonter jusqu'au tout début pour qu'un branch puisse rejouer
    # depuis zéro.
    store = MemoryStore(dest_dir, lib.instructions_dir, scen_dir)
    store.append_event_log({"turn": 0, "env": {}})

    fixture_res = personnage_banc.install(dest_dir, profil=profil)
    if fixture_res["status"] not in ("installed", "unchanged"):
        return {"status": "refused", "save_dir": str(dest_dir),
                "message": f"REFUS : fixture personnage en échec sur la "
                           f"save fraîche — {fixture_res['message']}"}

    verdict = verifier(dest_dir, profil=profil)
    if verdict["status"] != "ok":
        return {"status": "refused", "save_dir": str(dest_dir),
                "message": f"REFUS : vérification post-fabrication en échec "
                           f"— {verdict['message']}"}

    return {"status": "created", "save_dir": str(dest_dir),
            "message": f"save de départ '{slug}' fabriquée depuis le "
                       f"scénario '{scenario_slug}' ({dest_dir})."}


def verifier(save_dir: Path, profil: str = DEFAULT_PROFIL) -> dict:
    """Vérifie SUR DISQUE le contrat de la save de départ : tour 0 (aucun
    tour dans transcript.md — la scène d'ouverture n'a pas encore été jouée,
    elle reste à établir par le MJ au premier `go`), personnage présent avec
    arme et armure équipées. Rend {"status": "ok"|"refused", "message": str}.
    """
    store = MemoryStore(save_dir)
    nb_tours = len(store.turns())
    if nb_tours != 0:
        return {"status": "refused",
                "message": f"tour {nb_tours} (attendu 0) — ce n'est pas une "
                           f"save de départ"}

    profile = personnage_banc.PROFILES.get(profil)
    if profile is None:
        return {"status": "refused", "message": f"profil inconnu '{profil}'"}
    entry = personnage_banc._player_entry(store)
    rpg = store.rpg_state()
    if not personnage_banc._is_installed(entry, rpg, profile):
        return {"status": "refused",
                "message": "personnage absent ou incomplet (profil "
                           f"'{profil}' non installé tel quel)"}

    return {"status": "ok", "message": f"tour 0, personnage '{profile['name']}'"
                                        f" présent (arme + armure équipées)."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fabrique la save de DÉPART gelée du banc de nuit "
                    "(tour 0, personnage créé — Issue #275/I-465).")
    parser.add_argument("--slug", default=DEFAULT_SLUG,
                        help=f"slug de la save de départ à créer (défaut : {DEFAULT_SLUG})")
    parser.add_argument("--from-save", default=DEFAULT_FROM_SAVE,
                        help="save existante dont on reprend le scénario, "
                             f"si --scenario n'est pas donné (défaut : {DEFAULT_FROM_SAVE})")
    parser.add_argument("--scenario", default=None,
                        help="slug de scénario explicite (déduit de --from-save par défaut)")
    parser.add_argument("--profil", default=DEFAULT_PROFIL,
                        choices=sorted(personnage_banc.PROFILES),
                        help=f"profil de personnage (défaut : {DEFAULT_PROFIL})")
    parser.add_argument("--force", action="store_true",
                        help="reconstruit à neuf une save de départ déjà présente")
    args = parser.parse_args(argv)

    result = fabriquer(args.slug, args.from_save, args.scenario, args.profil,
                       args.force)
    # stdout forcé en UTF-8 en tête de fichier (#279) : plus besoin de repli
    # ASCII, le message passe quel que soit le terminal.
    print(result["message"])
    return 0 if result["status"] == "created" else 2


if __name__ == "__main__":
    raise SystemExit(main())
