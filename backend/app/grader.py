"""Deterministic grader. No LLM anywhere in this file.

Correct == the learner's result set equals the frozen expected result set:
  * columns compared by POSITION (names/aliases ignored)
  * values normalised (numbers -> 2dp, numeric-looking text -> number, dates -> ISO, strings trimmed)
  * rows compared as a multiset, or in order when question.ordered is True
"""
from collections import Counter
from datetime import date, datetime
import re
from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")
_NUMERIC_TEXT = re.compile(r"^\s*-?\d+(\.\d+)?\s*$")


def _num(v):
    d = Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)
    return str(d + 0)  # +0 turns -0.00 into 0.00


def norm_value(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        try:
            return _num(v)
        except Exception:
            return str(v)
    if isinstance(v, datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0) else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    t = str(v).strip()
    if _NUMERIC_TEXT.match(t):   # e.g. to_char(..., 'FMMM') -> '1' equals numeric 1
        return _num(t)
    return t


def norm_rows(rows):
    return [tuple(norm_value(v) for v in r) for r in rows]


def _key(row):
    # sortable key that tolerates None
    return tuple(("" if v is None else str(v)) for v in row)


def compare(got_rows, got_ncols, expected_rows, expected_ncols, ordered):
    """Return (correct: bool, diff: dict). `expected_rows` must already be normalised."""
    got = norm_rows(got_rows)
    exp = [tuple(r) for r in expected_rows]
    diff = {"expected_rows": len(exp), "got_rows": len(got),
            "expected_cols": expected_ncols, "got_cols": got_ncols}
    if got_ncols != expected_ncols:
        diff["reason"] = "column_count"
        return False, diff
    if ordered:
        if got == exp:
            return True, diff
        if Counter(got) == Counter(exp):
            diff["reason"] = "order"
            return False, diff
    else:
        if Counter(got) == Counter(exp):
            return True, diff
    g, e = Counter(got), Counter(exp)
    diff["missing_rows"] = sum((e - g).values())
    diff["extra_rows"] = sum((g - e).values())
    diff["has_duplicates"] = any(c > 1 for c in g.values()) and not any(c > 1 for c in e.values())
    diff["reason"] = "rows"
    return False, diff


def describe(diff):
    """Short deterministic, learner-facing explanation of a wrong result."""
    r = diff.get("reason")
    if r is None:
        return "Correct."
    if r == "column_count":
        return f"Expected {diff['expected_cols']} column(s), your query returned {diff['got_cols']}."
    if r == "order":
        return "Right rows, wrong order. Check the sort the question asks for."
    parts = [f"Expected {diff['expected_rows']} row(s), you returned {diff['got_rows']}."]
    if diff.get("missing_rows"):
        parts.append(f"{diff['missing_rows']} expected row(s) missing.")
    if diff.get("extra_rows"):
        parts.append(f"{diff['extra_rows']} row(s) that shouldn't be there.")
    if diff.get("has_duplicates"):
        parts.append("Your result has duplicate rows.")
    return " ".join(parts)
