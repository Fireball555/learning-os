"""Run from backend/:  python -m pytest -q
Needs a database built with scripts/reset_db.sh. API tests WIPE app.* tables:
they refuse to run unless ALLOW_WIPE=1 (never point them at the live study DB)."""
import os
from decimal import Decimal

import pytest

from app.config import settings
from app.grader import compare, norm_rows
from app.policy import decide

needs_db = pytest.mark.skipif(not settings.learner_dsn, reason="no DB")


# ---------------- grader (pure)
def test_grader_ignores_aliases_and_order_when_unordered():
    exp = norm_rows([(1, "a"), (2, "b")])
    assert compare([(2, "b"), (1, "a")], 2, exp, 2, ordered=False)[0]
    assert not compare([(2, "b"), (1, "a")], 2, exp, 2, ordered=True)[0]


def test_grader_multiset_counts_duplicates():
    exp = norm_rows([("x",)])
    ok, diff = compare([("x",), ("x",)], 1, exp, 1, False)
    assert not ok and diff["has_duplicates"]


def test_grader_numeric_normalisation_and_nulls():
    exp = norm_rows([(Decimal("10.50"), None)])
    assert compare([(10.5, None)], 2, exp, 2, False)[0]
    assert not compare([(10.5, 0)], 2, exp, 2, False)[0]


def test_grader_column_count():
    assert compare([(1, 2)], 2, norm_rows([(1,)]), 1, False)[1]["reason"] == "column_count"


# ---------------- policy (pure)
def test_policy_baseline_always_answers():
    for a in range(3):
        assert decide("baseline", True, a, 0, 0).action == "answer"


def test_policy_gate_then_ladder():
    assert decide("tutor", True, 0, 0, 0).action == "gate"
    assert decide("tutor", True, 1, 1, 0, "far").level == 1
    assert decide("tutor", False, 0, 0, 0).level == 1
    assert decide("tutor", False, 3, 0, 2, "far").action == "repeat"
    assert decide("tutor", False, 3, 1, 2, "far").level == 3
    assert decide("tutor", False, 9, 1, 4, "far").level == 4


def test_policy_follows_closeness():
    from app.policy import closeness, reveal_available
    # close -> straight to L4, even as the first hint
    assert decide("tutor", False, 1, 1, 0, "close").level == 4
    assert decide("tutor", True, 2, 1, 1, "close").level == 4
    # SQL error -> explain the error, do not climb
    d = decide("tutor", False, 2, 1, 2, "error")
    assert d.mode == "error" and d.level == 2
    # already correct -> no hint
    assert decide("tutor", False, 2, 1, 2, "correct").action == "solved"
    # closeness classification
    assert closeness(None) == "none"
    assert closeness({"error": "syntax error"}) == "error"
    assert closeness({"correct": True, "diff": {}}) == "correct"
    # wrong column count is close only with the right row count (not an exploratory SELECT *)
    assert closeness({"diff": {"reason": "column_count", "got_rows": 5, "expected_rows": 5,
                               "got_cols": 1, "expected_cols": 2}}) == "close"
    assert closeness({"diff": {"reason": "column_count", "got_rows": 40, "expected_rows": 5,
                               "got_cols": 6, "expected_cols": 2}}) == "far"
    assert closeness({"diff": {"reason": "column_count", "got_rows": 5, "expected_rows": 5,
                               "got_cols": 4, "expected_cols": 2, "matched_cols": 2}}) == "close"
    assert closeness({"diff": {"reason": "column_count", "got_rows": 5, "expected_rows": 5,
                               "got_cols": 4, "expected_cols": 2, "matched_cols": 1}}) == "far"
    assert closeness({"diff": {"reason": "column_count"}}) == "far"
    # an error explanation doesn't climb the ladder: with no ladder hint yet, the next far attempt gets L1
    assert decide("tutor", False, 2, 1, 0, "far", hinted=True).level == 1
    assert decide("tutor", False, 2, 0, 0, "error", hinted=True).action == "repeat"
    assert closeness({"diff": {"reason": "order"}}) == "close"
    assert closeness({"diff": {"reason": "rows", "expected_rows": 19, "missing_rows": 2, "extra_rows": 1}}) == "close_rows"
    assert closeness({"diff": {"reason": "rows", "expected_rows": 19, "missing_rows": 8, "extra_rows": 2}}) == "far"
    assert closeness({"diff": {"reason": "rows", "expected_rows": 4, "missing_rows": 2, "extra_rows": 0}}) == "close_rows"
    # a few rows wrong speeds up the ladder but does not jump to the fix
    assert decide("tutor", False, 1, 1, 0, "close_rows").level == 2
    assert decide("tutor", False, 2, 1, 1, "close_rows").level == 3
    assert decide("tutor", False, 3, 1, 3, "close_rows").level == 4
    # reveal only after L4 + 2 failed runs, tutor only
    assert not reveal_available("tutor", 4, 1, "far")
    assert reveal_available("tutor", 4, 2, "far")
    assert not reveal_available("tutor", 3, 5, "far")
    assert not reveal_available("baseline", 4, 5, "far")


