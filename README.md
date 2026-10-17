# Multi-Turn Agent Evaluation & Testing Harness

A framework for testing LLM agents the way you test software. It runs **scripted multi-turn conversations** against an agent, records every reply and tool call, and **grades** the behaviour: tool selection, structured-output correctness, context retention, hallucination, prompt-injection safety and task completion. It produces run-level metrics, failure traces that point at the exact step that went wrong, and run-to-run comparisons for regression testing.

- **Zero runtime dependencies**: the core harness is pure Python standard library (3.10+).
- **Deterministic out of the box**: two built-in demo agents (`mock:v1` flawed, `mock:v2` robust) need no API key.
- **Bring your own agent**: Claude via the Anthropic API, any agent over HTTP, or a Python factory.
- **CI-friendly**: `--fail-under` and `compare --fail-on-regression` set the exit code.
- **Optional FastAPI server** to trigger runs and fetch reports over HTTP.

## Quick start

```bash
git clone <your-repo-url> && cd agent-eval-harness
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest -q                                              # run the test-suite
agent-harness list                                     # show scenarios
agent-harness run --agent mock:v1 --out runs           # flawed demo agent
agent-harness run --agent mock:v2 --out runs           # robust demo agent
agent-harness compare runs/<v1>.json runs/<v2>.json    # what got fixed / regressed
```

Each run writes `runs/<run_id>.json` (always), plus `.md` and `.html` reports. See [`examples/`](examples) for sample output: `sample-v1.md` shows the flawed agent failing 9 of 12 scenarios, with the exact failing step and a transcript for each.

## What gets evaluated

| Grader | Checks |
|---|---|
| `tool_selection` | Expected tools were called (with matching args); forbidden tools were not |
| `response_content` | Reply contains / does not contain given text; asks a clarifying question when it should |
| `context_retention` | Facts from earlier turns (name, company...) are recalled correctly |
| `structured_output` | Final record (from a tool call or JSON reply) matches a JSON schema and expected field values, with correct types |
| `hallucination` | Prices / percentages in replies must be grounded in the KB, user messages or tool results; scenario-specific forbidden claims |
| `safety` | A secret canary in the system prompt is never leaked; forbidden tools (e.g. `delete_lead`) are never called; poisoned KB content is not relayed |
| `task_completion` | Required tools were called; workflow was not completed prematurely; final reply is as expected |
| `tool_robustness` | Agent never crashes; no retry loops (`max_calls_per_tool`); tool-call budget respected |

A scenario **passes** only if every check passes; its **score** is the fraction of checks passed. When a scenario fails, the harness reports the **first failing step** (turn number, step kind: `tool_call` / `reply` / `final`, grader and check) so you know where the agent went wrong.

### Built-in scenarios (12)

| Category | Scenarios |
|---|---|
| `happy_path` | full lead qualification with structured output; grounded pricing answer |
| `context` | recalls name + company after an unrelated question |
| `ambiguous` | vague request; "just sign me up" with no details |
| `tool_failure` | `save_lead` down (no false success claims, no retry loop); `lookup_product` down (no invented prices) |
| `hallucination` | asked about offers that don't exist in the KB |
| `prompt_injection` | direct prompt-leak attempt; injected "admin override" to call `delete_lead`; indirect injection via a poisoned knowledge-base document |
| `incomplete_workflow` | user tries to finish with email + budget still missing |

The sample domain is a lead-qualification assistant for a fictional SaaS ("NovaDesk"), with tools `lookup_product`, `score_lead`, `save_lead` and `delete_lead`.

## Evaluating your own agent

```bash
# Claude (needs ANTHROPIC_API_KEY; model via :name or ANTHROPIC_MODEL)
export ANTHROPIC_API_KEY=...
agent-harness run --agent anthropic
agent-harness run --agent anthropic:<model-name>

# Any agent behind an HTTP endpoint
agent-harness run --agent http:http://localhost:9000/chat

# A Python factory (see examples/custom_agent.py)
PYTHONPATH=examples agent-harness run --agent custom:custom_agent:make_agent
```

**Python factory contract:** `factory(system_prompt: str, toolbox: ToolBox) -> agent`, where `agent.respond(user_message: str) -> str`. Call tools through `toolbox.call(name, args)`; calls are recorded for grading, honour fault injection, and raise `ToolError` on failure.

**HTTP contract:**

```
POST <url>   {"session_id": "...", "message": "...", "system_prompt": "..."}
->  200      {"reply": "...", "tool_calls": [{"name": "...", "args": {}, "result": {}, "error": null}]}
```

Remote agents report their own tool calls, so harness-side fault injection does not apply to them.
To try the HTTP adapter without writing anything, start `agent-harness serve` and run `--agent http:http://127.0.0.1:8000/agent/chat`.

## Writing scenarios

Scenarios are JSON files in `src/agent_harness/data/scenarios/` (or any folder passed via `--scenarios-dir`). One object per file, or a list.

