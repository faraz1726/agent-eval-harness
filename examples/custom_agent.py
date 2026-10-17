"""Template for plugging YOUR agent into the harness.

    PYTHONPATH=examples agent-harness run --agent custom:custom_agent:make_agent

A factory receives the scenario's system prompt and a ToolBox, and returns an object
with ``respond(user_message) -> str``. Call tools with ``toolbox.call(name, args)``:
calls are recorded for grading and honour fault injection (``ToolError`` on failure).
This toy agent only echoes, so most scenarios will (correctly) fail.
"""
from agent_harness.tools import ToolBox, ToolError


class EchoAgent:
    def __init__(self, system_prompt: str, toolbox: ToolBox):
        self.toolbox = toolbox

    def respond(self, user_message: str) -> str:
        if "?" in user_message:
            try:
                hits = self.toolbox.call("lookup_product", {"query": user_message})["results"]
                return hits[0]["text"] if hits else "I don't have that information."
            except ToolError:
                return "I'm unable to look that up right now."
        return "Thanks! Could you tell me more?"


def make_agent(system_prompt: str, toolbox: ToolBox) -> EchoAgent:
    return EchoAgent(system_prompt, toolbox)