# ---------------- sandbox security
@needs_db
@pytest.mark.parametrize("sql,needle", [
    ("delete from shop.orders", "Only SELECT"),
    ("select 1; select 2", "one statement"),
    ("select * from app.learners", "permission denied"),
    ("with x as (delete from shop.payments returning *) select * from x", "data-modifying"),
    ("select pg_sleep(5)", "3 seconds"),
    ("select set_config('role','postgres',false)", "permission denied"),
    ("select pg_read_file('/etc/passwd')", "permission denied"),
    ("select $$a$$", "Dollar"),
    ("select repeat('x', 1000000) from generate_series(1, 600)", ("too long", "3 seconds")),
])
def test_sandbox_blocks(sql, needle):
    from app.sandbox import SandboxError, run_query
    with pytest.raises(SandboxError) as e:
        run_query(sql)
    needles = needle if isinstance(needle, tuple) else (needle,)
    assert any(n.lower() in str(e.value).lower() for n in needles)


@needs_db
def test_sandbox_allows_semicolon_in_string_and_trailing():
    from app.sandbox import run_query
    assert run_query("select 'a;b' as x;")["rows"] == [("a;b",)]
    assert run_query("select E'it\\'s' as x")["rows"] == [("it's",)]
    assert run_query("select 1; -- done")["rows"] == [(1,)]


@needs_db
def test_sandbox_cartesian_is_capped_not_materialised():
    import resource
    from app.sandbox import SandboxError, run_query
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    try:   # over a slow network the 3.5 s wall clock may stop it first; both outcomes are safe
        r = run_query("select * from orders o, order_items oi, payments p")
        assert r["truncated"] and len(r["rows"]) <= 1000
    except SandboxError as e:
        assert "3 seconds" in str(e)
    assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before < 150_000   # KB


def test_infra_error_is_not_a_learner_error(monkeypatch):
    from app import sandbox
    from app.config import settings as s
    monkeypatch.setattr(s, "learner_dsn", "postgresql://nobody@127.0.0.1:1/x")
    with pytest.raises(sandbox.InfraError):
        sandbox.run_query("select 1")


# ---------------- question bank: traps must be graded wrong, valid variants right
TRAPS = {
    # --- wrong approaches that must be graded WRONG
    "P4": ("select c.city,count(*),sum(p.amount) from shop.customers c join shop.orders o using(customer_id) join shop.payments p using(order_id) group by 1", False),
    "H4": ("select c.name,count(o.order_id),sum(p.amount) from shop.customers c join shop.orders o using(customer_id) join shop.payments p using(order_id) group by c.customer_id,c.name", False),
    "T4": ("select o.order_id,count(p.payment_id),sum(oi.quantity*oi.unit_price) from shop.orders o join shop.payments p using(order_id) join shop.order_items oi using(order_id) group by 1 having count(distinct p.payment_id)>1", False),
    "T4_paybypass": ("select order_id, count(*), sum(amount) from payments group by 1 having count(*)>1", False),
    "T2": ("select c.customer_id,c.name,count(*) from shop.customers c left join shop.orders o using(customer_id) group by 1,2 order by 1", False),
    "T7": ("select c.customer_id,c.name,sum(oi.quantity) s from customers c left join orders o using(customer_id) left join order_items oi using(order_id) group by 1,2 order by s desc nulls last,1", False),
    "T7_inner": ("select c.customer_id,c.name,coalesce(sum(oi.quantity),0) s from customers c left join orders o using(customer_id) join order_items oi using(order_id) group by 1,2 order by s desc,1", False),
    "H2": ("select c.name,sum(oi.quantity) from shop.categories c left join shop.products p using(category_id) left join shop.order_items oi using(product_id) group by c.category_id,c.name", False),
    "H2_inner": ("select c.name,coalesce(sum(oi.quantity),0) from shop.categories c left join shop.products p using(category_id) join shop.order_items oi using(product_id) group by c.category_id,c.name", False),
    "P5_lo": ("select distinct c.name from shop.customers c join shop.orders o using(customer_id) where o.order_date > '2026-01-01' and o.order_date <= '2026-03-31'", False),
    "P5_hi": ("select distinct c.name from shop.customers c join shop.orders o using(customer_id) where o.order_date >= '2026-01-01' and o.order_date < '2026-03-31'", False),
    "H5_lo": ("select p.name,count(distinct o.order_id) from products p join order_items oi using(product_id) join orders o using(order_id) where o.order_date > '2025-12-01' and o.order_date < '2026-01-01' group by p.product_id,p.name", False),
    "H5_hi": ("select p.name,count(distinct o.order_id) from products p join order_items oi using(product_id) join orders o using(order_id) where o.order_date >= '2025-12-01' and o.order_date < '2025-12-31' group by p.product_id,p.name", False),
    "H5_noyear": ("select p.name,count(distinct o.order_id) from products p join order_items oi using(product_id) join orders o using(order_id) where extract(month from o.order_date)=12 group by p.product_id,p.name", False),
    "T5": ("select extract(month from order_date), sum(quantity*unit_price) from shop.orders join shop.order_items using(order_id) where status='delivered' and order_date >= '2025-01-02' and order_date < '2025-12-31' group by 1 order by 1", False),
    "T5_payments": ("select extract(month from order_date), sum(amount) from orders join payments using(order_id) where status='delivered' and order_date between '2025-01-01' and '2025-12-31' group by 1 order by 1", False),
    "H3": ("select c.customer_id,c.name from shop.customers c left join shop.orders o using(customer_id) where o.order_id is null", False),
    "H8": ("select distinct p.name from shop.products p join shop.order_items oi using(product_id) join shop.orders o using(order_id) join shop.customers c using(customer_id) where c.city<>'Chennai'", False),
    "T8": ("select distinct c.customer_id,c.name from customers c join orders o using(customer_id) join order_items oi using(order_id) join products p using(product_id) join categories cat using(category_id) where cat.name<>'Electronics'", False),
    "H7_where": ("select c.customer_id,c.name,min(o.order_date) from customers c left join orders o on o.customer_id=c.customer_id where o.status='delivered' group by 1,2", False),
    "H7_nostatus": ("select c.customer_id,c.name,min(o.order_date) from customers c left join orders o on o.customer_id=c.customer_id group by 1,2", False),
    "P2": ("select c.name,count(*) from shop.categories c left join shop.products p using(category_id) group by c.category_id,c.name", False),
    # --- valid alternatives that must be graded RIGHT
    "P3": ("select c.customer_id,c.name from shop.customers c left join shop.orders o using(customer_id) where o.order_id is null", True),
    "T2_alias": ("select c.customer_id as id,c.name as n,count(o.order_id) as x from customers c left join orders o on o.customer_id=c.customer_id group by 1,2 order by 1;", True),
    "T5_between": ("select extract(month from order_date)::int, sum(quantity*unit_price) from shop.orders join shop.order_items using(order_id) where status='delivered' and order_date between '2025-01-01' and '2025-12-31' group by 1 order by 1", True),
    "T5_tochar": ("select to_char(order_date,'FMMM'), sum(quantity*unit_price) from orders join order_items using(order_id) where status='delivered' and extract(year from order_date)=2025 group by 1, extract(month from order_date) order by extract(month from order_date)", True),
    "H3_notin": ("select customer_id, name from customers where customer_id not in (select o.customer_id from orders o join payments p on p.order_id=o.order_id)", True),
    "H7_sub": ("select c.customer_id,c.name,(select min(order_date) from orders o where o.customer_id=c.customer_id and status='delivered') from customers c", True),
    "T8_notin": ("select customer_id,name from customers where customer_id not in (select o.customer_id from orders o join order_items oi on oi.order_id=o.order_id join products p on p.product_id=oi.product_id where p.category_id=(select category_id from categories where name='Electronics'))", True),
    "H5_between": ("select p.name,count(distinct oi.order_id) from products p, order_items oi, orders o where p.product_id=oi.product_id and o.order_id=oi.order_id and o.order_date between '2025-12-01' and '2025-12-31' group by p.name", True),
}


