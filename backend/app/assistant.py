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
from collections import Counter

from .grader import compare, describe, norm_rows
from .sandbox import InfraError, SandboxError, run_many, run_query

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
    1: ("LEVEL 1 — LOCATE. One or two sentences, at most 45 words, ending with a question.\n"
        "If there is an attempt: point at the EXACT part of their query or result that is wrong, so they can find "
        "the cause themselves. Be concrete: quote their own clause or name (e.g. 'Your JOIN ... ON p.product_id = "
        "p.product_id compares a column with itself. What should it be compared with?'), or use the example rows "
        "below (e.g. 'Customer 17 is missing from your result. What do they have that the others don't?'). "
        "Say WHERE the problem is, not how to fix it. You may name tables and columns from the schema.\n"
        "If there is no attempt: ask which pieces of information the question needs and which tables hold them.\n"
        "FORBIDDEN: naming any SQL feature or keyword the student has NOT used themselves (see 'Features the "
        "student has used'), steps of the solution, lists, any SQL they haven't written."),
    2: ("LEVEL 2 — CONCEPT. At most 3 short sentences, 70 words, one paragraph.\n"
        "Name the ONE SQL idea or feature they need next and explain in plain words WHY it solves the problem "
        "(e.g. 'An inner join keeps only rows that match on both sides; a left join keeps every row of the first "
        "table.'). Relate it to their attempt if there is one.\n"
        "EXPLAIN, don't instruct: no 'Use X instead of Y', no 'change line N'. End with a short question that "
        "lets them apply the idea themselves.\n"
        "FORBIDDEN: saying exactly where to put it or the full plan, details beyond the one idea (e.g. what to "
        "count), headings, bullet lists, SQL code, filter values they have not written themselves."),
    3: ("LEVEL 3 — SKELETON. The skeleton below will be shown to the learner after your text. Write ONLY 1-2 "
        "sentences (at most 50 words) saying how the learner's attempt differs in SHAPE from this skeleton "
        "(e.g. 'You join both tables at once; the skeleton totals each table separately first.'). "
        "FORBIDDEN: filling in any blank, writing SQL, repeating the skeleton."),
    4: ("LEVEL 4 — FIX. At most 4 sentences. Look at the learner's latest attempt and the grader feedback.\n"
        "Name the exact clause that is wrong, say why in one sentence, and say precisely what to change. "
        "You may quote their wrong fragment and show the corrected FRAGMENT only.\n"
        "FORBIDDEN: the corrected full query, fixing parts they already have right."),
}



# Deterministic shape check on every TUTOR reply (in addition to the leak guard): a reply that breaks
# the limits for its level is retried once with the reason, then replaced by the deterministic hint.
LEVEL_LIMITS = {
    1: dict(chars=320, code=2, fence=False, names=True),    # quoted code only from their own query (or the question)
    2: dict(chars=450, code=2, fence=False, names=True),
    3: dict(chars=320, code=2, fence=False, names=True),   # the LLM's sentence only; the skeleton is added by code
    4: dict(chars=650, code=6, fence=True, names=True),
    "error": dict(chars=650, code=6, fence=True, names=True),     # small blocks; vocabulary checked below
}
# SQL features a hint may not INTRODUCE (L1 and error hints): each is allowed only if the learner's own query,
# or the error message, already uses it. Word-boundary patterns that look like SQL, so ordinary English
# ("not included", "behaving", "two distinct facts", "except for") is not caught.
#   name -> (pattern in the hint, pattern in the learner's SQL / error message)
CONSTRUCTS = {
    "left join": (r"\b(left|right|full)[\s-]+(outer[\s-]+)?join\b|\bouter[\s-]+join\b", r"\b(left|right|full)\s+(outer\s+)?join\b"),
    # a comma list in FROM is a (cross) join too, so "cross join" may be said about it
    "inner join": (r"\b(inner|cross)[\s-]+join\b", r"\bjoin\b|\bfrom\s+[\w.]+(\s+(as\s+)?\w+)?\s*,\s*[\w.]+"),
    "exists": (r"\bnot\s+exists\b|\bexists\s*\(", r"\bexists\b"),
    "anti-join": (r"\banti[\s-]?join\b", r"\bexists\b|\bnot\s+in\b|\bis\s+null\b"),
    "coalesce": (r"\bcoalesce\b", r"\bcoalesce\b"),
    "distinct": (r"\bselect\s+distinct\b|\bdistinct\s*\(|`[^`]*\bdistinct\b[^`]*`|\bDISTINCT\b", r"\bdistinct\b"),
    "group by": (r"\bgroup\s+by\b", r"\bgroup\s+by\b"),
    "having": (r"\bHAVING\b|`[^`]*\bhaving\b[^`]*`|\bhaving\s+(count|sum|max|min|avg)\b|\ba\s+having\s+(clause|filter)\b"
               r"|\b(using|use|with|add|in|into|a)\s+having\b(?!\s+(no|any|a|an|the|more|less|only|been)\b)|\bhaving\s*[?.,]",
               r"\bhaving\b"),
    "extract": (r"\bextract\s*\(|\bdate_part\b|\bdate_trunc\b", r"\bextract\b|\bdate_part\b|\bdate_trunc\b"),
    "subquery": (r"\bsub-?quer(y|ies)\b|\binner\s+quer(y|ies)\b|\bnested\s+(query|select)\b|\bctes?\b|\bcommon table expression|\(\s*select\b",
                 r"\(\s*select\b|^\s*with\b"),
    "not in": (r"\bnot\s+in\s*\(|\bNOT\s+IN\b", r"\bnot\s+in\b"),
    # only as SQL (uppercase or in backticks): "a row where o.status is null" is plain English
    "is null": (r"\bIS\s+(NOT\s+)?NULL\b|`[^`]*\bis\s+(not\s+)?null\b[^`]*`", r"\bis\s+(not\s+)?null\b"),
    "except/union": (r"\bEXCEPT\b|\bUNION\b|`[^`]*\b(except|union)\b[^`]*`", r"\bexcept\b|\bunion\b"),
    "count distinct": (r"\bcount\s*\(\s*distinct\b", r"\bcount\s*\(\s*distinct\b"),
}
_CONSTRUCT_RX = {k: (re.compile(h), re.compile(u, re.I | re.M)) for k, (h, u) in CONSTRUCTS.items()}


