"""Simulated learners on the TUTOR arm, to check the pacing of the hint ladder before real people.

Each persona is an LLM told to act as a student who only knows certain SQL. That limit is ENFORCED
by code: an attempt that uses a construct the persona doesn't know, and that no hint so far has
mentioned, is rejected and the persona has to try again. The tutor side is the real thing:
policy.decide + grader + sandbox + assistant.tutor_hint (real prompts, leak guard, shape check).

Nothing is written to the database: state is kept in memory, and queries go through the
read-only learner role. Safe to run against the study database before the pretest.

This is a pacing check, NOT data. An LLM is a poor stand-in for a real novice; never report
these numbers as results. What it can show: whether learners reach "Show solution" too often,
how often each level is used, and how often hints fall back to the built-in text.

Groq tokens: the tutor uses the app's model chain (same daily limits as the real sessions).
Defaults are small; the script prints tokens used and stops at --budget.

Run from the repo root:
  python scripts/simulate_learners.py                       # 3 personas x 4 hard questions
  python scripts/simulate_learners.py --questions T1 T2 T3 T4 T5 T6 T7 T8 --personas novice
  python scripts/simulate_learners.py --learner-model qwen/qwen3.8-27b --budget 150000
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import assistant  # noqa: E402
from app.config import settings  # noqa: E402
from app.grader import compare, describe  # noqa: E402
from app.policy import closeness, decide, reveal_available  # noqa: E402
from app.sandbox import InfraError, SandboxError, run_query  # noqa: E402

Q = {q["id"]: q for q in json.loads(settings.questions_json.read_text())}

# construct -> (regex on the learner's SQL, regex on hint text that "teaches" it)
CONSTRUCTS = {
    # a comma list in FROM ("FROM customers c, orders o") is a join too
    "join":      (r"\bjoin\b|\bfrom\s+[\w.]+(\s+(as\s+)?\w+)?\s*,\s*[\w.]+", r"\bjoin\b"),
    "left join": (r"\b(left|right|full)\s+(outer\s+)?join\b", r"\b(left|outer)\s+join\b|\bleft\b"),
    "exists":    (r"\bexists\b", r"\bexists\b"),
    "not in":    (r"\bnot\s+in\s*\(", r"\bnot\s+in\b"),
    "subquery":  (r"\(\s*select\b", r"\bsub-?quer|\(\s*select\b|\bexists\b|\bnot\s+in\b"),
    "with":      (r"^\s*with\b", r"\bwith\b|\bcte\b"),
    "distinct":  (r"\bdistinct\b", r"\bdistinct\b"),
    "coalesce":  (r"\bcoalesce\b", r"\bcoalesce\b"),
    "dates":     (r"\bextract\s*\(|\bdate_part\b|\bdate_trunc\b|\binterval\b", r"\bextract\b|\bdate_part\b|\bdate_trunc\b|\binterval\b"),
}

PERSONAS = {
    "novice": dict(
        knows=[],
        text="You know SELECT, FROM, WHERE (=, <, >, AND, OR, BETWEEN, LIKE), ORDER BY, LIMIT, COUNT/SUM/AVG/MIN/MAX "
             "and GROUP BY/HAVING on ONE table. You have never seen JOIN, LEFT JOIN, subqueries, EXISTS, IN (...), "
             "DISTINCT, COALESCE or date functions. You often forget details of the question."),
    "middle": dict(
        knows=["join", "distinct"],
        text="You know single-table SQL well (SELECT, WHERE, GROUP BY, HAVING, ORDER BY, aggregates, DISTINCT) and "
             "you have seen a plain `JOIN ... ON` once. You do not know LEFT JOIN, subqueries, EXISTS, NOT IN, "
             "COALESCE or date functions. You tend to join everything and filter in WHERE."),
    "strong": dict(
        knows=["join", "distinct", "left join", "coalesce"],
        text="You know single-table SQL, inner JOIN and LEFT JOIN, DISTINCT and COALESCE. You do not know "
             "subqueries, EXISTS, NOT IN, CTEs or date functions. You make the usual slips: filtering a LEFT JOIN "
             "in WHERE, counting rows that fan out, forgetting a column."),
}

LEARNER_SYSTEM = """You are role-playing a university student practising SQL (PostgreSQL) in a tutoring app.
{persona}
Stay in character: only write SQL a student with exactly this knowledge would write. You may use a new
construct ONLY after a tutor hint has mentioned it. Make honest attempts; don't pretend to be worse on purpose.
Reply with ONE query in a ```sql block and nothing else."""

TOKENS = {"learner": 0, "tutor_est": 0}


def learner_llm(model, system, user):
    from groq import Groq
    client = Groq(api_key=settings.groq_api_key, timeout=30.0, max_retries=2)
    kw = dict(model=model, temperature=0.7,
              messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    kw.update(assistant._model_kwargs(model))
    r = client.chat.completions.create(**kw)
    TOKENS["learner"] += getattr(r.usage, "total_tokens", 0) or 0
    return assistant._strip_reasoning(r.choices[0].message.content or "")


def extract_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip().rstrip(";")


def unknown_constructs(sql, knows, hints):
    taught = " ".join(hints).lower()
    bad = []
    for name, (use_rx, teach_rx) in CONSTRUCTS.items():
        if name in knows or not re.search(use_rx, sql, re.I | re.M):
            continue
        if not re.search(teach_rx, taught, re.I):
            bad.append(name)
    return bad


def run_attempt(q, sql):
    try:
        res = run_query(sql)
    except SandboxError as e:
        return {"sql_text": sql, "error": str(e), "diff": None, "correct": False}, None
    ok, diff = compare(res["rows"], res["ncols"], q["expected_rows"], q["expected_ncols"], q["ordered"])
    return {"sql_text": sql, "error": None, "diff": diff, "correct": ok}, res


def feedback(att, res):
    if att["error"]:
        return f"ERROR: {att['error']}"
    if att["correct"]:
        return "Correct!"
    rows = "\n".join(" | ".join(str(v) for v in r) for r in res["rows"][:5])
    return f"Not right yet. {describe(att['diff'])}\nFirst rows you got:\n{rows}"


def simulate(persona_name, qids, model, max_runs, budget, mastered_skills, verbose):
    p = PERSONAS[persona_name]
    system = LEARNER_SYSTEM.format(persona=p["text"])
    out = []
    for qid in qids:
        q = Q[qid]
        hints, history, levels = [], [], []
        st = dict(attempts=0, since=0, last_level=0, hinted=False, fails_after_l4=0, l4_seen=False, last=None)
        result, rejected, fallbacks = "gave up", 0, 0
        mastered = q["skill"] in mastered_skills
        while st["attempts"] < max_runs:
            if TOKENS["learner"] + TOKENS["tutor_est"] > budget:
                result = "budget"
                break
            # the persona asks for help when it has none yet and the last run failed (or nothing run yet)
            if not st["attempts"] or (st["last"] and not st["last"]["correct"]):
                cl = closeness(st["last"])
                if reveal_available("tutor", st["last_level"], st["fails_after_l4"], cl):
                    result = "REVEAL"
                    break
                d = decide("tutor", mastered, st["attempts"], st["since"], st["last_level"], cl,
                           st["fails_after_l4"], hinted=st["hinted"])
                if d.action == "hint":
                    t0 = time.perf_counter()
                    r = assistant.tutor_hint(q, d.level, st["last"], mode=d.mode)
                    TOKENS["tutor_est"] += 0 if r["source"] == "fallback" and not r["guard_blocked"] else \
                        3000 * (1 + (r["source"] == "llm_retry") + (r["source"] == "fallback"))
                    fallbacks += r["source"] == "fallback"
                    hints.append(r["text"])
                    lab = f"E{d.level}" if d.mode == "error" else f"L{d.level}"
                    levels.append(lab + ("*" if r["source"] == "fallback" else ""))
                    st["hinted"], st["since"] = True, 0
                    if d.mode == "normal":
                        st["last_level"] = max(st["last_level"], d.level)
                        if d.level == 4:
                            st["l4_seen"] = True
                    if verbose:
                        print(f"    [{lab} {r['source']} {int((time.perf_counter()-t0)*1000)}ms] {r['text'][:300]!r}")
                elif d.action == "gate" and verbose:
                    print("    [gate] try once first")
            # the persona writes an attempt
            ctx = (f"{assistant.SCHEMA_TEXT}\n\nQuestion:\n{q['prompt']}\n\n"
                   + "".join(f"Your attempt {i+1}:\n```sql\n{a}\n```\nResult: {f}\n\n" for i, (a, f) in enumerate(history))
                   + "".join(f"Tutor hint {i+1}:\n{h}\n\n" for i, h in enumerate(hints))
                   + "Write your next attempt.")
            sql = extract_sql(learner_llm(model, system, ctx))
            bad = unknown_constructs(sql, p["knows"], hints)
            if bad:
                rejected += 1
                ctx += (f"\n\n(You don't know {', '.join(bad)} and no hint has taught it. Write your best attempt "
                        "using ONLY what you know, even if you suspect it is wrong.)")
                sql = extract_sql(learner_llm(model, system, ctx))
                if unknown_constructs(sql, p["knows"], hints):
                    # still out of character: behave like a lost student who runs something simple
                    first = q["sql"].split("FROM", 1)[1].split()[0] if "FROM" in q["sql"] else "shop.customers"
                    sql = f"select * from {first}"
            att, res = run_attempt(q, sql)
            st["attempts"] += 1
            st["since"] += 1
            st["last"] = att
            if st["l4_seen"] and not att["correct"]:
                st["fails_after_l4"] += 1
            history.append((sql, feedback(att, res)))
            if verbose:
                print(f"    run {st['attempts']}: {closeness(att):10s} {sql[:110]!r}")
            if att["correct"]:
                result = "solved"
                if max([int(x[1]) for x in levels if x.startswith("L")] or [0]) <= 1:
                    mastered_skills.add(q["skill"])
                break
        out.append(dict(q=qid, result=result, runs=st["attempts"], levels=" ".join(levels) or "-",
                        fallbacks=fallbacks, rejected=rejected))
        print(f"  {persona_name:7s} {qid}: {result:16s} runs={st['attempts']} hints={' '.join(levels) or '-'}"
              f" fallbacks={fallbacks} out-of-character attempts={rejected}", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", nargs="+", default=["novice", "middle", "strong"], choices=list(PERSONAS))
    ap.add_argument("--questions", nargs="+", default=["T2", "T3", "T6", "T8"])
    ap.add_argument("--learner-model", default="openai/gpt-oss-20b")
    ap.add_argument("--max-runs", type=int, default=6, help="about 45 min / 8 questions = ~6 runs each")
    ap.add_argument("--budget", type=int, default=120000, help="stop after about this many Groq tokens")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every hint and attempt")
    a = ap.parse_args()
    if not settings.groq_api_key:
        sys.exit("GROQ_API_KEY not set in .env")
    try:
        run_query("select 1")
    except (InfraError, SandboxError) as e:
        sys.exit(f"database not reachable: {e}")
    allres = {}
    for p in a.personas:
        print(f"\n== {p} ==")
        allres[p] = simulate(p, a.questions, a.learner_model, a.max_runs, a.budget, set(), a.verbose)
    print("\n== summary (pacing check, not data) ==")
    for p, rs in allres.items():
        n = len(rs)
        count = lambda k: sum(r["result"] == k for r in rs)
        fb = sum(r["fallbacks"] for r in rs)
        nh = sum(len(r["levels"].split()) for r in rs if r["levels"] != "-")
        print(f"  {p:7s} solved {count('solved')}/{n} | reached Show solution {count('REVEAL')}/{n} | "
              f"not solved in {a.max_runs} runs {count('gave up')} | fallback hints {fb}/{nh} | "
              f"out-of-character attempts {sum(r['rejected'] for r in rs)}")
    print(f"tokens: learner {TOKENS['learner']}, tutor ~{TOKENS['tutor_est']} (estimate)")
    print("Rule of thumb: Show solution on more than 2 of 8 questions = the ladder is too slow.")


if __name__ == "__main__":
    main()
