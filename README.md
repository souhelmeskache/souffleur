# Souffleur

**A local, private AI storytelling engine — your worlds, your model, your memory.**

*Named after the théâtre prompter — the [souffleur](https://en.wikipedia.org/wiki/Prompter)
who sits just out of sight and quietly feeds the actors their lines. That's the job:
stay out of the way, keep the story moving.*

Souffleur is a fork of [Coderain](https://github.com/Zwimy/coderain), an
AI-Dungeon-style interactive-fiction engine that runs on **your** machine against
**your** model (local via Ollama, or any OpenAI-compatible cloud key). No accounts,
no subscription, no server reading your stories. It's built around one idea most
tools hide: **your memory should be yours** — plain Markdown files you can read,
edit, diff, and own.

Free and open source (MIT) — see [Attribution](#attribution) below.

![Souffleur in action](docs/demo.gif)

---

## Why it's different

- **Markdown is the source of truth.** Every story is a folder of `.md` files —
  characters, locations, factions, items, threads, a running transcript, and
  tiered memory (recent turns → folded scenes → long arc + timeline + facts).
  Open them in any editor. No opaque database.
- **A real memory system, not a bigger context window.** Salience-ranked,
  alias-triggered lorebook activation; automatic summarization into scenes and an
  arc; optional semantic (vector) recall — all rebuildable from the Markdown.
- **A code validator between the model and the page.** An optional multi-brain
  "quad" pipeline (Planner → **deterministic code Validator** → Writer) means
  mechanics are checked by code, not hallucinated: engine-rolled dice, real
  inventory/gold/quests, an in-world clock that only moves forward.
- **Optional RPG campaign layer.** Stats, skill checks with fair engine-rolled
  dice, HP/mana/XP, inventory, a quest state machine, companions with mood +
  private side-chat — all toggleable; the core stays a clean narrative engine.
- **Bring your SillyTavern cards.** Import V1/V2/V3 character cards (PNG / JSON /
  charx) — the character, scenario, first message, and embedded lorebook become a
  ready-to-play world.
- **Local-first, BYO everything.** Ollama on your GPU, or paste a cloud key
  (DeepSeek, GLM, Claude, OpenRouter, …). Your key lives only on your machine.

## What this fork adds

Since diverging from upstream, this fork has grown a second layer purpose-built
for running **published tabletop adventure modules** as structured, spoiler-safe
campaigns, on top of the narrative engine above:

- **A D&D 5e rules engine** (`rules_engine/`, built on the MIT-licensed
  `dnd5e-engine` + CC-BY-4.0 `dnd5e-srd-data` — see [NOTICE-dnd5e.md](NOTICE-dnd5e.md))
  for real stat blocks, checks, and combat resolution instead of narrated-only
  outcomes.
- **A module converter pipeline** (`coderain/converter/`) that turns an existing
  adventure module's text into a validated, zero-dangling-reference "partition" —
  nodes, records, roll tables, secrets, tensions, resources — checked by a
  deterministic validator before it's ever played.
- **Structured, zero-spoiler character creation** (`webui.py` conversation
  flow) — four canonical windows (Origin → Social posture → Central tension →
  Personal stake) that build a player's `Personnage` and `Destinee` (milestones)
  from real campaign data, while a 5-rule guard keeps secrets, internal ids, and
  future/foreshadowing markers out of anything shown to the player.
- **A combat + character-sheet UI** (`webapp/`) — tactical grid, tokens, HP/
  initiative tracking, and a live character panel reading straight from the
  engine's world state.

## Install

**Desktop (Windows), zero setup:** download the latest `Coderain-win-x64.zip`
from [Releases](../../releases), unzip, run `Coderain.exe`. It opens in its own
window — no Python, no terminal. For local models, install
[Ollama](https://ollama.com/download) and pull a model — the in-app
**Settings → Local** guide walks you through it.

**From source (any OS)** — one command, no manual venv:

```bash
git clone https://github.com/souhelmeskache/ttrpg-mvp
cd ttrpg-mvp
python start.py         # Windows: double-click Coderain.bat  •  macOS/Linux: ./run.sh
```

The **first run creates a `.venv`, installs the requirements, and opens the web
app** in your browser (http://127.0.0.1:8377) — you only need Python 3.10+ on
your PATH. After that, `python start.py` just launches. Other modes:
`--cli` (terminal), `--no-browser`, `--port 8399`, `--gui` (the retro UI).

<details><summary>Prefer to manage the venv yourself?</summary>

```bash
python -m venv .venv && . .venv/Scripts/activate   # or .venv/bin/activate
pip install -r requirements.txt
python start.py                                    # or: python server.py
```
</details>

## Run local models (optional, free, private)

1. Install [Ollama](https://ollama.com/download).
2. `ollama pull qwen3:4b` (planner) and `ollama pull gemma3:4b` (writer).
3. Set `OLLAMA_CONTEXT_LENGTH=16384` and restart Ollama (its default 4k starves
   long stories).
4. In the app → **Settings → Local**, pick your models. That's it — 100% offline.

Prefer a cloud model? **Settings → Hosted**: paste a key (DeepSeek/GLM are cheap
and strong), done.

## Tech

Python + FastAPI backend, a vanilla-JS single-page app, SSE streaming. The engine
is provider-agnostic (one OpenAI-compatible client). Tests: `python run_tests.py`
(each `tests/*.py` is a standalone, offline script — see
[CLAUDE.md](CLAUDE.md) for the full test/PR workflow). A retro Win2000 Tkinter UI
(`gui.py`) survives as an easter egg.

## Attribution & third-party components

**This project is based on [Coderain](https://github.com/Zwimy/coderain) by
Zwimy**, licensed **MIT**. The original [LICENSE](LICENSE) is preserved unchanged
in this repository, as required by the MIT license. This fork has since diverged
significantly (see [What this fork adds](#what-this-fork-adds) above) but the
narrative-engine core — Markdown-as-source-of-truth, the memory system, the
Planner/Validator/Writer pipeline, SillyTavern card import — originates with
Zwimy's upstream project. If you'd like to support the original work directly:
[Ko-fi](https://ko-fi.com/zwimy) · [GitHub Sponsors](https://github.com/sponsors/Zwimy).

Two third-party components are bundled as regular dependencies (pinned in
[requirements.txt](requirements.txt)) and carry obligations of their own,
reproduced in full in **[NOTICE-dnd5e.md](NOTICE-dnd5e.md)**:

| Component | What it provides | License | Obligation |
|---|---|---|---|
| [`dnd5e-engine`](https://github.com/tapestria/nat20) 0.3.0 | D&D 5e rules engine (checks, combat resolution) | MIT | License + notice ship with the package distribution |
| [`dnd5e-srd-data`](https://github.com/tapestria/nat20) 0.3.0 | D&D 5e SRD dataset (stat blocks, rules text) | **CC-BY-4.0** | **Attribution notice must be reproduced** — done in full in `NOTICE-dnd5e.md` |

For every other dependency in `requirements.txt`, see the license audit posted
as a comment on the PR that added this section — none require special handling
(no strong copyleft, nothing unlicensed).

## License

MIT — see [LICENSE](LICENSE). Do anything you want with it, per the same terms
Zwimy released the original under.
