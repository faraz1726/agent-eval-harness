"""Plain dataclasses shared by the runner, graders and reports (stdlib only)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolCallRecord:
    name: str
    args: dict
    result: Any = None
    error: str | None = None
    latency_ms: float = 0.0


@dataclass
class TurnRecord:
    index: int
    user: str
    reply: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str | None = None


@dataclass
class Trace:
    scenario_id: str
    agent: str
    system_prompt: str
    turns: list[TurnRecord] = field(default_factory=list)
    allowed_text: str = ""  # text the agent may legitimately quote (KB, user turns, tool results)

    @property
    def all_tool_calls(self) -> list[ToolCallRecord]:
        return [c for t in self.turns for c in t.tool_calls]

    def calls_named(self, name: str) -> list[ToolCallRecord]:
        return [c for c in self.all_tool_calls if c.name == name]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CheckResult:
    grader: str
    name: str
    passed: bool
    detail: str = ""
    turn: int | None = None  # None => scenario-level ("final") check


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    description: str
    passed: bool
    score: float
    checks: list[CheckResult]
    trace: dict
    duration_s: float
    failure_step: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunResult:
    run_id: str
    agent: str
    created_at: str
    scenarios: list[ScenarioResult]
    summary: dict

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "agent": self.agent,
            "created_at": self.created_at,
            "summary": self.summary,
            "scenarios": [s.to_dict() for s in self.scenarios],
        }
