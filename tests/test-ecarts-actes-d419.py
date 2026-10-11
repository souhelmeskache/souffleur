"""D-419 : un écart déjà acté par la partie doit primer sur le texte d'un
nœud, pas seulement être suivi 2 fois sur 5 par un Director neuf (appel sans
mémoire). Mesuré sur papier : un Director neuf suit le texte du nœud même
contredit 2 fois sur 5 ; servi COLLÉ au texte du nœud avec la mention qu'il
prime, 5 sur 5. Aujourd'hui, un écart acté n'était rangé nulle part dans la
save.

Ce test, 100 % synthétique (D-109, zéro matériau de campagne réel), couvre :

  1. `validator.validate()` : un `ecart_acte` bien formé est accepté ; chaque
     cas mal formé est refusé, nommé (liste absente/mal formée, noeud vide,
     noeud inconnu de la partition chargée, texte vide, texte > 300
     caractères).
  2. L'application (`Engine.apply_envelope` -> `validator.apply_world`)
     range l'écart dans `state.json` sous `ecarts: {noeud: [texte, ...]}`,
     sans doublon exact (même texte reposé deux fois -> une seule entrée ;
     un texte différent sur le même nœud -> ajouté).
  3. L'annulation d'un tour (`Engine.restore_pre_turn_rpg`, la même chaîne
     que `undo_last`/`retry_turn`) défait un écart posé CE tour — l'état est
     restauré par instantané (`validator.snapshot_state`), ce test le
     vérifie.
  4. La photo du Director (chemin MCP, `mcp_server.assemble_context_to_file`)
     porte le bloc "Écarts déjà actés sur ce nœud (ils priment sur le texte
     ci-dessus) :" et le texte de l'écart, placé APRÈS le texte du nœud
     courant et AVANT l'objectif de la scène ; l'écart d'un AUTRE nœud
     n'apparaît jamais dans cette photo.
  5. Le paquet du narrateur (`mcp_server.paquet_narrateur`) porte le même
     bloc pour le nœud courant.
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

from coderain.config import load_config
from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition
from coderain.engine import Engine
from coderain.memory import Library
from coderain import assembleur_position as ap
from coderain import validator as validator_mod

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def _manifest():
    return Manifest(titre="module factice D-419", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="4" * 64,
                    date_conversion="2026-10-11T00:00:00+00:00",
                    version_convertisseur="test")


def _lien(cible_id: str) -> dict:
    return {"cible_id": cible_id, "condition_textuelle": ""}


def _build_partition() -> Partition:
    """Deux nœuds : para-01 (scénario, objectif + lien) où vit l'écart
    testé, para-02 (scène nue) qui ne doit JAMAIS voir l'écart de l'autre."""
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil",
        "Vous êtes devant une porte close ; votre torche grésille.",
        "scenario", liens=[_lien("para-02")], anchors=[(0, 40)],
        objectif_md="Franchir le seuil, quoi qu'il advienne."))
    p.nodes.append(Node(
        "para-02", "scene", "Le couloir",
        "Un couloir humide s'enfonce dans le noir.",
        "scene", anchors=[(0, 40)]))
    p.aventure = None
    return p


def _save_with_partition(root: Path, partition_dir: Path, titre: str,
                         location: str = "para-01"):
    lib = Library(root)
    slug = lib.create_story(titre, "Un donjon oublié, version factice.")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    store = lib.store(slug)
    state = store.world_state()
    state.setdefault("player", {})["location"] = location
    store.set_world_state(state)
    return lib, slug, store


TMP = Path(tempfile.gettempdir()) / "se_ecarts_actes_d419"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)

cfg = load_config()
cfg.generation["trinity_brain"] = False

TEXTE_OK = "le personnage a vendu sa torche au marché il y a trois tours"
TEXTE_PARA01 = ("la torche a été vendue au marché il y a trois tours ; "
               "elle ne grésille plus")
TEXTE_PARA02 = "le pont de pierre s'est déjà effondré sous le chariot"

try:
    # --- 1) validate() : bien formé -> accepté ; chaque refus nommé --------
    lib_a, slug_a, store_a = _save_with_partition(
        TMP / "app-validate", partition_dir, "Garde — validate", "para-01")

    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": TEXTE_OK}]}}, store_a)
    assert rejected == [], rejected
    assert clean["deltas"]["ecart_acte"] == [
        {"noeud": "para-01", "texte": TEXTE_OK}], clean
    section("1a) ecart_acte bien formé (noeud connu, texte <= 300) -> accepté")

    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"ecart_acte": "pas une liste"}}, store_a)
    assert "ecart_acte" not in clean.get("deltas", {}), clean
    assert len(rejected) == 1 and rejected[0]["delta"] == "ecart_acte", rejected
    section("1b) ecart_acte pas une liste -> refusé, nommé")

    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"ecart_acte": ["pas un objet"]}}, store_a)
    assert "ecart_acte" not in clean.get("deltas", {}), clean
    assert len(rejected) == 1 and rejected[0]["delta"] == "ecart_acte", rejected
    section("1c) élément de la liste pas un objet -> refusé, nommé")

    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "", "texte": TEXTE_OK}]}}, store_a)
    assert "ecart_acte" not in clean.get("deltas", {}), clean
    assert len(rejected) == 1 and rejected[0]["delta"] == "ecart_acte", rejected
    assert "noeud" in rejected[0]["reason"], rejected
    section("1d) noeud vide -> refusé, nommé")

    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "nimporte-quoi-hors-partition", "texte": TEXTE_OK}]}},
        store_a)
    assert "ecart_acte" not in clean.get("deltas", {}), clean
    assert len(rejected) == 1, rejected
    assert rejected[0]["delta"] == "ecart_acte:nimporte-quoi-hors-partition", \
        rejected
    section("1e) noeud inconnu de la partition chargée -> refusé, nommé "
           "(réutilise la lecture de nœuds de la garde `location`, D-282 "
           "règle 1)")

    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": "   "}]}}, store_a)
    assert "ecart_acte" not in clean.get("deltas", {}), clean
    assert len(rejected) == 1 and rejected[0]["delta"] == "ecart_acte:para-01", \
        rejected
    section("1f) texte vide -> refusé, nommé")

    trop_long = "x" * 301
    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": trop_long}]}}, store_a)
    assert "ecart_acte" not in clean.get("deltas", {}), clean
    assert len(rejected) == 1 and rejected[0]["delta"] == "ecart_acte:para-01", \
        rejected
    assert "301" in rejected[0]["reason"], rejected
    section("1g) texte > 300 caractères -> refusé, nommé")

    # --- sans partition chargée : refus explicite (même garde que location) -
    lib_np = Library(TMP / "app-sans-partition")
    slug_np = lib_np.create_story("Sans partition", "Monde vide.")
    store_np = lib_np.store(slug_np)
    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": TEXTE_OK}]}}, store_np)
    assert "ecart_acte" not in clean.get("deltas", {}), clean
    assert len(rejected) == 1 and rejected[0]["delta"] == "ecart_acte", rejected
    section("1h) aucune partition chargée -> refus explicite (même garde "
           "que `location`, #281)")

    # --- 2) application : rangé sous state.json, sans doublon --------------
    lib_b, slug_b, store_b = _save_with_partition(
        TMP / "app-apply", partition_dir, "Application", "para-01")
    eng_b = Engine(cfg, store_b)
    events = eng_b.apply_envelope(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": TEXTE_OK}]}}, rpg_on=False,
        log_turn=1)
    assert any("écart acté sur para-01" in e for e in events), events
    state_b = store_b.world_state()
    assert state_b["ecarts"] == {"para-01": [TEXTE_OK]}, state_b
    section("2a) ecart_acte validé -> rangé sous state.json['ecarts']")

    events = eng_b.apply_envelope(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": TEXTE_OK}]}}, rpg_on=False,
        log_turn=2)
    state_b = store_b.world_state()
    assert state_b["ecarts"] == {"para-01": [TEXTE_OK]}, state_b
    assert not any("écart acté" in e for e in events), events
    section("2b) même écart reposé -> aucun doublon (liste inchangée)")

    autre_texte = "le personnage porte désormais une lanterne à huile"
    eng_b.apply_envelope(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": autre_texte}]}}, rpg_on=False,
        log_turn=3)
    state_b = store_b.world_state()
    assert state_b["ecarts"] == {"para-01": [TEXTE_OK, autre_texte]}, state_b
    section("2c) texte différent sur le même nœud -> ajouté (pas un repli "
           "sur le premier)")

    # --- 3) annulation d'un tour défait l'écart posé CE tour ---------------
    lib_c, slug_c, store_c = _save_with_partition(
        TMP / "app-rollback", partition_dir, "Rollback", "para-01")
    eng_c = Engine(cfg, store_c)
    eng_c._pre_turn_rpg = eng_c._snapshot_rpg()
    eng_c._pre_turn_reveals, eng_c._pre_turn_canon, eng_c._pre_turn_events = \
        [], [], []
    eng_c.apply_envelope(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": TEXTE_OK}]}}, rpg_on=False,
        log_turn=1)
    assert store_c.world_state().get("ecarts") == {"para-01": [TEXTE_OK]}, \
        store_c.world_state()
    eng_c.restore_pre_turn_rpg()
    assert not store_c.world_state().get("ecarts"), store_c.world_state()
    sections_c = ap.build_sections(partition_dir, store_c, "para-01", [],
                                   "", director_sys=False)
    scene_c = next(s for s in sections_c
                   if s.title.startswith("Scène courante"))
    assert "Écarts déjà actés" not in scene_c.render(), scene_c.render()
    section("3) l'annulation du tour (restore_pre_turn_rpg, même chaîne que "
           "undo_last/retry_turn) défait l'écart posé ce tour — restauré "
           "par instantané (validator.snapshot_state) ; la photo ne porte "
           "plus le bloc une fois l'écart défait")

    # --- 4/5) la photo sert l'écart sous le nœud, jamais celui d'un autre --
    lib_d, slug_d, store_d = _save_with_partition(
        TMP / "app-photo", partition_dir, "Photo", "para-01")
    projection.derive(partition_dir, TMP / "app-photo", slug_d,
                      corpus_dir=TMP / "corpus")
    store_d = lib_d.store(slug_d)
    eng_d = Engine(cfg, store_d)
    eng_d.apply_envelope(
        {"v": 1, "deltas": {"ecart_acte": [
            {"noeud": "para-01", "texte": TEXTE_PARA01},
            {"noeud": "para-02", "texte": TEXTE_PARA02}]}}, rpg_on=False,
        log_turn=1)
    state_d = store_d.world_state()
    assert state_d["ecarts"] == {"para-01": [TEXTE_PARA01],
                                 "para-02": [TEXTE_PARA02]}, state_d

    mcp_server._engine = None
    mcp_server._store = store_d
    mcp_server._slug = slug_d
    mcp_server._last_applied_events = None

    result = mcp_server.assemble_context_to_file("J'observe la porte.")
    texte_director = Path(result["path"]).read_text(encoding="utf-8")
    assert "Écarts déjà actés sur ce nœud (ils priment sur le texte " \
          "ci-dessus) :" in texte_director, texte_director[:2000]
    assert TEXTE_PARA01 in texte_director, texte_director[:2000]
    assert TEXTE_PARA02 not in texte_director, \
        "l'écart de para-02 ne doit jamais apparaître dans la photo de " \
        "para-01 -> " + texte_director[:3000]
    idx_corps = texte_director.index("votre torche grésille")
    idx_ecart = texte_director.index("Écarts déjà actés")
    idx_objectif = texte_director.index("Objectif de la scène")
    assert idx_corps < idx_ecart < idx_objectif, \
        (idx_corps, idx_ecart, idx_objectif, texte_director[:3000])
    section("4) photo du Director (chemin MCP, assemble_context_to_file) : "
           "bloc + texte de l'écart, après le texte du nœud, avant "
           "l'objectif ; aucun bloc pour un autre nœud")

    paquet = mcp_server.paquet_narrateur(
        "Angle : la torche promise ne grésillera pas.",
        "J'observe la porte.", sans_mecanique=True)
    texte_narrateur = Path(paquet["path"]).read_text(encoding="utf-8")
    assert "Écarts déjà actés sur ce nœud (ils priment sur le texte " \
          "ci-dessus) :" in texte_narrateur, texte_narrateur[:2000]
    assert TEXTE_PARA01 in texte_narrateur, texte_narrateur[:2000]
    assert TEXTE_PARA02 not in texte_narrateur, texte_narrateur[:3000]
    section("5) paquet du narrateur (mcp_server.paquet_narrateur) : même "
           "bloc pour le nœud courant")

    # --- section de l'AUTRE nœud : porte SON écart, jamais celui de para-01-
    history = store_d.turns()
    sections_para02 = ap.build_sections(partition_dir, store_d, "para-02",
                                        history, "", director_sys=False)
    scene_para02 = next(s for s in sections_para02
                        if s.title.startswith("Scène courante"))
    assert TEXTE_PARA02 in scene_para02.render(), scene_para02.render()
    assert TEXTE_PARA01 not in scene_para02.render(), scene_para02.render()
    section("6) build_sections sur para-02 : porte SON écart (TEXTE_PARA02), "
           "jamais celui de para-01 — l'isolation par nœud marche dans les "
           "deux sens")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nOK test-ecarts-actes-d419 — {len(FAIT)} sections vertes")
