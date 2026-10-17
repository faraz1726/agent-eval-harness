"""Markdown / HTML / console reports and comparison rendering."""
from __future__ import annotations

import html

ICON = {True: "PASS", False: "FAIL"}


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _transcript(result: dict) -> list[str]:
    fail = result.get("failure_step") or {}
    lines = []
    for t in result["trace"]["turns"]:
        marker = "  <-- first failure" if fail.get("turn") == t["index"] else ""
        lines.append(f"[turn {t['index']}] USER : {t['user']}")
        for c in t["tool_calls"]:
            status = f"ERROR {c['error']}" if c.get("error") else f"-> {c['result']}"
            lines.append(f"           TOOL : {c['name']}({c['args']}) {status}")
        lines.append(f"           AGENT: {t['reply'] or '(no reply)'}{marker}")
        if t.get("error"):
            lines.append(f"           CRASH: {t['error']}")
    return lines


def to_markdown(run: dict) -> str:
    s = run["summary"]
    out = [f"# Agent Evaluation Report", "",
           f"- **Agent:** `{run['agent']}`", f"- **Run ID:** `{run['run_id']}`", f"- **Created:** {run['created_at']}",
           f"- **Scenarios:** {s['passed_scenarios']}/{s['total_scenarios']} passed ({_pct(s['pass_rate'])})",
           f"- **Mean score:** {s['mean_score']:.3f}  |  **Checks:** {s['checks_passed']}/{s['checks_total']}",
           f"- **Tool calls:** {s['tool_calls_total']} ({s['tool_errors_total']} errored)  |  "
           f"**Avg turn latency:** {s['avg_turn_latency_ms']} ms", "",
           "## By category", "", "| Category | Passed | Total | Pass rate |", "|---|---|---|---|"]
    for k, v in sorted(s["by_category"].items()):
        out.append(f"| {k} | {v['passed']} | {v['total']} | {_pct(v['pass_rate'])} |")
    out += ["", "## By grader", "", "| Grader | Checks passed | Total | Pass rate |", "|---|---|---|---|"]
    for k, v in sorted(s["by_grader"].items()):
        out.append(f"| {k} | {v['passed']} | {v['total']} | {_pct(v['pass_rate'])} |")
    out += ["", "## Scenarios", "", "| Scenario | Category | Result | Score | First failing step |", "|---|---|---|---|---|"]
    for r in run["scenarios"]:
        f = r.get("failure_step")
        step = "-" if not f else f"{f['step_kind']} (turn {f['turn'] if f['turn'] is not None else 'final'}): {f['grader']}/{f['check']}"
        out.append(f"| {r['scenario_id']} | {r['category']} | {ICON[r['passed']]} | {r['score']:.2f} | {step} |")
    failed = [r for r in run["scenarios"] if not r["passed"]]
    if failed:
        out += ["", "## Failure traces"]
        for r in failed:
            out += ["", f"### {r['scenario_id']}", "", r["description"], "", "Failed checks:", ""]
            for c in r["checks"]:
                if not c["passed"]:
                    where = "final" if c["turn"] is None else f"turn {c['turn']}"
                    out.append(f"- `{c['grader']}/{c['name']}` ({where}): {c['detail']}")
            out += ["", "```text", *_transcript(r), "```"]
    return "\n".join(out) + "\n"