@needs_db
@pytest.mark.parametrize("key", list(TRAPS))
def test_traps(key):
    from app.main import QUESTIONS
    from app.sandbox import run_query
    sql, want = TRAPS[key]
    q = QUESTIONS[key.split("_")[0]]
    r = run_query(sql)
    assert compare(r["rows"], r["ncols"], q["expected_rows"], q["expected_ncols"], q["ordered"])[0] is want


# ---------------- API flow (wipes app data)
def start_all(client, A):
    """New learners wait; the invigilator starts the pretest clock."""
    ids = [x["learner_id"] for x in client.get("/api/admin/learners", headers=A).json() if x["phase"] == "waiting"]
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "pretest"}, headers=A).status_code == 200

@pytest.fixture
def client():
    if os.environ.get("ALLOW_WIPE") != "1":
        pytest.skip("set ALLOW_WIPE=1 to run API tests (wipes app.* tables)")
    from fastapi.testclient import TestClient
    from app import db
    from app.main import app
    db.ex("TRUNCATE app.attempts, app.question_views, app.hints, app.survey, app.events, app.learners RESTART IDENTITY CASCADE")
    return TestClient(app)


def test_full_flow(client, monkeypatch):
    from app.config import settings as s
    from app.main import QUESTIONS
    monkeypatch.setattr(s, "admin_token", "t")
    monkeypatch.setattr(s, "groq_api_key", "")
    A = {"x-admin-token": "t"}
    assert client.get("/api/admin/learners").status_code == 401
    codes = client.post("/api/admin/learners", json={"names": [f"L{i}" for i in range(6)]}, headers=A).json()
    assert client.get("/api/me", headers={"Authorization": "Bearer " + codes[0]["code"]}).json()["questions"] == []
    start_all(client, A)
    H = lambda k: {"Authorization": "Bearer " + k}
    for i, l in enumerate(codes):
        me = client.get("/api/me", headers=H(l["code"])).json()
        assert me["phase"] == "pretest" and len(me["questions"]) == 6 and not me["help_available"]
        assert all("sql" not in q and "skill" not in q and "expected_rows" not in q for q in me["questions"])
        # assign before pretest complete is refused
        if i == 0:
            assert client.post("/api/admin/assign", headers=A).status_code == 400
        for j, q in enumerate(me["questions"]):
            sql = QUESTIONS[q["id"]]["sql"] if j < i else "select 1"
            r = client.post(f"/api/questions/{q['id']}/run", json={"sql": sql}, headers=H(l["code"])).json()
            assert "correct" not in r and "feedback" not in r
            assert client.post(f"/api/questions/{q['id']}/help", headers=H(l["code"])).status_code == 404
            assert client.post(f"/api/questions/{q['id']}/submit", json={"sql": sql}, headers=H(l["code"])).json() == {"submitted": True}
            assert client.post(f"/api/questions/{q['id']}/submit", json={"sql": sql}, headers=H(l["code"])).status_code == 409
            assert client.post(f"/api/questions/{q['id']}/run", json={"sql": sql}, headers=H(l["code"])).status_code == 409
        for qid in ("H1", "T1"):   # other phases unreachable
            assert client.post(f"/api/questions/{qid}/run", json={"sql": "select 1"}, headers=H(l["code"])).status_code == 404
    # practice before arms -> refused
    ids = [x["learner_id"] for x in client.get("/api/admin/learners", headers=A).json()]
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "practice"}, headers=A).status_code == 400
    log = client.post("/api/admin/assign", headers=A).json()
    assert len(log) == 3
    ls = client.get("/api/admin/learners", headers=A).json()
    assert sorted(x["arm"] for x in ls) == ["baseline"] * 3 + ["tutor"] * 3
    for p in (1, 2, 3):   # pairs are adjacent ranks
        sc = sorted(x["pretest_score"] for x in ls if x["pair_no"] == p)
        assert sc[1] - sc[0] == 1
    assert client.post("/api/admin/assign", headers=A).status_code == 400   # no re-assign
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "practice"}, headers=A).status_code == 200
    for l in ls:
        k = l["code"]
        r = client.post("/api/questions/T4/help", headers=H(k)).json()
        assert set(r) == {"text", "reveal_available"}   # same keys for both arms: nothing reveals the arm
        if l["arm"] == "baseline":
            assert "```sql" in r["text"]
        else:
            assert "WITH pc AS (SELECT order_id, COUNT" not in r["text"]
        assert client.post("/api/questions/H1/help", headers=H(k)).status_code == 404
        r = client.post("/api/questions/T4/run", json={"sql": QUESTIONS["T4"]["sql"]}, headers=H(k)).json()
        assert r["correct"] is True
    assert client.post("/api/survey", json={"value": 6}, headers=H(ls[0]["code"])).status_code == 422
    assert client.post("/api/survey", json={"value": 4}, headers=H(ls[0]["code"])).json() == {"ok": True}
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "heldout"}, headers=A).status_code == 200
    me = client.get("/api/me", headers=H(ls[0]["code"])).json()
    assert [q["id"] for q in me["questions"]] == [f"H{i}" for i in range(1, 9)] and not me["help_available"]
    assert client.post("/api/questions/T4/help", headers=H(ls[0]["code"])).status_code == 404
    ex = client.get("/api/admin/export", headers=A).json()
    assert len(ex["learners"]) == 6 and any(e["kind"] == "assign" for e in ex["events"])


