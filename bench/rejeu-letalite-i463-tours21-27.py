"""Rejeu de mesure — I-463 lane 2 (Issue #237, D-274 §3).

Au banc `20260831-202617`, tours 21-27, le Director a résolu 7 attaques
contre l'« ice-fiend » du module *Beyond the Vale of Madness* avec des
nombres INVENTÉS ad hoc (`resolve_check(ability_scores={"dex":20})` pour
reconstituer le bonus d'attaque du fiend, `ability_scores={"str":10}` pour le
joueur, CA du joueur assumée à 10 « sans armure ») — aucun outil de l'époque
ne lisait les deux fiches de bout en bout. #236 a livré `attack(attacker,
target)` + `derived_combat` (D-274 §1 : CA/bonus dérivés de la fiche, jamais
inventés ; un nombre absent est un refus, pas un défaut silencieux). Ce
script rejoue les mêmes 7 tours via `attack`, avec les VRAIES valeurs
reconstituées du save `beyond-the-vale-of-madness` (corpus privé
`ttrpg-corpus`, hors périmètre de ce dépôt — D-109/D-206), puis mesure sur
1000 graines la létalité réelle de ce combat pour comparaison au banc.

Fixture 100% synthétique dérivée de ces valeurs (D-109) : le nom de la
créature du module n'apparaît nulle part ici — seuls ses champs mécaniques
`ca`/`pv`/`attaque_bonus`/`degats`, DÉJÀ publiés en clair dans le corps de
l'Issue #237, sont repris sous un nom fictif.

## Reconstitution du tour 21 (voir docs/letalite-rejeu-tours-21-27.md)

- Créature (record réel du converter, cité dans l'Issue #237) : ca=15,
  pv=28, attaque_bonus=+5, degats="9 (1d8+3) slashing".
- Joueur (`rpg.player` réel du save, PAS le gabarit `player.md` vide) :
  stats {strength:0, agility:1, ...}, level 1, hp 20/20, `inventory: {}` —
  AUCUNE arme équipée. `derived_combat` en tire CA=11 (10 + mod agility 1)
  et un bonus d'attaque à mains nues de +2 (mod FOR 0 + maîtrise niveau 1),
  mais AUCUN dé de dégâts (`degats` vide sans arme) : `attack` refuse toute
  attaque du joueur — c'est le résultat central de ce rejeu (D-274 §1).

Verdicts mécaniques (D-134) : égalité numérique / présence de sous-chaîne,
jamais une lecture de qualité — même discipline que
`tests/test-element-attaque-i463.py`.
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.memory import Entry, Library
from coderain.modules import rpg as rpg_mod

import mcp_server

# --- fixture synthétique dérivée des vraies valeurs (D-109/D-206) ----------
# Créature : mêmes champs mécaniques que le record réel du module, nom
# fictif. Le joueur : mêmes stats/niveau/inventaire que le VRAI
# `rpg.player` du save (state.json), pas le gabarit `player.md` (vide,
# jamais rempli — voir le constat dans le livrable).
CREATURE_SLUG = "brute-des-glaces-banc"
CREATURE_ATTRS = {
    "ca": "15", "pv": "28", "attaque_bonus": "+5",
    "degats": "9 (1d8+3) slashing",
}
PLAYER_STATS = {
    "strength": 0, "agility": 1, "intelligence": 0, "knowledge": 1,
    "willpower": 1, "charisma": 0, "dexterity": 0, "constitution": 0,
    "wisdom": 0,
}
PLAYER_LEVEL = 1
PLAYER_HP_MAX = 20
REAL_SAVE_SEED = 1079851431   # rpg.seed du save réel — fil de continuité,
                              # pas une reproduction bit-à-bit du banc (les
                              # 7 tours du banc n'ont jamais consommé ce
                              # compteur : ils passaient par resolve_check/
                              # roll_damage ad hoc, hors discipline nonce).


def _make_store():
    root = os.path.join(tempfile.gettempdir(), "rejeu_letalite_i463")
    if os.path.exists(root):
        shutil.rmtree(root)
    lib = Library(root)
    slug = lib.saves.create(
        "RejeuLetaliteI463", mode="rpg",
        premise="Rejeu de mesure I-463 lane 2, D-109/D-206 — fixture "
                "synthétique dérivée du save réel, aucun matériau de "
                "campagne.")
    store = lib.store(slug)
    assert store.mode() == "rpg" and store.rpg_enabled()
    store.upsert_entry("characters.md", Entry(
        title="Brute des glaces (banc)", slug=CREATURE_SLUG, importance=3,
        attrs=dict(CREATURE_ATTRS),
        body="Fixture synthétique — mêmes champs mécaniques que le record "
             "réel cité dans l'Issue #237, nom fictif (D-109)."))
    mcp_server._engine = None
    mcp_server._store = store
    mcp_server._slug = slug
    mcp_server._last_applied_events = None
    return store


def _reset_player(store, *, seed, hp=PLAYER_HP_MAX, enemies=None):
    rpg = store.rpg_state()
    p = rpg.setdefault("player", {})
    p["stats"] = dict(PLAYER_STATS)
    p["level"] = PLAYER_LEVEL
    p["hp"], p["hp_max"] = hp, PLAYER_HP_MAX
    p["conditions"] = []
    p["death_saves"] = {"successes": 0, "failures": 0}
    rpg["inventory"] = {}          # vrai save : aucune arme équipée
    rpg["enemies"] = dict(enemies or {})
    rpg["seed"], rpg["rolls"] = seed, 0
    store.set_rpg_state(rpg)
    return rpg


# --- partie 1 : rejeu littéral des tours 21-27 via `attack`, seed fixe -----
def rejeu_tours_21_27() -> list[dict]:
    """Rejoue la séquence réelle (fiend/joueur/fiend/joueur/... — tour 21
    d'abord le fiend, tour 22 le joueur riposte, etc., cf. tour-21.md à
    tour-27.md) via `attack`, avec la vraie fiche. Rend un tour de rejeu
    par tour banc, y compris toute erreur de refus."""
    store = _make_store()
    _reset_player(store, seed=REAL_SAVE_SEED)
    # séquence réelle : impair = fiend attaque le joueur, pair = joueur
    # attaque la créature (tours 21-27, cf. les journaux tour-NN.md).
    sequence = [
        (21, CREATURE_SLUG, "player"),
        (22, "player", CREATURE_SLUG),
        (23, CREATURE_SLUG, "player"),
        (24, "player", CREATURE_SLUG),
        (25, CREATURE_SLUG, "player"),
        (26, "player", CREATURE_SLUG),
        (27, CREATURE_SLUG, "player"),
    ]
    out = []
    for tour, attacker, target in sequence:
        res = mcp_server.attack(attacker=attacker, target=target)
        out.append({"tour": tour, "attacker": attacker, "target": target,
                    "result": res})
        # un `downed` du joueur arrête le rejeu, comme au banc (tour 27).
        p = store.rpg_state().get("player") or {}
        if "downed" in (p.get("conditions") or []) or "dead" in (p.get("conditions") or []):
            break
    return out


# --- partie 2 : mesure statistique sur 1000 graines -------------------------
# Réplique exactement l'algorithme de `attack()` (roll_check puis, sur
# touche, roll_damage — même discipline seed+nonce) sans repasser par un
# store à chaque graine : 1000 graines * ~4 jets reste instantané, et
# `rpg_mod.roll_check`/`roll_damage` SONT les fonctions que `attack` appelle
# — aucune divergence de logique avec le rejeu de la partie 1 (validé par
# `_verifie_coherence_avec_attack` plus bas).
FIEND_ATTACK_BONUS = 5
FIEND_DAMAGE = "9 (1d8+3) slashing"
PLAYER_AC = 11        # derived_combat(agility=1) : 10 + 1
MAX_ROUNDS = 40        # plafond du banc (« jouer ... 40 tours max »)


def _simulate_one(seed: int) -> dict:
    """Un combat : le fiend attaque, le joueur tente de riposter (refus
    systématique — pas d'arme dans la vraie fiche), en alternance, jusqu'à
    ce que le joueur tombe à 0 PV (`downed`) ou que le plafond de tours du
    banc soit atteint."""
    hp = PLAYER_HP_MAX
    nonce = 0
    fiend_hits = fiend_attacks = 0
    total_damage = 0
    player_attempts = 0
    tours = 0
    downed = False
    for round_no in range(1, MAX_ROUNDS + 1):
        # tour du fiend (impair dans la numérotation banc : 21, 23, 25...)
        tours += 1
        fiend_attacks += 1
        nonce += 1
        hit = rpg_mod.roll_check(FIEND_ATTACK_BONUS, PLAYER_AC, seed, nonce)
        if hit["success"]:
            fiend_hits += 1
            nonce += 1
            dmg = rpg_mod.roll_damage(FIEND_DAMAGE, seed, nonce)
            hp = max(0, hp - dmg["total"])
            total_damage += dmg["total"]
        if hp <= 0:
            downed = True
            break
        # tour du joueur : `attack` refuse AVANT tout jet (missing degats) —
        # aucun nonce consommé, aucun aléa (D-274 §1).
        tours += 1
        player_attempts += 1
    return {
        "seed": seed, "downed": downed, "tours_to_downed": tours if downed else None,
        "fiend_attacks": fiend_attacks, "fiend_hits": fiend_hits,
        "total_damage_taken": total_damage, "player_attempts": player_attempts,
        "hp_end": hp,
    }


def mesure_1000_graines(n: int = 1000) -> dict:
    runs = [_simulate_one(seed) for seed in range(n)]
    downed_runs = [r for r in runs if r["downed"]]
    hits = sum(r["fiend_hits"] for r in runs)
    attacks = sum(r["fiend_attacks"] for r in runs)
    avg_damage_per_hit = (sum(r["total_damage_taken"] for r in runs) / hits
                          if hits else 0.0)
    avg_damage_per_attack = (sum(r["total_damage_taken"] for r in runs) / attacks
                             if attacks else 0.0)
    tours_medians = [r["tours_to_downed"] for r in downed_runs]
    return {
        "n": n,
        "fiend_hit_chance": hits / attacks if attacks else 0.0,
        "player_hit_chance": 0.0,   # refus systématique, aucun jet (D-274 §1)
        "player_attack_attempts_refused": sum(r["player_attempts"] for r in runs),
        "avg_damage_per_hit": avg_damage_per_hit,
        "avg_damage_per_fiend_attack": avg_damage_per_attack,
        "median_tours_to_downed": (statistics.median(tours_medians)
                                    if tours_medians else None),
        "downed_rate": len(downed_runs) / n,
        "creature_death_rate": 0.0,   # jamais : le joueur ne peut jamais toucher
        "player_win_rate": 0.0,
    }


def _verifie_coherence_avec_attack(rejeu: list[dict]) -> None:
    """Sanity : le rejeu littéral (partie 1, via `attack`) et la boucle de
    mesure (partie 2, via roll_check/roll_damage directs) doivent voir
    EXACTEMENT les mêmes refus/touches sur les mêmes graines/nonces — sinon
    la mesure statistique ne serait pas fidèle à l'outil réellement rejoué."""
    fiend_hit_tours = [t for t in rejeu if t["attacker"] == CREATURE_SLUG]
    player_tours = [t for t in rejeu if t["attacker"] == "player"]
    assert player_tours, "aucun tour joueur rejoué"
    for t in player_tours:
        err = str((t["result"] or {}).get("error", ""))
        assert "missing degats" in err, (
            f"tour {t['tour']}: refus attendu 'missing degats', reçu {t['result']!r}")
    assert fiend_hit_tours, "aucun tour fiend rejoué"
    for t in fiend_hit_tours:
        r = t["result"]
        assert "error" not in r, f"tour {t['tour']}: refus inattendu {r!r}"
        assert r["target_ac"] == PLAYER_AC, (
            f"tour {t['tour']}: CA joueur relue {r['target_ac']} != {PLAYER_AC} attendu")
        assert r["attack_bonus"] == FIEND_ATTACK_BONUS


if __name__ == "__main__":
    print("=== Partie 1 : rejeu littéral des tours 21-27 (attack, seed fixe) ===")
    rejeu = rejeu_tours_21_27()
    for t in rejeu:
        r = t["result"]
        if "error" in r:
            print(f"tour {t['tour']:2d} {t['attacker']:>20s} -> {t['target']:<20s} : "
                  f"REFUS — {r['error']}")
        else:
            print(f"tour {t['tour']:2d} {t['attacker']:>20s} -> {t['target']:<20s} : "
                  f"roll={r['roll']} total={r['total']} vs CA {r['target_ac']} "
                  f"hit={r['hit']} damage={(r.get('damage') or {}).get('total')}")
    _verifie_coherence_avec_attack(rejeu)
    print("\ncohérence rejeu <-> mesure statistique : OK\n")

    print("=== Partie 2 : mesure sur 1000 graines ===")
    m = mesure_1000_graines(1000)
    print(json.dumps(m, indent=2, ensure_ascii=False))

    assert m["player_hit_chance"] == 0.0
    assert m["creature_death_rate"] == 0.0
    assert m["player_win_rate"] == 0.0
    assert m["downed_rate"] == 1.0, (
        "le joueur devrait tomber dans les 40 tours sur les 1000 graines "
        f"(downed_rate={m['downed_rate']})")
    print("\nrejeu-letalite-i463-tours21-27: OK")
