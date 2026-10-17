import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from agent_harness.agents.anthropic_agent import AnthropicAgent
from agent_harness.runner import run_suite
from agent_harness.scenarios import load_scenarios
from agent_harness.service import DemoChat, HarnessService
from agent_harness.tools import ToolBox, ToolError
import tempfile


def test_toolbox_validation_and_fault_injection():
    tb = ToolBox()
    assert tb.call("lookup_product", {"query": "growth plan price"})["results"][0]["id"] == "prod-growth"
    for bad in ({"name": "A"}, {"name": "A", "company": "B", "email": "nope", "budget_usd": 1},
                {"name": "A", "company": "B", "email": "a@b.co", "budget_usd": "1"}):
        try:
            tb.call("save_lead", bad)
            raise AssertionError("expected ToolError")
        except ToolError:
            pass
    assert tb.call("save_lead", {"name": "A", "company": "B", "email": "a@b.co", "budget_usd": 1})["status"] == "saved"
    faulty = ToolBox(faults={"lookup_product": "timeout"})
    try:
        faulty.call("lookup_product", {"query": "x"})
        raise AssertionError("expected ToolError")
    except ToolError as exc:
        assert "timed out" in str(exc)


def test_tool_calls_are_recorded_even_on_error():
    tb = ToolBox()
    sink = []
    tb.sink = sink
    try:
        tb.call("delete_lead", {"lead_id": "nope"})
    except ToolError:
        pass
    assert sink[0].name == "delete_lead" and sink[0].error


def test_anthropic_agent_tool_loop_with_fake_api():
    tb = ToolBox()
    sink = []
    tb.sink = sink
    agent = AnthropicAgent("sys", tb, api_key="test")
    responses = iter([
        {"stop_reason": "tool_use", "content": [
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "id": "tu_1", "name": "lookup_product", "input": {"query": "growth plan"}}]},
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Growth is $199 per month."}]},
    ])
    payloads = []
    agent._post = lambda payload: (payloads.append(json.loads(json.dumps(payload))) or next(responses))
    assert agent.respond("How much is Growth?") == "Growth is $199 per month."
    assert [c.name for c in sink] == ["lookup_product"]
    assert payloads[0]["tools"][0]["name"] == "lookup_product"
    tool_result = payloads[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "$199" in tool_result["content"]


def test_anthropic_agent_reports_tool_errors_to_model():
    tb = ToolBox(faults={"lookup_product": "error"})
    agent = AnthropicAgent("sys", tb, api_key="test")
    responses = iter([
        {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "x", "name": "lookup_product", "input": {"query": "a"}}]},
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Sorry, I can't look that up right now."}]},
    ])
    seen = []
    agent._post = lambda p: (seen.append(json.loads(json.dumps(p))) or next(responses))
    agent.respond("price?")
    assert seen[1]["messages"][-1]["content"][0]["is_error"] is True


def test_http_adapter_end_to_end_against_local_server():
    chat = DemoChat()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            data = json.dumps(chat.chat(body["session_id"], body["message"], body.get("system_prompt"))).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/agent/chat"
        # faults can't be injected into a remote agent, so run the scenarios that don't need them
        ids = ["happy_path_qualification", "pricing_grounded", "context_retention_three_turns",
               "injection_prompt_leak", "incomplete_workflow_missing_fields"]
        run = run_suite(f"http:{url}", scenarios=load_scenarios(ids=ids)).to_dict()
        assert run["summary"]["pass_rate"] == 1.0, [s for s in run["scenarios"] if not s["passed"]]
    finally:
        server.shutdown()


def test_service_layer_runs_and_reports():
    with tempfile.TemporaryDirectory() as tmp:
        svc = HarnessService(tmp)
        assert len(svc.list_scenarios()) >= 12
        started = svc.start_run("mock:v2", category="prompt_injection")
        assert started["summary"]["pass_rate"] == 1.0
        assert svc.list_runs()[0]["run_id"] == started["run_id"]
        assert "Agent Evaluation Report" in svc.run_report(started["run_id"], "md")
        for bad in ("../etc/passwd", "missing"):
            try:
                svc.get_run(bad)
                raise AssertionError("expected KeyError")
            except KeyError:
                pass