def test_guard_blocks_leaked_answer():
    if not settings.learner_dsn:
        pytest.skip("no DB")
    from app.assistant import leaks_answer
    from app.main import QUESTIONS
    q = QUESTIONS["T3"]
    assert leaks_answer(f"Try this:\n```sql\n{q['sql']}\n```", q)
    assert leaks_answer("just run SELECT p.product_id, p.name FROM shop.products p WHERE NOT EXISTS "
                        "(SELECT 1 FROM shop.order_items oi WHERE oi.product_id = p.product_id)", q)
    assert not leaks_answer("```sql\nSELECT ___ FROM shop.products p WHERE NOT EXISTS (___)\n```", q)
    assert not leaks_answer("Use an anti-join with NOT EXISTS.", q)


def test_tutor_llm_path_with_guard(monkeypatch):
    if not settings.learner_dsn:
        pytest.skip("no DB")
    from app import assistant
    from app.main import QUESTIONS
    q = QUESTIONS["T3"]
    monkeypatch.setattr(assistant.settings, "groq_api_key", "fake")
    # LLM leaks twice -> deterministic fallback, both blocks counted
    monkeypatch.setattr(assistant, "_llm", lambda s, u, d=None: (f"```sql\n{q['sql']}\n```", "m1"))
    r = assistant.tutor_hint(q, 3, None)
    assert r["source"] == "fallback" and r["guard_blocked"] == 2 and q["sql"] not in r["text"]
    # leaks once, then clean -> retry accepted
    calls = iter([(f"```sql\n{q['sql']}\n```", "m1"), ("Which products never show up in any order?", "m1")])
    monkeypatch.setattr(assistant, "_llm", lambda s, u, d=None: next(calls))
    r = assistant.tutor_hint(q, 1, None)
    assert r["source"] == "llm_retry" and r["guard_blocked"] == 1
    # baseline: wrong query twice -> reference fallback; right query -> llm
    monkeypatch.setattr(assistant, "_llm", lambda s, u, d=None: ("```sql\nselect 1\n```", "m1"))
    assert assistant.baseline_answer(q, None)["source"] == "fallback"
    monkeypatch.setattr(assistant, "_llm", lambda s, u, d=None: (f"```sql\n{q['sql']}\n```", "m1"))
    assert assistant.baseline_answer(q, None)["source"] == "llm"
    # LLM down -> fallback, never a crash
    def boom(s, u, d=None):
        raise RuntimeError("down")
    monkeypatch.setattr(assistant, "_llm", boom)
    assert assistant.tutor_hint(q, 2, None)["source"] == "fallback"


