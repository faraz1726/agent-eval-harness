"""Command line interface: list / run / compare / serve."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .metrics import compare_runs
from .report import comparison_markdown, console_summary, to_html, to_markdown
from .runner import run_suite
from .scenarios import CATEGORIES, load_scenarios


def _cmd_list(args) -> int:
    for sc in load_scenarios(args.scenarios_dir, category=args.category):
        print(f"{sc['id']:<34} {sc['category']:<20} {len(sc['turns'])} turn(s)  {sc.get('description', '')}")
    return 0


def _cmd_run(args) -> int:
    run = run_suite(args.agent, scenarios_dir=args.scenarios_dir, ids=args.scenario, category=args.category).to_dict()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = out / run["run_id"]
    formats = {f.strip() for f in args.format.split(",")}
    (base.with_suffix(".json")).write_text(json.dumps(run, indent=2), encoding="utf-8")  # always saved for `compare`
    if "md" in formats:
        base.with_suffix(".md").write_text(to_markdown(run), encoding="utf-8")
    if "html" in formats:
        base.with_suffix(".html").write_text(to_html(run), encoding="utf-8")
    print(console_summary(run))
    print(f"\nSaved: {base.with_suffix('.json')}")
    if run["summary"]["pass_rate"] < args.fail_under:
        print(f"FAILED: pass rate {run['summary']['pass_rate']:.2%} is below --fail-under {args.fail_under:.2%}", file=sys.stderr)
        return 1
    return 0


def _cmd_compare(args) -> int:
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    cand = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    cmp = compare_runs(base, cand)
    print(comparison_markdown(cmp))
    if args.fail_on_regression and cmp["regressions"]:
        print(f"FAILED: {len(cmp['regressions'])} regression(s) detected", file=sys.stderr)
        return 1
    return 0


def _cmd_serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print('uvicorn is not installed. Run: pip install -e ".[server]"', file=sys.stderr)
        return 2
    from .server import create_app
    uvicorn.run(create_app(args.out), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-harness", description="Multi-turn agent evaluation & testing harness")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    ls = sub.add_parser("list", help="list scenarios")
    ls.add_argument("--scenarios-dir")
    ls.add_argument("--category", choices=CATEGORIES)
    ls.set_defaults(func=_cmd_list)

    run = sub.add_parser("run", help="run the suite against an agent")
    run.add_argument("--agent", default="mock:v2",
                     help="mock:v1 | mock:v2 | anthropic[:model] | http:<url> | custom:<module>:<factory>")
    run.add_argument("--scenarios-dir")
    run.add_argument("--scenario", action="append", help="scenario id (repeatable)")
    run.add_argument("--category", choices=CATEGORIES)
    run.add_argument("--out", default="runs")
    run.add_argument("--format", default="md,html", help="extra report formats: md,html (JSON is always written)")
    run.add_argument("--fail-under", type=float, default=0.0, help="exit 1 if pass rate is below this (0-1)")
    run.set_defaults(func=_cmd_run)

    cmp = sub.add_parser("compare", help="compare two saved runs (baseline vs candidate)")
    cmp.add_argument("baseline")
    cmp.add_argument("candidate")
    cmp.add_argument("--fail-on-regression", action="store_true")
    cmp.set_defaults(func=_cmd_compare)

    srv = sub.add_parser("serve", help="start the FastAPI server")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--out", default="runs")
    srv.set_defaults(func=_cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
