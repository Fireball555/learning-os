"""Compute the pre-registered metrics from an export JSON (Admin console -> Download export).

Usage: python scripts/analyze.py export.json [--out results/]
Writes results.csv (one row per learner, anonymised) and results.md. Pilots are excluded;
excluded learners (no-show/dropout) are listed separately, never silently dropped.

PRIMARY (skill-matched, one item per skill on both sides):
  gain = (H1..H6 correct / 6) - (P1..P6 correct / 6), in percentage points.
  Decision rule (docs/preregistration.md): tutor mean gain - baseline mean gain >= 16.7 pts
  (one item) AND tutor gain > baseline gain in >= 2 of 3 pairs -> supported;
  the mirror image -> falsified; anything else -> inconclusive.
  Completion "collapses" if tutor mean practice solved < 0.75 x baseline mean.
SECONDARY: held-out /8, far-transfer items (H7, H8), practice solved /8, practice
  questions attempted, solved-before-any-help, help requests (real ones only), max/mean
  hint level, LLM fallback share, guard blocks, median seconds per held-out question,
  tab-switch events in test phases, return item (1-5).
No significance tests (n = 3 per arm).
"""
import argparse
import csv
import json
import re
import statistics as st
from datetime import datetime
from pathlib import Path

PRIMARY_PRE = [f"P{i}" for i in range(1, 7)]
PRIMARY_HELD = [f"H{i}" for i in range(1, 7)]
FAR = ["H7", "H8"]


