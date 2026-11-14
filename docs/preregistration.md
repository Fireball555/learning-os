# Pre-registration: Learning OS removal test

**Frozen by:** the git commit tagged `prereg`, made before the first pretest. The commit's SHA, plus `sha256sum backend/app/questions.json docs/preregistration.md scripts/analyze.py`, goes in a timestamped message to a third party before the pretest (for example, an email to 100x or a mentor).

**Keep the repo PRIVATE until the removal test is over (13 Nov).** It contains the held-out questions and their answers. Make it public afterwards; anyone can then check it against the hashes.

Every later change to the frozen files is listed under Deviations, with the reason.

## Hypothesis v1 (unchanged; later versions go in the case study with the evidence that caused them)
For learners who already know single-table SQL, an assistant that caps how much it reveals, based on what the learner has already shown they can do unaided, will produce higher scores on held-out multi-table questions taken later without any assistant than an assistant that gives the full query on request. Practice-session completion stays comparable.

"What the learner has shown they can do unaided", per skill:
- the pretest item for that skill was correct, OR
- an earlier practice question of the same skill was solved with no help beyond a level-1 hint.

This is updated live during practice.

## Decision rules (fixed now)
**Primary metric:** skill-matched gain per learner = (H1–H6 correct ÷ 6) − (P1–P6 correct ÷ 6), in percentage points. There is one item per skill on each side.

| Outcome | Condition |
|---|---|
| **Supported** | (round 2 is primary; see Deviation 3) Tutor mean gain − baseline mean gain ≥ one item, i.e. ≥ 100/6 = 16.67 points, **and** the tutor learner out-gains the baseline learner in at least two-thirds of the complete pairs (rounded up, and at least 2). With 3 pairs that is 2, with 4 it is 3, with 5 it is 4. |
| **Falsified** | The mirror image: baseline ahead by ≥ one item (16.67 points) **and** wins in at least two-thirds of the complete pairs. |
| **Inconclusive** | Anything else. Reported as "no evidence either way at n = <final n>". |

**Completion collapses** if the tutor arm's mean practice questions solved is below 0.75 × the baseline arm's mean. A collapse is reported next to the retention result, whatever that result is.

## Design
- At least 6 learners (about 9 expected), none on the team. Pilot runs are excluded from all results. The final n is whoever turns up to practice; a pair is complete when both members take the removal test. A complete pair is a tutor learner and a baseline learner who both finished the pretest and the removal test.
- **The pilot does NOT see the held-out set before 13 Nov.** The held-out flow is checked with a throwaway learner that the experimenter runs alone.
- Between subjects, tutor vs baseline, with equal numbers in each arm (± 1 with an odd total).
  - Learners are ranked by pretest score and paired with their neighbour (1–2, 3–4, …).
  - A coin flip within each pair (`secrets.randbelow`) decides who gets which arm.
  - Score ties are broken by a random draw. Draws and flips are logged in `app.events`.
  - A no-show is excluded before assignment and logged with the reason.
  - If learners come in separate sittings, those in the same sitting are ranked and paired as above. A learner who comes alone gets a coin flip; the next solo learner gets the opposite arm and becomes their pair (randomised in blocks of two).
  - With an odd count, the lowest-ranked learner is unpaired and gets their own coin flip.
