"""Evaluate any agent that is reachable over HTTP.

Request  (POST, JSON): {"session_id": str, "message": str, "system_prompt": str}
Response (JSON):       {"reply": str, "tool_calls": [{"name": str, "args": {}, "result": any, "error": str|null}]}
"""
from __future__ import annotations

import json
import urllib.request
import uuid

from . import AgentReply


class HTTPAgent:
    def __init__(self, system_prompt: str, tools, url: str, timeout: float = 60.0):
        self.system_prompt = system_prompt
        self.url = url
        self.timeout = timeout
        self.session_id = uuid.uuid4().hex

    def respond(self, user_message: str) -> AgentReply:
        body = json.dumps({"session_id": self.session_id, "message": user_message,
                           "system_prompt": self.system_prompt}).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST",
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return AgentReply(text=data.get("reply", ""), tool_calls=data.get("tool_calls", []))