def ts(s):
    return datetime.fromisoformat(s) if s else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def fmt(v):
    return "" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--out", default="results")
    ap.add_argument("--include-pilots", action="store_true", help="dry run on pilot/TEST data (never for the real report)")
    a = ap.parse_args()
    d = json.loads(Path(a.export).read_text())
    practice_ids = [q["id"] for q in d["questions"] if q["set"] == "practice"]
    real = [l for l in d["learners"] if a.include_pilots or not l["is_pilot"]]
    excluded = [l for l in real if l.get("excluded")]
    learners = [l for l in real if not l.get("excluded") and l["arm"]]

    rows = []
    for i, l in enumerate(sorted(learners, key=lambda x: (x["pair_no"] or 99, x["arm"])), start=1):
        lid = l["learner_id"]
        subs = {x["question_id"]: x for x in d["attempts"] if x["learner_id"] == lid and x["kind"] == "submit"}
        corr = lambda ids: sum(1 for q in ids if subs.get(q, {}).get("correct"))
        # A learner who took a test phase but left a question without a submit scores it as wrong
        # (pre-registered: blank = wrong). A learner with no submit at all in that phase never took it.
        has = lambda ids: any(q in subs for q in ids)
        pre_ok = has(PRIMARY_PRE)
        held_ok = has(PRIMARY_HELD)
        pre6, held6 = corr(PRIMARY_PRE), corr(PRIMARY_HELD)
        views = {v["question_id"]: v for v in d["views"] if v["learner_id"] == lid}
        runs = [x for x in d["attempts"] if x["learner_id"] == lid and x["kind"] == "run" and x["phase"] == "practice"]
        hints = [h for h in d["hints"] if h["learner_id"] == lid]
        # real help = a tutor ladder hint (1-4, error explanations included) or a baseline answer (9);
        # excludes gate (0), repeat (-1), solved (-2) and "Show solution" (8, counted as `revealed`)
        real_help = [h for h in hints if 1 <= h["level"] <= 4 or h["level"] == 9]
        levels = [h["level"] for h in real_help if h["level"] <= 4 and not h["source"].endswith("_error")]
        revealed = {h["question_id"]: h["created_at"] for h in hints if h["source"] == "reveal"}
        # pre-registered: a question solved only after "Show solution" does not count as solved
        solved = [q for q in practice_ids if views.get(q, {}).get("final_correct")
                  and not (q in revealed and ts(revealed[q]) <= ts(views[q]["finished_at"]))]
        first_help = {}
        for h in real_help + [h for h in hints if h["source"] == "reveal"]:
            if h["question_id"] not in first_help or ts(h["created_at"]) < ts(first_help[h["question_id"]]):
                first_help[h["question_id"]] = h["created_at"]
        solved_unaided = [q for q in solved
                          if q not in first_help or ts(views[q]["finished_at"]) < ts(first_help[q])]
        times = [(ts(views[q]["finished_at"]) - ts(views[q]["first_seen"])).total_seconds()
                 for q in PRIMARY_HELD + FAR
                 if q in views and views[q]["finished_at"] and q in subs and subs[q]["sql_text"].strip()
                 and not (subs[q].get("error") or "").endswith("(blank)")]   # real submits only
        hidden = [e for e in d["events"] if e["kind"] == "focus" and e["payload"].get("learner_id") == lid
                  and e["payload"].get("kind") == "hidden"]
        focus = sum(1 for e in hidden if e["payload"].get("phase") in ("pretest", "heldout"))
        focus_practice = sum(1 for e in hidden if e["payload"].get("phase") == "practice")
        surv = next((s["value"] for s in d["survey"] if s["learner_id"] == lid), None)
        llm_help = [h for h in real_help if h["source"].removesuffix("_error") in ("llm", "llm_retry", "fallback")]
        rows.append({
            "learner": f"L{i}", "arm": l["arm"], "pair": l["pair_no"],
            "pre_correct_6": pre6 if pre_ok else None,
            "held_correct_6": held6 if held_ok else None,
            "gain_pts": (100 * held6 / 6 - 100 * pre6 / 6) if (pre_ok and held_ok) else None,
            "held_correct_8": corr(PRIMARY_HELD + FAR) if held_ok else None,
            "far_correct_2": corr(FAR) if held_ok else None,
            "practice_solved_8": len(solved),
            "practice_attempted_8": len({x["question_id"] for x in runs}),
            "solved_before_help_8": len(solved_unaided),
            "help_requests": len(real_help),
            "revealed": len(revealed),
            "gates_repeats": len(hints) - len(real_help),
            "max_level": "full answer" if l["arm"] == "baseline" else (max(levels) if levels else 0),
            "mean_level": "full answer" if l["arm"] == "baseline" else (round(st.mean(levels), 2) if levels else 0),
            "fallback_share": round(sum(1 for h in llm_help if h["source"].removesuffix("_error") == "fallback") / len(llm_help), 2) if llm_help else None,
            "guard_blocks": sum(h["guard_blocked"] for h in hints),
            "median_sec_heldout_q": round(st.median(times)) if times else None,
            "tab_switches_tests": focus,
            "tab_switches_practice": focus_practice,
            "return_1to5": surv,
        })
    if not rows:
        raise SystemExit("no assigned, non-excluded, non-pilot learners in export")

    pairs = {}
    for r in rows:
        if r["pair"] is not None:
            pairs.setdefault(r["pair"], {})
            assert r["arm"] not in pairs[r["pair"]], f"pair {r['pair']} has two {r['arm']} learners"
            pairs[r["pair"]][r["arm"]] = r

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def arm_vals(arm, key):
        return [r[key] for r in rows if r["arm"] == arm and r[key] is not None]

    md = ["# Removal test results", "",
          ("DRY RUN INCLUDING PILOTS — not a result." if a.include_pilots else
           "Raw numbers per learner, pilot excluded, no significance claims (n = 3 per arm)."), "",
          "| " + " | ".join(rows[0].keys()) + " |", "|" + "---|" * len(rows[0])]
    md += ["| " + " | ".join(fmt(v) for v in r.values()) + " |" for r in rows]
    keys = ["pre_correct_6", "held_correct_6", "gain_pts", "held_correct_8", "far_correct_2",
            "practice_solved_8", "practice_attempted_8", "solved_before_help_8", "help_requests", "return_1to5"]
    md += ["", "| metric | tutor mean (n) | baseline mean (n) |", "|---|---|---|"]
    for k in keys:
        t, b = arm_vals("tutor", k), arm_vals("baseline", k)
        md.append(f"| {k} | {fmt(mean(t))} ({len(t)}) | {fmt(mean(b))} ({len(b)}) |")

    md += ["", "## Within-pair gain (tutor − baseline, points)"]
    wins = losses = complete = 0
    for p in sorted(pairs):
        t, b = pairs[p].get("tutor"), pairs[p].get("baseline")
        if t and b and t["gain_pts"] is not None and b["gain_pts"] is not None:
            diff = t["gain_pts"] - b["gain_pts"]
            complete += 1
            wins += diff > 0
            losses += diff < 0
            md.append(f"- pair {p}: {diff:+.1f}")
        else:
            md.append(f"- pair {p}: incomplete")

    tg, bg = mean(arm_vals("tutor", "gain_pts")), mean(arm_vals("baseline", "gain_pts"))
    ts_, bs = mean(arm_vals("tutor", "practice_solved_8")), mean(arm_vals("baseline", "practice_solved_8"))
    # pre-registered: at least two-thirds of the complete pairs (rounded up), and never fewer than 2
    need = max(2, -(-2 * complete // 3))
    verdict = "inconclusive"
    if tg is not None and bg is not None:
        if tg - bg >= 100 / 6 - 1e-9 and wins >= need:
            verdict = "SUPPORTED (pre-registered rule)"
        elif bg - tg >= 100 / 6 - 1e-9 and losses >= need:
            verdict = "FALSIFIED (pre-registered rule)"
    collapse = (ts_ is not None and bs and ts_ < 0.75 * bs)
    md += ["", "## Pre-registered decision",
           f"- mean gain: tutor {fmt(tg)} vs baseline {fmt(bg)} (difference {fmt(None if tg is None or bg is None else tg - bg)} pts; threshold 16.7)",
           f"- pairs favouring tutor: {wins}, favouring baseline: {losses} (of {complete} complete pairs; {need} needed)",
           f"- hypothesis on retention: **{verdict}**",
           f"- practice completion: tutor {fmt(ts_)} vs baseline {fmt(bs)} -> "
           f"{'**COLLAPSED** (< 0.75 x baseline)' if collapse else 'not collapsed'}"]
    md += ["", "## LLM fallback share per arm (pre-registered deviation if > 20%)"]
    for arm in ("tutor", "baseline"):
        # LLM-eligible replies only: ladder hints and baseline answers (not gates, repeats, reveals)
        hs = [h for h in d["hints"] if h["arm"] == arm and (1 <= h["level"] <= 4 or h["level"] == 9)
              and h["source"].removesuffix("_error") in ("llm", "llm_retry", "fallback")
              and any(l["learner_id"] == h["learner_id"] for l in learners)]
        fb = sum(1 for h in hs if h["source"].removesuffix("_error") == "fallback")
        share = fb / len(hs) if hs else 0
        md.append(f"- {arm}: {fb}/{len(hs)} = {share:.0%}" + ("  **DEVIATION: report it**" if share > 0.2 else ""))
        mix = {}
        for h in hs:
            mix[h.get("model") or "deterministic"] = mix.get(h.get("model") or "deterministic", 0) + 1
        md.append(f"  - models used ({arm}): " + ", ".join(f"{k} {v}" for k, v in sorted(mix.items(), key=lambda x: -x[1])))
    ids = {l["learner_id"] for l in learners}
    rej = [e["payload"] for e in d["events"] if e["kind"] == "hint_reject" and e["payload"].get("learner_id") in ids]
    if rej:
        md += ["", "## Why LLM replies were rejected (each was retried, then replaced by the built-in text)"]
        for arm in ("tutor", "baseline"):
            why = {}
            for r in rej:
                if r.get("arm") == arm:
                    k = re.sub(r"\d+", "N", str(r.get("why", "?")))[:80]
                    why[k] = why.get(k, 0) + 1
            if why:
                md.append(f"- {arm}: " + "; ".join(f"{k} x{v}" for k, v in sorted(why.items(), key=lambda x: -x[1])))
    if excluded:
        md += ["", f"Excluded learners (reported, not analysed): {len(excluded)}"]
    (out / "results.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