- Both arms use the same app, schema, context, UI and model chain (Groq, temperature 0.3: `openai/gpt-oss-120b`, then `openai/gpt-oss-20b`, then `qwen/qwen3.8-27b` when a model is rate-limited). The fallback applies to both arms at the same moment; every hint records which model wrote it, and the report shows the model mix per arm. Only the help policy differs.
  - **Tutor arm:** a ladder about the learner's own latest attempt: L1 symptom (a question about what is wrong with their result, naming no SQL feature), L2 concept (explains the idea, in words), L3 skeleton (a sentence plus the solution's outline with `___` blanks, made by code), L4 the exact fix (a fragment, never the full query). The level is set by rules (`policy.py`) from how close the latest run is, as measured by the grader:
    - SQL error: explain the error (does not climb the ladder: the next normal hint is still the next rung);
    - **close** (right rows, only the columns or the order wrong; a wrong column count counts only when the row count is right): straight to L4;
    - **a few rows wrong** (at most max(2, 20% of expected rows)): up two levels, since this is often the concept itself (e.g. inner vs left join);
    - **far**: one step up the ladder per new attempt.
    - Last resort: after L4 and 2 more failed runs, the learner may choose "Show solution". A question solved after that **does not count as solved** in practice completion; reveals are reported per learner.
    - The tutor never gives the full query otherwise; a deterministic guard checks every hint exactly as shown (at L3, the sentence plus the skeleton). Each help request waits at most 20 s for the LLM, then uses the built-in hint.
  - **Baseline arm:** the full correct query and a short explanation, every time. It is correct by construction, and the learner gets it through the same button.
- **Sessions:**
  - Pretest: 6 questions, **15 minutes**, unaided. Learners have not been taught joins, so low scores are expected and they are told so.
  - Practice: 8 questions, **45 minutes**, in the assigned arm.
  - Removal test: 8 held-out questions, **30 minutes**, at least 2 days after practice. Unaided, supervised, phones away.
  - The time limits are enforced by the server: the clock starts when the invigilator starts the phase. In the tests, whatever is in each editor is submitted automatically at 0, and anything still unsubmitted is recorded as blank. Practice stops at 0.
  - Nothing else is given in any phase: no query template and no cheat sheet.
- The two arms sit apart, in separate rows with screens facing away, and are asked not to look at or discuss each other's screens.

## Skills (each set covers all six)
- S1 INNER JOIN
- S2 LEFT JOIN keeping unmatched rows
- S3 anti-join
- S4 aggregate across a join (fan-out)
- S5 date range combined with a join
- S6 three or more tables

Held-out items are labelled near or far transfer in `question_bank.py`. H1–H6 are the skill-matched set; H7 and H8 (far) are reported separately.

## Scoring (deterministic)
- Correct = the result set equals the frozen expected set.
  - Columns are compared by position; names are ignored.
  - Values are normalised: numbers to 2 decimal places, numeric-looking text as numbers, dates in ISO format.
  - Rows are compared as a multiset unless the question requires an order.
- In the test phases, only the submitted query counts. A blank answer counts as wrong.
- A database outage is never scored: the server returns 503 and records nothing.

## Secondary metrics
- Held-out score out of 8
- Far-transfer score out of 2
- Practice questions solved out of 8
- Practice questions attempted
- Questions solved before any help
- Help requests (gates and repeats counted separately)
- Maximum and mean hint level
- Share of LLM fallbacks per arm
- Guard blocks
- Median seconds per held-out question (wall clock from first opening the question to submitting it)
- Tab-switch events during test phases (also logged in practice, reported separately)
- The return item, 1–5: "How likely are you to open this tomorrow?"

## Reporting rules
- Report every learner's raw numbers, including null or negative results.
- No significance tests at this sample size.
- A dropout after assignment is reported as a dropout. The learner is not replaced, and the metrics show n for each arm.
- If more than 20% of an arm's help replies are fallbacks (LLM down or rate-limited), report it as a deviation.
- Self-report, collected on paper before the removal test: "Since practice, did you practise joins, use ChatGPT for SQL, or discuss the practice questions?" Reported per learner.

## Known limitations (stated in advance)
- n is small (6 to 10), so only a large effect is detectable.
- A 2-day gap measures short-term retention, not the 6-week case in the brief.
- Learners are classmates and may talk between sessions.
- The baseline is an idealised answer button with no follow-up dialogue.

