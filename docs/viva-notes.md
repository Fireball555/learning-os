# Viva notes: answers to the brief's questions

**What must the system learn, decide or demonstrate?**
- **Decide:** for each help request, how much to reveal, from evidence of what this learner has done unaided on this skill. That is a rule in `policy.py`, not an LLM.
- **Demonstrate:** with the assistant removed, on unseen questions, these learners score higher than learners who were given answers.

**What counts as "writing this query unaided", precisely enough for a script?**
A query submitted in a test phase, in which the server has no help endpoint at all. It is correct when its result set equals the frozen expected result set:
- columns are compared by position;
- values are normalised;
- rows are compared as a multiset, unless the question requires an order.

No LLM is involved in grading.

**Smallest change to what the system says that would flip the result?**
Showing the complete query. The leak guard exists exactly for this, because a full answer in any part of a tutor reply makes it the baseline arm. The L3 skeleton is the closest the tutor gets to that line.

**How often can you afford the real test, and what do you steer by between runs?**
Once (n = 6, 2 days apart). In between, we steer by proxies:
- hint level reached;
- questions solved before any help;
- attempts per question;
- guard blocks;
- pilot observations.

These are proxies, and they are reported as such.

**Which part of writing a query should the system make harder on purpose, and which should it hand over?**
- **Harder:** choosing the tables and join, and the trap (LEFT vs INNER, fan-out, anti-join). That is the skill being tested.
- **Handed over completely:** the schema (always visible, with a join map), exact error messages, and the row and column feedback in practice. Syntax trivia is not the skill.

**The learner wants the answer at 11 pm. Who decides?**
- **In this study:** the pre-registered policy decides, and the learner was told so.
- **As a product:** I'd let the learner override after a visible attempt, and log it. The removal result tells you what that override costs.

**The removal test shows no difference. What do you check first?**
1. **Exposure:** did both arms attempt the same practice questions?
2. **Leakage:** guard blocks, fallback share, and whether arms saw each other's screens.
3. **Floor and ceiling:** were the pretest and held-out sets too hard or too easy for everyone?
4. **Fidelity:** did the tutor arm actually get the ladder, or mostly fallbacks?

Only after that would I conclude "no effect".

**Retention improves and completion drops. Which do you optimise?**
Retention, within the pre-registered collapse bound (≥ 0.75 × baseline completion). Beyond that bound, people won't open the tool tomorrow, and the return item (1–5) is measured to watch exactly that.

**What evidence would convince you that withholding is the wrong mechanism?**
Any of these:
- the tutor arm loses on held-out gain under the pre-registered rule;
- the tutor arm wins but completion collapses and the return score drops;
- tutor learners who reached L3/L4 gain no more than those who were given answers.

**Why is the baseline correct by construction?**
So the arms differ only in what the button returns. An ordinary chatbot that is sometimes wrong would weaken the baseline and flatter the tutor.

**Limitations (stated before the data):**
- n = 6;
- a 2-day gap, not 6 weeks;
- the learners are fellow students who may talk;
- one dataset and one schema.
