"""Claude via the Anthropic Messages API, using only the standard library.

Set ANTHROPIC_API_KEY (and optionally ANTHROPIC_MODEL). The agent runs a tool-use
loop: tool calls go through the harness ToolBox, so they are recorded and can have
faults injected.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..tools import ToolBox, ToolError

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"


class AnthropicAgent:
    def __init__(self, system_prompt: str, tools: ToolBox, model: str | None = None,
                 api_key: str | None = None, max_iterations: int = 6, max_tokens: int = 1024):
        self.system_prompt = system_prompt
        self.tools = tools
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.messages: list[dict] = []

    def _post(self, payload: dict) -> dict:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        req = urllib.request.Request(
            API_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"content-type": "application/json", "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Anthropic API error {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc

    def respond(self, user_message: str) -> str:
        self.messages.append({"role": "user", "content": user_message})
        for _ in range(self.max_iterations):
            resp = self._post({
                "model": self.model, "max_tokens": self.max_tokens, "system": self.system_prompt,
                "tools": self.tools.anthropic_tools(), "messages": self.messages})
            content = resp.get("content", [])
            self.messages.append({"role": "assistant", "content": content})
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if not tool_uses or resp.get("stop_reason") != "tool_use":
                return "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            results = []
            for block in tool_uses:
                try:
                    out = self.tools.call(block["name"], block.get("input", {}))
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "content": json.dumps(out)})
                except ToolError as exc:
                    results.append({"type": "tool_result", "tool_use_id": block["id"],
                                    "content": str(exc), "is_error": True})
            self.messages.append({"role": "user", "content": results})
        return "(agent stopped: tool-iteration limit reached)"
