"""运行 ChainLens 四个业务场景并保存可交付报告。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from chainlens.agents import ChainLensOrchestrator

QUESTIONS = (
    ("01_financing", "请找出有真实中标能力但没有融资记录的智能制造企业"),
    ("02_qualification", "未来一年哪些多年期资质需要续期，哪些企业曾有效但现在全部失效"),
    ("03_network", "智能制造产业链中哪些企业是关键节点，供需和协作关系如何"),
    ("04_region", "比较不同区县的产业健康和行业空转预警"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 ChainLens 决策分析流水线")
    parser.add_argument(
        "--output-dir",
        default=str(Path("data/outputs") / f"acceptance_{date.today():%Y%m%d}"),
        help="报告输出目录",
    )
    args = parser.parse_args()
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, object]] = []
    orchestrator = ChainLensOrchestrator()
    try:
        for slug, question in QUESTIONS:
            target = root / slug
            result = orchestrator.run(question, output_dir=target)
            summary.append(
                {
                    "slug": slug,
                    "question": question,
                    "intent": result.intent,
                    "finding_count": len(result.findings),
                    "evidence_count": len(result.evidence),
                    "artifacts": {key: str(path) for key, path in result.artifacts.items()},
                }
            )
            print(
                f"[ok] {slug}: intent={result.intent}, "
                f"findings={len(result.findings)}, evidence={len(result.evidence)}, "
                f"artifacts={len(result.artifacts)}"
            )
    finally:
        orchestrator.close()

    summary_path = root / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
