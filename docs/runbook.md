# Session runbook

## Before 11 Nov
- [ ] The GitHub repo is **private**: it contains the held-out answers.
- [ ] The Supabase project is not paused. Open its dashboard once.
- [ ] Deploy. Check that `/api/health` shows `"llm": true`.
- [ ] **Groq limits:** in the Groq console, check the **tokens per day and tokens per minute** for the models in the chain (gpt-oss-120b first), not the request count.
  - One help call is about 0.6–0.9k tokens. One session can use 100–150k tokens.
  - If your free tier allows fewer, use a paid/dev key.
  - During the session, the admin console shows "fallback" counts per arm. Over 20% means the LLM is being rate-limited.
- [ ] Before each session: `python scripts/check_models.py`. At least the first model should say OK.
- [ ] **Supabase query log:** check that the learner role can't read the query log, which holds the held-out reference queries.
  1. In the SQL editor, run `SET ROLE learner_ro; SELECT query FROM extensions.pg_stat_statements LIMIT 1; RESET ROLE;`
  2. If that returns a row, run `SELECT extensions.pg_stat_statements_reset();` as postgres after every `reset_db.sh`, and before the pretest.
- [ ] In `/admin`, **Add learners**. The Pilot box resets after every Create, so check it each time:
  - the 6 real names, with Pilot unticked;
  - your 7th person, with Pilot ticked;
  - a throwaway called "TEST", with Pilot ticked.
  - Print the codes on slips.
- [ ] **Pilot run, with your 7th person:**
  1. Select them and press **pretest** (starts the 15-min clock). They do all 6 questions.
  2. Click "tutor" in their Arm column, then move them to `practice`.
  3. Use Get help several times.
  4. Move them to `done`. **Do not show the pilot the held-out set.**
  5. Ask the pilot not to talk about the questions with anyone until 14 Nov. They are a classmate of the learners.
- [ ] **Check the held-out flow yourself** with the TEST learner: move it to `heldout` and submit a couple of answers.
- [ ] Download an export and run `python scripts/analyze.py export.json --include-pilots --out /tmp/dry` (dry run on pilot/TEST data). It should print tables.
- [ ] Write down from the pilot: any confusing question, how long each phase took, and any hint that gave too much away. Fix these **now**, before the tag (`bash scripts/reset_db.sh`, then redeploy).
- [ ] Pre-register:
  1. `git tag prereg && git push --tags`
  2. `git rev-parse prereg`
  3. `sha256sum backend/app/questions.json docs/preregistration.md scripts/analyze.py`
  4. Email the output to 100x or a mentor.
- [ ] Confirm both dates with all 6 learners: **11 Nov** and **13 Nov**.

## If learners can't all come at once
- Run them **in pairs** where possible: two people do pretest + practice in one sitting, then press **Assign** (they are paired and coin-flipped).
- A person who comes **alone**: Assign gives a coin flip; the **next** solo person automatically gets the other arm and becomes their pair.
- Each person's final test is **at least 2 days after their own practice**. The last practice must be by **12 Nov**.
- Tell everyone: "Please don't discuss the questions with anyone until 14 Nov." Staggered sessions make leaks more likely, so ask the self-report question before every final test.

## Session 1: Pretest + Practice (about 65 min)
1. Open the site 5 minutes early to wake the server.
2. Seat people so you can split them into two groups later. Hand out the slips.
3. Learners log in and see "Please wait". Say, then select all and press **pretest**, which starts the 15-minute clock:
   *"These questions cover joins, which you haven't learned yet. Nobody is expected to solve them. They show where you're starting from. Blanks are fine. No internet, no phones. Next you'll practise with help."*
   At 0, whatever is in each editor is submitted automatically.
4. When every learner shows **6 submitted**, click **Assign arms** and photograph the message, which shows the pairs and coin flips.
   - Anyone who doesn't show up: click **exclude** first.
   - Anyone whose screen is stuck: wait until 2 minutes after time-up and press **Assign** again. Their unsubmitted answers are then recorded as blank.
5. **Seat the tutor arm and the baseline arm apart**, in separate rows or opposite sides, with screens facing away. Say: "Please don't look at or talk about each other's screens."
6. Select all learners and move them to `practice`. Say: "Use the Get help button whenever you want. If you're stuck for about 5 minutes, move on."
   - Don't say which arm anyone is in.
   - Don't explain the hints.
7. Practice stops by itself at 45 minutes, and everyone answers the 1–5 question. Then move everyone to `break`.
8. Download the export as a backup.
9. Say: "Please don't practise SQL joins or discuss today's questions before Thursday."
10. Everyone clicks **Log out**.

## Session 2: Removal test (about 30 min, ≥ 2 days after that person's practice)
1. Wake the server 5 minutes early.
2. Hand out a paper slip with 3 yes/no questions. Since Tuesday, did you:
   - practise joins?
   - use ChatGPT for SQL?
   - discuss the practice questions?
   - Collect the slips.
3. Learners log in with their slips. Check that each name in the header is right.
4. Move everyone to `heldout` (this starts the 30-minute clock). Phones away. You invigilate. At 0, answers are submitted automatically.
5. When everyone shows **8 submitted**, move them to `done`.
6. Download the export, then run `python scripts/analyze.py export.json --out results/`.
7. Make the repo public.

## If something breaks
- **"Can't reach the server" or "Couldn't reach the database"** on a learner screen: nothing was recorded, so they just try again. Their typing is saved in the browser.
- **The server is down for more than 2 minutes:** pause the clock and note the time. Report it under Deviations.
- **A learner closed the tab:** they log in again with the slip. Their answers so far are kept.

## Don'ts
- Don't run `reset_db.sh --wipe-app` or `ALLOW_WIPE=1 pytest` against the live database once the pretest has started.
- Don't push to GitHub during a session. Auto-deploy is off, but don't redeploy either.
- Don't edit questions after the tag without recording the change under Deviations.
- Don't help any learner with the SQL itself. The only allowed answers are "it's in the schema panel" and "re-read the question".
