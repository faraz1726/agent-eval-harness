"""Framework-agnostic service layer used by the FastAPI server (and unit tests)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .agents.mock import LeadAgent
from .report import to_html, to_markdown
from .runner import build_system_prompt, run_suite
from .scenarios import load_scenarios
from .tools import ToolBox

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class DemoChat:
    """Hosts the built-in mock agents behind a session-based chat API, so the
    ``http:`` adapter can be demonstrated end to end without any API key."""

    def __init__(self) -> None:
        self.sessions: dict[str, tuple[LeadAgent, ToolBox]] = {}

    def chat(self, session_id: str, message: str, system_prompt: str | None = None, version: str = "v2") -> dict:
        if session_id not in self.sessions:
            toolbox = ToolBox()
            prompt = system_prompt or build_system_prompt({})
            self.sessions[session_id] = (LeadAgent(prompt, toolbox, version=version), toolbox)
        agent, toolbox = self.sessions[session_id]
        calls: list = []
        toolbox.sink = calls
        reply = agent.respond(message)
        toolbox.sink = None
        return {"reply": reply, "tool_calls": [
            {"name": c.name, "args": c.args, "result": c.result, "error": c.error} for c in calls]}


class HarnessService:
    def __init__(self, runs_dir: str | Path = "runs") -> None:
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.demo = DemoChat()

    def list_scenarios(self) -> list[dict]:
        return [{"id": s["id"], "category": s["category"], "description": s.get("description", ""),
                 "turns": len(s["turns"])} for s in load_scenarios()]

    def start_run(self, agent: str = "mock:v2", scenario_ids: list[str] | None = None,
                  category: str | None = None) -> dict:
        run = run_suite(agent, ids=scenario_ids, category=category).to_dict()
        (self.runs_dir / f"{run['run_id']}.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
        return {"run_id": run["run_id"], "agent": run["agent"], "summary": run["summary"]}

    def list_runs(self) -> list[dict]:
        out = []
        for p in sorted(self.runs_dir.glob("*.json"), reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({"run_id": d["run_id"], "agent": d["agent"], "created_at": d["created_at"],
                            "pass_rate": d["summary"]["pass_rate"]})
            except (json.JSONDecodeError, KeyError):
                continue
        return out

    def get_run(self, run_id: str) -> dict:
        if not _SAFE_ID.match(run_id):
            raise KeyError(run_id)
        path = self.runs_dir / f"{run_id}.json"
        if not path.is_file():
            raise KeyError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def run_report(self, run_id: str, fmt: str = "html") -> str:
        run = self.get_run(run_id)
        return to_html(run) if fmt == "html" else to_markdown(run)
