"""Gamebook deterministic route (P-conv-0, socle formes): named-entry heads,
renvoi graph + recollage, pointer pages, inline d100 tables. Everything runs
on SYNTHETIC material (module factice ci-dessous + fixture de structure) —
no real module text, no LLM, no network."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coderain.converter import validate_fidelity
from coderain.converter.cli import cmd_convert, main
import coderain.converter.cli as cli_mod
from coderain.converter.s1_local import (GAMEBOOK, assemble_pages,
                                         extract_d100_tables, scan_gamebook)

# ------------------------------------------------------------- module factice
MOD = (
    "THE PAPER FORK (SYNTHETIC GAMEBOOK FIXTURE)\n"
    "\n"
    "You wake at a paper fork. Nothing in this file is real content.\n"
    "\n"
    "FORKSTART?\n"
    "The path splits under a paper moon.\n"
    "♦ Take the left trail? Go to entry MOSSYGATE\n"
    "♦ Take the right trail? Go to entry\n"
    "STONYARD\n"
    "♦ Swim? Make an athletics check, DC 10. If you succeed,\n"
    "go to entry STON If you fail, go to entry SOAKED\n"
    "♦ Give up and go to entry NOWHERE\n"
    "\n"
    "MOSSYGATE\n"
    "Moss maps the gate. A tin key waits.\n"
    "♦ Take the key? Add a Tin Key to your inventory, then go to entry\n"
    "WESTBRIDGE\n"
    "♦ Leave it. Go to entry WESTBRIDGE\n"
    "\n"
    "BONECOLLEC\n"
    "TOR\n"
    "A collector of small bones bars the way.\n"
    "♦ Fight? Roll initiative!\n"
    "♦ Parley? Go to entry WESTBRIDGE\n"
    "\n"
    "WEST BRIDGE\n"
    "The bridge is paper too. Roll a d100.\n"
    "♦ If you score 1-40, go to entry TOLLPAID\n"
    "♦ If you score 41-80, go to entry\n"
    "TROLLTOLL\n"
    "♦ If you score 81-00, go to entry NOWHERE\n"
    "\n"
    "STONYARD\n"
    "Stones, stacked by nobody.\n"
    "♦ Rest? Go to entry FORKSTART\n"
    "\n"
    "SOAKED\n"
    "You are soaked.\n"
    "♦ Go back to entry\n"
    "FORKSTART\n"
    "\n"
    "QUIETFORD\n"
    "The ford is quiet today.\n"
    "♦ Sneak past? Go to entry\n"
    "MISTCROSS\n"
    "\n"
    + ("Filler prose keeps the two halves far apart. " * 60)
    + "\n\n"
    "LONGHAUL\n"
    "A long flat stretch of invented road.\n"
    "♦ Continue north? Go to entry\n"
    "MISTCROSS\n"
    "\n"
    "NIGHTCROSS?\n"
    "Night crossing, if it ever comes to that.\n"
    "\n"
    "TOLLPAID\n"
    "The toll was never collected. Onward.\n"
    "\n"
    "TROLLTOLL\n"
    "A toll troll counts pebbles.\n"
    "\n"
    "TILEPAGE 1\n"
    "Find tilepage 1 in the Maps Booklet.\n"
    "OPTIONS:\n"
    "♦ Checking for traps?: Go to entry TRAPLESS\n"
    "♦ When ready, move toward the green marker to go to entry FORKSTART\n"
)

print("0) scan: heads, merges, tuilage exact")
scan = scan_gamebook(MOD)
units = scan["units"]
spans = sorted((u.start, u.end) for u in units)
cov = validate_fidelity.coverage_report(units, [], len(MOD))
assert cov["gaps"] == [] and cov["overlaps"] == [], cov
print("   tuilage exact sur", len(MOD), "car.,", len(units), "unités")

uids = {u.uid for u in units}
for expected in ("forkstart", "mossygate", "bonecollector", "westbridge",
                 "stonyard", "soaked", "quietford", "longhaul",
                 "nightcross", "mistcross", "tollpaid", "trolltoll",
                 "tilepage-1", "ouverture"):
    assert expected in uids, (expected, sorted(uids))
# MISTCROSS n'existe qu'en bloc collé sous un verbe, référencé depuis
# l'autre moitié du module : promotion croisée. NIGHTCROSS? est une tête
# réelle : le « ? » tombe du slug, jamais du titre.
assert scan["pointers"] == 1
assert any("NOWHERE" in u for u in scan["unresolved"])
assert "TRAPLESS" in scan["unresolved"]
assert len(scan["unresolved"]) == 3, scan["unresolved"]
assert scan["flagged"] == [], scan["flagged"]
assert "mistcross" in scan["promoted"], scan["promoted"]
s2 = [u for u in units if u.structure == "S2"]
assert len(s2) == 1 and s2[0].uid == "tilepage-1"
print("   têtes attendues présentes, promotions:", scan["promoted"],
      "· non résolus:", scan["unresolved"])

# liens typés : le pont renvoie vers les deux cibles résolues seulement
node_of = scan["node_of_uid"]
wb_uid = next(u.uid for u in units if node_of[u.uid] == "westbridge")
part_scan_targets = {}
for u in units:
    part_scan_targets[u.uid] = [c["target"] for c in scan["resolved"]
                                if u.start <= c["raw"] < u.end]
assert set(part_scan_targets[wb_uid]) == {"tollpaid", "trolltoll"}, \
    part_scan_targets[wb_uid]
tf_uid = next(u.uid for u in units if node_of[u.uid] == "tilepage-1")
assert set(part_scan_targets[tf_uid]) == {"forkstart"}
print("   graphe de renvois attribué aux bons porteurs")

# table d100 inline (style ♦ score X-Y) contiguë 1-40 / 41-80 / 81-100
from coderain.converter.schemas import Partition, Manifest
p = Partition(Manifest(titre="t", corpus_source="5e", corpus_cible="5e",
                       structures=["S1", "S2"], hash_source="h",
                       date_conversion="d", version_convertisseur="v"))
made = extract_d100_tables(scan, MOD, p)
assert len(made) == 1, made
t = p.tables[0]
assert t.de == "1d100" and [(e["plage_debut"], e["plage_fin"])
                            for e in t.entrees] == \
    [(1, 40), (41, 80), (81, 100)], t.entrees
assert "NOWHERE" in t.entrees[2]["resultat_md"]
print("1) table d100 inline extraite:", made)

# ------------------------------------------------------------- bout en bout
OUT = Path(tempfile.mkdtemp(prefix="gb_conv_"))
try:
    src = OUT / "module-factice.txt"
    src.write_text(MOD, encoding="utf-8")
    (OUT / "aventure-auteur.json").write_text(json.dumps({
        "trajectoire": [], "conditions": [],
        "charniere_md": "fixture synthétique : la suite reste ouverte"}),
        encoding="utf-8")
    saved_corpus = cli_mod.CORPUS
    cli_mod.CORPUS = OUT                     # isolement des fichiers auteur
    try:
        res = cmd_convert(src, OUT / "partition", titre="Paper Fork",
                          mode="gamebook")
    finally:
        cli_mod.CORPUS = saved_corpus
    assert res["verdict"] == "VERT", res
    n_nodes = len({node_of[u.uid] for u in units})
    assert res["route_gamebook"]["nodes"] == n_nodes, res
    pdir = Path(res["out"])
    mfest = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
    assert mfest["structures"] == ["S1", "S2"], mfest
    assert mfest["version_convertisseur"] == "0.4.0+gamebook-local"
    idx = json.loads((pdir / "index.json").read_text(encoding="utf-8"))
    ids = {n["id"] for n in idx["nodes"]}
    assert {"ouverture", "bonecollector", "westbridge", "tilepage-1"} <= ids
    rep = json.loads((pdir / "rapport-conversion.json").read_text(
        encoding="utf-8"))
    assert rep["comptages"]["form_errors"] == 0, rep["details"]
    assert rep["comptages"]["coverage_gaps"] == 0
    print("2) cmd_convert gamebook: VERT,", res["nodes"], "nodes,",
          res["tables"], "table(s), zéro dangling")

    # CLI complet (--segmenter gamebook), même isolement des fichiers auteur
    saved_corpus = cli_mod.CORPUS
    cli_mod.CORPUS = OUT
    try:
        rc = main(["convert", str(src), "--titre", "Paper Fork Two",
                   "--out", str(OUT / "partition-cli"),
                   "--segmenter", "gamebook"])
    finally:
        cli_mod.CORPUS = saved_corpus
    assert rc == 0 and (OUT / "partition-cli" / "manifest.json").exists()
    print("3) CLI --segmenter gamebook: exit 0")
finally:
    shutil.rmtree(OUT, ignore_errors=True)

# ------------------------------------------------- fixture de structure v0
FIXTURE = Path(__file__).parent / "fixtures" / "module-fixture-gamebook-s2.txt"
OUT2 = Path(tempfile.mkdtemp(prefix="gb_fix_"))
try:
    src = OUT2 / "fixture.txt"
    shutil.copy(FIXTURE, src)
    (OUT2 / "aventure-auteur.json").write_text(json.dumps({
        "trajectoire": [], "conditions": [],
        "charniere_md": "fixture synthétique : la suite reste ouverte"}),
        encoding="utf-8")
    saved_corpus = cli_mod.CORPUS
    cli_mod.CORPUS = OUT2
    try:
        res = cmd_convert(src, OUT2 / "partition", titre="Silver Badger",
                          mode="gamebook")
    finally:
        cli_mod.CORPUS = saved_corpus
    assert res["verdict"] == "VERT", res
    idx = json.loads((Path(res["out"]) / "index.json").read_text(
        encoding="utf-8"))
    ids = {n["id"] for n in idx["nodes"]}
    # la forme visée par la passe d'analyse : entrées nommées + pointeur
    for expected in ("introduction", "adventurebegins", "reedbank",
                     "northgate", "badgerbattle", "lanternfound",
                     "tilepage-1"):
        assert expected in ids, (expected, sorted(ids))
    tabs = json.loads((Path(res["out"]) / "index.json").read_text(
        encoding="utf-8"))["tables"]
    assert any(t["de"] == "1d100" for t in tabs), tabs
    print("4) fixture de structure v0 convertie VERT:",
          res["nodes"], "nodes ·", res["tables"], "table(s) d100")
finally:
    shutil.rmtree(OUT2, ignore_errors=True)

# ------------------------------------------------------- assemble_pages
tmp = Path(tempfile.mkdtemp(prefix="gb_pages_"))
try:
    for n in (1, 2, 3):
        (tmp / f"page-{n:03d}.txt").write_text(f"page{n}text", encoding="utf-8")
    txt, starts = assemble_pages(tmp, 1, 3)
    assert txt == "page1text\n\npage2text\n\npage3text"
    assert starts == [0, 11, 22]
    scan2 = scan_gamebook(txt, GAMEBOOK, page_starts=starts)
    cov2 = validate_fidelity.coverage_report(scan2["units"], [], len(txt))
    assert cov2["gaps"] == [] and cov2["overlaps"] == []
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("5) assemble_pages + offsets de pages OK")

print("\nGAMEBOOK TESTS PASSED")
