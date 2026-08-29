"""D-260 lane (b) — Issue #127 : règles d'événement (events.md) évaluées PAR
CODE. Le Director ne reçoit que les règles CANDIDATES du tour (déclencheur
machine satisfait), jamais `event_rules_block()` entier (20 060 chars
constants mesurés, I-158). events.md est SYNTHÉTIQUE (D-109 : zéro matériau
réel versionné).

Couvre les critères d'acceptation de l'Issue #127 :
  1. triggers_all matche => servie ; ne matche pas => absente ; sans
     déclencheur => toujours servie (candidat permanent) ; triggers_not =>
     supprimée ; once/consumed inchangé.
  2. non-régression du contrat : event_fired sur une règle candidate
     traverse validator -> mark_event_consumed -> undo comme aujourd'hui.
  3. mesure imprimée : chars du bloc entier vs bloc servi ce tour, part
     triggée / non-triggée du fichier.
  4. déterminisme : deux assemblages au même haystack => bloc identique
     octet pour octet.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Entry, Library

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


root = os.path.join(tempfile.gettempdir(), "se_regles_evenement_verdicts_d260")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
save = lib.saves.create("Donjon factice D-260", mode="simple",
                        premise="Un donjon oublié, module de test synthétique.")
store = lib.store(save)

# --- events.md synthétique : trois profils --------------------------------
store.upsert_entry("events.md", Entry(
    "La herse s'abat", "herse-tombe", importance=4,
    attrs={"triggers_all": "levier", "once": "true"},
    body="then the portcullis slams shut, sealing the entrance."))
store.upsert_entry("events.md", Entry(
    "Le garde appelle des renforts", "renforts-gardes", importance=4,
    attrs={"triggers_all": "alarme", "triggers_not": "silence"},
    body="then two more guards arrive within two turns."))
store.upsert_entry("events.md", Entry(
    "La torche vacille quand le joueur hésite", "torche-vacille",
    importance=2,
    body="then the torchlight gutters, foreshadowing danger."))
store.upsert_entry("events.md", Entry(
    "Le pont s'effondre", "pont-effondre", importance=3,
    attrs={"once": "true", "triggers_all": "pont"},
    body="then the bridge collapses behind you."))

section("1) triggers_all : matche => candidate, ne matche pas => absente")
block_absent = store.event_rule_verdicts_block(
    [{"role": "player", "text": "J'observe la salle."}], "Je regarde autour de moi.")
assert "herse-tombe" not in block_absent
assert "torche-vacille" in block_absent, "candidat permanent doit rester servi"
block_present = store.event_rule_verdicts_block(
    [], "Je tire le levier près de la porte.")
assert "herse-tombe" in block_present
assert "levier" in block_present.lower()
print("  OK : herse-tombe absente hors contexte, présente quand 'levier' est dit")

section("2) sans déclencheur machine => candidat permanent")
assert "torche-vacille" in block_present
assert "torche-vacille" in block_absent
print("  OK : torche-vacille (titre naturel seul) toujours servie")

section("3) triggers_not => supprimée même si triggers_all matche")
block_alarme = store.event_rule_verdicts_block([], "L'alarme retentit !")
assert "renforts-gardes" in block_alarme
block_alarme_silence = store.event_rule_verdicts_block(
    [], "L'alarme retentit dans un silence de mort.")
assert "renforts-gardes" not in block_alarme_silence, \
    "triggers_not doit écarter la règle même si triggers_all matche aussi"
print("  OK : triggers_not écarte la règle malgré un triggers_all satisfait")

section("4) once/consumed : inchangé, la règle consommée disparaît du bloc")
store.mark_event_consumed("pont-effondre", True)
block_pont = store.event_rule_verdicts_block([], "Je traverse le pont.")
assert "pont-effondre" not in block_pont, "règle consommée ne doit jamais resservir"
store.mark_event_consumed("pont-effondre", False)     # undo, pour la suite
block_pont_2 = store.event_rule_verdicts_block([], "Je traverse le pont.")
assert "pont-effondre" in block_pont_2
print("  OK : consumed retire la règle, un-consumed (undo) la ramène")

section("5) déterminisme : même haystack => bloc identique octet pour octet")
a = store.event_rule_verdicts_block([], "L'alarme retentit !")
b = store.event_rule_verdicts_block([], "L'alarme retentit !")
assert a == b
assert a.encode("utf-8") == b.encode("utf-8")
print(f"  OK : {len(a)} chars, identiques sur deux assemblages")

section("6) mesure imprimée : bloc entier vs bloc servi ce tour")
entier = store.event_rules_block()
servi = store.event_rule_verdicts_block(
    [], "Je tire le levier près de la porte.")
rules = store.event_rules()
triggees = sum(1 for e in rules if e.triggers_all())
non_triggees = len(rules) - triggees
print(f"  event_rules_block() (entier)      : {len(entier):6} chars "
     f"(~{len(entier) // 4} tok), {len(rules)} règles")
print(f"  event_rule_verdicts_block() (tour) : {len(servi):6} chars "
     f"(~{len(servi) // 4} tok)")
print(f"  règles avec triggers_all (triggées) : {triggees} — "
     f"sans (candidats permanents) : {non_triggees}")
assert len(servi) < len(entier), "le bloc servi doit être strictement plus léger"

section("7) non-régression du contrat : event_fired sur règle candidate "
       "traverse validator -> mark_event_consumed -> undo")
cfg = load_config()
cfg.generation["trinity_brain"] = True
cfg.raw["trinity"] = {}
eng = Engine(cfg, store)


class EventStub:
    def complete(self, messages, **k):
        joined = " ".join(m["content"] for m in messages)
        assert "SCENARIO EVENT RULES" in joined
        assert "herse-tombe" in joined, "règle candidate absente du Director"
        assert "torche-vacille" in joined, "candidat permanent absent du Director"
        return json.dumps({"beat_plan": "La herse tombe dans un fracas.",
                           "envelope": {"v": 1,
                                        "deltas": {"event_fired": ["herse-tombe"]}}})

    def stream(self, messages, **k):
        joined = " ".join(m["content"] for m in messages)
        assert "herse-tombe" not in joined and "portcullis" not in joined, \
            "règle d'événement fuitée au Writer"
        yield "La herse s'abat dans un fracas de métal."


stub = EventStub()
eng.llm = stub
eng.trinity.director_llm = stub
eng.trinity.writer_llm = stub
out = "".join(eng.turn("Je tire le levier près de la porte."))
assert out == "La herse s'abat dans un fracas de métal."
rule = next(e for e in store.entries("events.md") if e.slug == "herse-tombe")
assert rule.attrs.get("consumed") == "true", "la règle candidate tirée doit se marquer consommée"
assert "herse-tombe" not in store.event_rules_block()
print("  OK : event_fired sur une règle candidate se marque consommée (validator + mark_event_consumed)")

assert eng.undo_last()
rule = next(e for e in store.entries("events.md") if e.slug == "herse-tombe")
assert rule.attrs.get("consumed") == "false", "undo doit un-consommer la règle"
print("  OK : undo un-consomme la règle — contrat inchangé (D-260 lane b)")

print("\nALL D-260 (b) CHECKS PASSED: " + ", ".join(FAIT))
