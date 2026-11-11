# Evidence to capture (for the case study, the demo and the viva)

Blur learner names and faces unless that person has said yes in writing.

## Before the session (11 Nov morning)
- [ ] **Consent:** a one-line consent from every learner, on paper or a Google Form. For example: "I agree my anonymised SQL attempts and answers are used in a study report; I can withdraw any time."
  - Include the 10 Nov learners.
  - Photograph the sheet, or export the form.
- [ ] **Pre-registration proof:** a screenshot of the GitHub **Release `prereg`** page, with its date and the 3 hashes.
- [ ] **Deploy proof:** a screenshot of `/api/health` showing `"llm": true`, and of the Render deploy showing the v2 commit.
- [ ] **Probe output:** keep the `python scripts/probe_hints.py` output (text file). It gives the v2 before/after hint examples.

## During the session
- [ ] **Room photo:** the two arms seated apart (backs or screens, not faces).
- [ ] **Admin console screenshots:**
  - after Assign (pairs and coin flips);
  - mid-practice (stats line: help / fallback per arm);
  - at the end.
- [ ] **Learner screens** (ask one tutor and one baseline learner, or use a pilot code):
  - pretest with the timer;
  - tutor: L1 hint, L2 hint, "Run a new attempt to unlock more help", Show solution (if reached);
  - baseline: the full answer;
  - final test (13 Nov): the "not told whether correct" banner.
- [ ] **Notes:** who came late, lost their connection, or left, with times.
- [ ] **The export:** click **Download export** at the end of *each* session (10 Nov, 11 Nov, 13 Nov). Keep all the files, never edited.

## Right after practice (2 minutes per learner)
- [ ] **Feedback quotes**, written down word for word with the name and permission. For example, "The AI tutor is very bad. It is not able to locate my problem."
- [ ] The return item (1–5) is recorded in the app automatically.

## 13 Nov: final test
- [ ] A **paper self-report** from every learner, before the test: "Since practice, did you practise joins, use ChatGPT for SQL, or discuss the questions?" Photograph the sheets.
- [ ] Screenshot of the admin console during the held-out phase.
- [ ] The final export, then `python scripts/analyze.py export.json --out results/`. Commit `results/results.md` and `results.csv`.

## After the test (for the write-up)
- [ ] Chart: gain per learner, by arm and round (one dot per learner, pairs joined by a line).
- [ ] Before/after hint examples: a v1 leak (`HAVING COUNT(…) = 0`) next to the v2 reply to the same query.
- [ ] Architecture diagram (the README mermaid, exported as an image).
- [ ] Screenshot of `docs/hypothesis-log.md` showing v1 to v2 (the "evidence changed the hypothesis" criterion).
- [ ] Make the GitHub repo **public** once all final tests are done, so anyone can check the hashes.

## Demo video (3–5 min, record after 13 Nov)
1. The problem in one sentence: the ChatGPT tab beside you.
2. The tutor arm: a wrong query, then L1 locates the problem, then L2 explains the concept, then the learner fixes it.
3. The baseline arm: the same question, the full answer at once.
4. The invigilator console: timers, Assign, export.
5. The result slide: the number you got, whatever it is, plus one learner quote.
6. What changed between v1 and v2, and why (the error-channel finding).
