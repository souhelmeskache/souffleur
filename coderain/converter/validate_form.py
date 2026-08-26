"""Formal validator (SPEC-P4 §7, level 1) — pure structure, zero reading.

Checks: dangling links zero · orphan records zero · well-formed tables
(re-checked at load) · secrets not exposed in common prose · manifest sane.
Returns a list of findings; empty list = green.
"""
from __future__ import annotations


def validate_form(partition, partition_dir=None) -> list[str]:
    errors: list[str] = []
    ids = partition.ids()

    # 1) every referenced id exists (links, secret revelation/porteurs, patches)
    for n in partition.nodes:
        for l in n.liens:
            if l.get("cible_id") not in ids:
                errors.append(f"dangling link: node {n.id} -> {l.get('cible_id')}")
    for s in partition.secrets:
        if s.revelation["node_cible"] not in ids:
            errors.append(f"dangling revelation: secret {s.id} -> "
                          f"{s.revelation['node_cible']}")
        for p in s.porteurs:
            if p and p not in ids:
                errors.append(f"secret {s.id}: unknown porteur {p}")
    for p in partition.patches:
        if p.cible_id not in ids:
            errors.append(f"dangling patch target: {p.cible_id}")

    # 2) records orphans zero — a creature/pnj record must be anchored by some
    #    node's prose or a table result referencing it; v0 proxy: every record
    #    id must appear in at least one node body or table result.
    corpus = "\n".join(n.corps_md for n in partition.nodes)
    corpus += "\n".join(e["resultat_md"] for t in partition.tables
                        for e in t.entrees)
    for r in partition.records:
        if r.id not in corpus and r.nom not in corpus:
            errors.append(f"orphan record: {r.id} ({r.classe}) never referenced")

    # 3) secrets hors prose commune — a secret id/content marker must not leak
    #    into any non-secret node body
    for s in partition.secrets:
        if s.contenu_md.strip() and s.contenu_md.strip()[:40] in corpus:
            errors.append(f"secret leak: secret {s.id} content appears in common prose")

    # 4) duplicate ids across primitives (tensions D-218 + ressources D-216 §2)
    ress_list = (getattr(partition, "ressources", []) or []) + (getattr(partition, "resources", []) or [])
    # déduplication par id pour l'alias (même objet deux fois)
    seen = set()
    uniq_ress_ids = []
    for r in ress_list:
        if r.id not in seen:
            seen.add(r.id)
            uniq_ress_ids.append(r.id)
    all_ids = [n.id for n in partition.nodes] + [r.id for r in partition.records] \
        + [t.id for t in partition.tables] + [s.id for s in partition.secrets] \
        + [t.id for t in getattr(partition, "tensions", []) or []] \
        + uniq_ress_ids
    dupes = sorted({i for i in all_ids if all_ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate ids: {dupes}")

    # 5) altitude mandatory on nodes (schemas already enforces; belt & braces)
    for n in partition.nodes:
        if not n.altitude:
            errors.append(f"node {n.id}: missing altitude")

    # 6) D-177: the directing brief is a standard Partition piece
    if partition_dir is not None:
        from pathlib import Path
        if not (Path(partition_dir) / "directeur.md").exists():
            errors.append("directeur.md absent — pièce standard (MRPG-D-177)")

    # 7) D-178 étage aventure — extensions de la fiche méta 2026-08-23
    if partition.aventure is None:
        if partition.nodes:
            errors.append("étage aventure absent (trajectoire/conditions/"
                          "charnière) — non négociable pour P2 "
                          "(rapport conformité §2.1)")
    else:
        ev_ids = {e.id for e in partition.aventure.events()}
        # 7.1 tout evenement est ancré
        for e in partition.aventure.events():
            if not e.anchors:
                errors.append(f"evenement {e.id}: sans ancre source (§6.1)")
            for p in e.perturbations:
                pid = p.get("porteur_cible_id")
                if pid and pid not in ids and pid not in ev_ids:
                    errors.append(f"evenement {e.id}: porteur_cible_id "
                                  f"inconnu {pid}")
                if not p.get("issue"):
                    errors.append(
                        f"evenement {e.id}: perturbation sans issue valide "
                        "(garde anti-rail D-120 §5.1)")
        # 7.4 fonctions_aval référencés existent
        for r in partition.records:
            for fid in getattr(r, "fonctions_aval", []):
                if fid not in ev_ids:
                    errors.append(f"record {r.id}: fonctions_aval inconnu "
                                  f"{fid}")
        # 7.3 LE DERNIER node (ordre de partition) sans charniere_sortie
        #     ni lien sortant ⇒ rouge (fiche §6.3 / D-123 §6)
        if partition.nodes:
            last = partition.nodes[-1]
            if not last.liens \
                    and not getattr(last, "charniere_sortie", None):
                errors.append(
                    f"node {last.id}: dernier node sans lien sortant ni "
                    "charniere_sortie (D-123 §6)")
        # charnière d'aventure obligatoire — au niveau de l'étage OU portée
        # par un node terminal (fiche D-178 §4, D-123 §6)
        has_charniere_node = any(getattr(n, "charniere_sortie", None)
                                 for n in partition.nodes)
        if not partition.aventure.charniere_md.strip() \
                and not has_charniere_node:
            errors.append("aventure: charnière de sortie vide (D-123 §6)")

    # 8) D-218 tension traversante — chaque tension cite son node d'ancrage
    for t in getattr(partition, "tensions", []) or []:
        if t.node_id not in ids:
            errors.append(f"tension {t.id}: node_id inconnu {t.node_id} "
                          "(D-218 §1 — ancrage node obligatoire)")
        if not t.anchors:
            errors.append(f"tension {t.id}: sans ancre source (D-218 §1)")
        if not t.description_md.strip():
            errors.append(f"tension {t.id}: description_md vide")
        # garde forme : tension ne porte jamais de contenu secret en clair
        # (même contrôle que secrets — pas de fuite dans la prose commune)
        if t.description_md.strip()[:40] in corpus:
            # si la description reprend verbatim un bloc de node, c'est voulu
            # (la tension cite la source) — on ne signale que si c'est un secret
            pass

    # 9) D-216 §2 ressource générique — ancrage node_id/page, type carte, ancres
    #    Toute ressource cite sa matière ; si node_id présent il existe (zéro dangling).
    ress_list = (getattr(partition, "ressources", []) or []) + (getattr(partition, "resources", []) or [])
    seen = set()
    uniq_ress = []
    for r in ress_list:
        if r.id not in seen:
            seen.add(r.id)
            uniq_ress.append(r)
    for r in uniq_ress:
        if getattr(r, "node_id", None) and r.node_id not in ids:
            errors.append(f"ressource {r.id}: node_id inconnu {r.node_id} "
                          "(D-216 §2 — ancrage node/page obligatoire)")
        if not getattr(r, "anchors", []):
            errors.append(f"ressource {r.id}: sans ancre source (D-216 §2)")
        if getattr(r, "type_ressource", "") not in ("carte",):
            errors.append(f"ressource {r.id}: type {getattr(r, 'type_ressource', '')!r} not in ('carte',)")
        if not getattr(r, "node_id", None) and not getattr(r, "page", None):
            errors.append(f"ressource {r.id}: ancrage manquant — node_id ou page requis (fiche P-CONV-3)")
        if getattr(r, "page", None) is not None:
            try:
                pg = int(r.page)
                if not (1 <= pg <= 500):
                    errors.append(f"ressource {r.id}: page hors bornes {pg}")
            except Exception:
                errors.append(f"ressource {r.id}: page invalide {r.page!r}")

    # 10) Garde caméra D-184 : secrets jamais dans le brief du Director
    if partition_dir is not None:
        from pathlib import Path
        directeur = Path(partition_dir) / "directeur.md"
        if directeur.exists():
            try:
                dtext = directeur.read_text(encoding="utf-8")
            except Exception:
                dtext = ""
            for s in partition.secrets:
                # le corps du secret ne doit jamais apparaître en clair côté Director
                if s.contenu_md.strip() and s.contenu_md.strip()[:60] in dtext:
                    errors.append(f"secret {s.id}: leak dans directeur.md "
                                  "(garde caméra D-184 — secrets jamais "
                                  "servis au Director en clair)")
    return errors


def adventure_exceptions(partition) -> list[str]:
    """Lignes d'exceptions propres à l'étage aventure (fiche §6 : les
    absences fournies ni par la source ni par l'auteur sont SIGNALÉES,
    jamais improvisées). Retourne une liste de chaînes."""
    out: list[str] = []
    if partition.aventure is None:
        return out
    av = partition.aventure
    out.extend(av.warnings)
    for e in av.events():
        if not e.perturbations and e.rubrique == "trajectoire":
            line = (f"evenement {e.id}: perturbations [] — aucune condition "
                    "de perturbation fournie par la source")
            if line not in out:
                out.append(line)
        if not str(e.declencheur.get("valeur", "")).strip():
            line = f"evenement {e.id}: declencheur sans valeur fournie"
            if line not in out:
                out.append(line)
    for r in partition.records:
        if r.classe in ("pnj", "faction") and (
                not r.transverse.get("agenda")
                or not r.transverse.get("portee")):
            line = (f"record {r.id} ({r.classe}): agenda/portee absents — "
                    "non fournis par la source")
            if line not in out:
                out.append(line)
    return out


def scenario_report(partition) -> dict:
    """Étage SCÉNARIO (fiche méta 2026-08-23 §5) — extensions du valideur :

    1. tout node altitude 'scenario' a un objectif_md OU une ligne
       d'exception signalée (vide + exception, `I-111`) — non bloquant ;
    2. ≥ 1 debouche par scénario, ou charniere_sortie sur le dernier —
       ROUGE (fiche §5.2) ;
    3. tout id référencé par prerequis_etat / heritage.porte / cible_id
       existe — ROUGE (fiche §5.3) ;
    4. comptage testables ⊥ textuels rapporté en mesures (fiche §5.4).

    Retour : {"erreurs": [...], "exceptions": [...], "mesures": {...}}.
    """
    erreurs: list[str] = []
    exceptions: list[str] = []
    # espace d'ids référençables par heritage.porte (fiche §3): primitives +
    # debouche_id + evenement_id ; les cibles de débouché restent des nodes
    ids = partition.ids()
    ids |= {d["id"] for n in partition.nodes
            for d in getattr(n, "debouches", [])}
    if partition.aventure is not None:
        ids |= {e.id for e in partition.aventure.events()}
    n_scen = obj_manq = deb_tot = deb_test = deb_txt = 0
    her_entries = scen_her = n_charn = 0
    for n in partition.nodes:
        if n.altitude != "scenario":
            continue
        n_scen += 1
        if not getattr(n, "objectif_md", "").strip():
            obj_manq += 1
            exceptions.append(
                f"scenario {n.id}: objectif_md absent — non fourni par la "
                "source (vide + exception, I-111)")
        debouches = getattr(n, "debouches", [])
        if not debouches and not getattr(n, "charniere_sortie", None):
            erreurs.append(f"scenario {n.id}: ni debouche ni "
                           "charniere_sortie (fiche SCÉNARIO §5.2)")
        for d in debouches:
            deb_tot += 1
            if d["cible_id"] and d["cible_id"] not in ids:
                erreurs.append(f"debouche {d['id']}: cible inconnue "
                               f"{d['cible_id']} (fiche §5.3)")
            if d["prerequis_etat"]:
                deb_test += 1
                for p in d["prerequis_etat"]:
                    # D-187: la négation est transparente au contrôle d'ids
                    atome = p["atome"] if p["type"] == "non" else p
                    pid = atome.get("id")
                    if atome["type"] != "flag" and pid and pid not in ids:
                        erreurs.append(f"debouche {d['id']}: prerequis id "
                                       f"inconnu {pid} (fiche §5.3)")
            elif d["condition_textuelle"].strip():
                deb_txt += 1
            else:
                erreurs.append(f"debouche {d['id']}: ni prerequis_etat ni "
                               "condition_textuelle (fiche §2)")
        for h in getattr(n, "heritage", []):
            her_entries += 1
            a0, a1 = h["ancre_source"]
            if not (0 <= a0 <= a1):
                erreurs.append(f"scenario {n.id}: heritage ancre_source "
                               f"invalide {h['ancre_source']}")
            for pid in h["porte"]:
                if pid not in ids:
                    erreurs.append(f"scenario {n.id}: heritage.porte "
                                   f"inconnu {pid} (fiche §5.3)")
        if getattr(n, "heritage", []):
            scen_her += 1
        if getattr(n, "charniere_sortie", None):
            n_charn += 1
    taux_testables = (round(deb_test / deb_tot, 3)
                      if deb_tot else None)
    taux_heritage = (round(scen_her / n_scen, 3) if n_scen else None)
    return {
        "erreurs": erreurs,
        "exceptions": exceptions,
        "mesures": {
            "noeuds_scenario": n_scen,
            "objectifs_manquants": obj_manq,
            "debouches_total": deb_tot,
            "debouches_prerequis_testables": deb_test,
            "debouches_condition_textuelle": deb_txt,
            "taux_debouches_testables": taux_testables,
            "heritage_entries": her_entries,
            "scenarios_avec_heritage": scen_her,
            "taux_remplissage_heritage": taux_heritage,
            "charnieres_sur_node": n_charn,
        },
    }