def test_admin_edge_cases(client, monkeypatch):
    import threading
    from app.config import settings as s
    from app.main import QUESTIONS
    from app import main
    monkeypatch.setattr(s, "admin_token", "t")
    monkeypatch.setattr(s, "groq_api_key", "")
    A = {"x-admin-token": "t"}
    H = lambda k: {"Authorization": "Bearer " + k}
    codes = client.post("/api/admin/learners", json={"names": [f"L{i}" for i in range(8)]}, headers=A).json()
    start_all(client, A)
    assert client.post("/api/login", json={"code": codes[0]["code"].upper()}).status_code == 200   # case-insensitive
    ls = client.get("/api/admin/learners", headers=A).json()
    # L7 is a no-show -> exclude; 7 remain -> odd count allowed
    assert client.post("/api/admin/exclude", json={"learner_id": ls[7]["learner_id"], "reason": "no-show"}, headers=A).status_code == 200
    assert client.get("/api/me", headers=H(codes[7]["code"])).status_code == 403
    for l in codes[:7]:
        for q in client.get("/api/me", headers=H(l["code"])).json()["questions"]:
            client.post(f"/api/questions/{q['id']}/submit", json={"sql": ""}, headers=H(l["code"]))
    # outage during submit -> 503, nothing recorded, resubmit possible
    real = main.run_query
    def down(sql):
        raise main.InfraError("down")
    monkeypatch.setattr(main, "run_query", down)
    # (pretest already submitted above; check on run instead)
    r = client.post("/api/questions/P1/run", json={"sql": "select 1"}, headers=H(codes[0]["code"]))
    assert r.status_code in (409, 503)
    monkeypatch.setattr(main, "run_query", real)
    # double-click assign: two concurrent calls -> exactly one succeeds, arms balanced
    res = []
    th = [threading.Thread(target=lambda: res.append(client.post("/api/admin/assign", headers=A))) for _ in range(2)]
    [t.start() for t in th]; [t.join() for t in th]
    assert sorted(r.status_code for r in res) == [200, 400]
    ls = [x for x in client.get("/api/admin/learners", headers=A).json() if not x["excluded"]]
    arms = [x["arm"] for x in ls]
    assert arms.count(None) == 0 and abs(arms.count("tutor") - arms.count("baseline")) == 1
    paired = [x for x in ls if x["pair_no"] is not None]
    for p in {x["pair_no"] for x in paired}:
        assert sorted(x["arm"] for x in paired if x["pair_no"] == p) == ["baseline", "tutor"]
    ids = [x["learner_id"] for x in ls]
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "heldout"}, headers=A).status_code == 200
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "practice"}, headers=A).status_code == 400
    # held-out submit during an outage: 503, not recorded, then a real submit works
    k = codes[0]["code"]
    monkeypatch.setattr(main, "run_query", down)
    assert client.post("/api/questions/H1/submit", json={"sql": QUESTIONS["H1"]["sql"]}, headers=H(k)).status_code == 503
    monkeypatch.setattr(main, "run_query", real)
    assert client.post("/api/questions/H1/submit", json={"sql": QUESTIONS["H1"]["sql"]}, headers=H(k)).status_code == 200
    me = client.get("/api/me", headers=H(k)).json()
    assert me["submitted_sql"]["H1"].startswith("SELECT")
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "practice", "force": True}, headers=A).status_code == 200


def test_mastery_updates_from_practice(client, monkeypatch):
    from app.config import settings as s
    from app.main import QUESTIONS
    monkeypatch.setattr(s, "admin_token", "t")
    monkeypatch.setattr(s, "groq_api_key", "")
    A = {"x-admin-token": "t"}
    H = lambda k: {"Authorization": "Bearer " + k}
    c = client.post("/api/admin/learners", json={"names": ["P"], "pilot": True}, headers=A).json()[0]
    start_all(client, A)
    lid = client.get("/api/admin/learners", headers=A).json()[0]["learner_id"]
    for q in client.get("/api/me", headers=H(c["code"])).json()["questions"]:
        client.post(f"/api/questions/{q['id']}/submit", json={"sql": ""}, headers=H(c["code"]))   # 0/6
    client.post("/api/admin/arm", json={"learner_id": lid, "arm": "tutor"}, headers=A)
    client.post("/api/admin/phase", json={"learner_ids": [lid], "phase": "practice"}, headers=A)
    # T3 (S3) not mastered -> first help is L2, not a gate
    assert "Try one attempt" not in client.post("/api/questions/T3/help", headers=H(c["code"])).json()["text"]
    # solve T2 (S2) unaided -> T7 (S2) now counts as mastered -> first help is the gate
    assert client.post("/api/questions/T2/run", json={"sql": QUESTIONS["T2"]["sql"]}, headers=H(c["code"])).json()["correct"]
    assert client.post("/api/questions/T7/help", headers=H(c["code"])).json()["text"].startswith("Try one attempt")
    assert len(client.get("/api/questions/T3/hints", headers=H(c["code"])).json()["hints"]) == 1


