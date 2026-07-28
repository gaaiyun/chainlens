from __future__ import annotations

from pathlib import Path

import pytest

from chainlens.agents.orchestrator import ChainLensOrchestrator
from chainlens.warehouse.access import Warehouse


@pytest.fixture(scope="module")
def orchestrator() -> ChainLensOrchestrator:
    instance = ChainLensOrchestrator(Warehouse())
    yield instance
    instance.close()


def test_router_distinguishes_the_four_decision_scenarios() -> None:
    router = ChainLensOrchestrator.classify

    assert router("哪些企业有真实经营能力但没有融资记录") == "financing"
    assert router("未来一年哪些资质需要续期") == "qualification"
    assert router("智能制造产业链中哪些企业是关键节点") == "network"
    assert router("比较不同区县的产业健康和行业分布") == "region"


def test_router_sends_general_data_questions_to_autonomous_analysis() -> None:
    router = ChainLensOrchestrator.classify

    assert router("统计经营状态分布") == "autonomous"
    assert router("按成立年份统计企业数量趋势") == "autonomous"
    assert router("按注册资本区间统计企业数量") == "autonomous"
    assert router("统计各融资轮次的企业数量") == "autonomous"


def test_standard_autonomous_question_does_not_require_llm_key(monkeypatch) -> None:
    monkeypatch.delenv("VOLCENGINE_ARK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    runtime = ChainLensOrchestrator(Warehouse())
    try:
        result = runtime.run("统计经营状态分布")
    finally:
        runtime.close()

    assert result.intent == "autonomous"
    assert result.metadata["planner"] == "deterministic_template"
    assert result.metadata["llm_used"] is False


def test_financing_run_produces_trace_evidence_charts_and_artifacts(
    orchestrator: ChainLensOrchestrator,
    tmp_path: Path,
) -> None:
    result = orchestrator.run(
        "请找出有真实中标能力但没有融资记录的智能制造企业",
        output_dir=tmp_path,
    )

    assert result.intent == "financing"
    assert result.findings
    assert result.actions
    assert len(result.evidence) >= 1
    assert not result.evidence.unverifiable
    assert result.charts
    assert result.artifacts.keys() >= {"markdown", "html", "pdf"}
    assert all(path.exists() for path in result.artifacts.values())
    assert "证据链" in result.report_markdown
    assert "凭空推断" in result.report_markdown
    assert [step.status for step in result.trace][-1] == "passed"


def test_quality_gate_rejects_reports_without_verifiable_evidence() -> None:
    with pytest.raises(ValueError, match="证据"):
        ChainLensOrchestrator.quality_gate([])
