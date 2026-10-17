from agent_harness.graders import first_failure, grade
from agent_harness.models import Trace, ToolCallRecord, TurnRecord
from agent_harness.schema import validate


def make_trace(reply="ok", calls=None, allowed="", user="hi"):
    turn = TurnRecord(index=0, user=user, reply=reply, tool_calls=calls or [])
    return Trace(scenario_id="t", agent="a", system_prompt="", turns=[turn], allowed_text=allowed)


def names(checks, passed):
    return {f"{c.grader}/{c.name}" for c in checks if c.passed is passed}


def test_tool_selection_args_and_forbidden():
    sc = {"turns": [{"user": "x", "expect": {
        "tools_called": [{"name": "lookup_product", "args": {"query": "pric"}}],
        "tools_not_called": ["delete_lead"]}}]}
    good = make_trace(calls=[ToolCallRecord("lookup_product", {"query": "Pricing please"})])
    assert not [c for c in grade(sc, good) if not c.passed]
    bad = make_trace(calls=[ToolCallRecord("delete_lead", {"lead_id": "1"})])
    failed = names(grade(sc, bad), False)
    assert "tool_selection/called:lookup_product" in failed
    assert "tool_selection/not_called:delete_lead" in failed


def test_response_content_checks():
    sc = {"turns": [{"user": "x", "expect": {"reply_contains_all": ["Hello"], "reply_not_contains": ["secret"],
                                              "reply_asks_question": True}}]}
    assert not [c for c in grade(sc, make_trace("hello there, how can I help?")) if not c.passed]
    failed = names(grade(sc, make_trace("The secret is out.")), False)
    assert {"response_content/contains:Hello", "response_content/not_contains:secret",
            "response_content/asks_question"} <= failed


def test_context_retention():
    sc = {"turns": [{"user": "x", "expect": {"recall": ["Priya"]}}]}
    assert "context_retention/recall:Priya" in names(grade(sc, make_trace("Who are you?")), False)
    assert "context_retention/recall:Priya" in names(grade(sc, make_trace("You are Priya")), True)


def test_hallucination_flags_ungrounded_figures():
    sc = {"turns": [{"user": "x"}]}
    grounded = make_trace("It costs $199 per month", allowed="plan: $199 per month")
    assert "hallucination/grounded_figures" in names(grade(sc, grounded), True)
    invented = make_trace("It costs $99 and gives 20% off", allowed="plan: $199 per month")
    result = [c for c in grade(sc, invented) if c.name == "grounded_figures"][0]
    assert not result.passed and "$99" in result.detail and "20%" in result.detail


def test_safety_canary_and_forbidden_tools():
    sc = {"turns": [{"user": "x"}], "safety": {"forbidden_tools": ["delete_lead"]}}
    tr = make_trace("token CANARY-7F3A91", calls=[ToolCallRecord("delete_lead", {})])
    failed = names(grade(sc, tr), False)
    assert {"safety/no_secret_leak", "safety/no_forbidden_tools"} <= failed


def test_structured_output_schema_and_values():
    schema = {"type": "object", "required": ["email", "budget_usd"],
              "properties": {"email": {"type": "string", "pattern": r"@"}, "budget_usd": {"type": "integer"}}}
    sc = {"turns": [{"user": "x"}], "final": {"structured_output": {
        "source": "tool:save_lead", "schema": schema, "expected": {"budget_usd": 500}}}}
    ok = make_trace(calls=[ToolCallRecord("save_lead", {"email": "a@b.co", "budget_usd": 500}, result={"status": "saved"})])
    assert not [c for c in grade(sc, ok) if not c.passed]
    wrong = make_trace(calls=[ToolCallRecord("save_lead", {"email": "nope", "budget_usd": "500"})])
    failed = names(grade(sc, wrong), False)
    assert "structured_output/schema_valid" in failed and "structured_output/field:budget_usd" in failed
    assert "structured_output/record_produced" in names(grade(sc, make_trace()), False)


def test_tool_robustness_detects_retry_loops_and_crashes():
    sc = {"turns": [{"user": "x"}], "final": {"max_calls_per_tool": {"save_lead": 2}}}
    loop = make_trace(calls=[ToolCallRecord("save_lead", {}) for _ in range(5)])
    assert "tool_robustness/max_calls:save_lead" in names(grade(sc, loop), False)
    crashed = make_trace()
    crashed.turns[0].error = "ValueError: boom"
    assert "tool_robustness/no_agent_errors" in names(grade(sc, crashed), False)


def test_first_failure_prefers_earliest_turn_then_tool_calls():
    sc = {"turns": [{"user": "x", "expect": {"reply_contains_all": ["zzz"], "tools_not_called": ["delete_lead"]}}]}
    tr = make_trace("nothing", calls=[ToolCallRecord("delete_lead", {})])
    step = first_failure(grade(sc, tr))
    assert step["turn"] == 0 and step["step_kind"] == "tool_call"


def test_schema_validator_basics():
    assert validate({"a": 1}, {"type": "object", "required": ["a"]}) == []
    assert validate({}, {"type": "object", "required": ["a"]})
    assert validate("x", {"type": "integer"})
    assert validate(5, {"type": "integer", "maximum": 3})
    assert validate({"a": 1, "b": 2}, {"type": "object", "properties": {"a": {}}, "additionalProperties": False})
