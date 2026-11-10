"""Learning OS API.

Experiment-protecting rules enforced HERE (server side), not in the UI:
 * A learner only ever receives questions of their CURRENT phase. Held-out
   prompts are never sent before the 'heldout' phase.
 * The help route answers only in phase 'practice' and only for practice
   questions; in every other phase it returns 404 (no assistant endpoint).
 * The arm is read from the database per learner; the client never sends it,
   and no response says which arm a learner is in.
 * Test phases (pretest, heldout) never reveal correctness to the learner.
 * A database outage is never recorded as a learner's wrong answer (503, nothing written).
"""
import json
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .assistant import SCHEMA_NOTES, baseline_answer, tutor_hint
from .config import settings
from .grader import compare, describe
from .policy import REVEAL_LEVEL, closeness, decide, reveal_available
from .sandbox import MAX_DISPLAY, InfraError, SandboxError, run_query

QUESTIONS = {q["id"]: q for q in json.loads(settings.questions_json.read_text())}
PHASE_SET = {"pretest": "pretest", "practice": "practice", "heldout": "heldout"}
TEST_PHASES = {"pretest", "heldout"}
PHASE_ORDER = ["waiting", "pretest", "practice", "break", "heldout", "done"]
# Hard time limits per phase (minutes). The clock starts when the invigilator moves a learner into the phase.
PHASE_MINUTES = {"pretest": 15, "practice": 45, "heldout": 30}
GRACE_S = 90          # after the deadline: time for the browser's auto-submit to arrive
TIME_UP = "Time is up for this part."
INFRA_MSG = "Couldn't reach the database just now. Nothing was recorded. Try again in a few seconds."


@asynccontextmanager
async def lifespan(_app):
    yield
    if db._pool is not None:
        db._pool.close()


