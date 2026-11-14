# Tutor LLM replies: round 1 (10 Nov, tutor v1)

**Scope:** every help reply the 4 real tutor-arm learners received on 10 Nov (learners 2, 8, 11, 14), 43 in total:
- 35 real help replies;
- 6 repeats;
- 2 gates.

Pilots are excluded. All AI replies came from `openai/gpt-oss-120b`.

**Method:** each reply was graded by hand against the learner's query at that moment. The grading asked:
1. Is the diagnosis correct?
2. Does it point at the exact place in *their* query?
3. Does it stay within its level, or does it give away more?

Every reply was then replayed through the v2 rules (`scripts/replay` in the session log).

## 1. Where the help actually went
| Kind of help | n | AI-written | Built-in fallback | Median length | Median wait |
|---|---|---|---|---|---|
| SQL-error explanation | 17 | 12 | 5 | 360 chars | 2.4 s |
| L1 with an attempt | 6 | 5 | 1 | 160 chars | 0.8 s |
| L1 before any attempt | 5 | 5 | 0 | 140 chars | 0.8 s |
| L2 concept | 6 | 6 | 0 | 400 chars | 1.2 s |
| L3 skeleton | 0 | – | – | – | – |
| L4 fix | 1 | 1 | 0 | 216 chars | 0.8 s |

**Finding 1: the ladder hardly ran.**
- About half of all help (17 of 35) was SQL-error explanations, which by design don't climb the ladder.
- L3 was never reached, and L4 only once.
- In practice the tutor that was delivered was "an error explainer, plus L1/L2", not the 4-level ladder that was designed.

## 2. Quality by kind (hand-graded)
| Kind | Correct and located | Gave away more than its level | Wrong or unhelpful |
|---|---|---|---|
| L1 with an attempt (AI, 5) | **4** ("your join matches every product to itself", "customers who bought Electronics still appear") | 0 | 1 (a cross join read as "drops customers") |
| L1 before any attempt (5) | 0, since there is nothing to locate | 1 ("two separate aggregates…" is the T4 plan) | 4 restate the question |
| L2 concept (6) | **6** | 2 (exact correlation `= p.product_id`; the case-sensitivity fix) | 0 |
| L4 fix (1) | 1 | 0 | 0 |
| Error explanation (AI, 12) | 6 (quotes, alias, typo, comma, GROUP BY) | **6** (see below) | 0 |
| Built-in fallbacks (6) | 0 | 0 | **6** (generic error text, or wrong for that query) |

**Finding 2: when the AI looks at a real attempt, its diagnosis is good.** It was correct in 11 of 12 cases at L1/L2/L4.

**Finding 3: the leaks came through the error channel.** Half of the AI error explanations solved more than the error:
- T3 (learner 11): `HAVING COUNT(o.order_id) = 0`, which is the core of the question. *This matches one learner's complaint, "it gives part of the code directly".*
- T4 (learner 14): "move it to HAVING or wrap in a subquery", plus code.
- T2 (learner 14): rewrote his `SUM(SELECT …)` into the correct correlated subquery.
- T4 (learner 2): a timeout explained by giving every join condition. That's L4-level help, given at L1.
- T3 (learner 11): fixed the comma *and* pointed out the next error.
- T7 (learner 11): wrote out the whole `LEFT JOIN … ON …` chain.

**Finding 4: the built-in fallbacks were the worst replies.**
- Every one of the 6 was generic ("read it word by word"), or wrong for that query: on learner 14's T4, "counts bigger after your joins?" when he had no joins at all.
- Two of them only appeared because the v1 rules rejected *accurate* AI replies, one for naming `unit_price` and one for saying "subquery" to a learner who was already using a subquery. *This matches another learner's complaint, "it can't locate my problem".*

**Finding 5: a third of the L1 hints came before any attempt.** Learners asked for help before running anything, and they got a restatement of the question.

**Finding 6: 6 repeat messages.** Learners clicked Get help again without running a new query and got "try the last hint first". From their side, the tutor looked stuck.

## 3. What v2 changes, and the replay check
The v2 rule: **a hint may use anything already in the learner's own query or in the error message, but may not introduce a new SQL feature or new code before L2 (the concept level).**

| Change | Replay of the real replies |
|---|---|
| Error hints: no new SQL features; one or two lines of the learner's own code at most | Both `HAVING` leaks are now rejected; all 6 clean error fixes (quotes, alias, typo, GROUP BY, comma) still pass |
| L1: may name the learner's own tables, columns and features | Both accurate T4 diagnoses that v1 rejected now pass |
| Timeout = wrong attempt, not an error | The "here are all the join conditions" reply can no longer happen |
| Built-in error text explains the specific PostgreSQL error | Replaces "read it word by word" |
| Built-in L1 says what is wrong with the result ("Expected 8 rows, you returned 12…") | Replaces generic questions |
| The AI is shown example rows that are missing, extra or duplicated in the learner's result | Lets L1 say "customer 17 is missing" instead of guessing |
| Get help is locked until a new run, in both arms | No more repeat messages |

Replay of the 33 real learner replies (pilots excluded): 22 accepted and 11 rejected on the first pass.
- Rejected, rightly:
  - every reply that brought in `HAVING` or `GROUP BY` the learner hadn't used;
  - the rewrite of `SUM(SELECT 1 …)` into the correct correlated subquery;
  - the full `LEFT JOIN … LEFT JOIN …` chain.
- Rejected only for their form: a few clean error fixes written as 3-line code blocks or with headings.
  - v1's prompt allowed that form; the v2 prompt asks for at most two lines.
  - A rejected reply gets one retry, told the reason, and then the specific built-in error text.
- The true v2 acceptance rate can only be measured with live replies: run `scripts/probe_hints.py`, and check the fallback share in the admin console during the session.
- An independent review added 53 hand-written edge cases (`shape_cases.py`). All pass except the prompt-only case below.

**Still not caught by the rules (prompt-only):**
- an error hint that mentions a second problem;
- an L1 given before any attempt that hints at the plan;
- an L2 that gives the exact fix detail.

These are left to the prompt, and are reported as limitations.
