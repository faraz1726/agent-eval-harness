"""Optional FastAPI server: run evaluations over HTTP and host a demo agent.

    pip install -e ".[server]"
    agent-harness serve --port 8000     # docs at http://localhost:8000/docs
"""
from .service import HarnessService


def create_app(runs_dir: str = "runs"):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, PlainTextResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('FastAPI is not installed. Run: pip install -e ".[server]"') from exc

    from . import __version__

    # NOTE: no `from __future__ import annotations` in this module: FastAPI must resolve the
    # locally defined request models at runtime.
    service = HarnessService(runs_dir)
    app = FastAPI(title="Agent Evaluation Harness", version=__version__)

    class RunRequest(BaseModel):
        agent: str = Field("mock:v2", description="mock:v1 | mock:v2 | anthropic[:model] | http:<url> | custom:<module>:<factory>")
        scenario_ids: list[str] | None = None
        category: str | None = None

    class ChatRequest(BaseModel):
        session_id: str
        message: str
        system_prompt: str | None = None
        version: str = "v2"

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/scenarios")
    def scenarios():
        return service.list_scenarios()

    @app.post("/runs")
    def create_run(req: RunRequest):
        try:
            return service.start_run(req.agent, req.scenario_ids, req.category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/runs")
    def runs():
        return service.list_runs()

    @app.get("/runs/{run_id}")
    def run_detail(run_id: str):
        try:
            return service.get_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    def run_report_html(run_id: str):
        try:
            return service.run_report(run_id, "html")
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None

    @app.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
    def run_report_md(run_id: str):
        try:
            return service.run_report(run_id, "md")
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None

    @app.post("/agent/chat")
    def agent_chat(req: ChatRequest):
        """Demo agent endpoint that follows the contract expected by the `http:` adapter."""
        if req.version not in ("v1", "v2"):
            raise HTTPException(status_code=400, detail="version must be v1 or v2")
        return service.demo.chat(req.session_id, req.message, req.system_prompt, req.version)

    return app