## Deviations
1. **Learner 1 ran before the `prereg` tag (10 Nov).** Learner 1 (tutor arm, unpaired solo arrival) took the pretest and practice on 10 Nov before this file was tagged. The questions, the decision rules and `analyze.py`'s scoring were the same as in the tagged commit.
2. **Error hints changed after learner 1 (10 Nov).**
   - What changed:
     - an error explanation may be up to 900 characters (was 650), may fix only the part of the query the error points at, and never the whole query;
     - the built-in fallback now explains the specific PostgreSQL error (misspelt name, GROUP BY, missing FROM entry, quotes, ...) instead of giving a generic text;
     - a query timeout (usually a missing join condition) is treated as a wrong attempt that climbs the ladder, not as an SQL error;
     - the reason for every rejected LLM reply is logged;
     - tab switches are also logged in practice.
   - Why: in learner 1's practice, 4 of 13 tutor hints (31%) were fallbacks, all of them error explanations, which is above the 20% limit. One error hint for a timeout gave the full `JOIN … ON` structure at L1.
   - Learner 1 got the earlier version. Their partner and every later learner get this one. This is reported next to learner 1's numbers.
3. **Tutor v2 and two rounds (decided 11 Nov, before any removal test).**
   - **Evidence:** round 1 (10 Nov, tutor v1), analysed in `docs/llm-analysis-round1.md`.
     - About half of all tutor help (17 of 35) was SQL-error explanations, and half of the AI-written ones solved more than the error. For example, one gave `HAVING COUNT(…) = 0` on T3.
     - The v1 rules rejected accurate L1 diagnoses, and the fallbacks that replaced them were generic or wrong.
     - Learner feedback said the same: "gives part of the code directly" and "can't locate my problem".
   - **What changed (tutor arm only; the baseline is unchanged):**
     - a hint may use anything in the learner's own query or the error message, but may not introduce a new SQL feature or new code before L2;
     - error explanations may show at most a one- or two-line fix in the learner's own SQL;
     - the tutor is shown example rows that are missing, extra or duplicated in the learner's result;
     - the built-in L1 says what is wrong with the result;
     - Get help is locked until a new run, in both arms, so there are no repeat replies;
     - Assign now takes only learners who have finished the pretest.
   - **Analysis:**
     - Pairs whose tutor learner practised from 11 Nov on (`V2_FROM` in `analyze.py`) form **round 2: tutor v2 vs baseline. This is the primary pre-registered decision.**
     - Round 1 (tutor v1) and all rounds pooled are reported separately, with the same rule.
     - Nobody had taken the removal test when this was decided.
4. **Session incidents, 10 Nov.**
   - One learner joined 7 min late, and his practice clock was restarted by the invigilator, giving 45 min of actual practice.
   - One learner (baseline, pair 4) lost his connection after the pretest. He does practice on 11 Nov and the removal test on 13 Nov.
   - Five people created in advance did not show up. They were excluded, then deleted, never having started.
5. **One round 2 tutor learner excluded after assignment (11 Nov).** He used an outside AI during practice: he solved 8/8 with no hints after scoring 0/6 on the pretest, with 14 tab switches. His data is reported, not analysed. His partner stays in the baseline mean, and the pair does not count toward the pair rule.
6. **Every session was remote and unsupervised (10–13 Nov).** Learners were on holiday in different cities, so the pretest, practice and removal test were all taken from home, not in one room. The "sit apart" and "phones away" rules could not be enforced.
   - Mitigations: tab switches are logged in every phase; every learner fills in a self-report (WhatsApp) before the removal test; and the rules are stated in writing ("only this tab, no AI, no notes").
   - **Rule fixed before any removal-test score was seen (13 Nov, 13:50 IST):**
     - A learner who reports outside help during the removal test is analysed in a separate sensitivity block, not the primary one. So is a learner with **more than 3 tab-hidden events during the removal test**.
     - The primary result is reported both with and without them.
   - The self-report answers (practice since, AI use) are reported per learner.
7. **Four learners took the removal test on 14 Nov, 3-4 days after practice instead of 2.** Three were tutor learners from round 1 and one was a baseline learner. They were unavailable on 13 Nov. A longer gap means more forgetting, which works slightly against the tutor arm. They are analysed as pre-registered, with no adjustment.

