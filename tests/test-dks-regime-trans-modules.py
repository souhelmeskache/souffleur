"""Application des deux règles de régime trans-modules à la partition DKS
réelle (Issue #75 point 4) : échéancier D-253.1 (`coderain/echeancier.py`,
Issue #71) + garde d'identité/résolution inter-modules D-253.2
(`coderain/converter/validate_inter_module.py`, Issue #72).

100% synthétique côté grammaire (D-109) : les sections 1-3 utilisent des
`Evenement`/`Partition` factices. La section 4 charge la partition-pconv3
RÉELLE (hors git, `corpus_dir()`, D-178) et n'en lit que les FORMES — ids,
types de déclencheur, comptes — jamais de citation narrative au-delà des
identifiants machine déjà publics dans les rapports pconv0-3 (ex. slugs de
node/record).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, timezone, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain import echeancier
from coderain.config import corpus_dir
from coderain.converter import validate_inter_module
from coderain.converter.schemas import (Aventure, Manifest, Node, Partition,
                                        Record, Ressource, Secret, Tension)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def _manifest(titre="module"):
    return Manifest(titre=titre, corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="0" * 64,
                    date_conversion="2026-08-26T00:00:00+00:00",
                    version_convertisseur="test")


# 1 -- echeancier.extraire() : conditions vivantes/echues/etats -------------
section("echeancier : vivantes/echues/etats sur Aventure synthetique")
av = Aventure(
    trajectoire=[
        {"description_md": "Front dote.", "declencheur": {"type": "date", "valeur": "2026-09-01"}},
        {"description_md": "Front a delai.", "declencheur": {"type": "delai", "valeur": "J+10"}},
        {"description_md": "Front etat.", "declencheur": {"type": "etat", "valeur": "porte franchie"}},
    ],
    conditions=[
        {"description_md": "Loi echue.", "declencheur": {"type": "date", "valeur": "2026-01-01"}},
    ],
    charniere_md="Sortie.",
)
ech = echeancier.extraire(av, date_reference=date(2026, 8, 29),
                          date_pose=date(2026, 8, 20), fichier="module-test")
assert len(ech.vivantes) == 2, ech.rapport()   # date future + delai J+10
assert len(ech.echues) == 1, ech.rapport()      # loi 2026-01-01
assert len(ech.etats) == 1, ech.rapport()       # declencheur etat, hors garde v0
assert ech.avertissements == []

# 2 -- garder_reportage : re-script qui perd une condition vivante REFUSE ---
section("garder_reportage : perte nommee refusee, re-emission acceptee")
perdu = echeancier.garder_reportage(ech.vivantes, apres=Aventure([], [], ""))
assert len(perdu) == 2, perdu
assert all("traj-01" in e or "traj-02" in e for e in perdu)
apres_ok = Aventure(
    trajectoire=[
        {"id": "traj-01", "description_md": "Front dote (re-script).", "declencheur": {"type": "date", "valeur": "2026-09-01"}},
        {"id": "traj-02", "description_md": "Front a delai (re-script).", "declencheur": {"type": "delai", "valeur": "J+3"}},
    ],
    conditions=[], charniere_md="Sortie.",
)
assert echeancier.garder_reportage(ech.vivantes, apres=apres_ok) == []

# 3 -- cross_module_report : orpheline detectee, slug suspect signale -------
section("cross_module_report : orpheline vs resolution inter-modules")
pa = Partition(_manifest("module A"))
pa.records.append(Record("garde-huygens", "pnj", "Huygens",
                         {"role": "garde", "description_md": "Garde."}, anchors=[(0, 5)]))
pb = Partition(_manifest("module B"))
pb.nodes.append(Node("scene-b", "scene", "SCENE B", "Corps.", "scenario",
                     anchors=[(0, 5)], heritage=[{"fait_md": "Rencontre le garde.",
                                                  "ancre_source": [0, 5],
                                                  "porte": ["garde-huygens", "fantome"]}]))
rapport_seul = validate_inter_module.cross_module_report([pb])
assert any("garde-huygens" in o for o in rapport_seul["orphelines"])
assert any("fantome" in o for o in rapport_seul["orphelines"])
rapport_ensemble = validate_inter_module.cross_module_report([pa, pb])
assert any("fantome" in o for o in rapport_ensemble["orphelines"])
assert not any("garde-huygens" in o for o in rapport_ensemble["orphelines"]), (
    "garde-huygens resout desormais contre l'ensemble (defini par module A)")
pb.records.append(Record("capitaine-huygens", "pnj", "Huygens",
                         {"role": "capitaine", "description_md": "Autre PNJ, meme nom."},
                         anchors=[(0, 5)]))
suspects = validate_inter_module.cross_module_report([pa, pb])["slugs_suspects"]
assert any("huygens" in s for s in suspects)

# 4 -- partition-pconv3 REELLE : les deux regles appliquees -----------------
section("partition-pconv3 reelle : echeancier + garde inter-modules")
part_dir = corpus_dir() / "death-knights-squire" / "partition-pconv3"
if part_dir.exists():
    av_txt = (part_dir / "aventure.md").read_text(encoding="utf-8")
    m = re.search(r"---\n(.*?)\n---", av_txt, re.S)
    fm = json.loads(m.group(1))
    av_reelle = Aventure(fm.get("trajectoire", []), fm.get("conditions", []),
                         fm.get("charniere_md", ""))

    # Regle 1 (D-253.1) : echeancier applique a l'Aventure reelle.
    ech_reelle = echeancier.extraire(
        av_reelle, date_reference=date(2026, 8, 29), date_pose=date(2026, 8, 26),
        fichier="death-knights-squire/partition-pconv3")
    n_traj = len(fm.get("trajectoire", []))
    n_cond = len(fm.get("conditions", []))
    assert len(ech_reelle.etats) == n_traj + n_cond, ech_reelle.rapport()
    assert ech_reelle.vivantes == [] and ech_reelle.echues == [], (
        "DKS n'a aucun evenement date/delai — tout est declencheur 'etat' "
        f"({ech_reelle.rapport()}), mesure conforme au module source")
    assert ech_reelle.avertissements == []
    # Ancres composees lisibles : fichier:offset-offset
    if ech_reelle.etats:
        assert ech_reelle.etats[0].ancre.startswith(
            "death-knights-squire/partition-pconv3:")

    # Regle 2 (D-253.2) : garde de resolution, meme a un seul module (la
    # convention de slug s'applique des l'entree en campagne, pas seulement
    # au deuxieme module).
    part = Partition(_manifest("Death Knight's Squire"))
    part.aventure = av_reelle
    for f in (part_dir / "nodes").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        mm = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not mm:
            continue
        nfm = json.loads(mm.group(1))
        part.nodes.append(Node(nid=nfm["id"], type_=nfm["type"], titre=nfm.get("titre", ""),
                               corps_md=mm.group(2).strip(), altitude=nfm["altitude"],
                               liens=nfm.get("liens", []), anchors=nfm["anchors"],
                               charniere_sortie=nfm.get("charniere_sortie"),
                               objectif_md=nfm.get("objectif_md", ""),
                               debouches=nfm.get("debouches"), heritage=nfm.get("heritage")))
    for f in (part_dir / "records").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        mm = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not mm:
            continue
        rfm = json.loads(mm.group(1))
        body = mm.group(2).strip()
        stats = json.loads(body) if body.startswith("{") else {}
        part.records.append(Record(rid=rfm["id"], classe=rfm["classe"], nom=rfm["nom"],
                                   stats_5e=stats, anchors=rfm["anchors"],
                                   tags=rfm.get("tags"), transverse=rfm.get("transverse"),
                                   fonctions_aval=rfm.get("fonctions_aval")))
    for f in (part_dir / "secrets").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        mm = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not mm:
            continue
        sfm = json.loads(mm.group(1))
        part.secrets.append(Secret(sfm["id"], mm.group(2).strip(), sfm["statut"],
                                   sfm["porteurs"], sfm["revelation"],
                                   sfm.get("consequence_si_brule", ""), sfm["anchors"]))
    for f in (part_dir / "tensions").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        mm = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not mm:
            continue
        tfm = json.loads(mm.group(1))
        part.tensions.append(Tension(tfm["id"], tfm["categorie"], mm.group(2).strip(),
                                     tfm["node_id"], anchors=tfm["anchors"]))
    for f in (part_dir / "resources").glob("*.md"):
        txt = f.read_text(encoding="utf-8")
        mm = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not mm:
            continue
        rfm = json.loads(mm.group(1))
        part.ressources.append(Ressource(rid=rfm["id"], type_ressource=rfm["type"],
                                         anchors=rfm["anchors"], node_id=rfm.get("node_id"),
                                         page=rfm.get("page"), fichier=rfm.get("fichier"),
                                         description_md=mm.group(2).strip()))
    part.resources = part.ressources

    rapport = validate_inter_module.cross_module_report([part])
    assert rapport["orphelines"] == [], (
        f"references non resolues meme au sein du seul module DKS : {rapport['orphelines']}")
    print("DKS solo — slugs_suspects (attendu vide, aucun autre module en "
          f"campagne pour l'instant) : {rapport['slugs_suspects']}")
else:
    print("SKIP partition reelle : dossier absent (CI)")

print(f"OK ({len(FAIT)} sections)")