app = FastAPI(title="Learning OS", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
if settings.allow_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.allow_origins,
                       allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- auth
def learner(authorization: str = Header(default="")):
    code = authorization.removeprefix("Bearer ").strip().lower()
    if not code:
        raise HTTPException(401, "Not logged in")
    row = db.q1("SELECT * FROM app.learners WHERE code = %s", (code,))
    if not row:
        raise HTTPException(401, "Unknown code")
    if row["excluded"]:
        raise HTTPException(403, "This code is no longer active. Please ask the invigilator.")
    return row


def admin(x_admin_token: str = Header(default="")):
    if not settings.admin_token or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(401, "Admin only")
    return True


def phase_questions(phase):
    s = PHASE_SET.get(phase)
    return [q for q in QUESTIONS.values() if q["set"] == s] if s else []


def question_for(L, qid):
    q = QUESTIONS.get(qid)
    if not q or q["set"] != PHASE_SET.get(L["phase"]):
        raise HTTPException(404, "Question not available")
    return q


def public_q(q):
    return {"id": q["id"], "prompt": q["prompt"], "ordered": q["ordered"]}


def _display(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)   # Decimal and anything else


def rows_for_json(rows):
    return [[_display(v) for v in r] for r in rows[:MAX_DISPLAY]]


def deadline(L):
    mins = PHASE_MINUTES.get(L["phase"])
    if not mins or not L.get("phase_started_at"):
        return None
    return L["phase_started_at"] + timedelta(minutes=mins)


def check_time(L, grace=GRACE_S):
    d = deadline(L)
    if d and datetime.now(timezone.utc) > d + timedelta(seconds=grace):
        raise HTTPException(410, TIME_UP)


def _blank_fill(c, learner_id, phase, reason):
    """Record a blank (wrong) submit for every unsubmitted question of `phase` for one learner."""
    for qid in [q["id"] for q in QUESTIONS.values() if q["set"] == phase]:
        c.execute("""INSERT INTO app.question_views (learner_id, question_id, phase) VALUES (%s,%s,%s)
                     ON CONFLICT (learner_id, question_id) DO NOTHING""", (learner_id, qid, phase))
        upd = c.execute("""UPDATE app.question_views SET finished_at = now(), final_correct = FALSE
                           WHERE learner_id=%s AND question_id=%s AND finished_at IS NULL""", (learner_id, qid))
        if upd.rowcount:
            c.execute("""INSERT INTO app.attempts (learner_id, question_id, phase, kind, sql_text, error, correct)
                         VALUES (%s,%s,%s,'submit','',%s,FALSE)""", (learner_id, qid, phase, reason))


def finalize_expired(c):
    """Blank-fill unsubmitted test questions of learners whose test time (plus grace) is over,
    so the data is complete even if a browser never auto-submitted."""
    for phase, mins in (("pretest", PHASE_MINUTES["pretest"]), ("heldout", PHASE_MINUTES["heldout"])):
        late = c.execute("""SELECT learner_id FROM app.learners WHERE phase=%s AND phase_started_at IS NOT NULL
                            AND now() > phase_started_at + make_interval(mins => %s) + make_interval(secs => %s)""",
                         (phase, mins, GRACE_S)).fetchall()
        for r in late:
            _blank_fill(c, r["learner_id"], phase, "time-up (blank)")


def event(kind, payload):
    db.ex("INSERT INTO app.events (kind, payload) VALUES (%s, %s)", (kind, db.J(payload)))


# ---------------------------------------------------------------- learner
class LoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


@app.post("/api/login")
def login(body: LoginIn):
    row = db.q1("SELECT display_name, phase, excluded FROM app.learners WHERE code = %s",
                (body.code.strip().lower(),))
    if not row:
        raise HTTPException(401, "Unknown code")
    if row["excluded"]:
        raise HTTPException(403, "This code is no longer active. Please ask the invigilator.")
    return {"name": row["display_name"], "phase": row["phase"]}


@app.get("/api/me")
def me(L=Depends(learner)):
    qs = phase_questions(L["phase"])
    views = {v["question_id"]: v for v in db.q(
        "SELECT * FROM app.question_views WHERE learner_id = %s", (L["learner_id"],))}
    status, submitted = {}, {}
    if L["phase"] in TEST_PHASES:
        subs = {a["question_id"]: a["sql_text"] for a in db.q(
            "SELECT question_id, sql_text FROM app.attempts WHERE learner_id=%s AND kind='submit'",
            (L["learner_id"],))}
    revealed = set() if L["phase"] in TEST_PHASES else {r["question_id"] for r in db.q(
        "SELECT DISTINCT question_id FROM app.hints WHERE learner_id=%s AND source='reveal'", (L["learner_id"],))}
    for q in qs:
        v = views.get(q["id"])
        if L["phase"] in TEST_PHASES:
            status[q["id"]] = "submitted" if v and v["finished_at"] else ("seen" if v else "new")
            if q["id"] in subs:
                submitted[q["id"]] = subs[q["id"]]
        else:
            st = "solved" if v and v["final_correct"] else ("seen" if v else "new")
            if st == "solved" and q["id"] in revealed:
                st = "revealed"           # solved only after "Show solution": not counted as solved
            status[q["id"]] = st
    survey_done = bool(db.q1("SELECT 1 FROM app.survey WHERE learner_id=%s AND item='return'",
                             (L["learner_id"],)))
    return {"name": L["display_name"], "phase": L["phase"],
            "questions": [public_q(q) for q in qs], "status": status, "submitted_sql": submitted,
            "help_available": L["phase"] == "practice", "survey_done": survey_done,
            "deadline": deadline(L).isoformat() if deadline(L) else None,
            "server_now": datetime.now(timezone.utc).isoformat()}


@app.get("/api/schema")
def schema(L=Depends(learner)):
    rows = db.q("""SELECT table_name, column_name, data_type FROM information_schema.columns
                   WHERE table_schema = 'shop' ORDER BY table_name, ordinal_position""")
    keys = {}
    for r in db.q(
        """SELECT kcu.table_name, kcu.column_name,
                  CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN 'PK' ELSE 'FK' END AS kind
           FROM information_schema.table_constraints tc
           JOIN information_schema.key_column_usage kcu
             ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
           WHERE tc.table_schema = 'shop' AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
           ORDER BY 3 DESC"""):
        k = (r["table_name"], r["column_name"])
        keys[k] = r["kind"] if k not in keys or keys[k] == r["kind"] else "PK FK"
    out = {}
    for r in rows:
        out.setdefault(r["table_name"], []).append(
            {"name": r["column_name"], "type": r["data_type"], "key": keys.get((r["table_name"], r["column_name"]))})
    order = ["customers", "orders", "order_items", "products", "categories", "payments"]
    return {"tables": [{"table": t, "columns": out[t]} for t in order if t in out], "notes": SCHEMA_NOTES}


@app.post("/api/questions/{qid}/view")
def view(qid: str, L=Depends(learner)):
    question_for(L, qid)
    db.ex("""INSERT INTO app.question_views (learner_id, question_id, phase) VALUES (%s,%s,%s)
             ON CONFLICT (learner_id, question_id) DO NOTHING""", (L["learner_id"], qid, L["phase"]))
    event("view", {"learner_id": L["learner_id"], "qid": qid, "phase": L["phase"]})
    return {"ok": True}


class SqlIn(BaseModel):
    sql: str = Field(max_length=5000)


def _grade(q, sql):
    """(res, err, ok, diff). Raises HTTP 503 on a database outage, before anything is written."""
    try:
        res = run_query(sql)
    except InfraError:
        raise HTTPException(503, INFRA_MSG)
    except SandboxError as e:
        return None, str(e), False, None
    ok, diff = compare(res["rows"], res["ncols"], q["expected_rows"], q["expected_ncols"], q["ordered"])
    return res, None, ok, diff


def _ensure_view(L, qid):
    db.ex("""INSERT INTO app.question_views (learner_id, question_id, phase) VALUES (%s,%s,%s)
             ON CONFLICT (learner_id, question_id) DO NOTHING""", (L["learner_id"], qid, L["phase"]))


@app.post("/api/questions/{qid}/run")
def run(qid: str, body: SqlIn, L=Depends(learner)):
    q = question_for(L, qid)
    check_time(L, grace=5)
    if L["phase"] in TEST_PHASES:
        done = db.q1("SELECT finished_at FROM app.question_views WHERE learner_id=%s AND question_id=%s",
                     (L["learner_id"], qid))
        if done and done["finished_at"]:
            raise HTTPException(409, "Already submitted")
    res, err, ok, diff = _grade(q, body.sql)
    _ensure_view(L, qid)
    db.ex("""INSERT INTO app.attempts (learner_id, question_id, phase, kind, sql_text, error, correct, got_rows, diff)
             VALUES (%s,%s,%s,'run',%s,%s,%s,%s,%s)""",
          (L["learner_id"], qid, L["phase"], body.sql, err, bool(ok),
           len(res["rows"]) if res else None, db.J(diff) if diff else None))
    out = {"error": err}
    if res:
        out.update(columns=res["columns"], rows=rows_for_json(res["rows"]), row_count=len(res["rows"]),
                   truncated=res["truncated"] or len(res["rows"]) > MAX_DISPLAY)
    if L["phase"] == "practice":
        out["correct"] = bool(ok)
        out["feedback"] = "Correct!" if ok else ("Your query has an error." if err else describe(diff))
        if ok:
            db.ex("""UPDATE app.question_views SET final_correct = TRUE,
                     finished_at = COALESCE(finished_at, now())
                     WHERE learner_id=%s AND question_id=%s""", (L["learner_id"], qid))
        out["reveal_available"] = False if ok else _can_reveal(L, _help_state(L, q))
    return out


@app.post("/api/questions/{qid}/submit")
def submit(qid: str, body: SqlIn, L=Depends(learner)):
    q = question_for(L, qid)
    if L["phase"] not in TEST_PHASES:
        raise HTTPException(404, "Not found")
    check_time(L)
    _ensure_view(L, qid)
    v = db.q1("SELECT finished_at FROM app.question_views WHERE learner_id=%s AND question_id=%s",
              (L["learner_id"], qid))
    if v["finished_at"]:
        raise HTTPException(409, "Already submitted")
    sql = body.sql.strip()
    if sql:
        res, err, ok, diff = _grade(q, sql)   # 503 on outage: nothing written, learner can resubmit
    else:
        res, err, ok, diff = None, "blank", False, None
    # The guarded UPDATE (finished_at IS NULL) is what enforces exactly one submit per question.
    with db.tx() as c:
        upd = c.execute("""UPDATE app.question_views SET finished_at = now(), final_correct = %s
                           WHERE learner_id=%s AND question_id=%s AND finished_at IS NULL""",
                        (bool(ok), L["learner_id"], qid))
        if upd.rowcount == 0:
            raise HTTPException(409, "Already submitted")
        c.execute("""INSERT INTO app.attempts (learner_id, question_id, phase, kind, sql_text, error, correct, got_rows, diff)
                     VALUES (%s,%s,%s,'submit',%s,%s,%s,%s,%s)""",
                  (L["learner_id"], qid, L["phase"], sql, err, bool(ok),
                   len(res["rows"]) if res else None, db.J(diff) if diff else None))
    return {"submitted": True}   # correctness deliberately NOT returned in test phases


def _mastered(lid, q):
    """What the learner has shown they can do UNAIDED on this question's skill:
    - the pretest item for the skill was correct, OR
    - an earlier practice question of the same skill was solved with no help beyond L1."""
    pre_ids = [x["id"] for x in QUESTIONS.values() if x["set"] == "pretest" and x["skill"] == q["skill"]]
    if db.q1("""SELECT 1 FROM app.attempts WHERE learner_id=%s AND phase='pretest' AND kind='submit'
                AND correct AND question_id = ANY(%s)""", (lid, pre_ids)):
        return True
    same = [x["id"] for x in QUESTIONS.values()
            if x["set"] == "practice" and x["skill"] == q["skill"] and x["id"] != q["id"]]
    return bool(db.q1("""SELECT 1 FROM app.question_views v
                         WHERE v.learner_id=%s AND v.question_id = ANY(%s) AND v.final_correct
                           AND COALESCE((SELECT max(h.level) FROM app.hints h
                                         WHERE h.learner_id=v.learner_id AND h.question_id=v.question_id
                                           AND h.created_at <= v.finished_at), 0) <= 1""", (lid, same)))


def _help_state(L, q):
    """Everything the policy needs, read from the database (never from the client)."""
    lid, qid = L["learner_id"], q["id"]
    attempts = db.q1("SELECT count(*) n FROM app.attempts WHERE learner_id=%s AND question_id=%s AND kind='run'",
                     (lid, qid))["n"]
    # latest hint of any kind on the ladder range (an error explanation included): for repeats and `since`
    last = db.q1("""SELECT level, created_at, text FROM app.hints WHERE learner_id=%s AND question_id=%s
                    AND level BETWEEN 1 AND 4 ORDER BY created_at DESC, hint_id DESC LIMIT 1""", (lid, qid))
    # ladder position: error explanations don't climb the ladder, so they are left out
    last_level = db.q1("""SELECT COALESCE(max(level), 0) m FROM app.hints WHERE learner_id=%s AND question_id=%s
                          AND level BETWEEN 1 AND 4 AND source NOT LIKE '%%\\_error'""", (lid, qid))["m"]
    since = attempts if not last else db.q1(
        """SELECT count(*) n FROM app.attempts WHERE learner_id=%s AND question_id=%s AND kind='run'
           AND created_at > (SELECT max(created_at) FROM app.hints WHERE learner_id=%s AND question_id=%s
                             AND level BETWEEN 1 AND 4)""", (lid, qid, lid, qid))["n"]
    fails_after_l4 = db.q1(
        """SELECT count(*) n FROM app.attempts WHERE learner_id=%s AND question_id=%s AND kind='run'
           AND NOT correct AND created_at > (SELECT min(created_at) FROM app.hints
                                             WHERE learner_id=%s AND question_id=%s AND level = 4
                                               AND source NOT LIKE '%%\\_error')""",
        (lid, qid, lid, qid))["n"]
    last_attempt = db.q1("""SELECT sql_text, error, diff, correct FROM app.attempts WHERE learner_id=%s
                            AND question_id=%s AND kind='run' ORDER BY created_at DESC LIMIT 1""", (lid, qid))
    revealed = bool(db.q1("SELECT 1 FROM app.hints WHERE learner_id=%s AND question_id=%s AND source='reveal'",
                          (lid, qid)))
    return dict(attempts=attempts, last=last, last_level=last_level, since=since,
                fails_after_l4=fails_after_l4, last_attempt=last_attempt,
                closeness=closeness(last_attempt), revealed=revealed)


def _can_reveal(L, st):
    return (not st["revealed"]) and reveal_available(L["arm"], st["last_level"], st["fails_after_l4"], st["closeness"])


@app.get("/api/questions/{qid}/hints")
def hints(qid: str, L=Depends(learner)):
    if L["phase"] != "practice":
        raise HTTPException(404, "Not found")
    q = question_for(L, qid)
    rows = db.q("SELECT text FROM app.hints WHERE learner_id=%s AND question_id=%s ORDER BY hint_id",
                (L["learner_id"], qid))
    can = _can_reveal(L, _help_state(L, q)) if L["arm"] in ("tutor", "baseline") else False
    return {"hints": [{"text": h["text"]} for h in rows], "reveal_available": can}


@app.post("/api/questions/{qid}/help")
def help_(qid: str, L=Depends(learner)):
    if L["phase"] != "practice":
        raise HTTPException(404, "Not found")   # no assistant outside practice
    q = question_for(L, qid)
    check_time(L, grace=5)
    if L["arm"] not in ("tutor", "baseline"):
        raise HTTPException(409, "Help isn't switched on for you yet. Ask the invigilator.")
    lid = L["learner_id"]
    mastered = _mastered(lid, q)
    st = _help_state(L, q)
    d = decide(L["arm"], mastered, st["attempts"], st["since"], st["last_level"],
               st["closeness"], st["fails_after_l4"], hinted=st["last"] is not None)
    if d.action in ("gate", "solved"):
        r = dict(text=d.message, source=d.action, guard_blocked=0, model=None, latency_ms=0)
    elif d.action == "repeat":
        r = dict(text=d.message + "\n\n" + st["last"]["text"], source="repeat",
                 guard_blocked=0, model=None, latency_ms=0)
    elif d.action == "answer":
        r = baseline_answer(q, st["last_attempt"])
    else:
        r = tutor_hint(q, d.level, st["last_attempt"], mode=d.mode)
    stored = {"hint": d.level, "answer": d.level, "gate": 0, "repeat": -1, "solved": -2}[d.action]
    db.ex("""INSERT INTO app.hints (learner_id, question_id, arm, level, attempts_before, mastered, text, source,
             guard_blocked, model, latency_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (lid, qid, L["arm"], stored, st["attempts"], mastered, r["text"],
           r["source"] if d.mode == "normal" else r["source"] + "_error",
           r["guard_blocked"], r["model"], r["latency_ms"]))
    st2 = _help_state(L, q)
    return {"text": r["text"], "reveal_available": _can_reveal(L, st2)}


@app.post("/api/questions/{qid}/reveal")
def reveal(qid: str, L=Depends(learner)):
    """Tutor arm, last resort: only after L4 and REVEAL_AFTER more failed runs, and only when the
    learner chooses it. Logged as source='reveal'; a revealed question does not count as solved."""
    if L["phase"] != "practice":
        raise HTTPException(404, "Not found")
    q = question_for(L, qid)
    check_time(L, grace=5)
    st = _help_state(L, q)
    if not _can_reveal(L, st):
        raise HTTPException(409, "Not available yet. Keep trying with the hints.")
    text = f"Here is a query that answers it:\n```sql\n{q['sql']}\n```\nCompare it with your attempt, line by line."
    db.ex("""INSERT INTO app.hints (learner_id, question_id, arm, level, attempts_before, mastered, text, source,
             guard_blocked, model, latency_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,'reveal',0,NULL,0)""",
          (L["learner_id"], qid, L["arm"], REVEAL_LEVEL, st["attempts"], None, text))
    return {"text": text, "reveal_available": False}


class SurveyIn(BaseModel):
    value: int = Field(ge=1, le=5)


@app.post("/api/survey")
def survey(body: SurveyIn, L=Depends(learner)):
    if L["phase"] != "practice":
        raise HTTPException(404, "Not found")
    db.ex("""INSERT INTO app.survey (learner_id, item, value) VALUES (%s,'return',%s)
             ON CONFLICT (learner_id, item) DO UPDATE SET value = EXCLUDED.value, created_at = now()""",
          (L["learner_id"], body.value))
    return {"ok": True}


class ClientEvent(BaseModel):
    kind: str = Field(pattern="^(blur|focus|hidden|visible)$")
    qid: str | None = Field(default=None, max_length=8)


@app.post("/api/event")
def client_event(body: ClientEvent, L=Depends(learner)):
    """Tab-switch / focus-loss log in test phases (reported per learner, not enforced)."""
    if L["phase"] in TEST_PHASES:
        event("focus", {"learner_id": L["learner_id"], "phase": L["phase"], "kind": body.kind, "qid": body.qid})
    return {"ok": True}


# ---------------------------------------------------------------- admin
class NewLearners(BaseModel):
    names: list[str]
    pilot: bool = False


@app.post("/api/admin/learners")
def create_learners(body: NewLearners, _=Depends(admin)):
    """New learners start in 'waiting' with no clock; the pretest clock starts when the
    invigilator presses 'pretest' (Start) for them in the console."""
    out = []
    for n in body.names:
        n = n.strip()
        if not n:
            continue
        code = "-".join(secrets.token_hex(3) for _ in range(2))   # 48 bits, e.g. 3fa9c1-07be42
        db.ex("INSERT INTO app.learners (code, display_name, is_pilot, phase) VALUES (%s,%s,%s,'waiting')",
              (code, n, body.pilot))
        out.append({"name": n, "code": code})
    return out


def pretest_scores(c=None):
    sql = """SELECT l.learner_id, count(*) FILTER (WHERE a.correct) AS score
             FROM app.learners l LEFT JOIN app.attempts a
               ON a.learner_id = l.learner_id AND a.phase='pretest' AND a.kind='submit'
             GROUP BY l.learner_id"""
    rows = c.execute(sql).fetchall() if c else db.q(sql)
    return {r["learner_id"]: r["score"] for r in rows}


LEARNER_LIST_SQL = """SELECT l.*, (SELECT count(*) FROM app.question_views v WHERE v.learner_id=l.learner_id
                   AND v.phase=l.phase AND v.finished_at IS NOT NULL) AS finished_in_phase,
                   (SELECT count(*) FROM app.question_views v WHERE v.learner_id=l.learner_id
                   AND v.phase='pretest' AND v.finished_at IS NOT NULL) AS pretest_done
                   FROM app.learners l ORDER BY l.learner_id"""


@app.get("/api/admin/learners")
def list_learners(_=Depends(admin)):
    scores = pretest_scores()
    rows = db.q(LEARNER_LIST_SQL)
    for r in rows:
        r["pretest_score"] = scores.get(r["learner_id"], 0)
        r["created_at"] = r["created_at"].isoformat()
    return rows


@app.post("/api/admin/assign")
def assign_arms(_=Depends(admin)):
    """Rank active, non-pilot, unassigned learners by pretest score; pair 1-2, 3-4, ...;
    coin flip within each pair. Ties broken by a random draw. With an odd count the
    lowest-ranked learner is left unpaired and gets their own coin flip.
    One transaction under a table lock: a double click cannot assign twice."""
    with db.tx() as c:
        c.execute("LOCK TABLE app.learners IN SHARE ROW EXCLUSIVE MODE")
        finalize_expired(c)
        scores = pretest_scores(c)
        rows = c.execute(LEARNER_LIST_SQL).fetchall()
        rows = [r for r in rows if not r["is_pilot"] and not r["excluded"] and r["arm"] is None]
        if not rows:
            raise HTTPException(400, "No unassigned learners (pilots and excluded learners are skipped)")
        unfinished = [r["display_name"] for r in rows if r["pretest_done"] < 6]
        if unfinished:
            raise HTTPException(400, "Still in the pretest: " + ", ".join(unfinished)
                                + ". Wait until 2 minutes after their time is up and press Assign again "
                                "(unsubmitted answers are then recorded as blank), or exclude a no-show.")
        for r in rows:
            r["pretest_score"] = scores.get(r["learner_id"], 0)
        tiebreak = {r["learner_id"]: secrets.randbelow(10**9) for r in rows}
        rows.sort(key=lambda r: (-r["pretest_score"], tiebreak[r["learner_id"]]))
        next_pair = (c.execute("SELECT COALESCE(max(pair_no), 0) AS m FROM app.learners").fetchone()["m"]) + 1
        log = []
        for i in range(0, len(rows) - 1, 2):
            a, b = rows[i], rows[i + 1]
            flip = secrets.randbelow(2)
            tutor, base = (a, b) if flip == 0 else (b, a)
            pair = next_pair + i // 2
            for lid, arm in ((tutor["learner_id"], "tutor"), (base["learner_id"], "baseline")):
                upd = c.execute("UPDATE app.learners SET arm=%s, pair_no=%s WHERE learner_id=%s AND arm IS NULL",
                                (arm, pair, lid))
                if upd.rowcount != 1:
                    raise HTTPException(409, "Assignment changed underneath; nothing was saved. Try again.")
            log.append({"pair": pair, "tutor": tutor["learner_id"], "baseline": base["learner_id"],
                        "scores": [a["pretest_score"], b["pretest_score"]], "flip": flip})
        if len(rows) % 2:
            odd = rows[-1]
            # Learners arriving one at a time: if an earlier solo learner is still unpaired, this one
            # gets the OPPOSITE arm and the two become a pair (randomised in blocks of two).
            # Otherwise a coin flip, and this learner waits unpaired for the next solo arrival.
            waiting = c.execute("""SELECT learner_id, arm FROM app.learners WHERE arm IS NOT NULL AND pair_no IS NULL
                                   AND NOT is_pilot AND NOT excluded ORDER BY learner_id LIMIT 1""").fetchone()
            if waiting:
                arm = "baseline" if waiting["arm"] == "tutor" else "tutor"
                pair = next_pair + len(rows) // 2
                c.execute("UPDATE app.learners SET arm=%s, pair_no=%s WHERE learner_id=%s AND arm IS NULL",
                          (arm, pair, odd["learner_id"]))
                c.execute("UPDATE app.learners SET pair_no=%s WHERE learner_id=%s", (pair, waiting["learner_id"]))
                log.append({"pair": pair, arm: odd["learner_id"],
                            ("tutor" if arm == "baseline" else "baseline"): waiting["learner_id"],
                            "scores": [odd["pretest_score"]], "completes_earlier_solo": True})
            else:
                arm = "tutor" if secrets.randbelow(2) == 0 else "baseline"
                c.execute("UPDATE app.learners SET arm=%s, pair_no=NULL WHERE learner_id=%s AND arm IS NULL",
                          (arm, odd["learner_id"]))
                log.append({"pair": None, arm: odd["learner_id"], "scores": [odd["pretest_score"]], "unpaired": True})
        c.execute("INSERT INTO app.events (kind, payload) VALUES ('assign', %s)",
                  (db.J({"pairs": log, "tiebreak": {str(k): v for k, v in tiebreak.items()},
                         "at": datetime.now(timezone.utc).isoformat()}),))
    return log


class ArmIn(BaseModel):
    learner_id: int
    arm: str


@app.post("/api/admin/arm")
def set_arm(body: ArmIn, _=Depends(admin)):
    """Manual arm (pilot only — real learners go through /assign)."""
    if body.arm not in ("tutor", "baseline"):
        raise HTTPException(400, "bad arm")
    r = db.q1("SELECT is_pilot FROM app.learners WHERE learner_id=%s", (body.learner_id,))
    if not r or not r["is_pilot"]:
        raise HTTPException(400, "Manual arm only allowed for pilot learners")
    db.ex("UPDATE app.learners SET arm=%s WHERE learner_id=%s", (body.arm, body.learner_id))
    return {"ok": True}


class ExcludeIn(BaseModel):
    learner_id: int
    reason: str = Field(min_length=1, max_length=200)


@app.post("/api/admin/exclude")
def exclude(body: ExcludeIn, _=Depends(admin)):
    """Mark a no-show / duplicate / dropout. Their code stops working; they're left out of
    assignment; analysis reports them as excluded. Logged with the reason."""
    with db.tx() as c:
        if c.execute("UPDATE app.learners SET excluded = TRUE WHERE learner_id=%s",
                     (body.learner_id,)).rowcount != 1:
            raise HTTPException(404, "No such learner")
    event("exclude", {"learner_id": body.learner_id, "reason": body.reason})
    return {"ok": True}


class PhaseIn(BaseModel):
    learner_ids: list[int]
    phase: str
    force: bool = False


@app.post("/api/admin/phase")
def set_phase(body: PhaseIn, _=Depends(admin)):
    if body.phase not in PHASE_ORDER:
        raise HTTPException(400, "bad phase")
    rows = db.q("SELECT learner_id, display_name, arm, phase FROM app.learners WHERE learner_id = ANY(%s)",
                (body.learner_ids,))
    if len(rows) != len(set(body.learner_ids)):
        raise HTTPException(404, "Unknown learner id in the selection")
    if body.phase == "practice":
        missing = [r["display_name"] for r in rows if r["arm"] is None]
        if missing:
            raise HTTPException(400, f"Assign arms first: {', '.join(missing)}")
    back = [r["display_name"] for r in rows if PHASE_ORDER.index(body.phase) < PHASE_ORDER.index(r["phase"])]
    if back and not body.force:
        raise HTTPException(400, f"That moves {', '.join(back)} BACKWARDS. Re-send with force if you really mean it.")
    with db.tx() as c:
        finalize_expired(c)   # BEFORE the move, while learners are still in their test phase
        # anyone leaving a test phase: whatever is still unsubmitted is recorded as blank (= wrong)
        for r in rows:
            if r["phase"] in TEST_PHASES and r["phase"] != body.phase:
                _blank_fill(c, r["learner_id"], r["phase"], "left phase unsubmitted (blank)")
        # the clock (re)starts only for learners actually entering a new phase
        c.execute("""UPDATE app.learners SET phase_started_at = CASE WHEN phase = %s THEN phase_started_at ELSE now() END,
                     phase = %s WHERE learner_id = ANY(%s)""", (body.phase, body.phase, body.learner_ids))
    event("phase", {"ids": body.learner_ids, "phase": body.phase, "force": body.force})
    return {"ok": True}


@app.get("/api/admin/export")
def export(_=Depends(admin)):
    def dump(sql):
        rows = db.q(sql)
        for r in rows:
            for k, v in list(r.items()):
                if isinstance(v, datetime):
                    r[k] = v.isoformat()
        return rows
    return {
        "questions": [{k: q[k] for k in ("id", "set", "skill", "ordered", "transfer")} for q in QUESTIONS.values()],
        "learners": dump("SELECT learner_id, is_pilot, excluded, arm, pair_no, phase FROM app.learners"),
        "attempts": dump("SELECT * FROM app.attempts ORDER BY attempt_id"),
        "views": dump("SELECT * FROM app.question_views"),
        "hints": dump("SELECT * FROM app.hints ORDER BY hint_id"),
        "survey": dump("SELECT * FROM app.survey"),
        "events": dump("SELECT * FROM app.events ORDER BY event_id"),
    }


@app.get("/api/admin/stats")
def stats(_=Depends(admin)):
    """Live check during a session: is the LLM answering, or are we on fallbacks (e.g. Groq rate limits)?"""
    rows = db.q("""SELECT h.arm, count(*) FILTER (WHERE h.level >= 1) AS help,
                          count(*) FILTER (WHERE h.level >= 1 AND h.source = 'fallback') AS fallback,
                          COALESCE(sum(h.guard_blocked), 0) AS blocked
                   FROM app.hints h JOIN app.learners l ON l.learner_id = h.learner_id
                   WHERE NOT l.is_pilot GROUP BY h.arm""")
    out = {r["arm"]: {"help": r["help"], "fallback": r["fallback"], "blocked": int(r["blocked"])} for r in rows}
    models = db.q("""SELECT COALESCE(h.model, 'deterministic') AS model, count(*) AS n FROM app.hints h
                     JOIN app.learners l ON l.learner_id = h.learner_id
                     WHERE NOT l.is_pilot AND h.level >= 1 GROUP BY 1 ORDER BY 2 DESC""")
    for arm in out.values():
        arm["models"] = {m["model"]: m["n"] for m in models}
    return out


@app.get("/api/health")
def health():
    db.q1("SELECT 1")
    return {"ok": True, "questions": len(QUESTIONS), "llm": bool(settings.groq_api_key)}


# ---------------------------------------------------------------- frontend
if settings.frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return FileResponse(settings.frontend_dist / "index.html")
