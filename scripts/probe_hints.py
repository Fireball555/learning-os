"""Probe tutor v2 with the REAL stuck moments from round 1 (10 Nov), through the real pipeline:
example rows -> prompt -> LLM -> leak guard + v2 shape rules -> one retry -> built-in fallback.
About 1-2 Groq calls per scenario. Nothing is written to the database (read-only sandbox only).

Run from the repo root:  python scripts/probe_hints.py          (all scenarios)
                         python scripts/probe_hints.py 1 4 7    (only those)
Paste the whole output back to Claude.
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

# (what to look for, question, the learner's real SQL, level the policy would choose, mode)
SCENARIOS = [
    ("ERROR, alias in WHERE. Must NOT suggest HAVING (Praneeth T3 leak)", "T3",
     "select p.product_id, p.name ,count(o.order_id) as ocount from products p inner join order_items o "
     "on p.product_id=o.product_id where ocount=0", 1, "error"),
    ("ERROR, missing JOIN keyword. Fix only that, no rewrite (Praneeth T7)", "T7",
     "SELECT c.customer_id, c.name, COALESCE(SUM(ot.quantity), 0) AS total_units FROM customers c LEFT JOIN orders o "
     "ON c.customer_id = o.customer_id order_items ot on o.order_id = ot.order_id GROUP BY c.customer_id, c.name "
     "ORDER BY total_units DESC, c.customer_id ASC", 1, "error"),
    ("ERROR, SUM(SELECT ...). Explain the error, don't hand over the subquery (Ashish T2)", "T2",
     "SELECT c.customer_id, c.name, SUM(SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id) "
     "FROM customers c ORDER BY c.customer_id", 1, "error"),
    ("ERROR, aggregate in WHERE (Praneeth T3)", "T3",
     "select p.product_id, p.name from products p inner join order_items o on p.product_id=o.product_id "
     "where count(o.product_id) is null", 1, "error"),
    ("L1, must LOCATE: sums payments instead of items (Ashish T4; v1 rejected the good answer)", "T4",
     "SELECT o.order_id, (SELECT COUNT(*) FROM payments p WHERE o.order_id = p.order_id) as payment_count, "
     "(SELECT SUM(amount) FROM payments p WHERE o.order_id = p.order_id) FROM orders o "
     "WHERE (SELECT COUNT(*) FROM payments p WHERE o.order_id = p.order_id) > 1", 1, "normal"),
    ("L1, must LOCATE: joins a column to itself (Ashish T3)", "T3",
     "SELECT DISTINCT p.product_id, p.name FROM products p JOIN order_items o ON p.product_id = p.product_id", 1, "normal"),
    ("L1, comma cross join. Point at the missing link, no LEFT JOIN (Samyuktha T2)", "T2",
     "select c.customer_id , c.name , count(o.order_id) as order_count from customers c, orders o "
     "group by c.customer_id, c.name order by c.customer_id", 1, "normal"),
    ("L1, fan-out: payments x items (Gowtham T4)", "T4",
     "select p.order_id,count(p.payment_id),sum(a.quantity*a.unit_price) from payments p join order_items a "
     "on a.order_id=p.order_id group by p.order_id having count(p.payment_id)>1", 1, "normal"),
    ("L1, no attempt yet (blank page, T5). A question, no plan", "T5", None, 1, "normal"),
    ("L2, concept after a comma join (Praneeth T1)", "T1",
     "select distinct p.name, p.price from products p , order_items o where o.unit_price < p.price", 2, "normal"),
    ("L3, skeleton sentence (Samyuktha-style T8, '<>' logic)", "T8",
     "SELECT DISTINCT c.customer_id, c.name FROM customers c JOIN orders o ON o.customer_id = c.customer_id "
     "JOIN order_items oi ON oi.order_id = o.order_id JOIN products p ON p.product_id = oi.product_id "
     "JOIN categories cat ON cat.category_id = p.category_id WHERE cat.name <> 'Electronics'", 3, "normal"),
    ("L4, exact fix: right rows, wrong order (Gowtham T7)", "T7",
     "select c.customer_id,c.name,coalesce(sum(a.quantity),0) as total from customers c left join orders o "
     "on o.customer_id=c.customer_id left join order_items a on a.order_id=o.order_id group by c.customer_id "
     "order by total desc", 4, "normal"),
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
        print("=" * 100)
        print(f"#{i} {title}\n   {qid} level {'E' if mode == 'error' else level} | closeness: {closeness(att)}"
              + (f" | grader: {att['error'] or att['diff']}" if att else ""))
        r = assistant.tutor_hint(q, level, att, mode=mode)
        for rj in r.get("rejects") or []:
            print(f"   REJECTED ({rj.get('model')}): {rj['why']}\n      {(rj.get('text') or '')[:400]!r}")
        print(f"   FINAL: {r['source']} | model {r['model']} | {r['latency_ms']} ms | {len(r['text'])} chars")
        print("-" * 100)
        print(r["text"])
    print("=" * 100)


if __name__ == "__main__":
    main()
