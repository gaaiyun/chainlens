"""从已验证的分析结果生成 Markdown、HTML、PNG 和 PDF。

报告层只负责排版和可视化，不计算 OCS、健康指数或筛选阈值。
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .contracts import AnalysisResult, ChartSpec


def _safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_") or "chart"


def _markdown_table(frame: pd.DataFrame, limit: int = 20) -> str:
    if frame.empty:
        return "_无记录。_"
    sample = frame.head(limit).copy()
    columns = [str(column) for column in sample.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in sample.itertuples(index=False, name=None):
        values = [str(value).replace("|", "\\|") if pd.notna(value) else "" for value in row]
        lines.append("| " + " | ".join(values) + " |")
    if len(frame) > limit:
        lines.append(f"\n> 仅展示前 {limit} 行，完整数据保留在内存结果中。")
    return "\n".join(lines)


def compose_markdown(result: AnalysisResult) -> str:
    lines = [
        f"# {result.title}",
        "",
        f"> 用户问题：{result.question}",
        f"> 场景：`{result.intent}`",
        "",
        "## 结论",
        "",
    ]
    for finding in result.findings:
        lines.append(f"- {finding.text}（证据 `{finding.evidence_id}`）")
        if finding.caveat:
            lines.append(f"  - 限定：{finding.caveat}")
    if not result.findings:
        lines.append("- 当前没有足够的可验证记录形成结论。")

    lines.extend(["", "## 建议行动", ""])
    lines.extend(f"- {action}" for action in result.actions)
    if not result.actions:
        lines.append("- 暂无自动生成的行动建议。")

    lines.extend(["", "## 图表", ""])
    for chart in result.charts:
        lines.append(f"- `{chart.chart_id}`：{chart.title}（{chart.kind}）")

    lines.extend(["", "## 数据明细", ""])
    for key, frame in result.tables.items():
        lines.extend([f"### {key}", "", _markdown_table(frame), ""])

    lines.extend(
        [
            "## 证据链",
            "",
            result.evidence.to_markdown(),
            "",
            "## 方法与边界",
            "",
            "- 所有数字、排名和筛选结果来自确定性 SQL/Python 内核；表达层不重新计算指标。",
            "- 零融资记录只表示在当前公开数据源中不可见，不等于企业从未获得融资。",
            "- 本报告不构成授信、投资、处罚或政策认定，需由业务人员核验原始材料。",
            "- 禁止凭空推断缺失字段，空数据不生成业务结论。",
        ]
    )
    return "\n".join(lines)


def _configure_plot_font() -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def render_charts(result: AnalysisResult, output_dir: Path) -> dict[str, Path]:
    _configure_plot_font()
    chart_paths: dict[str, Path] = {}
    for spec in result.charts:
        frame = result.tables.get(spec.data_key)
        if frame is None or frame.empty or spec.x not in frame or spec.y not in frame:
            continue
        data = frame[[spec.x, spec.y]].dropna().head(20).copy()
        if data.empty:
            continue
        figure, axis = plt.subplots(figsize=(10, 5.5), dpi=150)
        if spec.kind == "line":
            axis.plot(data[spec.x].astype(str), pd.to_numeric(data[spec.y], errors="coerce"), marker="o")
        else:
            data = data.iloc[::-1]
            axis.barh(data[spec.x].astype(str), pd.to_numeric(data[spec.y], errors="coerce"))
        axis.set_title(spec.title)
        axis.set_xlabel(spec.x)
        axis.set_ylabel(spec.y)
        figure.tight_layout()
        target = output_dir / f"{_safe_filename(spec.chart_id)}.png"
        figure.savefig(target, bbox_inches="tight")
        plt.close(figure)
        chart_paths[spec.chart_id] = target
    return chart_paths


def _html_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "<p>无记录。</p>"
    return frame.head(20).to_html(index=False, classes="data-table", border=0)


def _write_html(result: AnalysisResult, chart_paths: dict[str, Path], target: Path) -> None:
    finding_html = "".join(
        f"<li>{html.escape(item.text)} <small>证据 {html.escape(item.evidence_id)}</small>"
        f"<br><em>{html.escape(item.caveat)}</em></li>"
        for item in result.findings
    )
    action_html = "".join(f"<li>{html.escape(item)}</li>" for item in result.actions)
    chart_html = "".join(
        f"<h3>{html.escape(spec.title)}</h3><img src='{html.escape(chart_paths[spec.chart_id].name)}'>"
        for spec in result.charts
        if spec.chart_id in chart_paths
    )
    tables_html = "".join(
        f"<h3>{html.escape(key)}</h3>{_html_table(frame)}" for key, frame in result.tables.items()
    )
    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(result.title)}</title>
<style>
body {{ max-width: 1180px; margin: 2rem auto; font-family: Arial, sans-serif; color: #202124; line-height: 1.6; }}
h1 {{ border-bottom: 2px solid #1f6f8b; padding-bottom: .5rem; }}
img {{ max-width: 100%; height: auto; margin-bottom: 1rem; }}
.data-table {{ border-collapse: collapse; width: 100%; font-size: .88rem; }}
.data-table th, .data-table td {{ border: 1px solid #d8dee4; padding: .35rem .5rem; text-align: left; }}
.data-table th {{ background: #edf4f7; }}
small {{ color: #586069; }}
em {{ color: #805ad5; }}
</style>
</head>
<body>
<h1>{html.escape(result.title)}</h1>
<p><strong>问题：</strong>{html.escape(result.question)}</p>
<p><strong>场景：</strong>{html.escape(result.intent)}</p>
<h2>结论</h2><ul>{finding_html}</ul>
<h2>建议行动</h2><ul>{action_html}</ul>
<h2>图表</h2>{chart_html}
<h2>数据明细</h2>{tables_html}
<h2>证据链</h2>{result.evidence.to_markdown().replace("|", " | ")}
<h2>方法与边界</h2>
<ul>
<li>数字与筛选结果由确定性内核计算，表达层不改写指标。</li>
<li>零融资记录只表示当前数据源不可见，不等于从未融资。</li>
<li>报告不构成授信、投资、处罚或政策认定。</li>
</ul>
</body>
</html>"""
    target.write_text(body, encoding="utf-8")


