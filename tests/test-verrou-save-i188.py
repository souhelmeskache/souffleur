"""I-188 (Issue #115) : verrou de save côté pont MCP — une session ouverte
est un moteur vivant, `load_save` ne doit plus laisser une seconde session
écraser la première en silence.

Fixture 100% SYNTHÉTIQUE (D-109) : save fabriqué pour le test via Library,
aucun matériau de campagne réel.

3 sections :
  1. coderain.save_lock — unitaire : acquire/read/release, un pid vivant
     étranger bloque, un pid mort (orphelin) se réclame tout seul, release
     ne touche jamais le lock d'un autre process.
  2. mcp_server.load_save — un lock étranger vivant refuse le chargement
     avec une erreur motivée (pas de mutation de _store/_engine/_slug) ; le
     même process peut recharger son propre save ; un lock orphelin se
     réclame automatiquement au lieu de bloquer le save à jamais.
  3. fermeture propre — `_release_save_lock` (câblé sur atexit/signal dans
     mcp_server.py) retire le lock de la session courante.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain import save_lock
from coderain.memory import Library

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


TMP = Path(tempfile.gettempdir()) / "se_verrou_save_i188"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)

lib = Library(TMP / "app")
scen = lib.scenarios.create("World", "A premise about a fabricated coast.")
slug = lib.saves.create("Run verrou", scen)
save_dir = TMP / "app" / "saves" / slug

# --------------------------------------------------- section 1 (unitaire) ---
section("1) save_lock : acquire/read, pid vivant étranger bloque")
assert save_lock.read(save_dir) is None, "aucun lock avant le premier acquire"
lock = save_lock.acquire(save_dir, slug)
assert lock["pid"] == os.getpid()
on_disk = save_lock.read(save_dir)
assert on_disk == lock
# ce process est le sien -> pas "held by other"
assert save_lock.held_by_other_live_process(save_dir) is None

# simule un pid étranger mais bien vivant : un vrai sous-processus qu'on
# laisse tourner quelques secondes.
proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
try:
    foreign = {"pid": proc.pid, "host": "autre-machine", "slug": slug,
               "opened": time.time()}
    (save_dir / save_lock.LOCK_NAME).write_text(json.dumps(foreign),
                                                 encoding="utf-8")
    held = save_lock.held_by_other_live_process(save_dir)
    assert held is not None and held["pid"] == proc.pid, \
        "un pid étranger vivant doit bloquer le chargement"
    print("1a) pid étranger vivant -> bloqué")

    section("1b) release ne touche jamais le lock d'un autre process")
    save_lock.release(save_dir, slug)  # ce process n'est pas le propriétaire
    assert save_lock.read(save_dir) is not None, \
        "release a effacé le lock d'un AUTRE process — ne doit jamais arriver"
    print("1b) release respecte le pid propriétaire")
finally:
    proc.terminate()
    proc.wait(timeout=10)
    time.sleep(0.5)  # laisse l'OS libérer le pid (marge Windows)

section("1c) pid mort (orphelin) se réclame tout seul")
orphan = {"pid": proc.pid, "host": "session-tuee", "slug": slug,
          "opened": time.time()}
(save_dir / save_lock.LOCK_NAME).write_text(json.dumps(orphan),
                                             encoding="utf-8")
assert not save_lock._pid_alive(proc.pid), \
    "le sous-processus doit être bien mort à ce stade"
assert save_lock.held_by_other_live_process(save_dir) is None, \
    "un lock orphelin (pid mort) doit se réclamer, pas bloquer"
print("1c) lock orphelin réclamé (pid mort)")

section("1d) lock corrompu se lit comme absent")
(save_dir / save_lock.LOCK_NAME).write_text("{ pas du json", encoding="utf-8")
assert save_lock.read(save_dir) is None
assert save_lock.held_by_other_live_process(save_dir) is None
(save_dir / save_lock.LOCK_NAME).unlink()
print("1d) lock corrompu = pas de lock utilisable")

# ------------------------------------------------ section 2 (mcp_server) ----
section("2) load_save : refus motivé sur lock étranger vivant")
proc2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
try:
    foreign2 = {"pid": proc2.pid, "host": "autre-poste", "slug": slug,
                "opened": time.time()}
    (save_dir / save_lock.LOCK_NAME).write_text(json.dumps(foreign2),
                                                 encoding="utf-8")

    mcp_server._store = None
    mcp_server._engine = None
    mcp_server._slug = ""
    mcp_server._saves_root = TMP / "app" / "saves"
    mcp_server._lib = lib  # même Library que la fixture, pas celle du repo réel

    out = mcp_server.load_save(slug)
    assert "error" in out, out
    assert "verrouillé" in out["error"] or "locked" in out["error"].lower()
    assert out["locked_by"]["pid"] == proc2.pid
    # aucune mutation d'état : le refus n'a pas chargé le save.
    assert mcp_server._store is None and mcp_server._slug == ""
    print("2a) load_save refuse un save verrouillé par une autre session vivante")
finally:
    proc2.terminate()
    proc2.wait(timeout=10)

section("2b) load_save : lock orphelin réclamé, chargement passe")
orphan2 = {"pid": proc2.pid, "host": "session-tuee", "slug": slug,
           "opened": time.time()}
(save_dir / save_lock.LOCK_NAME).write_text(json.dumps(orphan2),
                                             encoding="utf-8")
out2 = mcp_server.load_save(slug)
assert "error" not in out2, out2
assert out2["slug"] == slug
assert mcp_server._slug == slug
held_now = save_lock.read(save_dir)
assert held_now["pid"] == os.getpid(), \
    "load_save doit poser SON PROPRE lock après avoir réclamé l'orphelin"
print("2b) lock orphelin réclamé automatiquement, chargement réussit")

section("2c) même process : recharger son propre save ne se bloque pas lui-même")
out3 = mcp_server.load_save(slug)
assert "error" not in out3, out3
print("2c) même process peut recharger le save qu'il tient déjà")

section("2d) changer de save libère le lock du précédent")
slug_b = lib.saves.create("Run verrou B", scen)
save_dir_b = TMP / "app" / "saves" / slug_b
out4 = mcp_server.load_save(slug_b)
assert "error" not in out4, out4
assert save_lock.read(save_dir) is None, \
    "le lock du premier save doit être libéré en changeant de save"
assert save_lock.read(save_dir_b)["pid"] == os.getpid()
print("2d) load_save d'un autre slug libère le lock du précédent")

# --------------------------------------------------- section 3 (shutdown) ---
section("3) fermeture propre : _release_save_lock retire le lock courant")
assert save_lock.read(save_dir_b) is not None
mcp_server._release_save_lock()
assert save_lock.read(save_dir_b) is None, \
    "_release_save_lock doit retirer le lock de la session à l'arrêt propre"
print("3) fermeture propre libère le lock")

mcp_server._store = None
mcp_server._engine = None
mcp_server._slug = ""

print("\nALL I-188 VERROU SAVE (#115) CHECKS PASSED: " + ", ".join(FAIT))