def features_used(*texts):
    """SQL features present in the learner's own query (and the error message, if any)."""
    t = "\n".join(x for x in texts if x)
    return {k for k, (_, used) in _CONSTRUCT_RX.items() if used.search(t)}


def new_features(hint, allowed):
    """Features the hint names that are not in `allowed`."""
    low = hint.lower()   # lower-case patterns run on the lowered text, the UPPERCASE-only ones on the original
    return [k for k, (rx, _) in _CONSTRUCT_RX.items() if k not in allowed and (rx.search(low) or rx.search(hint))]


_LIST_OR_HEADING = re.compile(r"(?m)^\s*(?:[-*•]\s|\d+[.)]\s|#{1,6}\s|\*\*[^*]+\*\*\s*:?\s*$)")
_SCHEMA_NAMES = None


def _schema_names():
    global _SCHEMA_NAMES
    if _SCHEMA_NAMES is None:
        # only snake_case identifiers (order_items, unit_price, ...): plain words like "orders" or
        # "customers" are normal English in a concept hint and are allowed
        names = {w for w in re.findall(r"\b[a-z]+_[a-z_]+\b", SCHEMA_TEXT)}
        _SCHEMA_NAMES = names
    return _SCHEMA_NAMES


def shape_problem(text, level, mode="normal", attempt=None, question=None):
    """Return None if the reply fits its level, else a short reason (fed back to the LLM on retry).
    `attempt` (the learner's latest run) and `question` set what the hint may mention: anything already in
    the learner's own query or the error message, nothing new (at L1 and in error hints)."""
    lim = LEVEL_LIMITS["error" if mode == "error" else level]
    own_sql = (attempt or {}).get("sql_text") or ""
    err = (attempt or {}).get("error") or ""
    if len(text) > lim["chars"]:
        return f"too long ({len(text)} characters; the limit is {lim['chars']})"
    if (level in (1, 2) or mode == "error") and _LIST_OR_HEADING.search(text):
        return "uses a list or headings; write one short paragraph"
    if not lim["fence"] and "```" in text:
        return "contains a code block; no code block at this level"
    # a backticked bare name (`products`, `c.name`, `JOIN`) is not a code fragment; only real snippets count
    snippets = [x for x in re.findall(r"`([^`\n]+)`", _SQL_SPAN.sub(" ", text)) if not re.fullmatch(r"\s*[\w.]+\s*", x)]
    if len(snippets) > lim["code"]:
        return "contains too many code fragments"
    if level == 1 or mode == "error":
        new = new_features(text, features_used(own_sql, err))
        if new:
            return (f"names a SQL feature the student hasn't used ({new[0]}); "
                    + ("explain only the error, using their own SQL" if mode == "error"
                       else "point at where the problem is, not at the fix"))
    if level == 1 and mode != "error":
        source = own_sql if own_sql else (question or {}).get("prompt", "")
        if not own_sql:   # before any attempt, naming the tables to use would be the plan itself
            hit = [n for n in _schema_names() if re.search(rf"\b{re.escape(n)}\b", text.lower())
                   and not re.search(rf"\b{re.escape(n)}\b", source.lower())]
            if hit:
                return f"names tables or columns ({', '.join(sorted(hit)[:3])}) before any attempt; ask about the information needed"
        for span in re.findall(r"`([^`\n]+)`", text):     # quoted code must come from their own query
            if not _from_own(span, source):
                return (f"quotes code the student didn't write (`{span[:40]}`); quote only their own query"
                        if own_sql else f"quotes code (`{span[:40]}`); there is no attempt yet, so ask about the information needed")
    if mode == "error":
        blocks = [b.strip() for b in _SQL_SPAN.findall(text)]
        if len(blocks) > 2 or any(len(b) > 160 or b.count("\n") > 1 for b in blocks):
            return "the code is too long; show only the corrected fragment the error is about (one or two lines)"
        for b in blocks + [m for m in re.findall(r"`([^`\n]+)`", _SQL_SPAN.sub(" ", text))]:
            joins = len(re.findall(r"(?i)\bjoin\b", b))
            if joins >= 2 or (joins and re.search(r"(?i)\bfrom\b", b)):
                return "rewrites the joins; show only the fragment the error is about"
            if re.search(r"(?i)\bselect\b", b) and _new_tokens(b, own_sql):
                return "rewrites part of the query; show only the fragment the error is about, in their own SQL"
        for span in re.findall(r"`([^`\n]+)`", _SQL_SPAN.sub(" ", text)):
            if len(span) > 70:
                return "a code fragment is too long; show only the part the error is about"
    return None


