"""Help-level policy. Deterministic, rule-based, no LLM.

v2 (10 Nov, after the first live try-out): help follows HOW CLOSE the learner's latest
attempt is (measured by the grader), not just how many hints they have asked for.

Inputs (all from the database, never from the client):
  arm               'tutor' | 'baseline'
  mastered          learner has shown this question's SKILL unaided: pretest item correct, or an
                    earlier practice question of the same skill solved with at most an L1 hint
  attempts          runs on this question so far (practice)
  attempts_since    runs since the last hint on this question
  last_level        highest tutor level already given on this question (0 = none)
  closeness         classification of the latest run (see `closeness()`):
                    'none' | 'error' | 'far' | 'close_rows' | 'close' | 'correct'
                    'close'      = right rows, only the columns or the order are off (a mechanical slip)
                                   (a wrong column count is close only if the row count matches)
                    'close_rows' = only a few rows wrong (often the CONCEPT itself, e.g. inner vs left join)
  fails_after_l4    runs that were not correct since the first L4 hint on this question

Tutor ladder (never reveals an executable full query; every level is about the learner's
own latest attempt when there is one):
  L1 symptom   – what is wrong with their result, as a question; no SQL feature or schema names
  L2 concept   – explains the idea behind the fix, in words; at most 2 short code words
  L3 skeleton  – one or two sentences + a code-made outline of the solution with ___ blanks; never runs
  L4 fix       – the exact change to make to their attempt, as a fragment, never the full query
  E  error     – explains the SQL error message and how to fix that line (mechanics, not the
                 skill; given straight away and does not climb the ladder)
Last resort: after L4 and REVEAL_AFTER more failed runs, the learner may choose
"Show solution" (logged as revealed; a revealed question does not count as solved).
Baseline: level 9 = full working query with a short explanation, on every request.
"""
from dataclasses import dataclass

MAX_LEVEL = 4
BASELINE_LEVEL = 9
REVEAL_LEVEL = 8
REVEAL_AFTER = 2          # failed runs after the first L4 hint before "Show solution" appears
CLOSE_ROW_SHARE = 0.2     # at most this share of rows wrong (missing + extra) counts as close


@dataclass(frozen=True)
class Decision:
    action: str   # 'gate' | 'repeat' | 'hint' | 'answer' | 'solved'
    level: int
    mode: str = "normal"   # 'normal' | 'error'
    message: str = ""


GATE_MSG = "Try one attempt yourself first. Run it, then ask again if it's still not right."
REPEAT_MSG = "Try using the last hint first. Run a new attempt, and the next hint will go one step further."
SOLVED_MSG = "Your latest query is already correct. Nice work. Move on to the next question."


def closeness(last_attempt) -> str:
    """Deterministic classification of the learner's latest run, from the grader's output."""
    if not last_attempt:
        return "none"
    if last_attempt.get("error"):
        # a timeout is almost always a missing join condition (rows multiplied): a concept problem,
        # not a typo, so it climbs the ladder like any wrong attempt instead of getting an error explanation
        if str(last_attempt["error"]).startswith("Query took longer than"):
            return "far"
        return "error"
    if last_attempt.get("correct"):
        return "correct"
    d = last_attempt.get("diff") or {}
    reason = d.get("reason")
    if reason == "order":
        return "close"
    if reason == "column_count":
        # close only when the ROWS are right: same row count, and either columns are missing
        # (e.g. DISTINCT(a, b) packed into one) or every expected column is among the extra ones.
        # An exploratory SELECT * on the wrong rows is far.
        if d.get("got_rows") is not None and d.get("got_rows") == d.get("expected_rows"):
            if (d.get("got_cols") or 0) < (d.get("expected_cols") or 0):
                return "close"
            if d.get("matched_cols") == d.get("expected_cols"):
                return "close"
        return "far"
    if reason == "rows":
        exp = max(1, d.get("expected_rows") or 0)
        wrong = (d.get("missing_rows") or 0) + (d.get("extra_rows") or 0)
        if wrong <= max(2, CLOSE_ROW_SHARE * exp):
            return "close_rows"
    return "far"


def decide(arm: str, mastered: bool, attempts: int, attempts_since: int, last_level: int,
           closeness: str = "none", fails_after_l4: int = 0, hinted: bool | None = None) -> Decision:
    """hinted: any hint (including an error explanation) was already given on this question.
    Error explanations don't climb the ladder, so they are not counted in last_level."""
    if hinted is None:
        hinted = last_level > 0
    if arm == "baseline":
        return Decision("answer", BASELINE_LEVEL)
    if arm != "tutor":
        raise ValueError(f"unknown arm {arm!r}")

    if closeness == "correct":
        return Decision("solved", 0, message=SOLVED_MSG)
    if last_level == 0 and attempts == 0:
        if mastered:
            return Decision("gate", 0, message=GATE_MSG)
        return Decision("hint", 1)            # no attempt yet: always start with the lightest touch
    if hinted and attempts_since == 0:
        return Decision("repeat", last_level, message=REPEAT_MSG)
    if closeness == "error":
        # explain the error; it does not climb the ladder (errors are mechanics). Stored at
        # max(1, last_level) with an *_error source, and ignored when computing last_level.
        return Decision("hint", max(1, last_level), mode="error")
    if closeness == "close":                 # right rows, wrong shape: give the exact fix
        return Decision("hint", MAX_LEVEL)
    if closeness == "close_rows":            # a few rows wrong is usually the concept itself:
        return Decision("hint", min(MAX_LEVEL, max(2, last_level + 2)))   # speed up, but don't skip to the fix
    # far from the answer: climb one step (first hint is L1)
    return Decision("hint", min(MAX_LEVEL, last_level + 1))


def reveal_available(arm: str, last_level: int, fails_after_l4: int, closeness: str) -> bool:
    return arm == "tutor" and last_level >= MAX_LEVEL and fails_after_l4 >= REVEAL_AFTER and closeness != "correct"
