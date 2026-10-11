"""D-404/D-415 (chantier 3) : le rôle du Director produit, servi par le
moteur, et le tour du régime principal — la table relance un Director neuf
à chaque tour.

Ce test, 100 % synthétique (D-109, zéro matériau de campagne réel), couvre :

  1. `photo_director` sur une save synthétique au jeu actif : la première
     section est « Rôle (Director) », son texte est celui de
     `coderain/roles/director.md` (titres internes du rôle abaissés d'un
     niveau, voir point 1d) ; « Personnage joué », « Fiche de personnage »,
     les règles RPG et les derniers tours sont présents ; `DIRECTOR_SYS` n'y
     est pas (aucune de ses phrases repères).
  2. Le rôle ne porte plus « sur papier » ; il porte « Fin du tour »,
     `paquet_narrateur` et `actor`.
  3. Chaque nom d'outil appelé (identifiant suivi de `(`) entre backquotes
     dans `coderain/roles/director.md` existe comme outil MCP du serveur ;
     chaque outil listé dans `coderain/roles/agents/director.md` existe
     aussi (garde anti-dérive rôle/moteur) ; `coderain/roles/agents/
     narrateur.md` porte `model: sonnet` et `effort: low` ;
     `coderain/roles/agents/boucheur.md` ne porte aucun outil. Les trois
     fichiers doivent exister — aucun saut silencieux si l'un manque.
  4. `paquet_narrateur` ne sert jamais la section « Rôle (Director) »
     (inchangé, à revérifier).
  5. Le préfixe stable de la photo du Director est identique entre deux
     tours sans changement de position.
  6. Défaut mesuré (chantier 3, correctif) : les titres internes du rôle
     (`## Trois gestes`/`## Le moteur`/`## La visée`/`## Fin du tour`) ne
     doivent jamais apparaître comme des sections de la photo — la photo ne
     porte qu'une seule ligne `## Rôle (Director)`, ces quatre titres sont
     abaissés en `### `, et `sections` (rendu par `photo_director`) ne les
     contient pas.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition
from coderain.memory import Entry
from coderain import assembleur_position as ap
from coderain import validator as validator_mod

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


ROLE_PATH = ROOT / "coderain" / "roles" / "director.md"
AGENT_DIRECTOR_PATH = ROOT / "coderain" / "roles" / "agents" / "director.md"
AGENT_NARRATEUR_PATH = ROOT / "coderain" / "roles" / "agents" / "narrateur.md"
AGENT_BOUCHEUR_PATH = ROOT / "coderain" / "roles" / "agents" / "boucheur.md"

NOM = "Sora Veil"
GENRE = "femme — elle ; accords au féminin"


def _manifest():
    return Manifest(titre="module factice D-404/D-415", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="6" * 64,
                    date_conversion="2026-10-11T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil",
        "Vous êtes devant une porte close ; votre torche grésille.",
        "scenario", anchors=[(0, 40)],
        objectif_md="Franchir le seuil, quoi qu'il advienne."))
    p.aventure = None
    return p


TMP = Path(tempfile.gettempdir()) / "se_role_director_d404_d415"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)

mcp_server._engine = None       # pas d'Engine chargé — le pont MCP seul
mcp_server._last_applied_events = None

try:
    # --- fixture : une save RPG, au jeu actif, avec position valide -------
    app_dir = TMP / "app"
    lib = mcp_server.Library(app_dir)
    slug = lib.saves.create("Test D-404/D-415", premise="Un seuil.",
                            mode="rpg")
    (lib.saves.dir(slug) / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    projection.derive(partition_dir, app_dir, slug, corpus_dir=TMP / "corpus")
    store = lib.store(slug)

    # Personnage joué (I-15/I-18) : nom + genre explicite.
    store.upsert_entry("player.md", Entry(
        title=NOM, slug="player", importance=5,
        attrs={"status": "prête au combat", "genre": GENRE},
        body="Identity: combattante de test (D-109), sans lien avec un "
             "module joué.\n"))

    # Fiche mécanique (I-17) : stats + niveau, pour servir « Fiche de
    # personnage » + « RPG MODULE (mechanics ON) ».
    rpg = store.rpg_state()
    rpg.setdefault("player", {})["stats"] = {"strength": 3, "agility": 2}
    rpg["player"]["level"], rpg["player"]["hp"], rpg["player"]["hp_max"] = \
        4, 14, 14
    store.set_rpg_state(rpg)

    # Position valide (I-219 : player.location est la seule source lue par
    # current_location) — condition d'eligible() pour le chemin position.
    state = store.world_state()
    state.setdefault("player", {})["location"] = "para-01"
    store.set_world_state(state)

    # Derniers tours (pour la section « DERNIERS TOURS ») — déjà journalisés
    # au moteur, comme le ferait record_turn.
    store.append_turn("player", "J'observe la porte close.")
    store.append_turn("narrator", "La torche grésille dans le silence.")

    mcp_server._store = store
    mcp_server._slug = slug
    mcp_server._last_applied_events = None

    role_text = ROLE_PATH.read_text(encoding="utf-8")

    # --- 1) photo_director : Rôle (Director) en tête, le reste du paquet --
    result = mcp_server.photo_director("J'observe la porte close.")
    texte = Path(result["path"]).read_text(encoding="utf-8")

    role_text_abaisse = re.sub(r"(?m)^## ", "### ", role_text).strip()
    attendu_role = "## Rôle (Director)\n" + role_text_abaisse
    assert texte.startswith(attendu_role), \
        (f"« Rôle (Director) » devrait être la PREMIÈRE section, texte "
         f"celui de coderain/roles/director.md (titres internes abaissés "
         f"d'un niveau) -> {texte[:4000]!r}")
    section("1a) photo_director : « Rôle (Director) » en tête, texte "
           "identique à coderain/roles/director.md (titres internes "
           "abaissés)")

    assert "Personnage joué" in texte and NOM in texte, \
        f"« Personnage joué »/nom absents -> {texte[:4000]!r}"
    assert "Fiche de personnage" in texte, \
        f"« Fiche de personnage » absente -> {texte[:4000]!r}"
    assert "RPG MODULE (mechanics ON)" in texte, \
        f"« RPG MODULE (mechanics ON) » absente -> {texte[:4000]!r}"
    assert "DERNIERS TOURS" in texte, \
        f"les derniers tours devraient être servis -> {texte[:4000]!r}"
    section("1b) photo_director : Personnage joué, Fiche de personnage, "
           "RPG MODULE, derniers tours — tous présents")

    assert "LOGIC AGENT" not in texte, \
        f"DIRECTOR_SYS (LOGIC AGENT) ne devrait jamais atteindre " \
        f"photo_director -> {texte[:2000]!r}"
    assert "CONVERSATION D'ACCORD" not in texte, \
        f"DIRECTOR_SYS (CONVERSATION D'ACCORD) ne devrait jamais " \
        f"atteindre photo_director -> {texte[:2000]!r}"
    section("1c) photo_director : DIRECTOR_SYS absent (aucune phrase repère)")

    # --- 1d) les titres internes du rôle n'apparaissent jamais comme des --
    # --- sections de la photo (défaut mesuré, correctif chantier 3) -------
    lignes_h2 = [l for l in texte.splitlines() if l.startswith("## ")]
    assert lignes_h2.count("## Rôle (Director)") == 1, \
        (f"la photo devrait porter EXACTEMENT une ligne « ## Rôle "
         f"(Director) » -> {lignes_h2}")
    for titre_interne in ("## Trois gestes", "## Le moteur", "## La visée",
                         "## Fin du tour"):
        assert titre_interne not in lignes_h2, \
            (f"le titre interne du rôle « {titre_interne} » ne devrait "
             f"jamais apparaître comme une ligne « ## » de la photo "
             f"(devrait être abaissé en « ### ») -> {lignes_h2}")
        assert titre_interne.replace("## ", "### ") in texte, \
            f"« {titre_interne} » devrait apparaître abaissé en `### ` -> " \
            f"{texte[:4000]!r}"
    sections_rendues = result["sections"]
    for titre_interne in ("Trois gestes", "Le moteur", "La visée",
                         "Fin du tour"):
        assert titre_interne not in sections_rendues, \
            (f"« {titre_interne} » ne devrait jamais apparaître dans "
             f"`sections` (rendu de photo_director) -> {sections_rendues}")
    assert "Rôle (Director)" in sections_rendues, \
        f"« Rôle (Director) » devrait apparaître dans `sections` -> " \
        f"{sections_rendues}"
    section("1d) les titres internes du rôle (Trois gestes/Le moteur/La "
           "visée/Fin du tour) n'apparaissent ni comme ligne `## ` de la "
           "photo ni dans `sections` — une seule `## Rôle (Director)`")

    # --- 2) le rôle produit : plus « sur papier », porte « Fin du tour » --
    assert "sur papier" not in role_text, \
        "le rôle ne devrait plus porter la section « sur papier »"
    assert "Fin du tour" in role_text, \
        "le rôle devrait porter la section « Fin du tour »"
    assert "paquet_narrateur" in role_text, \
        "le rôle devrait citer paquet_narrateur (l'unique canal narrateur)"
    assert "actor" in role_text, \
        "le rôle devrait toujours porter `actor` (roll_check)"
    section("2) coderain/roles/director.md : « sur papier » retiré, "
           "« Fin du tour »/`paquet_narrateur`/`actor` présents")

    # --- 3) garde anti-dérive : chaque outil cité existe au serveur MCP ---
    tools = asyncio.run(mcp_server.mcp.list_tools())
    tool_names = {t.name for t in tools}

    outils_role = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)\(", role_text))
    assert outils_role, "aucun outil backquoté trouvé dans le rôle — regex ?"
    manquants_role = sorted(outils_role - tool_names)
    assert not manquants_role, \
        (f"outil(s) cité(s) par coderain/roles/director.md absent(s) du "
         f"serveur MCP (dérive rôle/moteur) : {manquants_role}")
    section("3a) chaque outil cité dans coderain/roles/director.md existe "
           "au serveur MCP")

    assert AGENT_DIRECTOR_PATH.exists(), \
        (f"coderain/roles/agents/director.md manquant — devrait porter, en "
         f"`tools:`, la forme `mcp__coderain-engine__<outil>` pour chaque "
         f"outil du rôle ({sorted(outils_role)})")
    agent_texte = AGENT_DIRECTOR_PATH.read_text(encoding="utf-8")
    outils_agent = set(re.findall(r"mcp__coderain-engine__([A-Za-z_]\w*)",
                                  agent_texte))
    assert outils_agent, \
        "coderain/roles/agents/director.md devrait lister au moins un outil MCP"
    manquants_agent = sorted(outils_agent - tool_names)
    assert not manquants_agent, \
        (f"outil(s) listé(s) par coderain/roles/agents/director.md "
         f"absent(s) du serveur MCP : {manquants_agent}")
    section("3b) chaque outil listé dans coderain/roles/agents/director.md "
           "existe au serveur MCP")

    assert AGENT_NARRATEUR_PATH.exists(), \
        "coderain/roles/agents/narrateur.md manquant"
    narrateur_texte = AGENT_NARRATEUR_PATH.read_text(encoding="utf-8")
    assert re.search(r"^model:\s*sonnet\s*$", narrateur_texte, re.MULTILINE), \
        (f"coderain/roles/agents/narrateur.md devrait porter `model: "
         f"sonnet` -> {narrateur_texte[:500]!r}")
    assert re.search(r"^effort:\s*low\s*$", narrateur_texte, re.MULTILINE), \
        (f"coderain/roles/agents/narrateur.md devrait porter `effort: low` "
         f"(D-417) -> {narrateur_texte[:500]!r}")
    section("3c) coderain/roles/agents/narrateur.md existe, porte "
           "`model: sonnet` et `effort: low`")

    assert AGENT_BOUCHEUR_PATH.exists(), \
        "coderain/roles/agents/boucheur.md manquant"
    boucheur_texte = AGENT_BOUCHEUR_PATH.read_text(encoding="utf-8")
    front_boucheur = boucheur_texte.split("---", 2)[1]
    assert re.search(r"^tools:\s*\[\s*\]\s*$", front_boucheur, re.MULTILINE), \
        (f"coderain/roles/agents/boucheur.md devrait porter `tools: []` "
         f"(aucun outil) -> {front_boucheur!r}")
    section("3d) coderain/roles/agents/boucheur.md existe, ne porte aucun "
           "outil")

    # --- 4) paquet_narrateur : jamais la section « Rôle (Director) » ------
    paquet = mcp_server.paquet_narrateur(
        "Angle : calme avant la porte.", "J'observe la porte close.",
        sans_mecanique=True)
    texte_narrateur = Path(paquet["path"]).read_text(encoding="utf-8")
    assert "Rôle (Director)" not in texte_narrateur, \
        (f"paquet_narrateur ne doit JAMAIS servir « Rôle (Director) » -> "
         f"{texte_narrateur[:2000]!r}")
    section("4) paquet_narrateur : toujours sans « Rôle (Director) »")

    # --- 5) préfixe stable identique entre deux tours sans transition -----
    history = store.turns()
    sections_t1 = ap.build_sections(
        partition_dir, store, "para-01", history,
        "J'observe la porte close.", rpg_on=True, director_sys=False,
        director_role=role_text)
    sections_t2 = ap.build_sections(
        partition_dir, store, "para-01", history,
        "J'observe encore la porte close.", rpg_on=True, director_sys=False,
        director_role=role_text)
    assert ap.stable_prefix(sections_t1) == ap.stable_prefix(sections_t2), \
        "le préfixe stable devrait être byte-identique entre deux tours " \
        "sans changement de position"
    section("5) préfixe stable de la photo du Director identique entre "
           "deux tours sans changement de position")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nOK test-role-director-d404-d415 — {len(FAIT)} sections vertes")
