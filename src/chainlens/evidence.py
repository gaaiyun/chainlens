"""证据链：让每一个进入报告的数字都能被回溯。

为什么需要这个：
在政府和金融场景里，"模型说的"没有价值，"能查证的"才有价值。
ChainLens 的每一条结论都必须携带 Evidence——产出它的内核、支撑它的 SQL、
命中的行数、计算时间、置信度和已知局限。CriticAgent 会拦掉没有证据的结论。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Evidence:
    """一条结论的可回溯凭证。"""

    kernel: str
    claim: str
    value: Any = None
    unit: str = ""
    sql: str = ""
    row_count: int = 0
    confidence: float = 1.0
    caveats: tuple[str, ...] = ()
    computed_at: str = field(default_factory=_now)

    @property
    def evidence_id(self) -> str:
        payload = f"{self.kernel}|{self.claim}|{self.sql}|{self.value}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    @property
    def is_verifiable(self) -> bool:
        """有 SQL 或有明确内核出处，且命中行数可解释，才算可核查。"""
        return bool(self.sql.strip()) and self.row_count >= 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kernel": self.kernel,
            "claim": self.claim,
            "value": self.value,
            "unit": self.unit,
            "sql": self.sql,
            "row_count": self.row_count,
            "confidence": round(self.confidence, 3),
            "caveats": list(self.caveats),
            "computed_at": self.computed_at,
        }


class EvidenceLedger:
    """一次分析任务里所有证据的账本。"""

    def __init__(self) -> None:
        self._items: list[Evidence] = []

    def add(self, evidence: Evidence) -> Evidence:
        self._items.append(evidence)
        return evidence

    def extend(self, items: Iterable[Evidence]) -> None:
        for item in items:
            self.add(item)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    @property
    def items(self) -> list[Evidence]:
        return list(self._items)

    @property
    def unverifiable(self) -> list[Evidence]:
        return [e for e in self._items if not e.is_verifiable]

    @property
    def min_confidence(self) -> float:
        return min((e.confidence for e in self._items), default=1.0)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps([e.to_dict() for e in self._items], ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        if not self._items:
            return "_本次分析没有产生证据记录。_"
        lines = [
            "| 证据ID | 内核 | 结论 | 取值 | 命中行 | 置信度 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for e in self._items:
            value = f"{e.value}{e.unit}" if e.value is not None else "-"
            lines.append(
                f"| `{e.evidence_id}` | {e.kernel} | {e.claim} | {value} | {e.row_count:,} | {e.confidence:.2f} |"
            )
        return "\n".join(lines)
