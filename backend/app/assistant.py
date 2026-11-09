"""Probabilistic part: the LLM phrases help at the level the policy chose.

Both arms use the SAME model, temperature, schema text and question context.
Only the instruction differs (tutor level vs full answer).

Guard (deterministic): every SQL-looking span in a TUTOR reply is executed in the
learner sandbox and graded. If any span returns the correct result set, the reply
is blocked (it leaked an executable full query). One retry with a stricter
instruction, then a deterministic fallback hint.
"""
import re
import time

from .config import settings
from .grader import compare, describe
from .sandbox import InfraError, run_many

SCHEMA_TEXT = """Tables (schema shop):
customers(customer_id PK, name, city, signup_date)
categories(category_id PK, name)
products(product_id PK, name, category_id FK->categories, price)
orders(order_id PK, customer_id FK->customers, order_date, status in delivered|shipped|cancelled)
order_items(order_id FK->orders, product_id FK->products, quantity, unit_price)  PK(order_id, product_id)
payments(payment_id PK, order_id FK->orders, amount, method in upi|card|cod, paid_on)
Notes: an order can have several items and several payments; cancelled orders have no payments;
payments for other orders sum to the item total + a 40.00 delivery fee."""

SCHEMA_NOTES = [
    "orders.status is one of: delivered, shipped, cancelled.",
    "An order can have several items (order_items) and several payments (instalments).",
    "Cancelled orders have no payments. Payments for any other order add up to its item total plus a 40.00 delivery fee.",
    "Tables live in schema shop; you can write customers or shop.customers.",
]

LEVEL_INSTRUCTIONS = {
    1: ("Give a CONCEPT hint: in 1-2 sentences name the SQL idea or pattern this question needs "
        "(e.g. which kind of join, or a trap to watch for). Do NOT mention specific table or column names. No SQL."),
    2: ("Give a PLAN hint: in 2-4 short sentences say which tables are involved, which join type to use, "
        "which keys to join on, and what to filter/group by. Plain words only. Do NOT write any SQL code."),
    3: ("Give a SKELETON hint: show the shape of the query as SQL with the key parts replaced by ___ blanks "
        "(at least the join condition, the filter and the aggregate must be blanks). "
        "The skeleton must NOT run as-is. Add one sentence on what goes in the blanks. Never give the complete query."),
    4: ("Give a FIX hint: look at the learner's latest attempt and the grader feedback. Point to the specific "
        "clause that is wrong and explain why in 2-3 sentences. You may quote the learner's own wrong line. "
        "Do NOT write the corrected full query."),
}

TUTOR_SYSTEM = """You are a SQL tutor helping a student learn multi-table SQL on PostgreSQL.
Your goal is that the student can solve such questions alone later, so you give only the help asked for.
NEVER write a complete working query that answers the question. Be brief, friendly and concrete.
The reference solution is given for YOUR understanding only; never copy or paraphrase it into SQL."""

BASELINE_SYSTEM = """You are a helpful SQL assistant for PostgreSQL.
When the student asks for help, give the complete working query that answers the question in a ```sql code block,
followed by 1-2 sentences explaining it. Be brief."""

FALLBACK = {
    "S1": {1: "Rows you need live in two tables. Join them on the column they share (a primary key matched to a foreign key).",
           2: "Find the table that holds the filter column and the table that holds the output column, then INNER JOIN them on their shared id."},
    "S2": {1: "Some rows have no match, but the question still wants them. An inner join drops them; think about which join keeps them.",
           2: "Start FROM the table whose every row must appear, LEFT JOIN the other table, and count a column from the joined table (not *), using COALESCE where a 0 is needed."},
    "S3": {1: "You want rows that have NO matching row in another table. That's an anti-join.",
           2: "Use NOT EXISTS (a subquery that looks for a matching row) or a LEFT JOIN ... WHERE right_table.key IS NULL."},
    "S4": {1: "Joining a table that has several rows per key multiplies rows. Sums and counts can come out too big.",
           2: "Check whether any joined table has many rows per order. Count with COUNT(DISTINCT ...) or aggregate each table separately (subquery/CTE) before joining."},
    "S5": {1: "Filter on the date column of the right table, and be careful with inclusive/exclusive ends of the range.",
           2: "Join the tables, then filter with order_date >= start AND order_date < day after end (or BETWEEN for whole days). Remove duplicates if each item should appear once."},
    "S6": {1: "The columns you need sit in tables that aren't directly linked. Chain joins through the tables in between.",
           2: "Walk the foreign keys: customers -> orders -> order_items -> products (or categories). Join each pair on its key, then filter and group."},
}