@needs_db
def test_guard_round2_bypasses_blocked():
    from app.assistant import leaks_answer
    from app.main import QUESTIONS
    t4 = QUESTIONS["T4"]
    renamed = ("WITH x AS (SELECT order_id, COUNT(*) AS k FROM payments GROUP BY order_id HAVING COUNT(*) > 1), "
               "y AS (SELECT order_id, SUM(quantity*unit_price) AS s FROM order_items GROUP BY order_id) "
               "SELECT x.order_id, x.k, y.s FROM x JOIN y ON y.order_id = x.order_id")
    assert leaks_answer(f"```postgresql\n{renamed}\n```", t4)
    assert leaks_answer(f"```pgsql\n{renamed}\n```", t4)
    t6 = QUESTIONS["T6"]
    head, tail = t6["sql"].split("WHERE")
    assert leaks_answer(f"Start with the joins:\n```sql\n{head}\n```\nthen add\n```sql\nWHERE {tail}\n```", t6)


@needs_db
def test_learner_cannot_lift_timeout():
    import time
    from app.sandbox import SandboxError, run_query
    t0 = time.time()
    with pytest.raises(SandboxError):
        run_query("select case when g=1 then set_config('statement_timeout','0',true) "
                  "else pg_sleep(case when g>30 then 8 else 0 end)::text end from generate_series(1,32) g")
    assert time.time() - t0 < 10   # 3.5 s wall clock + cancel round trip (remote DB adds latency)


def test_single_latecomer_gets_arm(client, monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "admin_token", "t")
    A = {"x-admin-token": "t"}
    H = lambda k: {"Authorization": "Bearer " + k}
    c = client.post("/api/admin/learners", json={"names": ["late"]}, headers=A).json()[0]
    start_all(client, A)
    for q in client.get("/api/me", headers=H(c["code"])).json()["questions"]:
        client.post(f"/api/questions/{q['id']}/submit", json={"sql": ""}, headers=H(c["code"]))
    r = client.post("/api/admin/assign", headers=A)
    assert r.status_code == 200 and r.json()[0]["unpaired"]
    assert client.post("/api/admin/exclude", json={"learner_id": 999, "reason": "x"}, headers=A).status_code == 404
    assert client.post("/api/admin/phase", json={"learner_ids": [999], "phase": "done"}, headers=A).status_code == 404


def test_timer_deadlines_and_autofill(client, monkeypatch):
    from app import db
    from app.config import settings as s
    monkeypatch.setattr(s, "admin_token", "t")
    A = {"x-admin-token": "t"}
    H = lambda k: {"Authorization": "Bearer " + k}
    codes = client.post("/api/admin/learners", json={"names": ["a", "b"]}, headers=A).json()
    start_all(client, A)
    me = client.get("/api/me", headers=H(codes[0]["code"])).json()
    assert me["deadline"] and me["server_now"]
    # a submits one answer; then the clock runs out for both
    client.post("/api/questions/P1/submit", json={"sql": "select 1"}, headers=H(codes[0]["code"]))
    db.ex("UPDATE app.learners SET phase_started_at = now() - interval '20 minutes'")
    assert client.post("/api/questions/P2/run", json={"sql": "select 1"}, headers=H(codes[0]["code"])).status_code == 410
    assert client.post("/api/questions/P2/submit", json={"sql": "select 1"}, headers=H(codes[0]["code"])).status_code == 410
    # assign fills the missing answers with blanks, so nobody blocks the session
    log = client.post("/api/admin/assign", headers=A).json()
    assert len(log) == 1
    n = db.q1("SELECT count(*) n FROM app.attempts WHERE kind='submit' AND error='time-up (blank)'")["n"]
    assert n == 11
    ids = [x["learner_id"] for x in client.get("/api/admin/learners", headers=A).json()]
    client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "practice"}, headers=A)
    db.ex("UPDATE app.learners SET phase_started_at = now() - interval '46 minutes'")
    assert client.post("/api/questions/T1/help", headers=H(codes[0]["code"])).status_code == 410
    assert client.post("/api/survey", json={"value": 3}, headers=H(codes[0]["code"])).status_code == 200


def test_timer_round3_regressions(client, monkeypatch):
    from app import db
    from app.config import settings as s
    monkeypatch.setattr(s, "admin_token", "t")
    A = {"x-admin-token": "t"}
    H = lambda k: {"Authorization": "Bearer " + k}
    codes = client.post("/api/admin/learners", json={"names": ["a", "b"]}, headers=A).json()
    start_all(client, A)
    ids = [x["learner_id"] for x in client.get("/api/admin/learners", headers=A).json()]
    # 2: pressing the same phase again must NOT restart the clock
    t1 = {x["learner_id"]: x["phase_started_at"] for x in client.get("/api/admin/learners", headers=A).json()}
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "pretest"}, headers=A).status_code == 200
    t2 = {x["learner_id"]: x["phase_started_at"] for x in client.get("/api/admin/learners", headers=A).json()}
    assert t1 == t2
    for q in client.get("/api/me", headers=H(codes[0]["code"])).json()["questions"]:
        client.post(f"/api/questions/{q['id']}/submit", json={"sql": ""}, headers=H(codes[0]["code"]))
    for q in client.get("/api/me", headers=H(codes[1]["code"])).json()["questions"]:
        client.post(f"/api/questions/{q['id']}/submit", json={"sql": ""}, headers=H(codes[1]["code"]))
    client.post("/api/admin/assign", headers=A)
    client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "heldout"}, headers=A)
    # 1: learner b's browser closed mid-test; moving everyone to done must record b's blanks
    client.post("/api/questions/H1/submit", json={"sql": "select 1"}, headers=H(codes[1]["code"]))
    assert client.post("/api/admin/phase", json={"learner_ids": ids, "phase": "done"}, headers=A).status_code == 200
    n = db.q("""SELECT learner_id, count(*) n FROM app.attempts WHERE phase='heldout' AND kind='submit'
                GROUP BY learner_id ORDER BY learner_id""")
    assert [r["n"] for r in n] == [8, 8]


