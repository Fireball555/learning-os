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

## After the pilot (10 Nov)
_Fill in: pilot pretest score, practice solved, hint levels used, confusing questions, and what we changed._

## After the removal test (13 Nov) → v2
_Fill in: the result under the pre-registered rule, then v2 of the hypothesis and the specific evidence (per-learner numbers, hint logs, observations) behind every word that changed._
