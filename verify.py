"""Deterministic geometry check: decide when the measured part provably matches the request.

If it does, the pipeline can skip the slower LLM self-check without losing quality. The rules are deliberately
conservative - when in doubt the answer is "not proven" and the LLM check runs as before:
- the request states an explicit overall size "A x B x C" (mm) and the bounding box matches it (any orientation,
  within max(0.3 mm, 2 %)),
- the part is one solid,
- every hole/bore diameter mentioned exists in the part (and the count matches when one is stated, e.g. "four 5 mm holes").
"""
from __future__ import annotations

import re

_NUM = r"(\d+(?:\.\d+)?)"
_TRIPLE = re.compile(rf"{_NUM}\s*(?:mm)?\s*(?:x|×|by|\*)\s*{_NUM}\s*(?:mm)?\s*(?:x|×|by|\*)\s*{_NUM}", re.I)
_WORDS = {"one": 1, "a": 1, "an": 1, "single": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
_COUNT = r"(\d+|one|a|an|single|two|three|four|five|six|seven|eight|nine|ten|twelve)"
_HOLE_WORDS = r"(?:through[- ]?)?(?:holes?|bores?)"
# "four 5 mm holes", "a 20 mm center bore", "two 5 mm diameter through-holes"
_HOLE_SPEC = re.compile(rf"(?:\b{_COUNT}\s+)?{_NUM}\s*mm\s*(?:diameter\s+|dia\.?\s+)?(?:center\s+|centre\s+|central\s+|"
                        rf"mounting\s+|screw\s+|vertical\s+|round\s+)?{_HOLE_WORDS}", re.I)
# "a bore of 12 mm diameter", "12 mm diameter bore" handled above; "hole 10 mm" style:
_HOLE_SPEC2 = re.compile(rf"{_HOLE_WORDS}\s*(?:of\s+)?(?:diameter\s+)?{_NUM}\s*mm", re.I)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.3, 0.02 * b)


def geometry_proven(requests: list[str], metrics: dict) -> bool:
    """True only when the measured part provably matches every checkable size in the requests."""
    if not requests or metrics.get("num_solids", 1) != 1 or not metrics.get("is_valid", True):
        return False
    text = " ".join(requests)

    # 1) explicit overall size - use the last one stated (a later chat message may change the size)
    triples = _TRIPLE.findall(text)
    if not triples:
        return False
    want = sorted(float(v) for v in triples[-1])
    have = sorted(float(v) for v in metrics["bbox_mm"])
    if not all(_close(h, w) for h, w in zip(have, want)):
        return False

    # 2) holes / bores
    holes = metrics.get("holes") or []
    found = {}
    for hdict in holes:
        found[hdict["d"]] = found.get(hdict["d"], 0) + hdict["n"]
    mentions_holes = re.search(r"\b(holes?|bores?)\b", text, re.I) is not None
    if mentions_holes and not holes:
        return False
    specs = [(c, float(d)) for c, d in _HOLE_SPEC.findall(text)] + [("", float(d)) for d in _HOLE_SPEC2.findall(text)]
    for count, d in specs:
        n_have = sum(n for dia, n in found.items() if _close(dia, d))
        if n_have == 0:
            return False
        if count:
            n_want = _WORDS.get(count.lower()) if not count.isdigit() else int(count)
            if n_want and n_want > 1 and n_have != n_want:
                return False
    return True