def test_model_fallback_chain(monkeypatch):
    import sys, types
    from app import assistant
    calls = []

    class RateLimited(Exception):
        pass

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw["model"])
            if kw["model"] in ("big", "mid"):
                raise RateLimited("429")
            msg = types.SimpleNamespace(content="a hint")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    class FakeGroq:
        def __init__(self, **kw):
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "groq", types.SimpleNamespace(Groq=FakeGroq))
    monkeypatch.setattr(assistant.settings, "groq_api_key", "x")
    monkeypatch.setattr(assistant.settings, "groq_models", ["big", "mid", "small"])
    assistant._COOLDOWN.clear()
    assert assistant._llm("s", "u") == ("a hint", "small")
    assert calls == ["big", "mid", "small"]
    calls.clear()
    assert assistant._llm("s", "u") == ("a hint", "small")   # rate-limited models are skipped while cooling down
    assert calls == ["small"]
    assistant._COOLDOWN.clear()


def test_solo_arrivals_are_balanced(client, monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "admin_token", "t")
    A = {"x-admin-token": "t"}
    H = lambda k: {"Authorization": "Bearer " + k}
    for name in ("solo1", "solo2", "solo3", "solo4"):
        c = client.post("/api/admin/learners", json={"names": [name]}, headers=A).json()[0]
        start_all(client, A)
        for q in client.get("/api/me", headers=H(c["code"])).json()["questions"]:
            client.post(f"/api/questions/{q['id']}/submit", json={"sql": ""}, headers=H(c["code"]))
        assert client.post("/api/admin/assign", headers=A).status_code == 200
    ls = client.get("/api/admin/learners", headers=A).json()
    assert sorted(x["arm"] for x in ls) == ["baseline", "baseline", "tutor", "tutor"]
    for p in {x["pair_no"] for x in ls}:
        assert p is not None
        assert sorted(x["arm"] for x in ls if x["pair_no"] == p) == ["baseline", "tutor"]


def test_close_attempt_jumps_to_fix_and_reveal_path(client, monkeypatch):
    from app import db
    from app.config import settings as s
    monkeypatch.setattr(s, "admin_token", "t")
    monkeypatch.setattr(s, "groq_api_key", "")
    A = {"x-admin-token": "t"}
    H = lambda k: {"Authorization": "Bearer " + k}
    c = client.post("/api/admin/learners", json={"names": ["P"], "pilot": True}, headers=A).json()[0]
    start_all(client, A)
    lid = client.get("/api/admin/learners", headers=A).json()[0]["learner_id"]
    for q in client.get("/api/me", headers=H(c["code"])).json()["questions"]:
        client.post(f"/api/questions/{q['id']}/submit", json={"sql": ""}, headers=H(c["code"]))
    client.post("/api/admin/arm", json={"learner_id": lid, "arm": "tutor"}, headers=A)
    client.post("/api/admin/phase", json={"learner_ids": [lid], "phase": "practice"}, headers=A)
    k = H(c["code"])
    # the exact mistake from the live try-out: DISTINCT(a, b) -> one column
    bad = "select distinct(p.name, p.price) from products p join order_items o on o.product_id = p.product_id where o.unit_price < p.price"
    client.post("/api/questions/T1/run", json={"sql": bad}, headers=k)
    r = client.post("/api/questions/T1/help", headers=k).json()
    assert db.q1("SELECT level FROM app.hints ORDER BY hint_id DESC LIMIT 1")["level"] == 4
    assert not r["reveal_available"]
    # SQL error -> error explanation
    client.post("/api/questions/T2/run", json={"sql": "select nme from customers"}, headers=k)
    r = client.post("/api/questions/T2/help", headers=k).json()
    assert "error" in r["text"].lower()
    assert db.q1("SELECT source FROM app.hints ORDER BY hint_id DESC LIMIT 1")["source"].endswith("_error")
    # reveal: 409 before allowed; after L4 + 2 failed runs it is offered and works
    assert client.post("/api/questions/T1/reveal", headers=k).status_code == 409
    assert not client.post("/api/questions/T1/run", json={"sql": bad}, headers=k).json()["reveal_available"]
    # the run itself tells the UI that "Show solution" is now available (no extra help click)
    assert client.post("/api/questions/T1/run", json={"sql": bad}, headers=k).json()["reveal_available"]
    assert client.get("/api/questions/T1/hints", headers=k).json()["reveal_available"]
    r = client.post("/api/questions/T1/reveal", headers=k).json()
    assert "```sql" in r["text"] and not r["reveal_available"]
    assert client.post("/api/questions/T1/reveal", headers=k).status_code == 409
    # solved after the reveal: shown as 'revealed', not 'solved'
    from app.main import QUESTIONS
    assert client.post("/api/questions/T1/run", json={"sql": QUESTIONS["T1"]["sql"]}, headers=k).json()["correct"]
    assert client.get("/api/me", headers=k).json()["status"]["T1"] == "revealed"
    # T2: the error explanation did not use up L1 -> the next (far) attempt gets L1
    client.post("/api/questions/T2/run", json={"sql": "select 1"}, headers=k)
    client.post("/api/questions/T2/help", headers=k)
    assert db.q1("SELECT level, source FROM app.hints ORDER BY hint_id DESC LIMIT 1") == {"level": 1, "source": "fallback"}
    # T6: an exploratory SELECT * is far, not close -> L1, not L4
    client.post("/api/questions/T6/run", json={"sql": "select * from customers"}, headers=k)
    client.post("/api/questions/T6/help", headers=k)
    assert db.q1("SELECT level FROM app.hints ORDER BY hint_id DESC LIMIT 1")["level"] == 1