_SQL_SPAN = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\n?(.*?)```", re.S)  # any fence label (sql, postgresql, pgsql, ...)
_TICK = re.compile(r"`([^`\n]+)`")
_START = re.compile(r"(?i)\b(with|select)\b")
_TOKEN = re.compile(r"[a-z_][a-z0-9_]*|\d+|[<>=!]+|'[^']*'", re.I)
MAX_GUARD_RUNS = 40
RECALL_BLOCK = 0.85


def sql_candidates(text: str):
    """Every plausible SQL span in a reply: fenced blocks, `inline` spans, and for each
    SELECT/WITH in the prose, every cut at a line end, ';', or sentence end after it."""
    fenced = [m.strip() for m in _SQL_SPAN.findall(text)]
    cands = list(fenced)
    # a query split over consecutive blocks ("the joins..." then "then add WHERE ...")
    for i in range(len(fenced)):
        for j in range(i + 2, len(fenced) + 1):
            cands.append("\n".join(fenced[i:j]))
    prose = _SQL_SPAN.sub("\n", text)
    cands += [m.strip() for m in _TICK.findall(prose) if _START.search(m)]
    prose = _TICK.sub(lambda m: " " + m.group(1) + " ", prose)
    for m in _START.finditer(prose):
        tail = prose[m.start():]
        cuts = {len(tail)}
        for rx in (r"\n", r";", r"\.\s", r"\*\*"):
            cuts.update(x.start() + (1 if rx == r";" else 0) for x in re.finditer(rx, tail))
        for c in sorted(cuts):
            frag = tail[:c].strip().strip("*`").strip()
            if re.search(r"(?i)\bfrom\b", frag):
                cands.append(frag)
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _tokens(sql):
    return [t.lower() for t in _TOKEN.findall(sql)]


def reference_recall(text: str, question: dict) -> float:
    """Share of the reference query's tokens (multiset) that appear in the reply."""
    ref = _tokens(question["sql"])
    got = {}
    for t in _tokens(text):
        got[t] = got.get(t, 0) + 1
    hit = 0
    for t in ref:
        if got.get(t, 0) > 0:
            got[t] -= 1
            hit += 1
    return hit / max(1, len(ref))


def leaks_answer(text: str, question: dict) -> bool:
    """Deterministic guard. True (block) if any SQL span in `text` returns the correct
    result set, if the reply contains >= 85% of the reference query's tokens, or if the
    database can't be reached to check (fail closed)."""
    cands = sql_candidates(text)
    code = "\n".join(_SQL_SPAN.findall(text) + _TICK.findall(_SQL_SPAN.sub("\n", text)))
    if code and reference_recall(code, question) >= RECALL_BLOCK:   # all code in the reply, taken together
        return True
    if any(reference_recall(c, question) >= RECALL_BLOCK for c in cands):
        return True
    try:
        for _, res in run_many(cands[:MAX_GUARD_RUNS]):
            if res is None:
                continue
            ok, _ = compare(res["rows"], res["ncols"], question["expected_rows"],
                            question["expected_ncols"], question["ordered"])
            if ok:
                return True
    except InfraError:
        return True
    return False


def answers_correctly(text: str, question: dict) -> bool:
    """Baseline check: does the reply contain a query that returns the right result?"""
    try:
        for _, res in run_many(sql_candidates(text)[:MAX_GUARD_RUNS]):
            if res and compare(res["rows"], res["ncols"], question["expected_rows"],
                               question["expected_ncols"], question["ordered"])[0]:
                return True
    except InfraError:
        return False
    return False


_BLANK_RULES = [
    (r"(?i)\bNOT EXISTS\b|\bEXISTS\b", "___ EXISTS"),
    (r"(?i)\bLEFT JOIN\b|\bJOIN\b", "___ JOIN"),
    (r"(?is)(\bON\b)(.*?)(?=___ JOIN|\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\)|$)", r"\1 ___ "),
    (r"(?is)(\bWHERE\b)(?!\s*___ EXISTS)(.*?)(?=\bGROUP\b|\bORDER\b|\bHAVING\b|\)\s*$|$)", r"\1 ___ "),
    (r"(?is)(\bWHERE\b\s*___ EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+\S+(?:\s+\w+)?)(.*?)(?=\bWHERE\b)", r"\1 ___ "),
    (r"(?is)(\bHAVING\b)(.*?)(?=\bORDER\b|\)\s*,|\)\s*$|$)", r"\1 ___ "),
    (r"(?i)\b(COUNT|SUM|MAX|MIN|AVG|COALESCE)\s*\(", "___("),
]


def skeleton(question):
    """Deterministic L3 skeleton: the reference with join type, join conditions, filters,
    HAVING and aggregate functions blanked out. Never executable."""
    s = question["sql"]
    for rx, rep in _BLANK_RULES:
        s = re.sub(rx, rep, s)
    s = re.sub(r"(?i)(\bFROM\s+\S+(?:\s+\w+)?)\s+___\s+(WHERE)", r"\1 \2", s)  # no stray blank before WHERE
    return re.sub(r"[ \t]+", " ", s).strip()


def _context(question, last_attempt):
    att = "The student has not run any attempt yet."
    if last_attempt:
        d = last_attempt.get("diff") or {}
        fb = last_attempt.get("error") or (describe(d) if d.get("reason") else "Correct: this attempt already returns the right result.")
        att = f"Student's latest attempt:\n```sql\n{last_attempt['sql_text']}\n```\nResult: {fb}"
    return (f"{SCHEMA_TEXT}\n\nQuestion:\n{question['prompt']}\n\n"
            f"Reference solution (for your understanding only):\n```sql\n{question['sql']}\n```\n\n{att}")


def _model_kwargs(model):
    """Reasoning models need room for their (hidden) reasoning plus the answer."""
    if "gpt-oss" in model:
        return dict(max_completion_tokens=900, reasoning_effort="low")
    if "qwen" in model:
        return dict(max_completion_tokens=900, reasoning_format="hidden")
    return dict(max_tokens=300)


def _strip_reasoning(text):
    """Drop any <think>...</think> block a reasoning model leaves in its reply."""
    return re.sub(r"(?is)<think>.*?</think>", "", text).strip()


_COOLDOWN = {}          # model -> time.monotonic() until which it is skipped
COOLDOWN_S = 120


def _llm(system, user):
    """Try each model in settings.groq_models in order. A model that is rate-limited, unavailable,
    times out or returns nothing is skipped for COOLDOWN_S. Returns (text, model)."""
    from groq import Groq
    client = Groq(api_key=settings.groq_api_key, timeout=12.0, max_retries=0)
    now = time.monotonic()
    chain = [m for m in settings.groq_models if _COOLDOWN.get(m, 0) <= now] or list(settings.groq_models)
    last = None
    for model in chain:
        kw = dict(model=model, temperature=0.3,
                  messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        kw.update(_model_kwargs(model))
        try:
            r = client.chat.completions.create(**kw)
            text = _strip_reasoning(r.choices[0].message.content or "")
            if text:
                return text, model
            last = RuntimeError(f"{model}: empty reply")
        except Exception as e:   # rate limit, model not found/decommissioned, timeout, 5xx
            last = e
        _COOLDOWN[model] = time.monotonic() + COOLDOWN_S
    raise last or RuntimeError("no model available")


def deterministic_hint(question, level, last_attempt):
    """Fallback used when the LLM is unavailable or its reply was blocked. Same ladder."""
    if level <= 2:
        return FALLBACK[question["skill"]][level]
    if level == 3:
        return ("Here is the shape of the query. Fill in each ___:\n```sql\n" + skeleton(question) + "\n```")
    fb = ""
    if last_attempt and (last_attempt.get("error") or (last_attempt.get("diff") or {}).get("reason")):
        fb = last_attempt.get("error") or describe(last_attempt["diff"])
    return (FALLBACK[question["skill"]][2] + (f"\n\nWhat went wrong in your last run: {fb}" if fb else "")
            + "\n\nCompare it with the shape:\n```sql\n" + skeleton(question) + "\n```")


def tutor_hint(question, level, last_attempt):
    """Return dict(text, source, guard_blocked, model, latency_ms)."""
    t0 = time.perf_counter()
    blocked = 0
    fallback = deterministic_hint(question, level, last_attempt)
    if not settings.groq_api_key:
        return dict(text=fallback, source="fallback", guard_blocked=0, model=None,
                    latency_ms=int((time.perf_counter() - t0) * 1000))
    user = _context(question, last_attempt) + f"\n\nTASK: {LEVEL_INSTRUCTIONS[level]}"
    for attempt, src in ((0, "llm"), (1, "llm_retry")):
        try:
            prompt = user if attempt == 0 else user + (
                "\n\nIMPORTANT: your previous reply contained a full working query. "
                "Reply again WITHOUT any complete query.")
            text, used = _llm(TUTOR_SYSTEM, prompt)
        except Exception:
            break
        if not leaks_answer(text, question):
            return dict(text=text, source=src, guard_blocked=blocked, model=used,
                        latency_ms=int((time.perf_counter() - t0) * 1000))
        blocked += 1
    return dict(text=fallback, source="fallback", guard_blocked=blocked, model=None,
                latency_ms=int((time.perf_counter() - t0) * 1000))


def baseline_answer(question, last_attempt):
    """Ordinary answer-giving assistant. Verified: if the LLM's query is wrong twice,
    fall back to the reference query, so the baseline is always a competent answer-giver."""
    t0 = time.perf_counter()
    ref = (f"Here is a query that answers it:\n```sql\n{question['sql']}\n```\n"
           "It joins the needed tables on their keys and returns the requested columns.")
    if not settings.groq_api_key:
        return dict(text=ref, source="fallback", guard_blocked=0, model=None,
                    latency_ms=int((time.perf_counter() - t0) * 1000))
    user = _context(question, last_attempt) + "\n\nTASK: Give the complete working query and a short explanation."
    for src in ("llm", "llm_retry"):
        try:
            text, used = _llm(BASELINE_SYSTEM, user)
        except Exception:
            break
        if answers_correctly(text, question):
            return dict(text=text, source=src, guard_blocked=0, model=used,
                        latency_ms=int((time.perf_counter() - t0) * 1000))
    return dict(text=ref, source="fallback", guard_blocked=0, model=None,
                latency_ms=int((time.perf_counter() - t0) * 1000))