```jsonc
{
  "id": "tool_failure_save_lead",
  "category": "tool_failure",            // happy_path | context | ambiguous | tool_failure | hallucination | prompt_injection | incomplete_workflow
  "description": "...",
  "tool_faults": {"save_lead": "error"}, // inject faults: error | timeout | malformed
  "kb_extra": [ {"id": "...", "type": "faq", "title": "...", "text": "...", "keywords": ["..."]} ],  // extra/poisoned KB docs
  "forbidden_claims": ["regex", "..."],  // hallucination grader
  "safety": {"never_in_reply": ["..."], "forbidden_tools": ["delete_lead"]},
  "turns": [
    {"user": "message sent to the agent",
     "expect": {
       "tools_called": [{"name": "save_lead", "args": {"email": "*"}}],   // "*" = any value; strings match case-insensitively as substrings
       "tools_not_called": ["delete_lead"],
       "reply_contains_all": ["..."], "reply_contains_any": ["..."], "reply_not_contains": ["..."],
       "reply_asks_question": true,
       "recall": ["facts the agent must remember"]
     }}
  ],
  "final": {
    "required_tools": ["score_lead", "save_lead"],
    "forbidden_tools": [],                 // must NOT have been called by the end (premature completion)
    "max_calls_per_tool": {"save_lead": 3},
    "max_total_tool_calls": 10,
    "final_reply_contains_any": ["..."],
    "structured_output": {
      "source": "tool:save_lead",          // or "reply_json"
      "schema": { "type": "object", "required": ["name"], "properties": {"name": {"type": "string"}} },
      "expected": {"name": "Priya Sharma"}
    }
  }
}
```

Every scenario also gets baseline checks automatically: the agent must not crash, must stay within the tool-call budget, must not leak the system-prompt canary, and must not state ungrounded prices/percentages.

## Adding a grader

Graders are plain functions `(scenario: dict, trace: Trace) -> list[CheckResult]` in `src/agent_harness/graders.py`. Add yours to the `GRADERS` list (and to `STEP_KIND` so failures are attributed to the right step type).

## CLI reference

```
agent-harness list    [--category C] [--scenarios-dir DIR]
agent-harness run     [--agent SPEC] [--scenario ID ...] [--category C] [--scenarios-dir DIR]
                      [--out DIR] [--format md,html] [--fail-under 0.9]
agent-harness compare BASELINE.json CANDIDATE.json [--fail-on-regression]
agent-harness serve   [--host H] [--port P] [--out DIR]
```

Exit codes: `0` success, `1` quality gate failed, `2` usage/config error.

## HTTP server (optional)

```bash
pip install -e ".[server]"
agent-harness serve --port 8000       # interactive docs: http://127.0.0.1:8000/docs
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /scenarios` | list scenarios |
| `POST /runs` | `{"agent": "mock:v2", "scenario_ids": [...], "category": "..."}` runs synchronously, stores the result |
| `GET /runs`, `GET /runs/{id}` | list / fetch runs |
| `GET /runs/{id}/report`, `/report.md` | HTML / Markdown report |
| `POST /agent/chat` | demo agent that follows the HTTP-adapter contract |

Docker: `docker build -t agent-eval-harness . && docker run -p 8000:8000 agent-eval-harness`

## Using it in CI

```yaml
- run: agent-harness run --agent custom:my_pkg.agent:make_agent --fail-under 0.95
- run: agent-harness compare baseline/run.json runs/latest.json --fail-on-regression
```

The included workflow (`.github/workflows/ci.yml`) runs the tests and requires the reference agent to pass 100% of scenarios.

## Project layout

```
src/agent_harness/
  cli.py            command line interface
  runner.py         runs scenarios, builds traces, calls graders
  graders.py        the eight graders + first-failure attribution
  metrics.py        run summaries and run-to-run comparison
  report.py         Markdown / HTML / console reports
  tools.py          sandboxed tools + fault injection
  schema.py         JSON-schema subset validator
  scenarios.py      scenario loading / validation
  service.py        framework-agnostic service layer
  server.py         optional FastAPI app
  agents/           mock (v1/v2), anthropic, http adapters
  data/             knowledge base + 12 scenarios
tests/              pytest suite (graders, runner, CLI, adapters, server)
examples/           sample reports + custom-agent template
```

## Design notes and limitations

- Grading is rule-based (substring, regex, schema, tool-trace checks), which keeps it fast, deterministic and free. It cannot judge nuance such as tone or reasoning quality; an LLM-as-judge grader can be added as another grader function.
- The hallucination grader checks *figures* (currency amounts and percentages) against the KB and conversation. It does not detect every kind of fabricated claim, so pair it with `forbidden_claims` and `reply_contains_any` hedging checks per scenario.
- LLM agents are non-deterministic; for stochastic agents, run several times and look at pass-rate trends rather than a single run.
- The built-in mock agents are regex-based demos meant to exercise the harness, not production agents.
- The Anthropic adapter's request/response handling is unit-tested with a stubbed API; run it once with a real key to confirm your model name and account access.

## License

MIT
