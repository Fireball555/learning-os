"""Help-level policy. Deterministic, rule-based, no LLM.

Inputs (all from the database, never from the client):
  arm               'tutor' | 'baseline'
  mastered          learner has shown this question's SKILL unaided: pretest item correct, or an
                    earlier practice question of the same skill solved with at most an L1 hint
  attempts          runs on this question so far (practice)
  attempts_since    runs since the last hint on this question
  last_level        highest tutor level already given on this question (0 = none)

Tutor ladder (never reveals an executable full query):
  L1 concept   – name the idea/pattern needed; no table or column names
  L2 plan      – which tables, join type, keys, grouping, in words; no SQL
  L3 skeleton  – SQL outline with ___ blanks for the key parts; must not run
  L4 fix       – points at what is wrong in the learner's latest attempt
Baseline: level 9 = full working query with a short explanation, on every request.
"""
from dataclasses import dataclass

MAX_LEVEL = 4
BASELINE_LEVEL = 9


@dataclass(frozen=True)
class Decision:
    action: str   # 'gate' | 'repeat' | 'hint' | 'answer'
    level: int
    message: str = ""


GATE_MSG = "Try one attempt yourself first. Run it, then ask again if it's still not right."
REPEAT_MSG = "Try using the last hint first. Run a new attempt, and the next hint will go one step further."


def decide(arm: str, mastered: bool, attempts: int, attempts_since: int, last_level: int) -> Decision:
    if arm == "baseline":
        return Decision("answer", BASELINE_LEVEL)
    if arm != "tutor":
        raise ValueError(f"unknown arm {arm!r}")

    if last_level == 0:
        if mastered and attempts == 0:
            return Decision("gate", 0, GATE_MSG)
        # skill shown unaided -> start at the lightest touch; not shown -> start at the plan
        return Decision("hint", 1 if mastered else 2)

    if attempts_since == 0:
        return Decision("repeat", last_level, REPEAT_MSG)
    return Decision("hint", min(MAX_LEVEL, last_level + 1))
