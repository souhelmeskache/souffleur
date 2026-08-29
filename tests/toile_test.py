"""L'étage toile (D-241 issue a, I-371a) — format, valideur de forme, étanchéité.

Fixture 100% SYNTHÉTIQUE: aucun contenu de campagne réel — ids, ancres et
secrets fabriqués pour le test uniquement (même discipline que campagne_test.py).

Covers:
  round-trip load/render — toile.md relit identique à ce qu'il écrit.
  validate() — ancre_module/condition_revelation obligatoires (refus sinon);
    etat connu; une révélation porte son ancre tracée; rattachement résolu
    contre les ids de campagne.md connus OU signalé.
  set_etat() — transitions latent->revele->caduc, jamais de retour en
    arrière (rétro-création interdite); revele exige une ancre.
  archivage — un fil qui passe caduc reste dans le fichier, jamais supprimé.
  étanchéité — l'id d'un fil latent n'apparaît dans aucun fichier source qui
    assemble le contexte servi au narrateur (grep plein-texte, D-241).
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coderain.toile import (Toile, FilToile, ETATS, load, load_file, render,
                            save_file, set_etat, validate)

# ---- fixture synthétique -------------------------------------------------
CAMPAGNE_IDS = {"fil-essai-un", "fil-essai-deux"}  # ids campagne.md connus (fixture)

TOILE = Toile(fil=[
    FilToile(
        id="fil-toile-un", ancre_module="module-essai-1/scene-2",
        condition_revelation="le joueur ouvre le coffre scellé",
        etat="latent", rattachement="fil-essai-un",
        secret_md="Secret fabriqué un — jamais improvisé, posé à l'avance."),
    FilToile(
        id="fil-toile-deux", ancre_module="module-essai-1/scene-5",
        condition_revelation="fin de l'acte deux",
        etat="revele", rattachement="",
        secret_md="Secret fabriqué deux — déjà révélé dans la fixture.",
        attrs={"revele_ancre": "T12"}),
    FilToile(
        id="fil-toile-trois", ancre_module="module-essai-2/intro",
        condition_revelation="jamais — rendu sans objet",
        etat="caduc", rattachement="fil-essai-deux",
        secret_md="Secret fabriqué trois — la campagne l'a rendu caduc."),
])


# ---- 1. round-trip -------------------------------------------------------
text = render(TOILE)
back = load(text)
assert [f.id for f in back.fil] == [f.id for f in TOILE.fil]
a, b = TOILE.fil[0], back.fil[0]
assert (a.ancre_module, a.condition_revelation, a.etat, a.rattachement) == \
       (b.ancre_module, b.condition_revelation, b.etat, b.rattachement)
assert back.fil[0].secret_md == a.secret_md
c, d = TOILE.fil[1], back.fil[1]
assert c.revele_ancre() == d.revele_ancre() == "T12"
# file round-trip too
tmp = os.path.join(tempfile.gettempdir(), "toile_fixture_test.md")
save_file(TOILE, tmp)
assert load_file(tmp).fil == back.fil

# ---- 2. validate: fixture bien formée = vide ------------------------------
errs = validate(TOILE, campagne_ids=CAMPAGNE_IDS)
assert errs == [], f"fixture valide rejetée: {errs}"

# ---- 3. validate: refus sans source ou sans condition de révélation -------
bad = load(render(TOILE))
bad.fil[0].ancre_module = ""
bad.fil[1].condition_revelation = "   "
errs = validate(bad, campagne_ids=CAMPAGNE_IDS)
assert any("ancre_module" in e for e in errs), errs
assert any("condition_revelation" in e for e in errs), errs

# ---- 4. validate: etat inconnu, révélation non tracée ---------------------
etat_inconnu = load(render(TOILE))
etat_inconnu.fil[0].etat = "invente"
errs = validate(etat_inconnu, campagne_ids=CAMPAGNE_IDS)
assert any("etat" in e and "invente" in e for e in errs), errs

sans_ancre = load(render(TOILE))
sans_ancre.fil[1].attrs.pop("revele_ancre", None)
errs = validate(sans_ancre, campagne_ids=CAMPAGNE_IDS)
assert any("revele sans ancre tracée" in e for e in errs), errs

# ---- 5. validate: rattachement résolu ou signalé --------------------------
inconnu = load(render(TOILE))
inconnu.fil[0].rattachement = "fil-campagne-fantome"
errs = validate(inconnu, campagne_ids=CAMPAGNE_IDS)
assert any("rattachement inconnu: fil-campagne-fantome" in e for e in errs), errs
assert validate(inconnu, campagne_ids=CAMPAGNE_IDS,
                signales={"fil-campagne-fantome"}) == []

malforme = load(render(TOILE))
malforme.fil[0].rattachement = "Pas Un Slug!"
errs = validate(malforme, campagne_ids=CAMPAGNE_IDS)
assert any("rattachement mal formé" in e for e in errs), errs

# id/duplication (même discipline que campagne.py)
errs = validate(Toile(fil=[
    FilToile(id="Fil Toile!", ancre_module="m", condition_revelation="c")]))
assert any("id non conforme" in e for e in errs), errs

dup = load(render(TOILE))
dup.fil.append(FilToile(id="fil-toile-un", ancre_module="m",
                        condition_revelation="c"))
assert any("dupliqué" in e for e in validate(dup, campagne_ids=CAMPAGNE_IDS))

# ---- 6. set_etat: transitions tracées, jamais de retour en arrière --------
camp = load(render(TOILE))
# latent -> revele exige une ancre
assert not set_etat(camp, "fil-toile-un", "revele")  # pas d'ancre: refusé
assert set_etat(camp, "fil-toile-un", "revele", ancre="T20")
f = camp.by_id("fil-toile-un")
assert f.etat == "revele" and f.revele_ancre() == "T20"
# revele -> caduc: permis
assert set_etat(camp, "fil-toile-un", "caduc")
# caduc est terminal: aucune transition ne repart
assert not set_etat(camp, "fil-toile-un", "revele", ancre="T21")
assert not set_etat(camp, "fil-toile-un", "latent")
# rétro-création interdite: un fil déjà révélé ne redevient jamais latent
assert not set_etat(camp, "fil-toile-deux", "latent")
# fil/etat absents: refusés proprement
assert not set_etat(camp, "fil-absent", "caduc")
assert not set_etat(camp, "fil-toile-un", "invente")

# ---- 7. archivage: un fil caduc reste dans le fichier, jamais supprimé ----
reloads = load(render(camp))
assert len(reloads.fil) == len(TOILE.fil), \
    "un fil caduc doit RESTER dans le fichier (trace, D-241)"
assert reloads.by_id("fil-toile-un").etat == "caduc"

# ---- 8. étanchéité: l'id d'un fil latent ne fuite dans aucun contexte -----
# rendu servi au narrateur (D-241: « jamais chargée dans un contexte de tour,
# même régime que campagne.md »). Recherche plein-texte de l'id d'un fil
# LATENT de la fixture sur tout le code source du dépôt: seuls toile.py (le
# module lui-même) et ce test peuvent le connaître.
latent_id = TOILE.fil[0].id  # "fil-toile-un" — latent dans la fixture d'origine
assert TOILE.fil[0].etat == "latent"
repo_root = Path(__file__).resolve().parents[1]
allowed = {Path(__file__).resolve(), repo_root / "coderain" / "toile.py"}
hits = []
for py in repo_root.rglob("*.py"):
    if py.resolve() in allowed:
        continue
    if any(part in (".git", "node_modules", "__pycache__") for part in py.parts):
        continue
    try:
        content = py.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    if latent_id in content:
        hits.append(str(py))
assert hits == [], f"id de fil latent trouvé hors toile.py/ce test: {hits}"
# aucun module d'assemblage de contexte n'importe la toile
for src_name in ("coderain/context.py", "coderain/memory.py", "mcp_server.py"):
    src = (repo_root / src_name).read_text(encoding="utf-8", errors="ignore")
    assert "toile" not in src.lower(), \
        f"{src_name} mentionne 'toile' — risque de câblage en contexte de tour"

print("toile_test: OK — round-trip, valideur de forme (refus source/condition, "
      "revele trace son ancre, rattachement résolu/signalé), transitions "
      "d'état sans retour en arrière, archivage biographique, étanchéité "
      "(grep id latent = zéro hors toile.py)")
