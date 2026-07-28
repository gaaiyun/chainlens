"""Run and archive the reviewed autonomous-analysis acceptance set."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from chainlens.agents import ChainLensOrchestrator  # noqa: E402


QUESTIONS: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("01_operating_status", "统计经营状态分布", ("status", "enterprise_count"), True),
    ("02_industry_top", "企业数量最多的行业 Top 10", ("industry_code", "enterprise_count"), True),
    ("03_financing_rounds", "统计融资轮次分布", ("round_name", "financing_events"), True),
    ("04_bidding_year", "按年度统计招投标趋势", ("year", "bidding_records"), True),
    ("05_qualification_year", "按年份统计资质发布数量", ("year", "qualification_records"), True),
    ("06_region_distribution", "统计企业地区分布 Top 10", ("district_code", "enterprise_count"), True),
    ("07_founding_trend", "按成立年份统计企业数量趋势", ("year", "enterprise_count"), True),
    ("08_investment_top", "对外投资数量最多的企业 Top 10", ("name", "investment_count"), True),
    ("09_capital_bands", "按注册资本区间统计企业数量", ("capital_range", "enterprise_count"), True),
    ("10_enterprise_detail", "查询一家企业的基本信息、融资、招投标和投资详情", ("eid", "name"), False),
)


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return _json_value(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if pd.isna(value):
        return None
    return value


def _serialize_result(result: Any) -> dict[str, Any]:
    return _json_value(
        {
            "question": result.question,
            "intent": result.intent,
            "title": result.title,
            "sql": result.metadata.get("sql"),
            "safe_sql": result.metadata.get("safe_sql"),
            "safety": result.metadata.get("safety"),
            "metadata": result.metadata,
            "tables": {
                key: frame.to_dict(orient="records")
                for key, frame in result.tables.items()
            },
            "findings": [item.__dict__ for item in result.findings],
            "actions": result.actions,
            "charts": [item.__dict__ for item in result.charts],
            "evidence": [item.to_dict() for item in result.evidence],
            "trace": [item.__dict__ for item in result.trace],
            "report_markdown": result.report_markdown,
            "artifacts": {key: path for key, path in result.artifacts.items()},
        }
    )


def _verify_result(result: Any, expected_columns: tuple[str, ...], expect_chart: bool) -> None:
    if result.intent != "autonomous":
        raise AssertionError(f"预期 autonomous，实际为 {result.intent}")
    if result.metadata.get("planner") != "deterministic_template":
        raise AssertionError("标准验收问题必须命中已审查 SQL 模板")
    if result.metadata.get("llm_used") is not False:
        raise AssertionError("标准验收问题不应依赖 LLM")
    if not result.metadata.get("safety", {}).get("is_safe"):
        raise AssertionError("safe SQL 校验未通过")
    if not result.metadata.get("safe_sql"):
        raise AssertionError("缺少 safe_sql")
    frame = result.tables.get("query_result")
    if frame is None or frame.empty:
        raise AssertionError("真实数据查询未返回记录")
    missing = [column for column in expected_columns if column not in frame.columns]
    if missing:
        raise AssertionError(f"结果缺少字段: {', '.join(missing)}")
    if not result.findings or not result.evidence or not result.report_markdown:
        raise AssertionError("结论、证据或报告不完整")
    if expect_chart and not result.charts:
        raise AssertionError("聚合问题未生成图表规格")


def main() -> int:
    parser = argparse.ArgumentParser(description="运行自主分析十问真实数据验收")
    parser.add_argument(
        "--output-dir",
        default=str(Path("data/outputs") / f"autonomous_acceptance_{date.today():%Y%m%d}"),
        help="验收产物目录",
    )
    args = parser.parse_args()
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []
    orchestrator = ChainLensOrchestrator()
    backend = orchestrator.warehouse.backend
    try:
        for slug, question, expected_columns, expect_chart in QUESTIONS:
            target = root / slug
            result = orchestrator.run(question, output_dir=target)
            _verify_result(result, expected_columns, expect_chart)
            payload = _serialize_result(result)
            result_path = target / "result.json"
            result_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            row_count = len(result.tables["query_result"])
            summary.append(
                {
                    "slug": slug,
                    "question": question,
                    "backend": backend,
                    "status": "passed",
                    "rows": row_count,
                    "findings": len(result.findings),
                    "evidence": len(result.evidence),
                    "charts": len(result.charts),
                    "safe_sql": result.metadata["safe_sql"],
                    "result": str(result_path),
                }
            )
            print(
                f"[OK] {slug}: backend={backend}, rows={row_count}, "
                f"findings={len(result.findings)}, charts={len(result.charts)}"
            )
    finally:
        orchestrator.close()

    summary_path = root / "summary.json"
    summary_path.write_text(
        json.dumps(_json_value(summary), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"[OK] 10/10 autonomous acceptance passed: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
