"""Exercise the deployed ChainLens API and archive auditable responses."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

import requests

from run_autonomous_acceptance import QUESTIONS

DEFAULT_API_URL = "https://chainlens-production.up.railway.app"
LONG_TAIL = (
    "11_economic_type",
    "按企业经济类型统计企业数量",
    ("econ_kind", "enterprise_count"),
    True,
)


def request_json(api_url: str, question: str, timeout: float) -> dict:
    try:
        response = requests.post(
            f"{api_url.rstrip('/')}/api/query",
            json={"question": question},
            headers={
                "User-Agent": "ChainLens-Public-Acceptance/1.0",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"API 连接失败: {type(exc).__name__}") from exc
    if not response.ok:
        raise RuntimeError(f"API HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def verify_response(
    payload: dict,
    expected_columns: tuple[str, ...],
    expect_chart: bool,
    *,
    expect_llm: bool,
) -> int:
    if payload.get("intent") != "autonomous":
        raise AssertionError(f"预期 autonomous，实际为 {payload.get('intent')}")
    if not payload.get("safe_sql") or not payload.get("safety", {}).get("is_safe"):
        raise AssertionError("公网响应缺少已通过校验的 safe_sql")
    rows = payload.get("tables", {}).get("query_result")
    if not isinstance(rows, list) or not rows:
        raise AssertionError("公网真实查询未返回记录")
    missing = [column for column in expected_columns if column not in rows[0]]
    if missing:
        raise AssertionError(f"公网结果缺少字段: {', '.join(missing)}")
    if not payload.get("findings") or not payload.get("evidence"):
        raise AssertionError("公网响应缺少结论或证据")
    if not payload.get("report_markdown") or not payload.get("trace"):
        raise AssertionError("公网响应缺少报告或执行 trace")
    if expect_chart and not payload.get("charts"):
        raise AssertionError("公网聚合问题未返回图表规格")
    llm_used = payload.get("metadata", {}).get("llm_used")
    if llm_used is not expect_llm:
        raise AssertionError(f"llm_used 预期 {expect_llm}，实际 {llm_used}")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 ChainLens 公网 API 验收")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument(
        "--output-dir",
        default=str(Path("data/outputs") / f"public_autonomous_acceptance_{date.today():%Y%m%d}"),
    )
    parser.add_argument("--include-long-tail", action="store_true")
    parser.add_argument("--timeout", type=float, default=150.0)
    args = parser.parse_args()
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    cases = list(QUESTIONS)
    if args.include_long_tail:
        cases.append(LONG_TAIL)
    summary: list[dict[str, object]] = []

    for index, (slug, question, expected_columns, expect_chart) in enumerate(cases):
        started = time.perf_counter()
        payload = request_json(args.api_url, question, args.timeout)
        expect_llm = index >= len(QUESTIONS)
        row_count = verify_response(
            payload,
            expected_columns,
            expect_chart,
            expect_llm=expect_llm,
        )
        elapsed = round(time.perf_counter() - started, 2)
        target = root / slug
        target.mkdir(parents=True, exist_ok=True)
        response_path = target / "response.json"
        report_path = target / "report.md"
        response_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        report_path.write_text(payload["report_markdown"], encoding="utf-8")
        summary.append(
            {
                "slug": slug,
                "question": question,
                "status": "passed",
                "rows": row_count,
                "elapsed_seconds": elapsed,
                "planner": payload.get("metadata", {}).get("planner"),
                "llm_provider": payload.get("metadata", {}).get("llm_provider"),
                "safe_sql": payload["safe_sql"],
                "response": str(response_path),
                "report": str(report_path),
            }
        )
        print(
            f"[OK] {slug}: rows={row_count}, elapsed={elapsed:.2f}s, "
            f"planner={summary[-1]['planner']}"
        )

    summary_path = root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"[OK] {len(cases)}/{len(cases)} public acceptance passed: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
