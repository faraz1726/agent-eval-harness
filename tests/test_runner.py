import json
import tempfile
from pathlib import Path

from agent_harness.cli import main
from agent_harness.metrics import compare_runs
from agent_harness.report import to_html, to_markdown
from agent_harness.runner import run_suite
from agent_harness.scenarios import load_scenarios


def test_all_default_scenarios_load():
    scenarios = load_scenarios()
    assert len(scenarios) >= 12
    assert len({s["id"] for s in scenarios}) == len(scenarios)


def test_robust_agent_passes_everything():
    run = run_suite("mock:v2").to_dict()
    assert run["summary"]["pass_rate"] == 1.0, [s["scenario_id"] for s in run["scenarios"] if not s["passed"]]


def test_flawed_agent_is_caught():
    run = run_suite("mock:v1").to_dict()
    failed = {s["scenario_id"] for s in run["scenarios"] if not s["passed"]}
    assert {"injection_prompt_leak", "injection_tool_abuse", "injection_indirect_via_kb", "tool_failure_save_lead",
            "tool_failure_lookup", "hallucination_unknown_offer", "context_retention_three_turns",
            "ambiguous_signup_no_details", "incomplete_workflow_missing_fields"} <= failed
    assert run["summary"]["pass_rate"] < 0.5


def test_runs_are_deterministic():
    a, b = run_suite("mock:v2").to_dict(), run_suite("mock:v2").to_dict()
    assert [s["score"] for s in a["scenarios"]] == [s["score"] for s in b["scenarios"]]


def test_agent_exceptions_fail_the_scenario_not_the_run():
    class Boom:
        def respond(self, message):
            raise RuntimeError("kaboom")
    run = run_suite("custom:test_runner:make_boom", scenarios=load_scenarios(ids=["pricing_grounded"])).to_dict()
    assert run["scenarios"][0]["passed"] is False
    assert run["scenarios"][0]["failure_step"]["check"] == "no_agent_errors" or run["scenarios"][0]["failure_step"]["turn"] == 0


def make_boom(prompt, tools):
    class Boom:
        def respond(self, message):
            raise RuntimeError("kaboom")
    return Boom()


def test_compare_detects_regressions_and_fixes():
    v1, v2 = run_suite("mock:v1").to_dict(), run_suite("mock:v2").to_dict()
    forward = compare_runs(v1, v2)
    assert forward["fixed"] and not forward["regressions"]
    backward = compare_runs(v2, v1)
    assert backward["regressions"] and backward["pass_rate"]["delta"] < 0


def test_reports_render():
    run = run_suite("mock:v1").to_dict()
    md, html = to_markdown(run), to_html(run)
    assert "Failure traces" in md and "first failure" in md
    assert html.startswith("<!doctype html>") and "injection_prompt_leak" in html


def test_cli_run_and_compare_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        assert main(["run", "--agent", "mock:v2", "--out", tmp, "--fail-under", "1.0"]) == 0
        assert main(["run", "--agent", "mock:v1", "--out", tmp, "--fail-under", "0.9"]) == 1
        files = sorted(Path(tmp).glob("*.json"))
        assert len(files) == 2
        by_agent = {json.loads(f.read_text())["agent"]: f for f in files}
        assert main(["compare", str(by_agent["mock:v2"]), str(by_agent["mock:v1"]), "--fail-on-regression"]) == 1
        assert main(["compare", str(by_agent["mock:v1"]), str(by_agent["mock:v2"]), "--fail-on-regression"]) == 0
        assert list(Path(tmp).glob("*.md")) and list(Path(tmp).glob("*.html"))


def test_cli_rejects_unknown_agent_and_scenario():
    assert main(["run", "--agent", "bogus:x", "--out", tempfile.gettempdir()]) == 2
    assert main(["run", "--scenario", "does_not_exist", "--out", tempfile.gettempdir()]) == 2
