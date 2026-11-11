# Hypothesis log

The brief scores "Learning: evidence changed your hypothesis, and you show where." Each entry below says what changed, the evidence that caused it, and the date. v1 is never edited.

## v1 (28 Oct, pre-registered)
For learners who already know single-table SQL, an assistant that caps how much it reveals, based on what the learner has already shown they can do unaided, will produce higher scores on held-out multi-table questions taken later without any assistant than an assistant that gives the full query on request. Practice completion stays comparable.

## Design changes before any learner data (evidence: our own review, not results)
| Date | Change | Evidence that caused it |
|---|---|---|
| 9 Nov | "What they can do unaided" now updates during practice (pretest OR an earlier practice question of the same skill solved with ≤ L1 help), not just from the pretest. | Learners haven't been taught joins, so the pretest will be at the floor. With pretest-only mastery the calibration would never fire, and we would be testing "hints vs answers", not calibration. |
| 9 Nov | Decision rule tightened: a gain difference of at least 1 question **and** ≥ 2/3 pairs. Collapse = < 0.75 × baseline completion. | With n = 3 per arm, "tutor mean > baseline mean" can be tipped by a third of a question. |
| 9 Nov | Primary metric = skill-matched gain (H1–H6 vs P1–P6). | The held-out set doubles two skills; the raw 8-vs-6 gain would bias toward those skills. |
| 10 Nov | Hard timers (15/45/30 min) and auto-submit; no template or cheat sheet in any phase. | Equal exposure across arms; "unaided" means nothing at all. |
| 10 Nov | Help policy v2: the level follows how close the latest attempt is (grader-measured: error / far / close), every hint diagnoses the learner's own query, and "Show solution" is offered as a last resort after L4 + 2 failed runs (revealed = not solved). | Live try-out: a query one fix from correct (`DISTINCT(a, b)` returning 1 column) got generic plan hints for 6 requests, because levels only rose with the number of requests and only L4 looked at the attempt. A learner who is close was being held back, and one who is stuck had no way out. |
| 10 Nov | Every first hint is L1, and each level has strict written rules plus a deterministic shape check (length, no lists or headings, code limits, no snake_case schema names at L1); a reply that breaks them is retried once, then replaced by the built-in hint. | Live try-out: the first hint on T5 (labelled help 1, actually L2) was an 800-character plan listing every table, the join, all filters and the aggregation, effectively the answer in words. |
| 10 Nov | Review round 4 fixes: a wrong column count is "close" only with the right row count; an error explanation no longer uses up L1; the leak guard checks the L3 sentence together with the skeleton; L1 checks match SQL keywords, not English words ("not included", "behaving"); the T8 skeleton keeps its join chain; each help request waits at most 20 s. | Independent review: `SELECT *` jumped straight to L4 and "Show solution" within 3 runs; an L3 sentence could fill every blank and pass; ordinary English L1 hints were rejected, which would have pushed the tutor arm's fallback share up. |

## After the pilot / learner 1 (10 Nov)
- **Learner 1** (real learner, tutor arm):
  - Pretest: 0/6. She struggled with single-table syntax too (no FROM, double quotes for text). She found the pretest "a little frightening".
  - Practice: solved 5/8 in 45 min, with 13 hints (L1–L2 only, no reveal). She said she would have finished the other 3 with more time. Return item 3/5.
- **Evidence → change:**
  - 31% of her hints were fallbacks, all error explanations, over the 20% limit. → Error hints were changed (Deviation 2).
  - A timeout hint gave L4-level join structure at L1. → Timeouts now climb the ladder.
- **Open question:** she wrote `LEFT JOIN … IS NULL` (T3) and `NOT IN (subquery)` (T8) without any hint teaching them. Did she get outside help, or did she already know them? → Tab switches are now logged in practice.
- **Kept as is:** practice stays at 45 min, so that every learner, including her pair partner, has the same exposure.

## Round 1 (10 Nov evening, tutor v1): 9 real learners
- **Practice solved:**
  - tutor (4): 7, 6, 4, 5 out of 8;
  - baseline: 8 and 8 for the two who practised, one did 1 run, one never started, and one practises on 11 Nov.
- **Baseline:** one learner copy-pasted all 8 answers in 7 minutes. This is expected for that arm and is a limitation on time-on-task.
- **Feedback:**
  - "The AI tutor can't locate my problem."
  - "It gives part of the code directly."
  - One learner liked it and said he would have finished all 8 with more time.
  - Return item: 3–5 out of 5.
- **Evidence (`docs/llm-analysis-round1.md`):**
  - When the AI saw a real attempt, its diagnosis was right in 11 of 12 cases.
  - The leaks all came through SQL-error explanations, which made up half of all help.
  - Built-in fallbacks were the worst replies.
  - The ladder barely ran: no L3, and only one L4.
- **Change → tutor v2:** the rule "may use only what is in the learner's own query or the error" (Deviation 3). Round 2 (11 Nov) is the primary test.
- **What this means for the hypothesis:** "capping how much it reveals" only works if *every* channel is capped. Error help turned out to be the main channel, not a side channel.

## After the removal test (13 Nov) → v2
_Fill in: the result under the pre-registered rule, then v2 of the hypothesis and the specific evidence (per-learner numbers, hint logs, observations) behind every word that changed._
