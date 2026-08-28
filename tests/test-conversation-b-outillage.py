"""I-341/D-219/D-220/I-144 : Conversation B — outillage webui 4 fenêtres.

100% synthétique (D-109) sauf (b) qui utilise tension-menace-goblins réelle.
Couvre : F1 dérivée de scene-origine, F3 alimentée par tension sans citer secret,
reformulation acceptée si non contraire, non-négociable contredit => refus nommé,
4 fenêtres complètes => Personnage Vahn 4 acquis + 3 jalons rattachés validate_form VERT,
garde 5 règles (aucun secret/node_id en sortie webui).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.config import corpus_dir
from webui import ConversationB

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def partition_synthetic():
    return {
        "nodes": [
            {"id": "scene-origine", "type": "scene", "titre": "Lisière d'Weathercote"},
            {"id": "scene-2", "type": "scene", "titre": "Château en ruine"},
        ],
        "tensions": [
            {"id": "tension-menace-goblins", "categorie": "menace",
             "description_md": "Surnombre gobelin.", "node_id": "scene-origine"},
            {"id": "tension-choix-den", "categorie": "choix",
             "description_md": "Dire ou mentir.", "node_id": "scene-2"},
            {"id": "tension-cout-peage", "categorie": "cout",
             "description_md": "Le péage du mensonge.", "node_id": "scene-2"},
        ],
        "resources": [
            {"id": "carte-hand-drawn-map", "type": "carte",
             "node_id": None, "page": 117,
             "fichier": "resources/carte-hand-drawn-map.jpg"},
            {"id": "carte-submap-1", "type": "carte",
             "node_id": "scene-2", "page": 112,
             "fichier": "resources/carte-submap-1.jpg"},
        ],
        "secrets": [
            {"id": "secret-arbre-rouge", "statut": "secret"},
            {"id": "secret-culte-kiaransalee", "statut": "suspect"},
            {"id": "secret-grakspores-immunite", "statut": "secret"},
        ],
        "aventure": {"trajectoire": 3, "conditions": 0},
    }


# a -- F1 dérivée de scene-origine PASS -----------------------------------
section("F1 : derivee de scene-origine")
pdata = partition_synthetic()
conv = ConversationB(pdata, "Vahn")
state = conv.start()
assert state["done"] is False
assert state["window"] == "origine"
assert state["window_number"] == 1
assert len(state["options"]) == 4
prose_f1 = state["prose"]
assert "Origine" in prose_f1
assert "Vahn" in prose_f1
for opt in state["options"]:
    assert "scene-origine" not in opt["texte"], "id node visible en option"
r1 = conv.submit("1")
assert r1["done"] is False
assert r1["window"] == "posture_sociale"
assert len(conv._acquis) == 1
assert len(conv._jalons) == 1
assert conv._jalons[0]["rattachement"] == "scene-origine"

# b -- F3 alimentée par tension-menace-goblins sans citer le secret PASS ---
section("F3 : alimentee par tension-menace-goblins sans citer le secret")
conv2 = ConversationB(pdata, "Vahn")
conv2.start()
conv2.submit("1")
conv2.submit("1")
state_f3 = conv2._current_state()
assert state_f3["window"] == "lien_tension"
prose_f3 = state_f3["prose"]
assert "menace" in prose_f3.lower() or "rôde" in prose_f3.lower()
for sid in ("secret-arbre-rouge", "secret-culte-kiaransalee",
            "secret-grakspores-immunite"):
    assert sid not in prose_f3, f"secret {sid} cité en sortie F3"
    for opt in state_f3["options"]:
        assert sid not in opt["texte"], f"secret {sid} dans option F3"
violations = conv2.guard_output(prose_f3)
assert violations == [], f"violations garde F3: {violations}"
r_f3 = conv2.submit("1")
assert r_f3["done"] is False
assert r_f3["window"] == "enjeu_personnel"
assert conv2._jalons[-1].get("rattachement") == "tension-menace-goblins"

# c -- Reformulation joueur acceptée si non contraire au non-négociable PASS
section("reformulation : acceptee si non contraire au non-negociable")
conv3 = ConversationB(pdata, "Vahn")
conv3.start()
r_reform = conv3.submit("Je suis un mercenaire sans passé")
assert "error" not in r_reform, f"reformulation acceptee rejetee: {r_reform}"
assert r_reform["window"] == "posture_sociale"
assert conv3._acquis[0] == "reformulation-0"
assert conv3._jalons[0]["intention_md"] == "Je suis un mercenaire sans passé"

# d -- Non-négociable contredit => refus nommé PASS -------------------------
section("non-negociable : contredit => refus nomme")
conv4 = ConversationB(pdata, "Vahn")
conv4.start()
r_refus = conv4.submit("Je ne porte jamais aucune dette envers personne, pas même un mort")
assert "error" in r_refus, "refus attendu pour contradiction non-negociable"
assert r_refus["error_type"] == "non-negotiable-contredit"
assert "non-negociable" in r_refus["error"].lower() or "dette" in r_refus["error"].lower()
assert conv4._idx == 0, "fenetre avance malgre refus"

# e -- 4 fenêtres complètes => Personnage Vahn 4 acquis + 3 jalons rattachés
#      validate_form VERT PASS
section("4 fenetres : Personnage Vahn 4 acquis + 3 jalons rattaches VERT")
conv5 = ConversationB(pdata, "Vahn")
conv5.start()
r1 = conv5.submit("1")
assert r1["window"] == "posture_sociale"
r2 = conv5.submit("2")
assert r2["window"] == "lien_tension"
r3 = conv5.submit("3")
assert r3["window"] == "enjeu_personnel"
r4 = conv5.submit("4")
assert r4["done"] is True
pers = conv5.personnage("vahn", "Vahn")
assert pers["id"] == "vahn"
assert pers["nom"] == "Vahn"
assert len(pers["acquis_conversation"]) == 4, \
    f"4 acquis attendus, {len(pers['acquis_conversation'])} obtenus"
assert len(pers["destinee"]) >= 2, \
    f"destinee >= 2 jalons, {len(pers['destinee'])} obtenus"
jalons_rattaches = [j for j in pers["destinee"] if j.get("rattachement")]
assert len(jalons_rattaches) >= 3, \
    f"3 jalons rattaches attendus, {len(jalons_rattaches)} obtenus"
from coderain.converter.schemas import Personnage
p_obj = Personnage(pers["id"], pers["nom"],
                   acquis_conversation=pers["acquis_conversation"],
                   destinee=pers["destinee"])
assert len(p_obj.acquis_conversation) == 4
assert len(p_obj.destinee) >= 2
tmp = Path(tempfile.mkdtemp(prefix="conv-b-e-"))
try:
    from coderain.converter.schemas import (Manifest, Node, Partition,
                                              Tension, Ressource, Aventure)
    from coderain.converter.emit import write_partition
    from coderain.converter import validate_form
    m = Manifest(titre="test", corpus_source="5e", corpus_cible="5e",
                 structures=["S1", "S2"], hash_source="0" * 64,
                 date_conversion="2026-08-27T00:00:00+00:00",
                 version_convertisseur="test")
    part = Partition(m)
    part.nodes.append(Node("scene-origine", "scene", "Origine",
                           "La lisière.", "scene", anchors=[(0, 10)]))
    part.nodes.append(Node("scene-2", "scene", "Château",
                           "Ruines.", "scene", anchors=[(10, 20)]))
    part.nodes[-1].liens.append({"cible_id": "scene-origine",
                                  "condition_textuelle": "retour"})
    part.tensions.append(Tension("tension-menace-goblins", "menace",
                                  "Surnombre gobelin.", "scene-origine",
                                  [(0, 5)]))
    part.tensions.append(Tension("tension-choix-den", "choix",
                                  "Dire ou mentir.", "scene-2", [(10, 15)]))
    part.tensions.append(Tension("tension-cout-peage", "cout",
                                  "Le péage.", "scene-2", [(15, 20)]))
    part.ressources.append(Ressource("carte-hand-drawn-map", "carte",
                                      [(0, 5)], page=117,
                                      fichier="resources/carte-hand-drawn-map.jpg"))
    part.resources = part.ressources
    part.aventure = Aventure(
        [{"id": "traj-01", "description_md": "Quête",
          "declencheur": {"type": "etat", "valeur": "quete"},
          "perturbations": [{"condition_etat": "abandon", "issue": "abandonnee",
                             "porteur_cible_id": "scene-origine"}],
          "ancres_sources": [[0, 10]]}],
        [], "Sortie")
    part.personnages.append(p_obj)
    write_partition(part, tmp)
    (tmp / "directeur.md").write_text("# Brief\nSans secret.\n",
                                       encoding="utf-8")
    errs = validate_form.validate_form(part, tmp)
    assert errs == [], f"validate_form VERT attendu mais {errs}"
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# f -- Garde 5 règles vérifiée (aucun secret/node_id en sortie webui) PASS --
section("garde 5 regles : aucun secret/node_id en sortie webui")
conv6 = ConversationB(pdata, "Vahn")
state = conv6.start()
all_prose = [state["prose"]]
all_opts_text = []
for opt in state["options"]:
    all_opts_text.append(opt["texte"])
r = conv6.submit("1")
all_prose.append(r.get("prose", ""))
for opt in r.get("options", []):
    all_opts_text.append(opt["texte"])
r = conv6.submit("1")
all_prose.append(r.get("prose", ""))
for opt in r.get("options", []):
    all_opts_text.append(opt["texte"])
r = conv6.submit("1")
all_prose.append(r.get("prose", ""))
for opt in r.get("options", []):
    all_opts_text.append(opt["texte"])
r = conv6.submit("1")
all_prose.append(r.get("prose", ""))
full_output = "\n".join(all_prose + all_opts_text)
for sid in ("secret-arbre-rouge", "secret-culte-kiaransalee",
            "secret-grakspores-immunite"):
    assert sid not in full_output, f"secret {sid} trouvé en sortie"
for nid in ("scene-origine", "scene-2"):
    assert nid not in full_output, f"id node {nid} trouvé en sortie"
for tid in ("tension-menace-goblins", "tension-choix-den", "tension-cout-peage"):
    assert tid not in full_output, f"id tension {tid} trouvé en sortie"
for rid in ("carte-hand-drawn-map", "carte-submap-1"):
    assert rid not in full_output, f"id ressource {rid} trouvé en sortie"
for marker in ("négociable", "non-négociable", "negociable", "non-negociable"):
    assert marker not in full_output.lower(), \
        f"marqueur {marker} visible en sortie"
violations = conv6.guard_output(full_output)
assert violations == [], f"violations garde: {violations}"

# g -- Partition réelle : Vahn synthétique dans partition-pconv3 -----------
section("partition reelle : Vahn via ConversationB sur partition-pconv3")
part_dir = corpus_dir() / "death-knights-squire" / "partition-pconv3"
if part_dir.exists():
    idx = json.loads((part_dir / "index.json").read_text(encoding="utf-8"))
    tensions_reelles = []
    for f in (part_dir / "tensions").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        import re
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if m:
            fm = json.loads(m.group(1))
            tensions_reelles.append({
                "id": fm["id"], "categorie": fm["categorie"],
                "description_md": m.group(2).strip(),
                "node_id": fm["node_id"]})
    pdata_reelle = {
        "nodes": idx.get("nodes", []),
        "tensions": tensions_reelles,
        "resources": idx.get("resources", []),
        "secrets": idx.get("secrets", []),
        "aventure": idx.get("aventure"),
    }
    conv7 = ConversationB(pdata_reelle, "Vahn")
    s = conv7.start()
    assert s["window"] == "origine"
    assert len(s["options"]) == 4
    for sid in idx.get("secrets", []):
        sid_str = sid["id"] if isinstance(sid, dict) else sid
        assert sid_str not in s["prose"]
    conv7.submit("1")
    conv7.submit("1")
    s3 = conv7._current_state()
    assert s3["window"] == "lien_tension"
    has_goblins = any("gobelins" in o.texte.lower()
                      for o in conv7._options)
    assert has_goblins, "option goblins absente en F3 sur partition reelle"
    conv7.submit("4")
    conv7.submit("4")
    assert conv7.is_done
    p7 = conv7.personnage("vahn", "Vahn")
    assert len(p7["acquis_conversation"]) == 4
    assert len(p7["destinee"]) >= 2
else:
    print("SKIP partition reelle : dossier absent (CI)")

print(f"\nOK test-conversation-b-outillage — {len(FAIT)} sections vertes")
