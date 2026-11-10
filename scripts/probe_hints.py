"""Probe the tutor prompts with realistic stuck learners: exactly ONE LLM call per scenario.

Each scenario = a practice question + a typical learner attempt (or none) + the level the policy
would choose. The attempt is run through the real sandbox and grader, so the LLM gets exactly the
context it gets in the app. Each reply is then checked locally (no extra LLM calls) with the real
leak guard and shape check.

Run from the repo root:  python scripts/probe_hints.py            (all 6 scenarios)
                         python scripts/probe_hints.py 2 5        (only scenarios 2 and 5)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import assistant  # noqa: E402
from app.config import settings  # noqa: E402
from app.grader import compare  # noqa: E402
from app.policy import closeness  # noqa: E402
from app.sandbox import SandboxError, run_query  # noqa: E402

Q = {q["id"]: q for q in json.loads(settings.questions_json.read_text())}

SCENARIOS = [
    ("Blank page, no idea where to start", "T1", None, 1, "normal"),
    ("Close: DISTINCT written like a function (1 column instead of 2)", "T1",
     "select distinct(p.name, p.price) from products p join order_items o on o.product_id = p.product_id "
     "where o.unit_price < p.price", 4, "normal"),
    ("Inner join drops customers with no orders (LEFT JOIN skill)", "T2",
     "select c.customer_id, c.name, count(*) from customers c join orders o on o.customer_id = c.customer_id "
     "group by c.customer_id, c.name order by c.customer_id", 2, "normal"),
    ("Fan-out: joins payments and items together, counts and sums double", "T4",
     "select o.order_id, count(p.payment_id), sum(oi.quantity * oi.unit_price) from orders o "
     "join payments p on p.order_id = o.order_id join order_items oi on oi.order_id = o.order_id "
     "group by o.order_id having count(p.payment_id) > 1", 3, "normal"),
    ("Anti-join done as '<>' (wrong logic, far)", "T8",
     "select distinct c.customer_id, c.name from customers c join orders o on o.customer_id = c.customer_id "
     "join order_items oi on oi.order_id = o.order_id join products p on p.product_id = oi.product_id "
     "join categories cat on cat.category_id = p.category_id where cat.name <> 'Electronics'", 1, "normal"),
    ("SQL error: misspelt column", "T5",
     "select extract(month from order_dat), sum(quantity * unit_price) from orders join order_items "
     "using (order_id) where status = 'delivered' group by 1 order by 1", 1, "error"),
]


def attempt_record(qid, sql):
    if sql is None:
        return None
    q = Q[qid]
    try:
        res = run_query(sql)
    except SandboxError as e:
        return {"sql_text": sql, "error": str(e), "diff": None, "correct": False}
    ok, diff = compare(res["rows"], res["ncols"], q["expected_rows"], q["expected_ncols"], q["ordered"])
    return {"sql_text": sql, "error": None, "diff": diff, "correct": ok}


def main():
    if not settings.groq_api_key:
        sys.exit("GROQ_API_KEY not set in .env")
    pick = {int(a) for a in sys.argv[1:]} or set(range(1, len(SCENARIOS) + 1))
    for i, (title, qid, sql, level, mode) in enumerate(SCENARIOS, start=1):
        if i not in pick:
            continue
        q = Q[qid]
        att = attempt_record(qid, sql)
        user = assistant.tutor_prompt(q, level, att, mode)
        print("=" * 100)
        print(f"#{i} {title}\n   question {qid}, level {'E' if mode == 'error' else level}, "
              f"closeness of attempt: {closeness(att)}")
        if att:
            print(f"   grader: {att['error'] or att['diff']}")
        try:
            text, model = assistant._llm(assistant.TUTOR_SYSTEM, user)
        except Exception as e:
            print(f"   LLM FAILED: {type(e).__name__}: {e}")
            continue
        shape = assistant.shape_problem(text, level, mode)
        leak = assistant.leaks_answer(assistant.finish_hint(text, q, level, mode), q)   # as the learner sees it
        text = assistant.finish_hint(text, q, level, mode)
        verdict = "LEAK (blocked)" if leak else (f"SHAPE: {shape}" if shape else "OK")
        print(f"   model: {model} | {len(text)} chars | verdict: {verdict}")
        print("-" * 100)
        print(text)
    print("=" * 100)


if __name__ == "__main__":
    main()
