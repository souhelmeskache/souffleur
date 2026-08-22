"""Rule conversion tables (SPEC-P4 §6): source corpus -> 5e, versioned.

⛔ A mechanical element with no table entry raises ConversionException —
it goes to the exceptions report, never improvised by the LLM. The tables
below are the v0 defaults; each carries its version so a future correction
is a new table revision, not an edit of history.
"""
from __future__ import annotations

TARGET_VERSIONS = ("2014", "2024")


class ConversionException(Exception):
    """No conversion table covers this value — reported, never guessed."""


class RuleTables:
    def __init__(self, source_corpus: str, target_version: str = "2014"):
        if target_version not in TARGET_VERSIONS:
            raise ValueError(f"target 5e version must be in {TARGET_VERSIONS}, "
                             f"got {target_version!r}")
        self.source_corpus = source_corpus          # e.g. "2e", "5e"
        self.target_version = target_version
        # Identity conversion: source already speaks the lingua franca.
        self.identity = source_corpus.lower().replace(" ", "") in ("5e", "5e2014", "5e2024")

    # -- THAC0 -> attack bonus ------------------------------------------------
    # To hit AC 0 a d20 roll >= THAC0 is needed, so bonus = 20 - THAC0.
    def thac0_to_attack_bonus(self, thac0: int) -> int:
        if self.identity:
            raise ConversionException("identity corpus: no THAC0 expected")
        return 20 - int(thac0)

    # -- AC (descending) -> AC 5e (ascending) ---------------------------------
    _AC_TABLE = {
        10: 10, 9: 11, 8: 12, 7: 13, 6: 14, 5: 15, 4: 16, 3: 17,
        2: 18, 1: 19, 0: 20,
    }

    def ac_to_5e(self, ac: int) -> int:
        if self.identity:
            return int(ac)
        if ac not in self._AC_TABLE:
            raise ConversionException(f"no AC table entry for {ac}")
        out = self._AC_TABLE[ac]
        if self.target_version == "2024":   # 2024 caps published-stat AC lower
            out = min(out, 22)
        return out

    # -- Saves (5 categories) -> three jets ------------------------------------
    SAVE_GROUPS = {
        "paralyzation_poison_death": "vigueur",
        "rod_staff_wand": "volonte",
        "petrification_polymorph": "vigueur",
        "breath_weapon": "reflexes",
        "spell": "volonte",
    }

    def save_category(self, save_2e: str) -> str:
        key = save_2e.strip().lower().replace(" ", "_").replace("/", "_").replace("-", "_")
        if key not in self.SAVE_GROUPS:
            raise ConversionException(f"unknown save category {save_2e!r}")
        return self.SAVE_GROUPS[key]

    # -- HD -> PV --------------------------------------------------------------
    def hd_to_pv(self, hd_count: int, die: int = 8, con_mod: int = 0) -> int:
        """Mean HP over HD, plus CON once per HD above the first at 2014 style.
        Kept deliberately simple and versioned: v0 uses mean-of-die."""
        avg = (die + 1) / 2
        pv = int(hd_count * avg + con_mod)
        if self.target_version == "2024":
            pv += hd_count // 4      # 2024 blocks trend slightly beefier
        return max(pv, 1)

    def convert_stats(self, raw: dict) -> dict:
        """Convert one stat block dict; unknown keys pass through untouched but
        any key starting with 'thac0'/'saves_' goes through its table."""
        out: dict = {}
        for k, v in raw.items():
            lk = k.lower()
            if lk == "thac0":
                out["attaque_bonus"] = self.thac0_to_attack_bonus(int(v))
            elif lk == "ca":
                out["ca"] = self.ac_to_5e(int(v))
            elif lk == "hd":
                out["pv"] = self.hd_to_pv(int(v))
            elif lk.startswith("save_"):
                out[f"jet_{self.save_category(lk[5:])}"] = v
            else:
                out[k] = v
        return out
