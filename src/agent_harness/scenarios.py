"""Scenario loading and validation."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_DIR = Path(__file__).parent / "data" / "scenarios"
CATEGORIES = ("happy_path", "context", "ambiguous", "tool_failure", "hallucination",
              "prompt_injection", "incomplete_workflow")


def validate_scenario(sc: dict, source: str = "") -> None:
    where = f" ({source})" if source else ""
    for key in ("id", "category", "turns"):
        if key not in sc:
            raise ValueError(f"scenario{where} is missing required key '{key}'")
    if not sc["turns"] or not all("user" in t for t in sc["turns"]):
        raise ValueError(f"scenario '{sc['id']}'{where}: every turn needs a 'user' message")


def load_scenarios(directory: str | Path | None = None, ids: list[str] | None = None,
                   category: str | None = None) -> list[dict]:
    folder = Path(directory) if directory else DEFAULT_DIR
    if not folder.is_dir():
        raise FileNotFoundError(f"Scenario directory not found: {folder}")
    scenarios: list[dict] = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for sc in (data if isinstance(data, list) else [data]):
            validate_scenario(sc, path.name)
            scenarios.append(sc)
    seen = set()
    for sc in scenarios:
        if sc["id"] in seen:
            raise ValueError(f"duplicate scenario id '{sc['id']}'")
        seen.add(sc["id"])
    if ids:
        unknown = set(ids) - seen
        if unknown:
            raise ValueError(f"unknown scenario id(s): {', '.join(sorted(unknown))}")
        scenarios = [s for s in scenarios if s["id"] in ids]
    if category:
        scenarios = [s for s in scenarios if s["category"] == category]
    return scenarios
