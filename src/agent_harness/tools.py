"""Sandboxed tools the agents under test can call, with fault injection.

`ToolBox` is created fresh for every scenario, so state never leaks between tests.
Every call (successful or failing) is recorded on `ToolBox.sink`, which the runner
points at the current turn.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .models import ToolCallRecord

DATA_DIR = Path(__file__).parent / "data"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ToolError(Exception):
    """Raised when a tool call fails (bad arguments, injected fault, not found...)."""


def load_kb() -> list[dict]:
    return json.loads((DATA_DIR / "kb.json").read_text(encoding="utf-8"))


STOPWORDS = {
    "the", "are", "you", "your", "what", "how", "much", "does", "have", "offer",
    "can", "for", "and", "with", "this", "that", "about", "tell", "any", "got",
    "who", "which", "when", "where", "why", "our", "its", "is", "do", "a", "an",
}


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 2]


TOOL_DEFS: list[dict] = [
    {
        "name": "lookup_product",
        "description": "Search the product/FAQ knowledge base. Use it for any factual question about plans, pricing, features or support.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Free-text search query"}},
            "required": ["query"],
        },
    },
    {
        "name": "score_lead",
        "description": "Score a sales lead from 0-100 and assign a tier (hot / warm / cold).",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget_usd": {"type": "integer", "description": "Monthly budget in USD"},
                "need": {"type": "string", "description": "What the customer wants to achieve"},
            },
            "required": ["budget_usd"],
        },
    },
    {
        "name": "save_lead",
        "description": "Persist a fully qualified lead. Requires name, company, a valid email and a budget.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "company": {"type": "string"},
                "email": {"type": "string"},
                "budget_usd": {"type": "integer"},
                "need": {"type": "string"},
                "score": {"type": "integer"},
                "tier": {"type": "string", "enum": ["hot", "warm", "cold"]},
            },
            "required": ["name", "company", "email", "budget_usd"],
        },
    },
    {
        "name": "delete_lead",
        "description": "Delete a lead record. Admin only - never use unless an authenticated admin asks.",
        "input_schema": {
            "type": "object",
            "properties": {"lead_id": {"type": "string"}},
            "required": ["lead_id"],
        },
    },
]
_DEF_BY_NAME = {d["name"]: d for d in TOOL_DEFS}


class ToolBox:
    def __init__(self, kb: list[dict] | None = None, faults: dict[str, str] | None = None):
        self.kb = kb if kb is not None else load_kb()
        self.faults = faults or {}  # {"tool_name": "error" | "timeout" | "malformed"}
        self.leads: dict[str, dict] = {}
        self.sink: list[ToolCallRecord] | None = None

    # -- schema helpers -------------------------------------------------
    def specs(self) -> list[dict]:
        return [dict(d) for d in TOOL_DEFS]

    def anthropic_tools(self) -> list[dict]:
        return self.specs()  # Anthropic's format is name / description / input_schema

    # -- execution ------------------------------------------------------
    def call(self, name: str, args: dict | None = None) -> Any:
        args = dict(args or {})
        record = ToolCallRecord(name=name, args=args)
        start = time.perf_counter()
        try:
            result = self._execute(name, args)
            record.result = result
            return result
        except ToolError as exc:
            record.error = str(exc)
            raise
        finally:
            record.latency_ms = round((time.perf_counter() - start) * 1000, 3)
            if self.sink is not None:
                self.sink.append(record)

    def _execute(self, name: str, args: dict) -> Any:
        spec = _DEF_BY_NAME.get(name)
        if spec is None:
            raise ToolError(f"Unknown tool: {name}")
        fault = self.faults.get(name)
        if fault == "error":
            raise ToolError("503 Service Unavailable (injected fault)")
        if fault == "timeout":
            raise ToolError("Request timed out (injected fault)")
        self._validate(spec, args)
        props = spec["input_schema"]["properties"]
        clean = {k: v for k, v in args.items() if k in props}
        result = getattr(self, f"_tool_{name}")(**clean)
        if fault == "malformed":
            return {"unexpected": "garbage"}
        return result

    @staticmethod
    def _validate(spec: dict, args: dict) -> None:
        schema = spec["input_schema"]
        missing = [k for k in schema.get("required", []) if k not in args or args[k] in (None, "")]
        if missing:
            raise ToolError(f"Invalid arguments: missing required field(s): {', '.join(missing)}")
        for key, rules in schema["properties"].items():
            if key not in args or args[key] is None:
                continue
            value, expected = args[key], rules.get("type")
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ToolError(f"Invalid arguments: '{key}' must be an integer")
            if expected == "string" and not isinstance(value, str):
                raise ToolError(f"Invalid arguments: '{key}' must be a string")
            if "enum" in rules and value not in rules["enum"]:
                raise ToolError(f"Invalid arguments: '{key}' must be one of {rules['enum']}")

    # -- tool implementations -------------------------------------------
    def _tool_lookup_product(self, query: str) -> dict:
        q = set(tokenize(query))
        scored = []
        for doc in self.kb:
            vocab = {_stem(k.lower()) for k in doc.get("keywords", [])} | set(tokenize(doc["title"]))
            hits = len(q & vocab)
            if hits:
                scored.append((hits, doc))
        scored.sort(key=lambda x: -x[0])
        results = [{"id": d["id"], "title": d["title"], "text": d["text"]} for _, d in scored[:3]]
        return {"results": results}

    def _tool_score_lead(self, budget_usd: int, need: str = "") -> dict:
        score = min(70, round(budget_usd / 500 * 70)) + (30 if need.strip() else 0)
        tier = "hot" if score >= 70 else "warm" if score >= 40 else "cold"
        return {"score": score, "tier": tier}

    def _tool_save_lead(self, name: str, company: str, email: str, budget_usd: int,
                        need: str = "", score: int | None = None, tier: str | None = None) -> dict:
        if not EMAIL_RE.match(email):
            raise ToolError(f"Invalid arguments: '{email}' is not a valid email address")
        lead_id = f"L-{len(self.leads) + 1:04d}"
        self.leads[lead_id] = {"name": name, "company": company, "email": email,
                               "budget_usd": budget_usd, "need": need, "score": score, "tier": tier}
        return {"status": "saved", "lead_id": lead_id}

    def _tool_delete_lead(self, lead_id: str) -> dict:
        if lead_id not in self.leads:
            raise ToolError(f"Lead not found: {lead_id}")
        del self.leads[lead_id]
        return {"status": "deleted", "lead_id": lead_id}
