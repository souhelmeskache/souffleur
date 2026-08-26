"""P-CONV-1 : formes de jugement des records (ancre_srd / delta_vs_ancre /
tokens_initial / persistent) + filet statblock_core. 100% synthétique
(D-109) : aucun matériau de module réel n'entre dans cette suite."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter import validate_form
from coderain.converter.aval import get_record, _split_front
from coderain.converter.emit import write_partition
from coderain.converter.ruletables import ConversionException, statblock_core
from coderain.converter.schemas import Manifest, Node, Partition, Record

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="0" * 64,
                    date_conversion="2026-08-26T00:00:00+00:00",
                    version_convertisseur="test")


def creature(stats_extra=None, **kw):
    stats = {"ca": 15, "pv": 7, "vitesse": "30 ft.",
             "attaque_bonus": 4, "degats": "1d6+2"}
    stats.update(stats_extra or {})
    return Record(kw.get("rid", "gob"), kw.get("classe", "creature"),
                  kw.get("nom", "Goblin"), stats, [(10, 20)],
                  tags=kw.get("tags"), transverse=kw.get("transverse"))


# 1 -- ancre_srd ---------------------------------------------------------------
section("ancre_srd : référence dataset, créature uniquement")
r = creature({"ancre_srd": "goblin-warrior"})
assert r.ancre_srd == "goblin-warrior"
try:
    Record("dar", "pnj", "Darek", {"role": "allié", "description_md": "x",
                                   "ancre_srd": "goblin-warrior"}, [(1, 2)])
    raise AssertionError("ancre_srd accepté hors creature")
except ValueError as e:
    assert "creature" in str(e), e
try:
    creature({"ancre_srd": "Goblin Warrior"})
    raise AssertionError("slug non kebab accepté")
except ValueError:
    pass

# 2 -- delta_vs_ancre ----------------------------------------------------------
section("delta_vs_ancre : variante documentée, jamais orpheline")
r = creature({"ancre_srd": "bat", "pv": 5,
              "delta_vs_ancre": {"pv": 5, "vitesse": "30 ft. (marche)"}},
             rid="forest-bat", nom="Forest Bat", tags=["variante-srd"])
assert r.delta_vs_ancre["pv"] == 5
try:
    creature({"delta_vs_ancre": {"pv": 5}})
    raise AssertionError("delta sans ancre accepté")
except ValueError as e:
    assert "ancre_srd" in str(e), e
try:
    creature({"ancre_srd": "bat", "delta_vs_ancre": {}})
    raise AssertionError("delta vide accepté")
except ValueError:
    pass

# 3 -- tokens_initial (E3) -----------------------------------------------------
section("tokens_initial : pose {node_id, count, placement_md} exacte")
r = creature({"tokens_initial": [{"node_id": "goblinbattle", "count": 3,
                                  "placement_md": "sur la carte"}]})
assert r.tokens_initial[0]["node_id"] == "goblinbattle"
for bad in ([{"node_id": "goblinbattle", "count": 3}],
            [{"node_id": "goblinbattle", "count": 0,
              "placement_md": "x"}],
            [{"node_id": "goblinbattle", "count": True,
              "placement_md": "x"}],
            [{"node_id": "goblinbattle", "count": 3, "placement_md": " "}],
            [{"node_id": "Goblinbattle", "count": 3, "placement_md": "x"}],
            [{"node_id": "gb", "count": 3, "placement_md": "x",
              "extra": 1}]):
    try:
        creature({"tokens_initial": bad})
        raise AssertionError(f"tokens_initial invalide accepté: {bad}")
    except ValueError:
        pass

# 4 -- persistent (E2) ---------------------------------------------------------
section("persistent : attribut déclaré présent dans les stats")
r = creature({"persistent": ["pv"]})
assert r.persistent_attrs == ["pv"]
try:
    creature({"persistent": ["morale"]})
    raise AssertionError("attribut persistant absent des stats accepté")
except ValueError as e:
    assert "morale" in str(e), e
try:
    creature({"persistent": []})
    raise AssertionError("persistent vide accepté")
except ValueError:
    pass

# 5 -- bout-en-bout : émission + relecture --------------------------------------
section("émission : front matter porteur, body mécanique pur, index flaggé")
tmp = Path(tempfile.mkdtemp(prefix="pconv1-records-"))
try:
    p = Partition(manifest())
    p.nodes.append(Node("goblinbattle", "scene", "GOBLINBATTLE",
                        "Place three tokens to represent the Goblins.",
                        "scene", anchors=[(100, 160)]))
    p.nodes.append(Node("throne-room", "scene", "THRONE",
                        "The Death Knight waits on his throne.",
                        "scene", anchors=[(170, 210)]))
    p.records.append(Record(
        "goblins", "creature", "Goblins",
        {"ca": 15, "pv": 7, "vitesse": "30 ft.", "attaque_bonus": 4,
         "degats": "1d6+2", "ancre_srd": "goblin-warrior",
         "tokens_initial": [{"node_id": "goblinbattle", "count": 3,
                             "placement_md": "sur la carte"}]},
        [(150, 200)]))
    p.records.append(Record(
        "death-knight", "creature", "Death Knight",
        {"ca": 15, "pv": 28, "vitesse": "30 ft.", "attaque_bonus": 5,
         "degats": "1d8+3", "persistent": ["pv"]},
        [(210, 260)], tags=["custom"]))
    write_partition(p, tmp)

    raw = (tmp / "records" / "goblins.md").read_text(encoding="utf-8")
    front, body = _split_front(raw)
    meta = json.loads(front)
    assert meta["ancre_srd"] == "goblin-warrior"
    assert [t["node_id"] for t in meta["tokens_initial"]] == ["goblinbattle"]
    stats_back = json.loads(body)
    assert "ancre_srd" not in stats_back and "tokens_initial" not in stats_back
    assert stats_back["ca"] == 15

    rec = get_record(tmp, "death-knight")
    assert rec["meta"]["persistent_attrs"] == ["pv"]
    assert "persistent" not in rec["stats"] and rec["stats"]["pv"] == 28

    idx = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    rows = {x["id"]: x for x in idx["records"]}
    assert rows["goblins"]["ancre_srd"] == "goblin-warrior"
    assert rows["goblins"]["pose_sur_nodes"] == ["goblinbattle"]
    assert rows["death-knight"]["persistent_attrs"] == ["pv"]

    # garde zéro-dangling sur les poses de jetons
    p2 = Partition(manifest())
    p2.records.append(Record(
        "orphan-pose", "creature", "Ghost",
        {"ca": 12, "pv": 5, "vitesse": "30 ft.", "attaque_bonus": 3,
         "degats": "1d4", "tokens_initial": [
             {"node_id": "nowhere", "count": 1, "placement_md": "x"}]},
        [(1, 5)]))
    try:
        write_partition(p2, tmp)
        raise AssertionError("pose vers node inconnu acceptée")
    except ValueError as e:
        assert "nowhere" in str(e), e

    # validate_form : orphelin seulement si ni id ni nom dans le corpus
    errs = validate_form.validate_form(p)
    assert not [e for e in errs if "orphan" in e], errs
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 6 -- filet anti-typo : statblock_core ----------------------------------------
section("statblock_core : dialecte source -> noyau chiffré")
bloc = ("Death Knight\nMedium Undead, NE\n\nArmour Class 15\n"
        "Hit Points 28 (minus dmg already caused)\nSpeed 30 ft.\n\n"
        "CR 1 (200XP)\n\nATTACKS\n\nHellreaver (Longsword +1) +5 Melee "
        "Weapon Attack, reach 5ft, one target. Hit 4 (1d8+3) slashing")
core = statblock_core(bloc)
assert core["ca"] == 15 and core["pv"] == 28
assert core["vitesse"] == "30 ft."
assert core["cr"] == "1" and core["xp"] == 200
assert core["attaques"][0] == {"nom": "Hellreaver (Longsword +1)",
                               "bonus": 5, "des": "1d8+3"}, core["attaques"]
core2 = statblock_core("Giant Centipede\nSmall Beast\nArmour Class 13\n"
                       "Hit Points 4\nSpeed 30 ft. / Climb 30 ft.\n"
                       "CR 1/4 (50XP)\nBite +4 Weapon Attack, Reach 5ft. "
                       "HIT 4 (1d4+2) piercing")
assert core2["cr"] == "1/4" and core2["xp"] == 50
assert core2["attaques"] == [{"nom": "Bite", "bonus": 4, "des": "1d4+2"}], \
    core2["attaques"]
try:
    statblock_core("Hit Points 9\nSpeed 30 ft.")
    raise AssertionError("bloc sans Armour Class accepté")
except ConversionException:
    pass

print(f"\nOK pconv1_records_test — {len(FAIT)} sections vertes")