def _new_tokens(span, own_sql):
    return set(_TOKEN.findall(span.lower())) - set(_TOKEN.findall(own_sql.lower()))


def _from_own(span, own_sql):
    """True if (almost) every token of `span` occurs in the learner's own SQL. Short spans (a keyword or
    two) must match exactly, so a single new keyword like `EXISTS` can't slip through."""
    toks = set(_TOKEN.findall(span.lower()))
    if not toks:
        return True
    new = len(_new_tokens(span, own_sql))
    return new <= (0 if len(toks) <= 3 else max(1, len(toks) // 5))   # a renamed alias / corrected spelling


ERROR_INSTRUCTION = ("ERROR hint. The learner's latest attempt failed with the SQL error shown. In at most 3 short "
                     "sentences (under 450 characters): say what the error message means in plain words, and exactly "
                     "where in THEIR query it comes from (quote their fragment in backticks). You may show the "
                     "corrected spelling of a name, or the one missing comma or keyword (one or two lines at most), but "
                     "only using SQL they have already written.\n"
                     "FORBIDDEN: any SQL keyword or feature the student has not used themselves (unless "
                     "the error message itself names it); rewriting their query; mentioning ANY other problem in it "
                     "(joins, grouping, filters, missing tables). Fixing the error is theirs; solving the question is theirs.")


TUTOR_SYSTEM = """You are a SQL tutor helping a student learn multi-table SQL on PostgreSQL.
Your goal is that the student can solve such questions alone later, so you give only the help asked for.
NEVER write a complete working query that answers the question. Be brief, friendly and concrete.
The reference solution is given for YOUR understanding only; never copy or paraphrase it into SQL.
Always talk about the learner's OWN latest attempt when there is one: what is right, what is wrong.
Never introduce a SQL feature the student hasn't used, unless your level says you may (level 2 and above).
Use plain text. You may use **bold** and `inline code` sparingly. No headings."""

BASELINE_SYSTEM = """You are a helpful SQL assistant for PostgreSQL.
When the student asks for help, give the complete working query that answers the question in a ```sql code block,
followed by 1-2 sentences explaining it. Be brief."""

FALLBACK = {   # deterministic hints when the LLM is unavailable or rejected: 1 = symptom, 2 = concept
    "S1": {1: "Which two facts does the question compare, and do they sit in the same table? If not, how could rows from both be lined up?",
           2: "A join lines up rows from two tables that share a key (an id that appears in both). Match the key in one table to the same key in the other."},
    "S2": {1: "Does your result have a row for everything the question asks about, including things with nothing to count? Check which ones are missing.",
           2: "An inner join keeps only rows that match on both sides. A LEFT JOIN keeps every row of the first table, with NULLs where nothing matches; count a column from the second table so those rows give 0."},
    "S3": {1: "The question is about things that NEVER happened. Can a row that exists show you that something is absent? Check whether your result contains rows it shouldn't.",
           2: "To keep rows with no match, test for absence: NOT EXISTS (a subquery that looks for a matching row), or a LEFT JOIN and then keep the rows where the joined side IS NULL."},
    "S4": {1: "Are some of your counts or totals bigger than they should be? Look at what one order turns into after your joins.",
           2: "Joining a table with several rows per key repeats the other side's rows, so sums and counts double up. Count distinct ids, or total each table separately before joining."},
    "S5": {1: "Check the dates in your result: does every row fall inside the range the question asks for, including the first and last day?",
           2: "Filter on the date column with both ends of the range: date >= the first day AND date < the day after the last day (or BETWEEN for whole days)."},
    "S6": {1: "The information you need is spread over more than two tables. Which tables sit in between and connect them?",
           2: "Chain joins along the keys, one pair of tables at a time, until the table with the information you need is connected."},
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


GUARD_BUDGET_S = 10.0


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
    t_end = time.monotonic() + GUARD_BUDGET_S
    try:
        for _, res in run_many(cands[:MAX_GUARD_RUNS]):
            if time.monotonic() > t_end:
                return True       # couldn't check everything in time: block (fail closed)
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
    (r"(?is)(\bON\b)(.*?)(?=___ JOIN|\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\)|$)", r"\1 ___\n"),
    (r"(?is)(\bWHERE\b)(?!\s*___ EXISTS)(.*?)(?=\bGROUP\b|\bORDER\b|\bHAVING\b|\)\s*$|$)", r"\1 ___ "),
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


def tutor_prompt(question, level, last_attempt, mode="normal", examples=None):
    task = ERROR_INSTRUCTION if mode == "error" else LEVEL_INSTRUCTIONS[level]
    if level == 3 and mode != "error":
        task += "\n\nSkeleton:\n```sql\n" + skeleton(question) + "\n```"
    return _context(question, last_attempt, examples) + f"\n\nTASK: {task}"


def finish_hint(text, question, level, mode="normal"):
    """L3 = the LLM's sentence + the deterministic skeleton of the correct solution."""
    if level == 3 and mode != "error":
        return text.strip() + "\n\n```sql\n" + skeleton(question) + "\n```"
    return text


def _context(question, last_attempt, examples=None):
    att = "The student has not run any attempt yet."
    used = "none (no attempt yet)"
    if last_attempt:
        d = last_attempt.get("diff") or {}
        fb = last_attempt.get("error") or (describe(d) if d.get("reason") else "Correct: this attempt already returns the right result.")
        att = f"Student's latest attempt:\n```sql\n{last_attempt['sql_text']}\n```\nResult: {fb}"
        if examples:
            att += "\n" + examples
        used = ", ".join(sorted(features_used(last_attempt["sql_text"]))) or "only basic SELECT / FROM / WHERE"
    return (f"{SCHEMA_TEXT}\n\nQuestion:\n{question['prompt']}\n\n"
            f"Reference solution (for your understanding only):\n```sql\n{question['sql']}\n```\n\n{att}\n\n"
            f"Features the student has used: {used}")


def result_examples(question, last_attempt, k=3):
    """Concrete rows for the tutor: some expected rows the attempt is missing, some rows it has that it
    shouldn't, and a duplicated row. Re-runs the learner's (read-only) query; '' if that isn't possible."""
    if not last_attempt or last_attempt.get("error") or last_attempt.get("correct"):
        return ""
    d = last_attempt.get("diff") or {}
    if d.get("reason") not in ("rows", "column_count"):
        return ""
    try:
        res = run_query(last_attempt["sql_text"])
    except Exception:          # SandboxError, InfraError, anything: the hint works without examples
        return ""
    got = Counter(norm_rows(res["rows"]))
    exp = Counter(tuple(r) for r in question["expected_rows"])
    def show(v):
        if v is None:
            return "NULL"
        t = str(v)[:40]
        return t[:-3] if re.fullmatch(r"-?\d+\.00", t) else t     # 17.00 -> 17 (ids, counts)
    fmt = lambda rows: "; ".join("(" + ", ".join(show(v) for v in r) + ")" for r in rows)
    out = []
    if d.get("reason") == "rows":
        miss = list((exp - got).elements())[:k]
        extra = list((got - exp).elements())[:k]
        dup = [r for r, c in got.items() if c > 1][:1]
        if miss:
            out.append(f"Example rows the student's result is MISSING: {fmt(miss)}")
        if extra:
            out.append(f"Example rows in the student's result that should NOT be there: {fmt(extra)}")
        if dup:
            out.append(f"A row that appears {got[dup[0]]} times in the student's result: {fmt(dup)}")
    else:
        out.append(f"First rows of the student's result: {fmt(norm_rows(res['rows'][:k]))}")
    return "\n".join(out)


def _model_kwargs(model):
    """Reasoning models need room for their (hidden) reasoning plus the answer."""
    if "gpt-oss" in model:
        return dict(max_completion_tokens=900, reasoning_effort="low")
    if "qwen" in model:
        return dict(max_completion_tokens=900, reasoning_format="hidden")
    return dict(max_tokens=300)


def _strip_reasoning(text):
    """Drop any <think>...</think> block a reasoning model leaves in its reply."""
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    return re.sub(r"(?is)<think>.*$", "", text).strip()     # an unterminated block: drop to the end


_COOLDOWN = {}          # model -> time.monotonic() until which it is skipped
COOLDOWN_S = 120


HELP_BUDGET_S = 20.0    # total wait for one help request; after it, the deterministic hint is used
MIN_CALL_S = 3.0


def _llm(system, user, deadline=None):
    """Try each model in settings.groq_models in order. A model that is rate-limited, unavailable,
    times out or returns nothing is skipped for COOLDOWN_S. Returns (text, model).
    `deadline` (time.monotonic()) caps the total wait across all models."""
    from groq import Groq
    now = time.monotonic()
    if deadline is None:
        deadline = now + HELP_BUDGET_S
    chain = [m for m in settings.groq_models if _COOLDOWN.get(m, 0) <= now] or list(settings.groq_models)
    last = None
    for model in chain:
        left = deadline - time.monotonic()
        if left < MIN_CALL_S:
            last = last or TimeoutError("help time budget used up")
            break
        client = Groq(api_key=settings.groq_api_key, timeout=min(12.0, left), max_retries=0)
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


_ERROR_EXPLAIN = [
    (r'column "?([\w.]+)"? must appear in the GROUP BY',
     "Every column you SELECT next to an aggregate (COUNT, SUM, ...) must also be listed in GROUP BY. "
     "Add {0} to your GROUP BY, or put it inside an aggregate."),
    (r'missing FROM-clause entry for table "(\w+)"',
     "You use the alias `{0}.` somewhere, but no table in your FROM part is called {0}. Every table you use a "
     "column from has to appear in FROM (or a JOIN) with that alias."),
    (r'invalid reference to FROM-clause entry for table "(\w+)"',
     "The alias {0} is used before (or outside) the place where it is defined. Check that each alias is defined "
     "once, and only used after its table appears in FROM or JOIN."),
    (r'table name "(\w+)" specified more than once',
     "Two tables in your query have the same alias {0}. Give each table its own alias."),
    (r'column "([^"]+)" does not exist',
     "There is no column called {0}. If it was meant as text, text values need single quotes: 'like this'. "
     "Double quotes are for names. Otherwise check the spelling against the schema on the left."),
    (r'relation "([^"]+)" does not exist',
     "There is no table called {0}. Check the spelling against the schema on the left."),
    (r'column ([\w.]+) does not exist',
     "There is no column called {0}. Check the spelling against the schema on the left (the error may suggest the right name)."),
    (r'syntax error at end of input',
     "The query ends too early: something is not finished, often a missing closing bracket or a missing condition at the end."),
    (r'syntax error at or near "([^"]+)"',
     "The database got confused right at {0}, or just before it. Check the words immediately before it: a missing comma, "
     "a missing FROM, a keyword in the wrong place, a reserved word such as order used as a name, or `is not` used "
     "for a comparison (use `<>` or `!=`)."),
    (r'aggregate functions are not allowed in WHERE',
     "WHERE is checked row by row, before any grouping happens, so it can't use COUNT or SUM. "
     "Where in a query can a condition look at the finished groups instead of single rows?"),
    (r'operator does not exist',
     "The two sides of a comparison have different types (for example a number compared with text). Check the quotes and the columns being compared."),
]


def explain_error(msg):
    """Deterministic, specific explanation of a PostgreSQL error message (fallback for error hints)."""
    for rx, tmpl in _ERROR_EXPLAIN:
        m = re.search(rx, msg, re.I)
        if m:
            return tmpl.format(*(g.strip() for g in m.groups()))
    return ("Read it word by word: it names the part of your query that the database could not understand "
            "(a misspelt column or table, a missing comma, or a bracket in the wrong place). Fix that part and run again.")


def deterministic_hint(question, level, last_attempt, mode="normal"):
    """Fallback used when the LLM is unavailable or its reply was blocked. Same ladder."""
    if mode == "error" and last_attempt and last_attempt.get("error"):
        return f"Your query stopped with this error:\n\n{last_attempt['error']}\n\n" + explain_error(last_attempt["error"])
    if level == 1 and last_attempt and (last_attempt.get("diff") or {}).get("reason"):
        # say concretely what is wrong with THEIR result, then the skill's symptom question
        return describe(last_attempt["diff"]) + " " + FALLBACK[question["skill"]][1]
    if level <= 2:
        return FALLBACK[question["skill"]][level]
    if level == 3:
        return ("Here is the shape of the query. Fill in each ___:\n```sql\n" + skeleton(question) + "\n```")
    fb = ""
    if last_attempt and (last_attempt.get("error") or (last_attempt.get("diff") or {}).get("reason")):
        fb = last_attempt.get("error") or describe(last_attempt["diff"])
    return (FALLBACK[question["skill"]][2] + (f"\n\nWhat went wrong in your last run: {fb}" if fb else "")
            + "\n\nCompare it with the shape:\n```sql\n" + skeleton(question) + "\n```")


def tutor_hint(question, level, last_attempt, mode="normal"):
    """Return dict(text, source, guard_blocked, model, latency_ms)."""
    t0 = time.perf_counter()
    blocked = 0
    rejects = []          # why each LLM reply was rejected (logged in app.events)
    fallback = deterministic_hint(question, level, last_attempt, mode)
    if not settings.groq_api_key:
        return dict(text=fallback, source="fallback", guard_blocked=0, model=None, rejects=[],
                    latency_ms=int((time.perf_counter() - t0) * 1000))
    deadline = time.monotonic() + HELP_BUDGET_S
    user = tutor_prompt(question, level, last_attempt, mode, result_examples(question, last_attempt))
    why = ""
    for attempt, src in ((0, "llm"), (1, "llm_retry")):
        try:
            prompt = user if attempt == 0 else user + f"\n\nIMPORTANT: your previous reply was rejected: {why}. Reply again, fixing that."
            text, used = _llm(TUTOR_SYSTEM, prompt, deadline)
        except Exception as e:
            rejects.append({"why": f"llm unavailable: {type(e).__name__}", "chars": 0})
            break
        # guard the hint exactly as the learner will see it (at L3: the sentence plus the skeleton,
        # so a sentence that fills the blanks is caught)
        if leaks_answer(finish_hint(text, question, level, mode), question):
            why = "it contained a full working query, or filled in the blanks; never give the complete query"
        else:
            why = shape_problem(text, level, mode, last_attempt, question)
            if why is None:
                return dict(text=finish_hint(text, question, level, mode), source=src, guard_blocked=blocked, model=used,
                            rejects=rejects, latency_ms=int((time.perf_counter() - t0) * 1000))
        rejects.append({"why": why, "chars": len(text), "model": used, "text": text[:1500]})
        blocked += 1
    return dict(text=fallback, source="fallback", guard_blocked=blocked, model=None, rejects=rejects,
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
    deadline = time.monotonic() + HELP_BUDGET_S
    rejects = []
    for src in ("llm", "llm_retry"):
        try:
            text, used = _llm(BASELINE_SYSTEM, user, deadline)
        except Exception as e:
            rejects.append({"why": f"llm unavailable: {type(e).__name__}", "chars": 0})
            break
        if answers_correctly(text, question):
            return dict(text=text, source=src, guard_blocked=0, model=used, rejects=rejects,
                        latency_ms=int((time.perf_counter() - t0) * 1000))
        rejects.append({"why": "baseline query not correct", "chars": len(text), "model": used, "text": text[:1500]})
    return dict(text=ref, source="fallback", guard_blocked=0, model=None, rejects=rejects,
                latency_ms=int((time.perf_counter() - t0) * 1000))
