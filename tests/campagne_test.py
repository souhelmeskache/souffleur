"""L'étage campagne (D-186 candidate) — format, valideur de forme, rapport.

Fixture 100% SYNTHÉTIQUE (fiche P2 du 2026-08-23): aucun contenu de campagne
réel, même migré — noms, faits et ancres fabriqués pour le test uniquement.

Covers:
  round-trip load/render — campagne.md relit identique à ce qu'il écrit.
  validate() — id/registre/fait/ancre/statut présents; porte bien formée;
    porte résolue contre records/flags/quests connus OU signalée (D-186).
  rapport() — actifs par registre, ancienneté, compteur de stagnation
    en SIGNAL (jamais une erreur) pour I-186.
  trace biographique — promu/scelle restent dans le fichier, jamais retirés.
"""
import os, sys, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.campagne import (Campagne, FilRouge, SEUIL_AVENTURES, load,
                               load_file, render, rapport, save_file,
                               set_statut, validate)

# ---- fixture synthétique -------------------------------------------------
# Records/flags/quests que "le save" connaît: slugs neutres de test.
RECORDS = {"record-alpha", "record-beta"}
FLAGS = {"fanion-essai"}
QUESTS = {"quete-essai": "ouverte"}

CAMP = Campagne(
    ambition_finale="Phrase d'ambition fabriquée pour la fixture de test.",
    fil_rouge=[
        FilRouge(
            id="fil-essai-un", registre="monde", statut="actif",
            fait_md="Fait de test un — phrase extraite fabriquée, pas une synthèse.",
            ancre_source="T3-4", attrs={"aventure_debut": "1"},
            porte=["record-alpha", "flag:fanion-essai",
                   "quete_etat:quete-essai:ouverte"]),
        FilRouge(
            id="fil-essai-deux", registre="interieur", statut="actif",
            fait_md="Fait de test deux — deuxième phrase fabriquée.",
            ancre_source="scene-fixture-a", attrs={"aventure_debut": "2"},
            porte=["record-beta"]),
        FilRouge(
            id="fil-essai-trois", registre="monde", statut="actif",
            fait_md="Fait de test trois — sans aventure_debut (âge incalculable).",
            ancre_source="etat:fixture-x", porte=[]),
        FilRouge(
            id="fil-essai-sorti", registre="interieur", statut="promu",
            fait_md="Fait de test sorti — reste dans le fichier (trace).",
            ancre_source="T9", attrs={"aventure_debut": "1"},
            porte=["record-alpha"]),
    ],
)


# ---- 1. round-trip -------------------------------------------------------
text = render(CAMP)
back = load(text)
assert back.ambition_finale == CAMP.ambition_finale
assert [f.id for f in back.fil_rouge] == [f.id for f in CAMP.fil_rouge]
a, b = CAMP.fil_rouge[0], back.fil_rouge[0]
assert (a.registre, a.statut, a.ancre_source, a.porte, a.aventure_debut()) == \
       (b.registre, b.statut, b.ancre_source, b.porte, b.aventure_debut())
assert back.fil_rouge[0].fait_md == a.fait_md
# file round-trip too
tmp = os.path.join(tempfile.gettempdir(), "campagne_fixture_test.md")
save_file(CAMP, tmp)
assert load_file(tmp).fil_rouge == back.fil_rouge

# ---- 2. validate: fixture bien formée = vide -----------------------------
assert validate(CAMP, records=RECORDS, flags=FLAGS, quests=QUESTS) == [], \
    f"fixture valide rejetée: {validate(CAMP, records=RECORDS, flags=FLAGS, quests=QUESTS)}"

# ---- 3. validate: forme manquante/mal formée détectée --------------------
bad = load(render(CAMP))
bad.fil_rouge[0].registre = "cosmique"
bad.fil_rouge[1].fait_md = "  "
bad.fil_rouge[2].ancre_source = ""
bad.fil_rouge[3].statut = "oublié"
errs = validate(bad, records=RECORDS, flags=FLAGS, quests=QUESTS)
assert len(errs) == 4, errs
assert any("registre" in e for e in errs)
assert any("fait_md" in e for e in errs)
assert any("ancre_source" in e for e in errs)
assert any("statut" in e for e in errs)

