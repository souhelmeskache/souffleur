"""D-260 lane (d) — Issue #132 : rejeu de la mesure I-158 sur la BOUCLE NEUVE
(assembleur keyé position, mergé : lanes (a) fb79593, (b) 2f75897, branchement
2060626). Mesure pure (même discipline qu'I-158, Issue #84) : aucune
optimisation, les écarts se consignent.

Corpus A — SYNTHÉTIQUE VERSIONNÉ (D-109, zéro matériau réel) : partition
factice projetée dans une save fraîche, `Engine._messages()` exercé de bout en
bout (mêmes couches que le jeu réel : `_augment_pack/_augment_style/
_augment_event_rules` par-dessus les sections STABLES/VOLATILES
d'`assembleur_position.build_sections` — rpg-rules.md et response_length y
sont désormais des sections stables, Issue #144, pas des couches `_augment_*`
additives comme avant ce correctif). Fait partie de la suite (`run_tests.py`),
assertions incluses.

Corpus B — RÉEL, HORS GIT (D-109/D-178) : si une save projetée existe
localement (pointeur explicite via `CODERAIN_MESURE_SAVE`, sinon la
convention `ttrpg-corpus/saves/<slug>` déjà utilisée par une partie jouée),
rejoue la même mesure dessus et imprime UNIQUEMENT des tailles agrégées —
aucun octet du contenu n'est écrit dans ce fichier ni ailleurs dans le repo.
Absent sur une machine qui n'a pas le dépôt privé `ttrpg-corpus` : cette
partie s'auto-saute (`SKIP`), le corpus A seul reste la garantie CI.

Rejeu : `python tests/mesure-d260-boucle-neuve.py`
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain import assembleur_position as ap
from coderain.config import Config, Profile
from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record, Secret
from coderain.engine import Engine
from coderain.memory import Library, MemoryStore

CHARS_PER_TOKEN = 4  # convention mesure I-158, coderain/memory.py:1309,1544

# Postes de non-construit chiffrés par I-158 (director-pipeline, budget=8000,
# save réelle planescape-vahn, 17 tours) — RÉFÉRENCE FIGÉE, pas re-mesurée
# (docs/mesure-i158-director-deux-corps.md §1).
I158_REGLES_PROSE_TOK = 5_196          # writer-rules.md dans store.assemble()
I158_ETAT_SANS_SELECTION_TOK = 7_951   # bloc STORY & MEMORY CONTEXT
I158_REGLES_EVENEMENT_TOK = 5_015      # event_rules_block(), Director-only
I158_TOTAL_TOK = 19_329


def _cfg(rpg_on: bool) -> Config:
    profile = Profile(name="mesure", base_url="http://localhost:0/v1",
                      model="mesure", api_key="unused", context_tokens=32_000)
    return Config(profile=profile,
                 generation={"trinity_brain": False, "max_tokens": 700},
                 memory={"context_budget_tokens": 8000},
                 rpg={"enabled": rpg_on}, retrieval={"enabled": False},
                 raw={})


def _engine(store: MemoryStore, rpg_on: bool) -> Engine:
    os.environ.setdefault("CODERAIN_NO_MODULES", "0")
    return Engine(_cfg(rpg_on), store)


# --------------------------------------------------------- corpus A fixture --
def _manifest() -> Manifest:
    return Manifest(titre="module factice D-260 (d)", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="0" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "Le seuil",
        "Vous êtes devant une porte close, gardée.", "scene",
        liens=[{"cible_id": "para-02",
               "condition_textuelle": "si vous forcez le passage"}],
        anchors=[(0, 40)]))
    p.nodes.append(Node(
        "para-02", "scene", "La salle des gardes",
        "Une torche brûle contre le mur du fond.", "scene",
        anchors=[(40, 80)]))
    p.records.append(Record(
        "garde-brutal", "pnj", "Garde brutal",
        {"role": "sentinelle", "description_md": "Un garde massif et nerveux.",
         "tokens_initial": [{"node_id": "para-01", "count": 1,
                             "placement_md": "contre la porte"}]},
        anchors=[(0, 40)]))
    p.secrets.append(Secret(
        "secret-fuite", "Le garde connaît un passage dérobé.", "secret",
        porteurs=["garde-brutal"],
        revelation={"declencheur": "corruption reussie", "node_cible": "para-01"},
        consequence_si_brule="le passage est muré", anchors=[(0, 40)]))
    p.aventure = None
    return p


def _write_synthetic_partition(out_dir: Path) -> Path:
    partition = _build_partition()
    write_partition(partition, out_dir)
    fm = ("---\n" + json.dumps({
        "etage": "adventure", "trajectoire": [],
        "conditions": [{"id": "cond-alarme",
                       "description_md": "La garnison est en alerte.",
                       "triggers_all": ["alarme"],
                       "declencheur": {"type": "etat", "valeur": "alarme"}}],
    }) + "\n---\n")
    (out_dir / "aventure.md").write_text(
        fm + "## Charnière de sortie\n\nLa nuit tombe.\n", encoding="utf-8")
    (out_dir / "directeur.md").write_text(
        "## Brief de direction\n\nReste tendu, jamais expéditif. Ne décris "
        "jamais une mécanique de jeu, seulement ce que le personnage perçoit.\n",
        encoding="utf-8")
    return out_dir


def _new_projected_save(root: Path, partition_dir: Path,
                        module_json_partition: Path) -> tuple[Library, str]:
    lib = Library(root)
    slug = lib.create_story("Test D-260 (d)", "Un donjon oublié.")
    projection.derive(partition_dir, root, slug, corpus_dir=root / "corpus")
    store = lib.saves.store(slug)
    (store.dir / "module.json").write_text(
        json.dumps({"partition": str(module_json_partition)}),
        encoding="utf-8")
    return lib, slug


# ------------------------------------------------------------- la mesure ----
def _section_breakdown(partition_dir: Path, store: MemoryStore, location: str,
                       history: list[dict], player_input: str,
                       scenes_tail: int, char_sheet: str, rpg_on: bool,
                       rpg_rules: str = "", response_length: str = ""
                       ) -> list[tuple[str, str, int]]:
    sections = ap.build_sections(partition_dir, store, location, history,
                                 player_input, scenes_tail, char_sheet, rpg_on,
                                 rpg_rules=rpg_rules,
                                 response_length=response_length)
    return [(s.marker, s.title, len(s.render())) for s in sections]


def _print_table(label: str, rows: list[tuple[str, str, int]], total_extra: int):
    print(f"\n--- {label} ---")
    total = 0
    for marker, title, n in rows:
        total += n
        print(f"  [{marker:8}] {title:55} {n:7} chars (~{n // CHARS_PER_TOKEN:6} tok)")
    if total_extra:
        print(f"  {'[additif]':10}{'(couches engine, non ventilées)':55} "
             f"{total_extra:7} chars (~{total_extra // CHARS_PER_TOKEN:6} tok)")
    grand = total + total_extra
    print(f"  {'TOTAL':10}{'':55} {grand:7} chars (~{grand // CHARS_PER_TOKEN:6} tok)")
    return grand


def _measure_save(label: str, partition_dir: Path, lib: Library, slug: str,
                  location: str, rpg_on: bool) -> dict:
    store = lib.saves.store(slug)
    engine = _engine(store, rpg_on)
    history = [{"role": "player", "text": "J'observe la porte."}]
    player_input = "Je pousse la porte."

    # Même fiche perso que `_messages()` calculerait (D-260 branchement,
    # #128 : `include_sheet=False` sur `_augment_rpg` car déjà servie ici) —
    # sinon rows/base_messages divergeraient sur la section "Fiche de
    # personnage" et fausseraient l'attribution des couches ci-dessous.
    char_sheet = (engine.rpg_mod.context_block(
                     store, prompt_narrate=engine.trinity is None)
                 if rpg_on and engine.rpg_mod is not None else "")
    # D-260 post-mesure (Issue #144, arbitrage (b)) : rpg-rules.md et la
    # directive response_length sont désormais des sections STABLES de
    # `assembleur_position` (pas des couches `_augment_*` additives) — même
    # contenu que `engine._messages()` calculerait, calculé ici pour que
    # `rows`/`base_messages` ci-dessous en tiennent compte identiquement.
    rpg_rules = store.read("rpg-rules.md").strip() if rpg_on else ""
    response_length = engine._response_length_directive()

    # Bloc de sections nu (assembleur position seul) — la ventilation par
    # poste I-158.
    rows = _section_breakdown(partition_dir, store, location, history,
                              player_input, engine.scenes_tail, char_sheet,
                              rpg_on, rpg_rules, response_length)

    # Paquet réellement servi par la boucle neuve — mêmes couches que
    # `engine._messages()` (D-260 branchement #128 ; réordonnées Issue #144)
    # MAIS mesurées couche par couche pour attribuer précisément ce que
    # chaque `_augment_*` ajoute (le "additif" n'est pas un bloc unique —
    # chaque couche a sa propre pression, résiduelle ou non). rpg-rules.md
    # et response_length ne sont plus des couches additives : elles sont
    # dans `rows` ci-dessus (sections stables), `_augment_rpg` n'a plus rien
    # à servir sur ce chemin (`include_sheet=False` déjà, et les règles
    # sont maintenant portées par `ap.assemble`) donc n'est plus appelé ici.
    partition_dir_p = Path(partition_dir)
    base_messages = ap.assemble(partition_dir_p, store, store.world_state(),
                                history, player_input,
                                scenes_tail=engine.scenes_tail,
                                char_sheet=char_sheet, rpg_on=rpg_on,
                                rpg_rules=rpg_rules,
                                response_length=response_length)
    after_pack = engine._augment_pack(base_messages)
    after_style = engine._augment_style(after_pack, include_length=False)
    after_events = engine._augment_event_rules(after_style, history, player_input)
    layers = [
        ("pack (I-373, propositions non routées)",
         len(after_pack[0]["content"]) - len(base_messages[0]["content"])),
        ("author's note (ST-21, hors response_length -- désormais stable)",
         len(after_style[0]["content"]) - len(after_pack[0]["content"])),
        ("verdicts de règles d'événement (lane b, #127)",
         len(after_events[0]["content"]) - len(after_style[0]["content"])),
    ]
    messages = after_events
    sys_text = messages[0]["content"]
    extra_rows = [("additif", title, n) for title, n in layers]
    grand_total = _print_table(label, rows + extra_rows, 0)

    # Stabilité de préfixe : un second tour SANS transition de node — la part
    # cachable (I-1643) = le préfixe octet-identique entre les deux appels.
    messages_2 = engine._messages(
        history, "J'inspecte la porte à la place, sans y toucher.")
    sys_text_2 = messages_2[0]["content"]
    prefix_len = 0
    for a, b in zip(sys_text, sys_text_2):
        if a != b:
            break
        prefix_len += 1
    cachable_pct = round(100 * prefix_len / max(len(sys_text), 1))
    print(f"  Préfixe cachable (2e tour, même position) : {prefix_len} chars "
         f"({cachable_pct}% du paquet) ; volatile : {len(sys_text) - prefix_len} chars")

    # Mapping des 3 postes de non-construit I-158 vers les sections neuves.
    by_title = {title: n for _, title, n in rows}
    brief = by_title.get("Brief de direction (directeur.md)", 0)
    scene_n = sum(n for _, t, n in rows if t.startswith("Scène courante"))
    presence_n = sum(n for _, t, n in rows if t.startswith("Présences"))
    world_n = sum(n for _, t, n in rows if t.startswith("État du monde"))
    verdicts_n = sum(n for _, t, n in rows if t.startswith("Verdicts"))
    events_layer_n = next(n for title, n in layers if title.startswith("verdicts de règles d'événement"))
    etat_sans_selection = scene_n + presence_n + world_n

    return {
        "label": label, "grand_total_tok": grand_total // CHARS_PER_TOKEN,
        "cachable_pct": cachable_pct,
        "brief_tok": brief // CHARS_PER_TOKEN,
        "etat_sans_selection_tok": etat_sans_selection // CHARS_PER_TOKEN,
        "verdicts_tok": (verdicts_n + events_layer_n) // CHARS_PER_TOKEN,
    }


def _print_comparatif(mesure: dict):
    print("\n=== Comparatif contre I-158 (director-pipeline, ancien assemblage) ===")
    print(f"{'Poste':45}{'I-158 (ancien)':>16}{'Boucle neuve':>16}")
    print(f"{'règles en prose (writer-rules / brief)':45}"
         f"{I158_REGLES_PROSE_TOK:>13} tok{mesure['brief_tok']:>13} tok")
    print(f"{'état sans sélection (STORY&MEMORY / scène+présences+monde)':45}"
         f"{I158_ETAT_SANS_SELECTION_TOK:>13} tok"
         f"{mesure['etat_sans_selection_tok']:>13} tok")
    label_evt = "regles d'evenement (event_rules_block / verdicts du tour)"
    print(f"{label_evt:45}"
         f"{I158_REGLES_EVENEMENT_TOK:>13} tok{mesure['verdicts_tok']:>13} tok")
    print(f"{'TOTAL paquet Director':45}"
         f"{I158_TOTAL_TOK:>13} tok{mesure['grand_total_tok']:>13} tok")
    delta_pct = round(100 * (1 - mesure['grand_total_tok'] / I158_TOTAL_TOK))
    print(f"\n  Écart : {delta_pct}% (cible D-260 : -90%)")
    verdict = "CIBLE ATTEINTE" if 1_500 <= mesure['grand_total_tok'] <= 2_500 \
        else ("SOUS LA CIBLE (mieux)" if mesure['grand_total_tok'] < 1_500
             else "AU-DESSUS DE LA CIBLE")
    print(f"  Verdict contre la fourchette 1 500-2 500 tokens : {verdict}")


# --------------------------------------------------------------------- run --
def run_corpus_a() -> dict:
    tmp = Path(tempfile.gettempdir()) / "se_mesure_d260_boucle_neuve"
    if tmp.exists():
        shutil.rmtree(tmp)
    partition_dir = _write_synthetic_partition(tmp / "partition")
    lib, slug = _new_projected_save(tmp / "app", partition_dir, partition_dir)
    mesure = _measure_save("CORPUS A — synthétique versionné (D-109)",
                           partition_dir, lib, slug, "para-01", rpg_on=False)
    _print_comparatif(mesure)
    return mesure


def run_corpus_b():
    """Corpus réel, hors git — s'auto-saute si absent (D-109/D-178)."""
    save_ptr = os.environ.get("CODERAIN_MESURE_SAVE", "").strip()
    if save_ptr:
        save_dir = Path(save_ptr)
    else:
        default_root = Path.home() / "ttrpg-corpus" / "saves"
        save_dir = default_root / "beyond-the-vale-of-madness"
    module_json = save_dir / "module.json"
    if not module_json.exists():
        print(f"\n--- CORPUS B — réel (hors git) : SKIP "
             f"({module_json} absent sur cette machine) ---")
        return None
    data = json.loads(module_json.read_text(encoding="utf-8"))
    partition_dir = Path(data["partition"])
    if not partition_dir.exists():
        print(f"\n--- CORPUS B — réel : SKIP (partition {partition_dir} absente) ---")
        return None
    # `Library.saves` resolves through `config.saves_dir(root)`, which only
    # returns `root/"saves"` unconditionally for a NON-production root — the
    # library root must be the PARENT of the saves/ dir, not saves/ itself.
    lib = Library(save_dir.parent.parent)
    slug = save_dir.name
    store = lib.saves.store(slug)
    state = store.world_state()
    location = str(state.get("location", ""))
    if not location or not ap.eligible(store, state):
        print("\n--- CORPUS B — réel : SKIP (save non éligible assembleur position) ---")
        return None
    rpg_on = store.rpg_enabled()
    mesure = _measure_save("CORPUS B — réel, hors git (aucun contenu ci-dessus)",
                           partition_dir, lib, slug, location, rpg_on)
    _print_comparatif(mesure)
    return mesure


if __name__ == "__main__":
    mesure_a = run_corpus_a()
    # Corpus A est la garantie CI : la cible doit se vérifier au moins sur le
    # cas synthétique (fixture volontairement petite — la fourchette absolue
    # 1500-2500 est jugée sur le corpus réel dans le doc, pas ici).
    assert mesure_a["grand_total_tok"] < I158_TOTAL_TOK, (
        "la boucle neuve ne doit jamais dépasser l'ancien total, même sur "
        "fixture synthétique")
    assert mesure_a["cachable_pct"] >= 50, (
        "moins de la moitié du paquet cachable au 2e tour sans transition — "
        "régression de stabilité de préfixe")
    run_corpus_b()
    print("\nALL D-260 (d) MEASUREMENTS PRINTED — see docs/mesure-d260-boucle-neuve.md")