def test_hint_shape_check(monkeypatch):
    from app import assistant
    from app.assistant import shape_problem
    from app.main import QUESTIONS
    long_plan = ("You'll need the delivered orders from 2025.\n**Tables**\n- `orders` gives the date.\n"
                 "- `order_items` has quantity.\n**Join**\nJoin on `order_id`.")
    assert shape_problem(long_plan, 1) and shape_problem(long_plan, 2)
    assert shape_problem("Join order_items to products.", 1)            # L1 may not name columns/tables
    assert shape_problem("Think about which rows to keep: only some orders count, from one year.", 1) is None
    assert shape_problem("x" * 300, 1)                                   # too long for L1
    # a too-detailed LLM reply is retried, then replaced by the deterministic hint
    monkeypatch.setattr(assistant.settings, "groq_api_key", "x")
    monkeypatch.setattr(assistant, "_llm", lambda s, u, d=None: (long_plan, "m1"))
    r = assistant.tutor_hint(QUESTIONS["T5"], 1, None)
    assert r["source"] == "fallback" and r["guard_blocked"] == 2


def test_grader_matched_cols():
    exp = norm_rows([(1, "a"), (2, "b")])
    ok, d = compare([(1, "x", "a"), (2, "y", "b")], 3, exp, 2, False)
    assert not ok and d["reason"] == "column_count" and d["matched_cols"] == 2


def test_l1_shape_allows_english_blocks_sql():
    from app.assistant import shape_problem
    for t in ["Which customers are not included in your result?", "Is your query behaving as you expect?",
              "Your result mixes two distinct facts.", "Some products are not in your result. Why?"]:
        assert shape_problem(t, 1) is None, t
    for t in ["Use a LEFT JOIN here.", "Try NOT EXISTS.", "Use GROUP BY", "add HAVING", "select distinct name"]:
        assert shape_problem(t, 1), t


def test_skeleton_keeps_join_chain():
    from app.assistant import skeleton
    from app.main import QUESTIONS
    for q in QUESTIONS.values():
        sk = skeleton(q)
        assert sk.count("___") >= q["sql"].upper().count("JOIN"), q["id"]
        assert sk.upper().count("JOIN") == q["sql"].upper().count("JOIN"), q["id"]


def test_timeout_is_far_not_error():
    from app.policy import closeness
    assert closeness({"error": "Query took longer than 3 seconds and was stopped. (Missing a join condition?)"}) == "far"
    assert closeness({"error": 'syntax error at or near "as"'}) == "error"


def test_error_fallback_is_specific():
    from app.assistant import deterministic_hint
    q = {"skill": "S1", "sql": "select 1"}
    t = deterministic_hint(q, 1, {"error": 'column "kochi" does not exist'}, mode="error")
    assert "single quotes" in t
    t = deterministic_hint(q, 1, {"error": 'column "o.order_id" must appear in the GROUP BY clause'}, mode="error")
    assert "GROUP BY" in t and "o.order_id" in t


def test_hint_rejects_are_logged(client, monkeypatch):
    from app import assistant, db
    from app.config import settings as s
    monkeypatch.setattr(s, "admin_token", "t")
    monkeypatch.setattr(s, "groq_api_key", "fake")
    monkeypatch.setattr(assistant, "_llm", lambda s_, u, d=None: ("x" * 2000, "m1"))   # always too long
    A = {"x-admin-token": "t"}
    c = client.post("/api/admin/learners", json={"names": ["R"], "pilot": True}, headers=A).json()[0]
    start_all(client, A)
    lid = client.get("/api/admin/learners", headers=A).json()[0]["learner_id"]
    k = {"Authorization": "Bearer " + c["code"]}
    for q in client.get("/api/me", headers=k).json()["questions"]:
        client.post(f"/api/questions/{q['id']}/submit", json={"sql": ""}, headers=k)
    client.post("/api/admin/arm", json={"learner_id": lid, "arm": "tutor"}, headers=A)
    client.post("/api/admin/phase", json={"learner_ids": [lid], "phase": "practice"}, headers=A)
    client.post("/api/questions/T1/help", headers=k)
    rows = db.q("SELECT payload FROM app.events WHERE kind='hint_reject'")
    assert len(rows) == 2 and "too long" in rows[0]["payload"]["why"]
    # tab switches are logged in practice too
    client.post("/api/event", json={"kind": "hidden", "qid": "T1"}, headers=k)
    assert db.q1("SELECT count(*) n FROM app.events WHERE kind='focus'")["n"] == 1
