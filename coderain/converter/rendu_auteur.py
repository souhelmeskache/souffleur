"""Bouclage AUTEUR du `rendu_md` par scène (Issue #187, dernier maillon).

Le chemin AUTEUR s'arrêtait à mi-course : `ecrivain_module.ecrire_module`
produit `declaration_rendu` ([{scene, rendu_md}]) et
`ecrivain_module.vers_scenario_auteur` sait le câbler en `[{node_id,
rendu_md}]`, mais rien ne construisait le `node_id_par_scene` qu'exige cette
seconde fonction, et rien n'écrivait le résultat dans `scenario-auteur.json`
— le fichier d'enrichissement à froid que `cli.py` (§ scenario-auteur.json)
LIT pour poser `scenarios[].rendu_md` via `Node.attach_scenario`. Ce module
est ce maillon manquant.

Flux en DEUX conversions (jamais une seule, le `node_id` n'existe qu'APRÈS
la première) :

  1. conversion normale du module écrit par l'Auteur (`cli.cmd_convert`) —
     produit une `Partition` dont chaque `Node.titre` reprend le
     heading/titre de scène du module source verbatim (`s1_local.py`
     § `node_for_unit`/`segment_s1`, même convention que `ECRITURE_SYS`
     dans `ecrivain_module.py` qui demande au LLM de citer ce heading
     verbatim dans `declaration_rendu[].scene`) ;
  2. `ecrire_rendu_auteur(declaration_rendu, partition, candidats)` relie
     chaque scène au node de MÊME titre (`node_id_par_scene`), câble via
     `vers_scenario_auteur`, puis FUSIONNE le résultat dans
     `scenario-auteur.json` (préserve `objectif_md`/`debouches`/`heritage`
     déjà présents pour ce node) ;
  3. reconversion (même source, même `cmd_convert`) : `cli.py` relit
     `scenario-auteur.json` et pose `rendu_md` sur les bons nodes via
     `Node.attach_scenario`.

Titre non unique dans la partition, ou scène sans node de même titre : signalé
(`avertissements`), jamais forcé (même esprit que `validate_form.scenario_report`)
— `vers_scenario_auteur` ignore déjà silencieusement les scènes hors mapping,
ce module ajoute le signalement que ce silence n'offre pas.

Zéro API : câblage déterministe (mapping + fusion JSON), aucun jugement LLM."""
from __future__ import annotations

import json
from pathlib import Path

from ..ecrivain_module import vers_scenario_auteur


def node_id_par_scene(partition) -> tuple[dict[str, str], set[str], list[str]]:
    """Mapping scène (`Node.titre`) -> `node_id` depuis la partition
    CONVERTIE — seul mécanisme fiable que le code de conversion expose
    (`Node.titre` reprend verbatim le heading/titre de scène du module,
    cf. `s1_local.node_for_unit`/`build_gamebook_partition`). Un titre porté
    par plusieurs nodes est ambigu : exclu du mapping, signalé, jamais
    résolu au hasard.

    Retour : (mapping, titres_ambigus, avertissements)."""
    par_titre: dict[str, list[str]] = {}
    for n in partition.nodes:
        par_titre.setdefault(n.titre, []).append(n.id)
    mapping: dict[str, str] = {}
    ambigus: set[str] = set()
    avertissements: list[str] = []
    for titre, ids in par_titre.items():
        if len(ids) == 1:
            mapping[titre] = ids[0]
        else:
            ambigus.add(titre)
            avertissements.append(
                f"scene {titre!r}: titre porté par {len(ids)} nodes "
                f"({', '.join(ids)}) — ambigu, aucune entrée câblée")
    return mapping, ambigus, avertissements


def chemin_scenario_auteur(candidats: list[Path]) -> Path:
    """Le premier candidat existant (mêmes emplacements que la lecture
    `cli.py` : CORPUS home puis à côté de la source) ; à défaut, le premier
    candidat sert de destination pour une création."""
    for c in candidats:
        if c.exists():
            return c
    return candidats[0]


def _fusionner(chemin: Path, entrees: list[dict]) -> dict:
    """Fusion non destructive dans `scenarios[]` : ajoute/replace `rendu_md`
    sur l'entrée du même `node_id`, préserve `objectif_md`/`debouches`/
    `heritage` déjà présents ; crée l'entrée si elle n'existe pas encore.
    Idempotente : rejouer avec les mêmes `entrees` ne change rien de plus."""
    if chemin.exists():
        data = json.loads(chemin.read_text(encoding="utf-8"))
    else:
        data = {}
    scenarios = data.setdefault("scenarios", [])
    by_id = {str(s.get("node_id", "")): s for s in scenarios}
    for e in entrees:
        nid = e["node_id"]
        cible = by_id.get(nid)
        if cible is None:
            cible = {"node_id": nid}
            scenarios.append(cible)
            by_id[nid] = cible
        cible["rendu_md"] = e["rendu_md"]
    return data


def ecrire_rendu_auteur(declaration_rendu: tuple[dict, ...], partition,
                        candidats: list[Path]) -> dict:
    """L'appelant de la conversion (humain ou lane future, cf. docstring de
    tête `vers_scenario_auteur`) invoque ceci une fois la partition
    convertie disponible : construit `node_id_par_scene`, câble via
    `vers_scenario_auteur`, fusionne dans `scenario-auteur.json`.

    Retour : {"chemin", "entrees", "avertissements"} — `entrees` est ce qui
    a effectivement été écrit, `avertissements` couvre titres ambigus et
    scènes sans node correspondant (non bloquant, jamais une entrée
    fantôme)."""
    mapping, ambigus, avertissements = node_id_par_scene(partition)
    for entry in declaration_rendu:
        scene = entry["scene"]
        if scene not in mapping and scene not in ambigus:
            avertissements.append(
                f"scene {scene!r}: aucun node correspondant dans la "
                "partition convertie — signalé, aucune entrée créée")
    entrees = vers_scenario_auteur(tuple(declaration_rendu), mapping)
    chemin = chemin_scenario_auteur(candidats)
    data = _fusionner(chemin, entrees)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    return {"chemin": chemin, "entrees": entrees,
           "avertissements": avertissements}
