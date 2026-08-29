"""I-206 : la troncature a EXISTING_ENTITIES_CAP fiches doit couper en priorite
les entites les MOINS importantes, pas celles qui arrivent tard dans l'index.

Script autonome, 100% hors-ligne : construit un Summarizer avec un store/llm
factices (jamais appeles ici) et n'exerce que _existing_context.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coderain.memory import Entry
from coderain.summarizer import EXISTING_ENTITIES_CAP, Summarizer


class _FakeIndex:
    def __init__(self, entries):
        # MemoryIndex.entries: slug -> (kind, Entry) — seul ce que
        # _existing_context lit ici.
        self.entries = {e.slug: ("character", e) for e in entries}


class _FakeStore:
    def __init__(self, entries):
        self._index = _FakeIndex(entries)

    def index(self):
        return self._index


def _make_entries(n: int) -> list[Entry]:
    """n entites, toutes declenchees par le texte, importance croissante avec
    l'ordre d'index (la moins importante est la PREMIERE de l'index -> sans
    tri, c'est elle qui survivrait a la troncature)."""
    return [Entry(title=f"Entity{i}", slug=f"entity-{i}", importance=i + 1,
                  body=f"body-{i}")
            for i in range(n)]


def test_troncature_garde_les_plus_importantes():
    n = EXISTING_ENTITIES_CAP + 3
    entries = _make_entries(n)
    store = _FakeStore(entries)
    summarizer = Summarizer.__new__(Summarizer)  # pas besoin de config/llm ici
    summarizer.store = store

    text = " ".join(f"Entity{i}" for i in range(n))
    ctx = summarizer._existing_context([{"role": "player", "text": text}])

    kept = set(summarizer._last_triggered) - set(summarizer._last_cut)
    assert len(kept) == EXISTING_ENTITIES_CAP, kept

    # Les entites gardees doivent etre celles de plus haute importance
    # (les 3 dernieres creees, importance la plus forte), pas les 12 premieres
    # de l'index.
    expected_kept = {f"entity-{i}" for i in range(3, n)}
    assert kept == expected_kept, (kept, expected_kept)

    # Les moins importantes (0, 1, 2) doivent avoir ete coupees.
    assert set(summarizer._last_cut) == {"entity-0", "entity-1", "entity-2"}

    for slug in expected_kept:
        assert slug in ctx


def test_pas_de_troncature_sous_le_plafond():
    entries = _make_entries(3)
    store = _FakeStore(entries)
    summarizer = Summarizer.__new__(Summarizer)
    summarizer.store = store

    text = " ".join(f"Entity{i}" for i in range(3))
    ctx = summarizer._existing_context([{"role": "player", "text": text}])

    assert summarizer._last_cut == []
    for e in entries:
        assert e.slug in ctx


if __name__ == "__main__":
    test_troncature_garde_les_plus_importantes()
    test_pas_de_troncature_sous_le_plafond()
    print("OK")
