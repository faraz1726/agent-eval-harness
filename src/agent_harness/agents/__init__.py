"""Agent adapters. An agent factory has the signature ``factory(system_prompt, toolbox) -> agent``.

An agent exposes ``respond(user_message) -> str | AgentReply``.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Callable

from ..tools import ToolBox


@dataclass
class AgentReply:
    """Returned by agents that run remotely and report their own tool calls."""
    text: str
    tool_calls: list[dict] = field(default_factory=list)  # [{"name","args","result","error"}]


AgentFactory = Callable[[str, ToolBox], object]


def build_agent_factory(spec: str) -> tuple[str, AgentFactory]:
    """Turn a CLI spec into ``(display_name, factory)``.

    mock:v1 | mock:v2            built-in deterministic demo agents
    anthropic[:model]            Claude via the Anthropic Messages API (needs ANTHROPIC_API_KEY)
    http:<url>                   any agent exposed over HTTP (see README for the contract)
    custom:<module>:<attr>       your own factory, e.g. custom:my_pkg.agent:make_agent
    """
    kind, _, rest = spec.partition(":")
    if kind == "mock":
        from .mock import LeadAgent
        version = rest or "v2"
        if version not in ("v1", "v2"):
            raise ValueError("mock agent version must be v1 or v2")
        return spec, lambda prompt, tools: LeadAgent(prompt, tools, version=version)
    if kind == "anthropic":
        from .anthropic_agent import AnthropicAgent
        return spec, lambda prompt, tools: AnthropicAgent(prompt, tools, model=rest or None)
    if kind == "http":
        from .http_agent import HTTPAgent
        if not rest:
            raise ValueError("http agent needs a URL, e.g. http:http://localhost:8000/agent/chat")
        return spec, lambda prompt, tools: HTTPAgent(prompt, tools, url=rest)
    if kind == "custom":
        module_name, _, attr = rest.partition(":")
        if not module_name or not attr:
            raise ValueError("custom agent spec must look like custom:<module>:<factory>")
        factory = getattr(importlib.import_module(module_name), attr)
        return spec, factory
    raise ValueError(f"Unknown agent spec '{spec}'. Use mock:v1, mock:v2, anthropic[:model], http:<url> or custom:<module>:<factory>")
