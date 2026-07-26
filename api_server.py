"""ChainLens 可选 API：静态前端配置接口地址后即可查询最新结果。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from chainlens.agents import ChainLensOrchestrator


def allowed_origins() -> list[str]:
    """Return explicit CORS origins, keeping local development convenient."""
    configured = os.getenv("CHAINLENS_ALLOWED_ORIGINS", "")
    origins = [item.strip() for item in configured.split(",") if item.strip()]
    return origins or ["*"]


app = FastAPI(title="ChainLens API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
orchestrator = ChainLensOrchestrator()


class QueryRequest(BaseModel):
    question: str = Field(..., description="中文产业分析问题")

    @field_validator("question")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question 不能为空")
        return value


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "engine": "deterministic-kernels",
        "database": orchestrator.warehouse.backend,
    }


@app.post("/api/query")
def query(payload: QueryRequest) -> JSONResponse:
    result = orchestrator.run(payload.question)
    body = {
        "question": result.question,
        "intent": result.intent,
        "title": result.title,
        "findings": [
            {"text": item.text, "evidence_id": item.evidence_id, "caveat": item.caveat}
            for item in result.findings
        ],
        "actions": result.actions,
        "charts": [chart.__dict__ for chart in result.charts],
        "tables": {key: frame.head(100).to_dict(orient="records") for key, frame in result.tables.items()},
        "evidence": [item.to_dict() for item in result.evidence],
        "trace": [step.__dict__ for step in result.trace],
        "report_markdown": result.report_markdown,
        "metadata": result.metadata,
    }
    return JSONResponse(content=jsonable_encoder(body))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=False)