def _write_pdf(result: AnalysisResult, chart_paths: dict[str, Path], target: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    font_name = "Helvetica"
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttf"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttf"),
    ):
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont("ChainLensFont", str(candidate)))
                font_name = "ChainLensFont"
                break
            except Exception:
                continue

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ChainLensBody",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=14,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#202124"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="ChainLensTitle",
            parent=styles["Title"],
            fontName=font_name,
            fontSize=18,
            leading=24,
        )
    )
    story = [Paragraph(html.escape(result.title), styles["ChainLensTitle"]), Spacer(1, 0.15 * inch)]
    story.append(Paragraph(f"问题：{html.escape(result.question)}", styles["ChainLensBody"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("结论", styles["Heading2"]))
    for finding in result.findings:
        story.append(Paragraph(f"• {html.escape(finding.text)} [证据 {finding.evidence_id}]", styles["ChainLensBody"]))
    story.append(Paragraph("建议行动", styles["Heading2"]))
    for action in result.actions:
        story.append(Paragraph(f"• {html.escape(action)}", styles["ChainLensBody"]))
    for chart_path in chart_paths.values():
        story.append(Spacer(1, 0.12 * inch))
        story.append(Image(str(chart_path), width=6.7 * inch, height=3.6 * inch))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("边界：数字来自确定性内核；零融资记录不等于从未融资；本报告不构成授信、投资或处罚认定。", styles["ChainLensBody"]))
    SimpleDocTemplate(str(target), pagesize=A4, title=result.title).build(story)


def write_artifacts(result: AnalysisResult, output_dir: str | Path) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result.report_markdown = compose_markdown(result)
    markdown_path = output / "chainlens_report.md"
    html_path = output / "chainlens_report.html"
    pdf_path = output / "chainlens_report.pdf"
    markdown_path.write_text(result.report_markdown, encoding="utf-8")
    chart_paths = render_charts(result, output)
    _write_html(result, chart_paths, html_path)
    _write_pdf(result, chart_paths, pdf_path)
    artifacts = {"markdown": markdown_path, "html": html_path, "pdf": pdf_path}
    artifacts.update({f"chart_{key}": path for key, path in chart_paths.items()})
    return artifacts
