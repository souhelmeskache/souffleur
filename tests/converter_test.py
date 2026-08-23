"""Converter P4 v0 tests: a fake specimen mixing S1/S2/S3 crosses the whole
chain with stub LLMs — segmentation, buckets, semantic conversion, rule
tables, both validator levels, exceptions report, emit. Negative tests pin
the anti-hallucination net (gap, dangling link, missing anchor, unknown
rule). No network, no model."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coderain.converter import convert_module
from coderain.converter.ruletables import RuleTables, ConversionException
from coderain.converter import validate_form, validate_fidelity
from coderain.converter.schemas import Node, Partition, Manifest

OUT = Path(tempfile.gettempdir()) / "se_converter_p4"
if OUT.exists():
    shutil.rmtree(OUT)

# ---------------------------------------------------------------- specimen --
S1 = "## 1. Depart\nVous vous reveillez. Si vous combattez, allez en 2.\n\n"
S2 = "## Salle A\nUn Gobelin garde la porte. Bibendum dort dans le coin.\n\n"
S3 = ("Table de tresor (1d6):\n1-1: piece d or\n2-6: rien du tout\n")
SOURCE = S1 + S2 + S3
A, B, C = len(S1), len(S1) + len(S2), len(SOURCE)


def _seg_json():
    return {"units": [
        {"id": "u-depart", "structure": "S1", "start": 0, "end": A,
         "titre": "Depart",
         "renvois": [{"condition": "si combattez", "cible": "2"}]},
        {"id": "u-salle-a", "structure": "S2", "start": A, "end": B,
         "titre": "Salle A"},
        {"id": "u-table-tresor", "structure": "S3", "start": B, "end": C,
         "titre": "Tresor"},
    ]}


RECORD_STATS = {"THAC0": "15", "CA": "5", "HD": "4",
                "vitesse": "9 m", "degats": "1d6"}


def _semantic_json(uid, start, end):
    anchor = [[start, end]]
    if uid == "u-salle-a":
        return {"nodes": [{"id": "salle-a", "type": "section",
                           "titre": "Salle A", "altitude": "scene",
                           "corps_md": SOURCE[start:end],
                           "liens": [],
                           # D-123 §6: le dernier node porte une charnière,
                           # jamais une fin
                           "charniere_sortie": {
                               "ouvre_vers_md": "la suite est ouverte",
                               "prerequis_etat": "etat: gobelin-porte neutralise"},
                           "anchors": anchor}],
                "records": [{"id": "gobelin-porte", "classe": "creature",
                             "nom": "Gobelin", "ruleset": "2e",
                             "stats_source": RECORD_STATS,
                             "anchors": anchor}]}
    if uid == "u-table-tresor":
        return {"tables": [{"id": "table-tresor", "de": "1d6",
                            "entrees": [
                                {"plage_debut": 1, "plage_fin": 1,
                                 "resultat_md": "piece d or"},
                                {"plage_debut": 2, "plage_fin": 6,
                                 "resultat_md": "rien du tout"}],
                            "anchors": anchor}]}
    return {"nodes": [{"id": "depart", "type": "chapitre", "titre": "Depart",
                       "altitude": "scene", "corps_md": SOURCE[start:end],
                       "liens": [{"cible_id": "salle-a",
                                  "condition_textuelle": "si combattez"}],
                       "anchors": anchor}],
            # D-178/D-182: étage aventure — trajectoire convertie (jamais
            # créée), perturbation avec issue (garde anti-rail D-120 §5.1)
            "evenements": [{"id": "ev-depart", "rubrique": "trajectoire",
                            "altitude": "adventure",
                            "description_md": "le monde continue sans le heros",
                            "declencheur": {"type": "etat",
                                            "valeur": "depart quitte"},
                            "once": True,
                            "consequences": ["la salle A se verrouille"],
                            "perturbations": [{
                                "condition_etat": "heros blesse avant l'entree",
                                "issue": "abandonnee"}],
                            "anchors": anchor}]}


class StubLLM:
    """Answers by stage, keyed off the system prompt."""

    def __init__(self, mutate=None):
        self.mutate = mutate or {}

    def complete(self, messages, **kw):
        system = messages[0]["content"]
        user = messages[1]["content"]
        if "You segment" in system:
            obj = self.mutate.get("segmentation") or _seg_json()
        elif "You classify" in system:
            obj = {"buckets": [
                {"id": "u-depart", "bucket": "consulte-a-froid"},
                {"id": "u-salle-a", "bucket": "mixte"},
                {"id": "u-table-tresor", "bucket": "change-en-jeu"}]}
        else:
            if "SEVERAL units" in system:
                uids = re.findall(r"Unit id: (\S+)", user)
                obj = {"units": [dict(_semantic_json(uid, *_unit_range(uid)),
                                      uid=uid) for uid in uids]}
            else:
                uid = user.split("Unit id: ")[1].split(" ")[0]
                obj = self.mutate.get(uid) or _semantic_json(uid, *_unit_range(uid))
        return json.dumps(obj)


# emit_json_ex checks hasattr(llm, "gen"); give the stub a plain attribute.
StubLLM.gen = {}


def _unit_range(uid):
    for u in _seg_json()["units"]:
        if u["id"] == uid:
            return u["start"], u["end"]
    raise KeyError(uid)


print("== happy path: specimen S1+S2+S3 crosses the whole chain ==")
partition, report = convert_module(
    SOURCE, titre="Specimen Test", structures=["S1", "S2", "S3"],
    corpus_source="2e", target_version="2014", llm_main=StubLLM(),
    out_dir=OUT / "partition", llm_recheck=StubLLM())
assert report["verdict"] == "VERT", report
assert report["comptages"]["form_errors"] == 0, report["details"]
assert report["comptages"]["coverage_gaps"] == 0
assert report["comptages"]["coverage_overlaps"] == 0
assert report["tokens"]["calls"] == 3, report["tokens"]   # 1 seg + 1 buckets + 1 batch(3 units)
assert report["tokens"]["chars_in_total"] > 0
print("   verdict VERT, coverage exact, meter counted", report["tokens"]["calls"], "calls")

# emitted directory is self-contained
pdir = OUT / "partition"
assert (pdir / "manifest.json").exists()
for sub in ("nodes", "records", "tables", "secrets"):
    assert (pdir / sub).is_dir()
assert sorted(f.name for f in (pdir / "nodes").iterdir()) == ["depart.md", "salle-a.md"]
mfest = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
assert mfest["corpus_cible"] == "5e" and mfest["structures"] == ["S1", "S2", "S3"]
assert mfest["hash_source"] and mfest["version_convertisseur"]
print("3) partition directory emitted, manifest complete")

# rule conversion actually ran: THAC0 15 -> +5, AC 5 -> 15, HD 4 -> 18 PV
gob = [r for r in partition.records if r.id == "gobelin-porte"][0]
st = gob.stats_5e
assert st["attaque_bonus"] == 5 and st["ca"] == 15 and st["pv"] == 18, st
print("4) rules converted deterministically:", {k: st[k] for k in ("attaque_bonus", "ca", "pv")})

# D-178/D-182: étage aventure converti, émis, garde anti-rail satisfaite
assert partition.aventure is not None, "étage aventure manquant"
traj = partition.aventure.trajectoire
assert len(traj) == 1 and traj[0].perturbations[0]["issue"] == "abandonnee"
assert partition.nodes[-1].charniere_sortie is not None   # D-123 §6
assert (pdir / "aventure.md").exists()
print("4bis) étage aventure émis: trajectoire + charnière de sortie")

print("5) negative: dangling link -> form error; gap -> ROUGE; no-anchor -> reject")
part2 = Partition(Manifest(titre="t", corpus_source="2e", corpus_cible="5e",
                           structures=["S1"], hash_source="h", date_conversion="d",
                           version_convertisseur="v"))
part2.nodes.append(Node("n1", "section", "N1", "body text here", "scene",
                        liens=[{"cible_id": "ghost", "condition_textuelle": ""}],
                        anchors=[(0, 10)]))
errs = validate_form.validate_form(part2)
assert any("dangling link" in e for e in errs), errs

units = []
from coderain.converter.schemas import Unit
units.append(Unit("a", "S1", 0, 50))
cov = validate_fidelity.coverage_report(units, [(0, 20)], 100)
assert cov["gaps"] == [[50, 100]] or cov["gaps"], cov
rep_gap = dict(report)
rep_gap["details"] = dict(report["details"])
rep_gap["comptages"] = dict(report["comptages"])
from coderain.converter.exceptions import build, render_md
bad = build({}, ["x"], {"gaps": [[0, 5]], "overlaps": [], "unanchored_claims": [],
                        "text_len": 100}, [], [], [])
assert bad["verdict"] == "ROUGE"
md = render_md(bad)
assert "| coverage_gaps | 1 |" in md
try:
    Node("n2", "section", "N2", "body", "scene", anchors=[])
    raise AssertionError("node without anchors must be rejected at construction")
except ValueError:
    pass
try:
    RuleTables("2e").save_category("inconnu total")
    raise AssertionError("unknown save must raise ConversionException")
except ConversionException:
    pass
print("   all four nets hold")

print("6) chunked segmentation keeps offsets exact across slices")
from coderain.converter.segmentation import segment_chunked, SEGMENT_CHUNK_CHARS

long_text = "".join(f"#{i + 1}\nParagraphe numero {i + 1} avec du texte.\n\n"
                    for i in range(1200))          # ~48k chars -> several chunks
seen_sizes = []


class ChunkStubLLM:
    gen = {}                                        # emit_json_ex looks for it

    def complete(self, messages, **kw):
        text = messages[1]["content"]
        seen_sizes.append(len(text))
        first = re.search(r"^#(\d+)", text, re.M).group(1)
        return json.dumps({"units": [
            {"id": f"u-{first}", "structure": "S1",
             "start": 0, "end": len(text), "titre": first}]})


units_c, errs = segment_chunked(ChunkStubLLM(), long_text)
assert errs == [], errs
assert len(units_c) == len(seen_sizes) >= 2
assert max(seen_sizes) <= SEGMENT_CHUNK_CHARS * 1.1
cov = validate_fidelity.coverage_report(units_c, [], len(long_text))
assert cov["gaps"] == [] and cov["overlaps"] == [], cov
print(f"   {len(units_c)} units from {len(seen_sizes)} chunks "
      f"(sizes {min(seen_sizes)}-{max(seen_sizes)})")

print("7) recheck sampling flags a divergent second pass")

class DivgentRecheck(StubLLM):
    def complete(self, messages, **kw):
        out = super().complete(messages, **kw)
        obj = json.loads(out)
        if isinstance(obj, dict) and "nodes" in obj and obj["nodes"]:
            obj["nodes"][0]["id"] = obj["nodes"][0]["id"] + "-bis"
            return json.dumps(obj)
        return out


_, rep3 = convert_module(SOURCE, titre="Specimen", structures=["S1", "S2", "S3"],
                         corpus_source="2e", target_version="2014",
                         llm_main=StubLLM(), out_dir=OUT / "p3",
                         llm_recheck=DivgentRecheck(), sampler_pct=0.5)
# verdict policy (declared): recheck divergence = nominal alarm for review,
# NOT a red light — only real losses/errors block.
assert rep3["verdict"] == "VERT", rep3
assert rep3["comptages"]["recheck_alarms"] >= 1
assert rep3["comptages"]["recheck_samples"] >= 1
print("   divergence caught:", rep3["details"]["recheck_alarms"])

print("\nCONVERTER P4 TESTS PASSED")
