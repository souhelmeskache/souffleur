"""Load config.yaml + .env and resolve the active provider profile."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .models import MIN_CONTEXT_BUDGET_TOKENS, MIN_CONTEXT_TOKENS


def _home_dir() -> Path:
    """Where user data lives (config.yaml, .env, saves/, scenarios/, …).

    - CODERAIN_HOME env var wins (portable installs, tests).
    - Frozen build (PyInstaller desktop app): %LOCALAPPDATA%\\Coderain —
      the exe dir is replaced on update, so data must not live there.
    - Source checkout: the repo root, as always.
    """
    override = os.environ.get("CODERAIN_HOME", "").strip()
    if override:
        p = Path(override)
    elif getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        p = Path(base) / "Coderain"
    else:
        return Path(__file__).resolve().parent.parent
    p.mkdir(parents=True, exist_ok=True)
    return p


ROOT = _home_dir()

# A fresh install (frozen app first run) has no config.yaml — this is the
# shipped default: local Ollama quad (qwen3 Director / gemma3 Writer). The
# Settings page rewrites it from the UI.
_DEFAULT_CONFIG = """\
active_profile: local
profiles:
  local:
    base_url: http://localhost:11434/v1
    model: qwen3:4b
    api_key_env: OLLAMA_API_KEY
    context_tokens: 16384
generation:
  temperature: 0.9
  top_p: 0.95
  max_tokens: 2500
  think: true
  use_memory_tool: false
  trinity_brain: true
memory:
  short_term_turns: 12
  medium_fold_after: 12
  medium_fold_size: 5
  long_fold_after: 8
  long_fold_size: 4
  context_budget_tokens: 8000
rpg: {}
retrieval:
  enabled: false
  embed_model: nomic-embed-text
  top_k: 4
trinity:
  director:
    profile: local
    model: qwen3:4b
  lorekeeper:
    profile: local
    model: gemma3:4b
  writer:
    profile: local
    model: gemma3:4b
