"""Agent 层的稳定数据契约。

这些对象把「计算结果」「证据」「表达产物」分开，避免报告层重新计算业务指标。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ..evidence import EvidenceLedger


@dataclass(frozen=True)
class Finding:
    """一条可展示的结论，必须能指向证据账本中的一项。"""

    text: str
    evidence_id: str
    caveat: str = ""


@dataclass(frozen=True)
class ChartSpec:
    """由确定性结果驱动的图表规格。"""

    chart_id: str
    title: str
    kind: str
    data_key: str
    x: str
    y: str


@dataclass(frozen=True)
class AgentTrace:
    """单个 Agent 节点的可审计执行记录。"""

    agent: str
    status: str
    detail: str


@dataclass
class AnalysisResult:
    """一次 ChainLens 分析的完整交付对象。"""

    question: str
    intent: str
    title: str
    tables: dict[str, pd.DataFrame]
    findings: list[Finding]
    actions: list[str]
    charts: list[ChartSpec]
    evidence: EvidenceLedger
    trace: list[AgentTrace]
    report_markdown: str = ""
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
