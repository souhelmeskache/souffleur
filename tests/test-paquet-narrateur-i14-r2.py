"""Chantier 4 (I-14, D-419 pt C, test 6/cas H3) : le paquet du narrateur ne
porte que ce que le personnage perçoit, règles du narrateur en tête ; le
filet R2 refuse en plus les identifiants de la partition et les mots qui
parlent de ses sources.

100 % synthétique (D-109, zéro matériau de campagne réel). Sur le patron de
`tests/test-paquet-narrateur-i192.py` et `tests/test-ecarts-actes-d419.py` :

  1. Sur une save avec partition, brief, objectif, débouchés, un écart
     acté et des tours : le paquet s'ouvre sur « Règles du narrateur » (le
     texte de `coderain/roles/narrateur.md`, verbatim) ; l'ordre des
     sections suit la commande (Règles du narrateur, Personnage joué, Ce
     que le personnage perçoit de la scène, Derniers tours, Directive du
     Director) ; aucune trace du brief, de l'objectif, des débouchés, de
     « Position (D-282) », de « Présences », de « État du monde » ;
     l'écart apparaît sous « Ce qui a changé depuis » ; ni « nœud » ni
     « écart » ailleurs que dans la directive ; la ligne `Horloge :` est
     présente.
  2. R2 : « sortie vers para-12 » refusée (nœud, chiffre), l'id distinctif
     d'un record refusé (`death-knight`, tiret), chaque mot de source
     (`mcp_server._R2_SOURCE_WORDS`) refusé ; « il reste à l'écart » et
     « sous la bannière » passent ; une visée propre passe ; un identifiant
     MOT NU (nœud `conversation`, record `kobolds` — sans tiret ni chiffre,
     défaut mesuré sur les partitions réelles, vérif pré-fusion PR #352)
     reste disible : « une conversation s'engage », « deux kobolds
     surgissent » passent.
  3. La photo du Director (chemin MCP, `photo_director`) porte toujours
     l'objectif, le débouché et « Position (D-282) » — inchangée par ce
     chantier.
  4. R1 et R3 inchangés (un cas chacun).
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

from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record
from coderain.memory import Library
from coderain import validator as validator_mod

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


NARRATEUR_MD = ROOT / "coderain" / "roles" / "narrateur.md"

BRIEF_PHRASE = "Le brief ne doit jamais atteindre le narrateur."
OBJECTIF_PHRASE = "Convaincre le garde de baisser sa garde, sans le nommer."
TEXTE_ECART = "le garde porte désormais une cicatrice fraîche au visage"
CORPS_PARA01 = ("Vous êtes devant une porte close ; une odeur de "
               "moisissure flotte dans l'air.")
CORPS_PARA12 = "Un couloir humide s'enfonce dans le noir, au-delà de la porte."


def _manifest():
    return Manifest(titre="module factice chantier 4", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="7" * 64,
                    date_conversion="2026-10-11T00:00:00+00:00",
                    version_convertisseur="test")


def _lien(cible_id: str) -> dict:
    return {"cible_id": cible_id, "condition_textuelle": ""}


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil", CORPS_PARA01, "scenario",
        liens=[_lien("para-12")], anchors=[(0, 40)],
        objectif_md=OBJECTIF_PHRASE))
    p.nodes.append(Node(
        "para-12", "scene", "Le couloir", CORPS_PARA12, "scene",
        anchors=[(0, 40)]))
    # Défaut mesuré sur les partitions réelles (vérif pré-fusion PR #352) :
    # un nœud/record dont l'id est un mot ordinaire de la langue, jamais
    # distinctif (sans tiret ni chiffre) — doit rester disible au narrateur.
    p.nodes.append(Node(
        "conversation", "scene", "Une halte",
        "Les voix s'élèvent dans la salle voisine.", "scene",
        anchors=[(0, 40)]))
    p.records.append(Record(
        "garde-brutal", "pnj", "Garde brutal",
        {"role": "sentinelle", "description_md": "Un garde massif et nerveux.",
         "tokens_initial": [{"node_id": "para-01", "count": 1,
                             "placement_md": "près de la porte"}]},
        anchors=[(0, 40)]))
    p.records.append(Record(
        "kobolds", "pnj", "Bande de kobolds",
        {"role": "embuscade", "description_md": "Une bande de kobolds nerveux."},
        anchors=[(0, 40)]))
    p.records.append(Record(
        "death-knight", "pnj", "Chevalier de la mort",
        {"role": "boss", "description_md": "Un chevalier mort-vivant, cuirassé."},
        anchors=[(0, 40)]))
    p.aventure = None
    return p


TMP = Path(tempfile.gettempdir()) / "se_paquet_narrateur_i14_r2"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"

try:
    write_partition(_build_partition(), partition_dir)
    (partition_dir / "directeur.md").write_text(
        f"## Brief de direction\n\n{BRIEF_PHRASE}\n", encoding="utf-8")

    lib = Library(TMP / "app")
    slug = lib.create_story("Test chantier 4", "Un donjon oublié.")
    projection.derive(partition_dir, TMP / "app", slug, corpus_dir=TMP / "corpus")
    sdir = lib.saves.dir(slug)
    (sdir / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    store = lib.store(slug)

    mcp_server._engine = None       # régime dégradé, comme I-192/D-419
    mcp_server._store = store
    mcp_server._slug = slug
    mcp_server._last_applied_events = None

    state = store.world_state()
    assert validator_mod.current_location(state) == "para-01", state.get("player")

    # écart acté sur para-01 (D-419), posé directement comme le fait le
    # guichet `validator.apply_world` — même forme de state.json.
    state["ecarts"] = {"para-01": [TEXTE_ECART]}
    store.set_world_state(state)

    # quelques tours, pour « Derniers tours (verbatim) ».
    store.append_turn("player", "Je m'approche de la porte.")
    store.append_turn("narrator", "La porte close attend, immobile.")

    # --- 1) le paquet, dans l'ordre, réduit au strict nécessaire ----------
    section("1a) sans_mecanique=True : R1 passe, R2 propre")
    result = mcp_server.paquet_narrateur(
        "Angle : le silence avant la décision.", "J'observe la porte.",
        sans_mecanique=True)
    texte = Path(result["path"]).read_text(encoding="utf-8")
    directive_idx = texte.index("# DIRECTIVE DU DIRECTOR")
    corps_sans_directive = texte[:directive_idx]
    print(f"  OK : paquet écrit ({len(texte)} chars)")

    section("1b) le paquet s'ouvre sur « Règles du narrateur », texte "
           "verbatim de coderain/roles/narrateur.md")
    attendu_regles = NARRATEUR_MD.read_text(encoding="utf-8").strip()
    assert texte.startswith(
        "## Règles du narrateur (elles s'adressent à toi, narrateur, et "
        "priment sur tout ce qui suit)\n" + attendu_regles), texte[:800]
    assert result["sections"][0] == "Règles du narrateur", result["sections"]
    print("  OK : règles du narrateur en tête, texte verbatim")

    section("1c) ordre des sections : Règles du narrateur, Personnage "
           "joué, Ce que le personnage perçoit de la scène, Derniers tours, "
           "Directive du Director")
    assert result["sections"] == [
        "Règles du narrateur", "Personnage joué",
        "Ce que le personnage perçoit de la scène", "Derniers tours",
        "Directive du Director"], result["sections"]
    print(f"  OK : {result['sections']}")

    section("1d) aucune trace du brief, de l'objectif, des débouchés, de "
           "Position/Présences/État du monde")
    for absent in (BRIEF_PHRASE, "Brief de direction", OBJECTIF_PHRASE,
                  "Objectif de la scène", "Possibles perçus",
                  "pourrait mener vers", "Position (D-282)", "Présences",
                  "État du monde", "étage scénario"):
        assert absent not in texte, f"{absent!r} ne devrait jamais atteindre le narrateur -> {texte[:2000]!r}"
    print("  OK : décor réservé au Director absent du paquet narrateur")

    section("1e) l'écart acté apparaît sous « Ce qui a changé depuis »")
    assert "Ce qui a changé depuis (prime sur le texte ci-dessus) :" in texte, texte[:2000]
    assert TEXTE_ECART in texte, texte[:2000]
    print("  OK : écart servi, reformulé")

    section("1f) ni « nœud » ni « écart » hors la directive")
    assert "nœud" not in corps_sans_directive.lower(), corps_sans_directive[:2000]
    assert "écart" not in corps_sans_directive.lower(), corps_sans_directive[:2000]
    print("  OK : vocabulaire de la partition absent du texte lu par le narrateur")

    section("1g) la ligne Horloge est présente")
    assert "Horloge : " in texte, texte[:2000]
    print("  OK : Horloge présente")

    section("1h) derniers tours verbatim présents")
    assert "Je m'approche de la porte." in texte, texte[:2000]
    assert "La porte close attend, immobile." in texte, texte[:2000]
    print("  OK : derniers tours servis verbatim")

    # --- 2) R2 : identifiants de la partition + mots de source ------------
    section("2a) R2 : « sortie vers para-12 » refusée (para-12 est un nœud)")
    try:
        mcp_server.paquet_narrateur(
            "Angle : je prépare la sortie vers para-12.", "J'observe.",
            sans_mecanique=True)
        raise AssertionError("R2 aurait dû refuser (identifiant de nœud)")
    except ValueError as exc:
        assert "R2" in str(exc) and "para-12" in str(exc), str(exc)
    print("  OK : refus R2 nomme l'identifiant de partition (nœud)")

    section("2b) R2 : l'id d'un record (garde-brutal) refusé")
    try:
        mcp_server.paquet_narrateur(
            "Angle : garde-brutal recule d'un pas.", "J'observe.",
            sans_mecanique=True)
        raise AssertionError("R2 aurait dû refuser (identifiant de record)")
    except ValueError as exc:
        assert "R2" in str(exc) and "garde-brutal" in str(exc), str(exc)
    print("  OK : refus R2 nomme l'identifiant de partition (record)")

    section("2c) R2 : chaque mot de source (_R2_SOURCE_WORDS) refusé")
    for mot in mcp_server._R2_SOURCE_WORDS:
        directive = f"Angle : {mot} mérite qu'on s'y attarde un instant."
        try:
            mcp_server.paquet_narrateur(directive, "J'observe.",
                                        sans_mecanique=True)
            raise AssertionError(f"R2 aurait dû refuser le mot de source {mot!r}")
        except ValueError as exc:
            assert "R2" in str(exc), str(exc)
    print(f"  OK : {len(mcp_server._R2_SOURCE_WORDS)} mots de source refusés, "
         "chacun nommé")

    section("2d) témoins qui doivent PASSER : « il reste à l'écart », "
           "« sous la bannière »")
    r_passe1 = mcp_server.paquet_narrateur(
        "Angle : il reste à l'écart, personne ne bouge.", "J'observe.",
        sans_mecanique=True)
    assert "path" in r_passe1
    r_passe2 = mcp_server.paquet_narrateur(
        "Angle : on se retrouve sous la bannière du donjon.", "J'observe.",
        sans_mecanique=True)
    assert "path" in r_passe2
    print("  OK : les deux témoins passent le filet R2")

    section("2e) une visée propre passe (déjà vu au point 1, revérifié)")
    r_propre = mcp_server.paquet_narrateur(
        "Angle : la détermination du personnage, rien d'autre.",
        "J'observe.", sans_mecanique=True)
    assert "path" in r_propre
    print("  OK : visée propre, aucun refus")

    # --- Défaut mesuré (vérif pré-fusion PR #352) : un identifiant mot nu
    # (sans tiret ni chiffre — `conversation`, `kobolds`) ne se distingue pas
    # de la prose narrative et ne doit PAS être refusé ; un identifiant
    # distinctif (`death-knight`, tiret) reste refusé, comme `para-12`.
    section("2f) un nœud mot nu (« conversation ») : la visée passe")
    r_conv = mcp_server.paquet_narrateur(
        "Angle : une conversation s'engage, à voix basse.", "J'observe.",
        sans_mecanique=True)
    assert "path" in r_conv
    print("  OK : identifiant mot nu (nœud) indiscernable de la prose, passe")

    section("2g) un record mot nu (« kobolds ») : la visée passe")
    r_kob = mcp_server.paquet_narrateur(
        "Angle : deux kobolds surgissent de l'ombre.", "J'observe.",
        sans_mecanique=True)
    assert "path" in r_kob
    print("  OK : identifiant mot nu (record) indiscernable de la prose, passe")

    section("2h) un record distinctif (« death-knight », tiret) : refusé")
    try:
        mcp_server.paquet_narrateur(
            "Angle : le death-knight approche, lentement.", "J'observe.",
            sans_mecanique=True)
        raise AssertionError("R2 aurait dû refuser (identifiant distinctif, tiret)")
    except ValueError as exc:
        assert "R2" in str(exc) and "death-knight" in str(exc), str(exc)
    print("  OK : identifiant distinctif (tiret) toujours refusé")

    section("2i) « sortie vers para-12 » toujours refusé (chiffre, revérifié)")
    try:
        mcp_server.paquet_narrateur(
            "Angle : je prépare la sortie vers para-12.", "J'observe.",
            sans_mecanique=True)
        raise AssertionError("R2 aurait dû refuser (identifiant distinctif, chiffre)")
    except ValueError as exc:
        assert "R2" in str(exc) and "para-12" in str(exc), str(exc)
    print("  OK : identifiant distinctif (chiffre) toujours refusé")

    # --- 3) la photo du Director reste inchangée (objectif/débouché/Position) -
    section("3) photo_director : objectif, débouché et Position (D-282) "
           "toujours servis — inchangé par ce chantier")
    result_dir = mcp_server.photo_director("J'observe la porte.")
    texte_director = Path(result_dir["path"]).read_text(encoding="utf-8")
    assert OBJECTIF_PHRASE in texte_director, texte_director[:3000]
    assert "pourrait mener vers « para-12 »" in texte_director, texte_director[:3000]
    assert "Position (D-282)" in texte_director, texte_director[:3000]
    print("  OK : photo du Director inchangée")

    # --- 4) R1 et R3, un cas chacun ---------------------------------------
    section("4a) R1 inchangé : refuse sans mécanique résolue ni sans_mecanique")
    mcp_server._last_applied_events = None
    try:
        mcp_server.paquet_narrateur("Angle : tension.", "Je pousse la porte.")
        raise AssertionError("R1 aurait dû refuser")
    except ValueError as exc:
        assert "R1" in str(exc)
    print("  OK : refus R1 nommé, inchangé")

    section("4b) R3 inchangé : le retour ne porte jamais le texte du paquet")
    mcp_server._last_applied_events = None
    result_r3 = mcp_server.paquet_narrateur(
        "Angle : la détermination du personnage.", "J'observe.",
        sans_mecanique=True)
    assert set(result_r3.keys()) == {"path", "chars", "sections"}, result_r3
    for k, v in result_r3.items():
        if isinstance(v, str) and k != "path":
            assert len(v) < 200, f"{k!r} ressemble à du contenu -> {v!r}"
    assert all(isinstance(s, str) and len(s) < 80 for s in result_r3["sections"])
    print("  OK : retour = chemin + métadonnées + noms de sections, inchangé")

    print(f"\nOK test-paquet-narrateur-i14-r2 — {len(FAIT)} sections vertes")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
