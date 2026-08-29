"""Snapshot automatique a l'ouverture de partie (I-148/ESC-4, Issue #110):
SaveLibrary.open()/Library.open() prennent une snapshot best-effort au moment
ou une save est ouverte, par-dessus le mecanisme MemoryStore.snapshot()
existant (jusque-la reserve au repli memoire pre-fold)."""
import os, sys, shutil, tempfile, json, stat
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_snap_open_i148")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)

scen = lib.scenarios.create("World", "A premise about a lighthouse.")
slug = lib.saves.create("Run A", scen)

# 1) opening a save takes a snapshot immediately (no play needed first).
store = lib.saves.open(slug)
snaps_dir = store.dir / ".snapshots"
assert snaps_dir.exists() and list(snaps_dir.iterdir()), "open() took no snapshot"
first = sorted(snaps_dir.iterdir())
print("1) open() snapshots on the very first open")

# 2) meta.json is part of what gets snapshotted (title/scenario/mode).
snap_dir = first[-1]
assert (snap_dir / "meta.json").exists(), "meta.json missing from the snapshot"
meta = json.loads((snap_dir / "meta.json").read_text(encoding="utf-8"))
assert meta.get("title") == "Run A"
print("2) meta.json is captured in the snapshot")

# 3) store() itself stays snapshot-free — only open() triggers one.
before = sorted(p.name for p in snaps_dir.iterdir())
lib.saves.store(slug)
lib.saves.store(slug)
after = sorted(p.name for p in snaps_dir.iterdir())
assert before == after, "bare store() must never snapshot"
print("3) bare store() takes no snapshot (only open() does)")

# 4) repeated opens respect the keep= rotation, same as pre-fold snapshots.
import time
for _ in range(4):
    time.sleep(1.01)  # snapshot dirs are second-granular; force distinct dirs
    lib.saves.open(slug, keep=3)
assert len(list(snaps_dir.iterdir())) == 3, list(snaps_dir.iterdir())
print("4) open() rotation respects keep=")

# 5) a snapshot failure must never block the open — Library.open() still
# returns a usable store. Simulate failure by replacing .snapshots with a
# read-only file where a directory is expected.
slug2 = lib.saves.create("Run B", scen)
store2 = lib.saves.store(slug2)
bad = store2.dir / ".snapshots"
bad.write_text("not a directory", encoding="utf-8")
try:
    opened = lib.open(slug2)  # Library-level passthrough
    assert opened.title == "Run B"
    assert opened.read("premise.md")  # store is fully usable despite the failure
    print("5) a snapshot failure never blocks open()")
finally:
    os.chmod(bad, stat.S_IWRITE)  # tidy up for shutil.rmtree at re-run