# un id non conforme n'est atteignable qu'en construction directe (load()
# slugifie toujours) — le valideur doit quand même le refuser
errs = validate(Campagne(ambition_finale="x", fil_rouge=[
    FilRouge(id="Fil Essai!", registre="monde", fait_md="corps",
             ancre_source="T1")]))
assert any("id non conforme" in e for e in errs), errs

dup = load(render(CAMP))
dup.fil_rouge.append(FilRouge(id="fil-essai-un", registre="monde",
                              fait_md="doublon", ancre_source="T1"))
assert any("dupliqué" in e for e in validate(dup))

malforme = load(render(CAMP))
malforme.fil_rouge[0].porte.append("flag:A B!")
errs = validate(malforme, records=RECORDS, flags=FLAGS, quests=QUESTS)
assert any("porte mal formée" in e for e in errs), errs

# ---- 4. validate: existence des cibles de porte --------------------------
inconnu = load(render(CAMP))
inconnu.fil_rouge[1].porte.append("record-inconnu")
inconnu.fil_rouge[1].porte.append("flag:nimporte")
inconnu.fil_rouge[1].porte.append("quete_etat:quete-inconnue:ouverte")
inconnu.fil_rouge[1].porte.append("quete_etat:quete-essai:soldee")
errs = validate(inconnu, records=RECORDS, flags=FLAGS, quests=QUESTS)
assert len(errs) == 4, errs
assert any("record inconnu" in e for e in errs)
assert any("flag inconnu" in e for e in errs)
assert any("quête inconnue" in e for e in errs)
assert any("état de quête incohérent" in e for e in errs)
# ...sauf si la porte est signalée (D-186: « connus du save ou signalés »)
signales = {"record-inconnu", "flag:nimporte",
            "quete_etat:quete-inconnue:ouverte", "quete_etat:quete-essai:soldee"}
assert validate(inconnu, records=RECORDS, flags=FLAGS, quests=QUESTS,
                signales=signales) == []

# ---- 5. rapport: comptages, ancienneté, signal de stagnation -------------
rep = rapport(CAMP, aventure_actuelle=6)
assert rep["total"] == 4
assert rep["par_statut"] == {"actif": 3, "promu": 1, "scelle": 0}
assert rep["actifs_par_registre"] == {"monde": 2, "interieur": 1}
ages = {a["id"]: a["aventures"] for a in rep["anciennete_actifs"]}
assert ages == {"fil-essai-un": 5, "fil-essai-deux": 4}
assert rep["anciennete_inconnue"] == ["fil-essai-trois"]
sig = rep["signal_stagnation"]
assert sig["seuil_aventures"] == SEUIL_AVENTURES
assert [e["id"] for e in sig["entrees"]] == ["fil-essai-un", "fil-essai-deux"], \
    "seuls les actifs AU-DELA du seuil sont signalés"

# ---- 6. transitions de statut: l'entrée reste, jamais supprimée ----------
camp2 = load(render(CAMP))
assert set_statut(camp2, "fil-essai-un", "promu")
assert set_statut(camp2, "fil-essai-deux", "scelle")
assert not set_statut(camp2, "fil-essai-un", "invente")
assert not set_statut(camp2, "fil-absent", "promu")
reloads = load(render(camp2))
assert len(reloads.fil_rouge) == len(CAMP.fil_rouge), \
    "une entrée promue/scellée doit RESTER dans le fichier"
by_id = {f.id: f.statut for f in reloads.fil_rouge}
assert by_id["fil-essai-un"] == "promu" and by_id["fil-essai-deux"] == "scelle"
rep2 = rapport(reloads, aventure_actuelle=6)
assert "fil-essai-un" not in {a["id"] for a in rep2["anciennete_actifs"]}, \
    "un actif promu ne compte plus dans l'ancienneté des actifs"

print("campagne_test: OK — round-trip, valideur de forme, portes "
      "(résolues/signalées), rapport (registres, ancienneté, signal I-186), "
      "trace biographique")