"""


@dataclass
class Profile:
    name: str
    base_url: str
    model: str
    api_key: str
    context_tokens: int
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    profile: Profile
    generation: dict[str, Any]
    memory: dict[str, Any]
    rpg: dict[str, Any]
    retrieval: dict[str, Any]
    raw: dict[str, Any]


def build_profile(data: dict, name: str, model: str | None = None) -> Profile:
    """Resolve a named profile from a loaded config dict into a Profile, optionally
    overriding just the model. Reused by the Trinity Brain so each stage can point at
    a different endpoint/key/model. Assumes .env is already loaded."""
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise SystemExit(
            f"profile '{name}' not found. Options: {', '.join(profiles)}"
        )
    p = profiles[name]
    base_url = p.get("base_url")
    model = model or p.get("model")
    if not base_url or not model:
        # A hand-edited/partial profile must fail with a readable message, not a
        # bare KeyError at server import (which loads config once at boot).
        raise SystemExit(
            f"profile '{name}' is incomplete — it needs both base_url and model")
    key_env = p.get("api_key_env", "")
    api_key = os.getenv(key_env, "") if key_env else ""
    if not api_key:
        # Ollama and some local servers don't check the key; use a placeholder.
        api_key = "not-needed"
    return Profile(
        name=name,
        base_url=base_url,
        model=model,
        api_key=api_key,
        # Floored, never capped: a too-small window starves the memory system
        # (an 8 GB GPU handles the floor locally), while 131k/200k/1M+ windows
        # pass straight through wherever the model allows them.
        context_tokens=max(MIN_CONTEXT_TOKENS,
                           int(p.get("context_tokens", 8192))),
        extra_headers=p.get("extra_headers", {}) or {},
    )


def _resolve_dir(env_var: str, config_key: str, default: Path) -> Path:
    """Shared resolution order for an overridable directory: `env_var` >
    `config_key:` in config.yaml > `default`. Never raises — a malformed or
    missing config.yaml just falls through to `default`; the caller decides
    whether the resolved path needs to exist."""
    override = os.environ.get(env_var, "").strip()
    if override:
        return Path(override)
    cfg_path = ROOT / "config.yaml"
    if cfg_path.exists():
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            raw = data.get(config_key)
            if raw:
                return Path(raw)
        except Exception:
            pass  # malformed config.yaml here is not this function's problem
    return default


def corpus_dir() -> Path:
    """Root of the campaign-material corpus (module converter input, real-
    partition test fixtures). Lives entirely outside this repo (D-178/D-224) —
    backed up in `modules-source/` of the private `ttrpg-corpus` GitHub repo
    since 2026-08-28 (phase 1 assainissement). Resolution order: `CORPUS_DIR`
    env var > `corpus_dir:` key in config.yaml > historical default location.

    Never raises — the corpus is optional (callers check `.exists()`; tests
    skip their real-partition sections when it's absent, same as before)."""
    return _resolve_dir("CORPUS_DIR", "corpus_dir",
                        Path(r"C:\Users\souhe\ttrpg-corpus\modules-source"))


def saves_dir(library_root: str | Path | None = None) -> Path:
    """Root of the save-games library (transcripts, per-story memory, state)
    for a `Library` rooted at `library_root`.

    `library_root` defaults to the production `ROOT`, and ONLY then is the
    `SAVES_DIR` env var / config.yaml `saves_dir:` override consulted — a
    `Library` opened against any other root (every test harness in `tests/`
    opens one against a throwaway tmp dir for isolation) always gets
    `library_root / "saves"` unconditionally, exactly as before this function
    existed. Without this guard, setting `saves_dir:` for real play data would
    silently redirect every test's saves too — cross-contaminating test runs
    with production data, or vice versa.

    For the production root, defaults to the historical `ROOT / "saves"` —
    unchanged for a fresh install, which is where the shipped demo save
    (`untitled`, scenario `the-veil`) keeps living. Overridable so real play
    data (derived from real modules) can live outside this repo instead
    (D-224) — set `saves_dir:` in config.yaml once real saves have been moved
    out; the demo save then stops being listed until the override is unset
    (both can't be scanned at once by this resolver)."""
    root = Path(library_root) if library_root is not None else ROOT
    if root != ROOT:
        return root / "saves"
    return _resolve_dir("SAVES_DIR", "saves_dir", ROOT / "saves")


def load_config(path: str | Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if not cfg_path.exists():                    # first run of a fresh install
        cfg_path.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("config.yaml is empty or malformed (expected a mapping)")

    active = data.get("active_profile")
    if active is None or active not in data.get("profiles", {}):
        raise SystemExit(
            f"active_profile '{active}' not found. "
            f"Options: {', '.join(data.get('profiles', {}))}"
        )
    profile = build_profile(data, active)
    return Config(
        profile=profile,
        generation=data.get("generation", {}),
        memory=data.get("memory", {}),
        rpg=data.get("rpg", {}) or {},
        retrieval=data.get("retrieval", {}) or {},
        raw=data,
    )


def context_budget(config: Config) -> int:
    """The assembled-memory budget in tokens. An explicit number is used as-is
    (floored); `auto`/0 derives it from the active profile's window — reply
    tokens + overhead reserved, everything else available to memory — so a 131k+
    long-context model gets its whole window without hand-tuning."""
    raw = config.memory.get("context_budget_tokens", 8000)
    auto = raw in (0, None) or (isinstance(raw, str)
                                and raw.strip().lower() == "auto")
    if auto:
        reply = int(config.generation.get("max_tokens", 700) or 700)
        derived = config.profile.context_tokens - reply - 2048
        return max(MIN_CONTEXT_BUDGET_TOKENS, derived)
    try:
        return max(MIN_CONTEXT_BUDGET_TOKENS, int(raw))
    except (TypeError, ValueError):
        return 8000


def save_yaml(data: dict, path: str | Path | None = None) -> None:
    """Persist the whole config dict back to config.yaml (comments are not kept)."""
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False,
                       allow_unicode=True),
        encoding="utf-8",
    )


def read_env() -> dict[str, str]:
    path = ROOT / ".env"
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]  # strip surrounding quotes a hand-editor may have added
            out[k.strip()] = v
    return out


def write_env(updates: dict[str, str]) -> None:
    env = read_env()
    env.update({k: v for k, v in updates.items() if k})
    lines = [f"{k}={v}" for k, v in env.items()]
    (ROOT / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
