"""Freeze expected result sets into backend/app/questions.json.

Runs every reference query THROUGH THE LEARNER SANDBOX (so a reference query
that a learner couldn't run would fail here), normalises the rows and writes the
single source of truth used by the grader, the exercise UI and the tutor.

Also self-checks: every reference query must grade correct against itself,
and no question may have an empty expected result.

Run from repo root:  python scripts/build_questions.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.grader import compare, norm_rows  # noqa: E402
from app.question_bank import QUESTIONS, SKILLS  # noqa: E402
from app.sandbox import run_query  # noqa: E402
from app.config import settings  # noqa: E402


def main():
    if not settings.learner_dsn:
        sys.exit("LEARNER_DATABASE_URL not set (.env)")
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    counts = Counter(q["set"] for q in QUESTIONS)
    assert counts == {"pretest": 6, "practice": 8, "heldout": 8}, counts
    for s in ("pretest", "practice", "heldout"):
        skills = {q["skill"] for q in QUESTIONS if q["set"] == s}
        assert skills == set(SKILLS), f"{s} does not cover all skills: {skills}"

    out = []
    for q in QUESTIONS:
        res = run_query(q["sql"])
        rows = norm_rows(res["rows"])
        assert rows, f"{q['id']}: empty expected result"
        assert not res["truncated"], f"{q['id']}: truncated"
        ok, diff = compare(res["rows"], res["ncols"], rows, res["ncols"], q["ordered"])
        assert ok, f"{q['id']}: reference does not grade correct against itself {diff}"
        out.append({**q, "transfer": q.get("transfer"), "expected_ncols": res["ncols"], "expected_rows": [list(r) for r in rows]})
        print(f"{q['id']:3} {q['set']:8} {q['skill']}  rows={len(rows):3}  cols={res['ncols']}")
    settings.questions_json.write_text(json.dumps(out, indent=1))
    print(f"wrote {settings.questions_json}")


if __name__ == "__main__":
    main()
