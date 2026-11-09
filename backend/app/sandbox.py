"""SQL sandbox for learner queries.

Defence in depth:
 1. Static check: exactly one statement, must start with SELECT or WITH.
 2. Executed over a SEPARATE connection that logs in as `learner_ro`
    (SELECT on schema shop only; no access to schema app).
 3. Transaction is READ ONLY; statement_timeout 3s (also set on the role).
 4. Row cap.
"""
import re
import threading
import time

import psycopg

from .config import settings

MAX_FETCH = 1000      # rows pulled for grading (largest expected answer is 63 rows)
MAX_DISPLAY = 200     # rows sent to the browser
MAX_SQL_LEN = 5000


MAX_BYTES = 2_000_000  # approx. bytes of result data pulled into the API process
MAX_CELL = 2_000       # longest single value allowed


class SandboxError(Exception):
    """The learner's query is invalid or failed: counts as the learner's error."""


class InfraError(Exception):
    """The database could not be reached: NOT the learner's fault; never graded."""


def _strip_comments_and_strings(sql: str) -> str:
    """Replace string literals/quoted identifiers with placeholders and drop comments,
    so we can look for ';' and the leading keyword safely."""
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j == -1:
                raise SandboxError("Unclosed /* comment.")
            i = j + 2
            out.append(" ")
        elif ch in ("'", '"'):
            estring = ch == "'" and i > 0 and sql[i - 1] in "eE" and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] == "_"))
            j = i + 1
            while True:
                if estring:
                    while j < n and sql[j] != ch:
                        j += 2 if sql[j] == "\\" else 1
                    if j >= n:
                        raise SandboxError("Unclosed quote.")
                else:
                    j = sql.find(ch, j)
                    if j == -1:
                        raise SandboxError("Unclosed quote.")
                if j + 1 < n and sql[j + 1] == ch:  # escaped '' or ""
                    j += 2
                    continue
                break
            out.append(" x ")
            i = j + 1
        elif ch == "$" and re.match(r"\$[A-Za-z_]*\$", sql[i:]):
            raise SandboxError("Dollar-quoted strings are not allowed.")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def check_sql(sql: str) -> str:
    """Return a cleaned single statement or raise SandboxError."""
    if not sql or not sql.strip():
        raise SandboxError("Empty query.")
    if len(sql) > MAX_SQL_LEN:
        raise SandboxError("Query too long.")
    bare = _strip_comments_and_strings(sql).strip()
    bare = bare.rstrip().rstrip(";").rstrip()
    if ";" in bare:
        raise SandboxError("Only one statement is allowed.")
    if not re.match(r"(?is)^\s*\(*\s*(select|with)\b", bare):
        raise SandboxError("Only SELECT (or WITH ... SELECT) queries are allowed.")
    # remove trailing semicolons from the real text too
    cleaned = sql.strip()
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def _connect():
    last = None
    for _ in range(2):  # one retry on a transient connection failure
        try:
            return psycopg.connect(settings.learner_dsn, autocommit=False, connect_timeout=8,
                                   prepare_threshold=None)
        except psycopg.OperationalError as e:
            last = e
            time.sleep(0.3)
    raise InfraError(f"database unreachable: {type(last).__name__}")


def _size(v):
    if v is None:
        return 4
    if isinstance(v, (bytes, bytearray, memoryview)):
        return len(v)
    return len(str(v))


def run_query(sql: str):
    """Run a learner query. Returns dict(columns, rows, ncols, truncated, ms).

    Uses a SERVER-SIDE cursor and pulls rows in small batches, so a cartesian
    product or a huge value never gets materialised in the API process
    (row cap MAX_FETCH, byte cap MAX_BYTES, cell cap MAX_CELL).
    Raises SandboxError for the learner's mistakes, InfraError for outages."""
    cleaned = check_sql(sql)
    conn = _connect()
    try:
        return _execute(conn, cleaned)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_many(sqls):
    """Run several candidate queries over ONE connection (used by the leak guard).
    Yields (sql, result | None). Invalid candidates yield None. InfraError propagates."""
    conn = None
    try:
        for sql in sqls:
            try:
                cleaned = check_sql(sql)
            except SandboxError:
                yield sql, None
                continue
            if conn is None or conn.closed or conn.broken:
                conn = _connect()
            try:
                yield sql, _execute(conn, cleaned)
            except SandboxError:
                yield sql, None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


WALL_CLOCK_S = 3.5   # enforced from Python too: a learner can't lift it with set_config()


def _execute(conn, cleaned):
    t0 = time.perf_counter()
    timer = threading.Timer(WALL_CLOCK_S, _cancel, args=(conn,))
    timer.daemon = True
    timer.start()
    try:
        conn.read_only = True
        with conn.transaction():
            with conn.cursor() as setup:
                setup.execute("SET LOCAL statement_timeout = '3s'")
                setup.execute("SET LOCAL search_path = shop")
                setup.execute("SET LOCAL work_mem = '8MB'")
            with conn.cursor(name="learner_q") as cur:
                cur.itersize = 50
                cur.execute(cleaned)
                rows, nbytes, truncated = [], 0, False
                while True:
                    if time.perf_counter() - t0 > WALL_CLOCK_S:
                        raise psycopg.errors.QueryCanceled("wall clock")
                    batch = cur.fetchmany(50)
                    if not batch:
                        break
                    for r in batch:
                        if any(_size(v) > MAX_CELL for v in r):
                            raise SandboxError("A value in your result is far too long. Check your query.")
                        nbytes += sum(_size(v) for v in r)
                        rows.append(r)
                    if len(rows) > MAX_FETCH or nbytes > MAX_BYTES:
                        truncated = True
                        break
                if cur.description is None:
                    raise SandboxError("Query returned no result set.")
                cols = [d.name for d in cur.description]
            raise _Rollback()
    except _Rollback:
        pass
    except SandboxError:
        raise
    except psycopg.errors.QueryCanceled:
        raise SandboxError("Query took longer than 3 seconds and was stopped. "
                           "(Missing a join condition? That multiplies every row by every row.)")
    except (psycopg.OperationalError, psycopg.InterfaceError) as e:
        if conn.broken or conn.closed:
            raise InfraError(f"database connection lost: {type(e).__name__}")
        raise SandboxError(_msg(e))
    except psycopg.Error as e:
        raise SandboxError(_msg(e))
    finally:
        timer.cancel()
    return {"columns": cols, "rows": rows[:MAX_FETCH], "ncols": len(cols), "truncated": truncated,
            "ms": int((time.perf_counter() - t0) * 1000)}


def _cancel(conn):
    try:
        conn.cancel_safe(timeout=2)
    except Exception:
        pass


class _Rollback(Exception):
    pass


def _msg(e):
    d = getattr(e, "diag", None)
    msg = d.message_primary if d and d.message_primary else str(e).split("\n")[0]
    hint = d.message_hint if d else None
    return msg + (f" (hint: {hint})" if hint else "")