def to_html(run: dict) -> str:
    s, e = run["summary"], html.escape
    rows = []
    for r in run["scenarios"]:
        f = r.get("failure_step")
        step = "-" if not f else e(f"{f['step_kind']} / turn {f['turn'] if f['turn'] is not None else 'final'} / {f['grader']}:{f['check']}")
        cls = "pass" if r["passed"] else "fail"
        rows.append(f"<tr><td>{e(r['scenario_id'])}</td><td>{e(r['category'])}</td>"
                    f"<td class='{cls}'>{ICON[r['passed']]}</td><td>{r['score']:.2f}</td><td>{step}</td></tr>")
    cats = "".join(f"<tr><td>{e(k)}</td><td>{v['passed']}/{v['total']}</td><td>{_pct(v['pass_rate'])}</td></tr>"
                   for k, v in sorted(s["by_category"].items()))
    graders = "".join(f"<tr><td>{e(k)}</td><td>{v['passed']}/{v['total']}</td><td>{_pct(v['pass_rate'])}</td></tr>"
                      for k, v in sorted(s["by_grader"].items()))
    traces = ""
    for r in run["scenarios"]:
        if r["passed"]:
            continue
        bad = "".join(f"<li><code>{e(c['grader'])}/{e(c['name'])}</code> "
                      f"({'final' if c['turn'] is None else 'turn ' + str(c['turn'])}): {e(c['detail'])}</li>"
                      for c in r["checks"] if not c["passed"])
        traces += (f"<details><summary>{e(r['scenario_id'])}</summary><p>{e(r['description'])}</p><ul>{bad}</ul>"
                   f"<pre>{e(chr(10).join(_transcript(r)))}</pre></details>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Agent Evaluation Report</title>
<style>body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}td,th{{border:1px solid #ddd;padding:6px 10px;text-align:left}}
th{{background:#f4f4f4}}.pass{{color:#0a7d33;font-weight:600}}.fail{{color:#b3261e;font-weight:600}}
pre{{background:#f7f7f7;padding:12px;overflow:auto;white-space:pre-wrap}}details{{margin:.6rem 0}}</style></head><body>
<h1>Agent Evaluation Report</h1>
<p><b>Agent:</b> <code>{e(run['agent'])}</code> &middot; <b>Run:</b> <code>{e(run['run_id'])}</code> &middot; {e(run['created_at'])}</p>
<p><b>{s['passed_scenarios']}/{s['total_scenarios']}</b> scenarios passed ({_pct(s['pass_rate'])}) &middot;
mean score {s['mean_score']:.3f} &middot; checks {s['checks_passed']}/{s['checks_total']} &middot;
{s['tool_calls_total']} tool calls ({s['tool_errors_total']} errored)</p>
<h2>By category</h2><table><tr><th>Category</th><th>Passed</th><th>Rate</th></tr>{cats}</table>
<h2>By grader</h2><table><tr><th>Grader</th><th>Checks</th><th>Rate</th></tr>{graders}</table>
<h2>Scenarios</h2><table><tr><th>Scenario</th><th>Category</th><th>Result</th><th>Score</th><th>First failing step</th></tr>{''.join(rows)}</table>
<h2>Failure traces</h2>{traces or '<p>No failures.</p>'}</body></html>"""


def console_summary(run: dict) -> str:
    s = run["summary"]
    lines = [f"Agent: {run['agent']}   Run: {run['run_id']}", ""]
    for r in run["scenarios"]:
        f = r.get("failure_step")
        extra = "" if not f else f"   <- {f['grader']}/{f['check']} @ {'turn ' + str(f['turn']) if f['turn'] is not None else 'final'}"
        lines.append(f"  [{ICON[r['passed']]}] {r['scenario_id']:<34} {r['score']:.2f}{extra}")
    lines += ["", f"Passed {s['passed_scenarios']}/{s['total_scenarios']} scenarios ({_pct(s['pass_rate'])}), "
                  f"mean score {s['mean_score']:.3f}, checks {s['checks_passed']}/{s['checks_total']}"]
    return "\n".join(lines)


def comparison_markdown(cmp: dict) -> str:
    pr, ms = cmp["pass_rate"], cmp["mean_score"]
    out = ["# Run comparison", "", f"- **Baseline:** `{cmp['baseline']}`", f"- **Candidate:** `{cmp['candidate']}`",
           f"- **Pass rate:** {_pct(pr['baseline'])} -> {_pct(pr['candidate'])} ({pr['delta'] * 100:+.1f} pts)",
           f"- **Mean score:** {ms['baseline']:.3f} -> {ms['candidate']:.3f} ({ms['delta']:+.3f})", ""]
    out.append(f"## Regressions ({len(cmp['regressions'])})")
    out += [f"- `{r['scenario_id']}`" + (f": {r['failure']['grader']}/{r['failure']['check']} - {r['failure']['detail']}" if r["failure"] else "")
            for r in cmp["regressions"]] or ["- none"]
    out += ["", f"## Fixed ({len(cmp['fixed'])})"] + ([f"- `{s}`" for s in cmp["fixed"]] or ["- none"])
    out += ["", f"## Still failing ({len(cmp['still_failing'])})"] + ([f"- `{s}`" for s in cmp["still_failing"]] or ["- none"])
    if cmp["only_in_baseline"] or cmp["only_in_candidate"]:
        out += ["", "## Scenario set differences", f"- only in baseline: {cmp['only_in_baseline'] or 'none'}",
                f"- only in candidate: {cmp['only_in_candidate'] or 'none'}"]
    return "\n".join(out) + "\n"
