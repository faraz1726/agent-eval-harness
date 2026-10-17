"""Run-level metrics and run-to-run comparison."""
from __future__ import annotations

from collections import defaultdict

from .models import ScenarioResult


def _rate(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0.0


def summarize(results: list[ScenarioResult]) -> dict:
    total = len(results)
    passed = sum(r.passed for r in results)
    by_cat: dict = defaultdict(lambda: {"total": 0, "passed": 0})
    by_grader: dict = defaultdict(lambda: {"total": 0, "passed": 0})
    by_step: dict = defaultdict(int)
    by_check: dict = defaultdict(int)
    turn_latencies, tool_calls, tool_errors, checks_total, checks_passed = [], 0, 0, 0, 0
    for r in results:
        by_cat[r.category]["total"] += 1
        by_cat[r.category]["passed"] += r.passed
        for c in r.checks:
            by_grader[c.grader]["total"] += 1
            by_grader[c.grader]["passed"] += c.passed
            checks_total += 1
            checks_passed += c.passed
        if r.failure_step:
            by_step[r.failure_step["step_kind"]] += 1
            by_check[f"{r.failure_step['grader']}:{r.failure_step['check']}"] += 1
        for t in r.trace["turns"]:
            turn_latencies.append(t["latency_ms"])
            tool_calls += len(t["tool_calls"])
            tool_errors += sum(1 for c in t["tool_calls"] if c.get("error"))
    for d in (*by_cat.values(), *by_grader.values()):
        d["pass_rate"] = _rate(d["passed"], d["total"])
    return {
        "total_scenarios": total,
        "passed_scenarios": passed,
        "failed_scenarios": total - passed,
        "pass_rate": _rate(passed, total),
        "mean_score": round(sum(r.score for r in results) / total, 4) if total else 0.0,
        "checks_total": checks_total,
        "checks_passed": checks_passed,
        "by_category": dict(by_cat),
        "by_grader": dict(by_grader),
        "first_failure_by_step_kind": dict(by_step),
        "first_failure_by_check": dict(sorted(by_check.items(), key=lambda kv: -kv[1])),
        "avg_turn_latency_ms": round(sum(turn_latencies) / len(turn_latencies), 3) if turn_latencies else 0.0,
        "tool_calls_total": tool_calls,
        "tool_errors_total": tool_errors,
    }


def compare_runs(base: dict, cand: dict) -> dict:
    """Compare two run dicts (as saved by `agent-harness run`). `base` = baseline, `cand` = candidate."""
    b = {s["scenario_id"]: s for s in base["scenarios"]}
    c = {s["scenario_id"]: s for s in cand["scenarios"]}
    regressions, fixed, still_failing, score_changes = [], [], [], []
    for sid in sorted(set(b) & set(c)):
        bp, cp = b[sid]["passed"], c[sid]["passed"]
        if bp and not cp:
            regressions.append({"scenario_id": sid, "failure": c[sid]["failure_step"]})
        elif not bp and cp:
            fixed.append(sid)
        elif not bp and not cp:
            still_failing.append(sid)
        delta = round(c[sid]["score"] - b[sid]["score"], 4)
        if delta:
            score_changes.append({"scenario_id": sid, "delta": delta})
    bs, cs = base["summary"], cand["summary"]
    return {
        "baseline": base["agent"], "candidate": cand["agent"],
        "pass_rate": {"baseline": bs["pass_rate"], "candidate": cs["pass_rate"],
                      "delta": round(cs["pass_rate"] - bs["pass_rate"], 4)},
        "mean_score": {"baseline": bs["mean_score"], "candidate": cs["mean_score"],
                       "delta": round(cs["mean_score"] - bs["mean_score"], 4)},
        "regressions": regressions, "fixed": fixed, "still_failing": still_failing,
        "score_changes": score_changes,
        "only_in_baseline": sorted(set(b) - set(c)), "only_in_candidate": sorted(set(c) - set(b)),
    }
