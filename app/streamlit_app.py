"""ChainLens 交互入口：页面只调用统一编排器。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from chainlens.agents import ChainLensOrchestrator  # noqa: E402


st.set_page_config(page_title="ChainLens 链见", page_icon="C", layout="wide")
st.title("ChainLens 链见")
st.caption("智能制造产业数据要素分析：数字由确定性内核计算，报告由证据链驱动。")

PRESETS = {
    "融资可见性": "请找出有真实中标能力但没有融资记录的智能制造企业",
    "资质续期": "未来一年哪些多年期资质需要续期，哪些企业曾有效但现在全部失效",
    "产业网络": "智能制造产业链中哪些企业是关键节点，供需和协作关系如何",
    "区域体检": "比较不同区县的产业健康和行业空转预警",
}


@st.cache_resource
def get_orchestrator() -> ChainLensOrchestrator:
    return ChainLensOrchestrator()


with st.sidebar:
    st.header("分析场景")
    preset = st.selectbox("选择问题模板", list(PRESETS))
    question = st.text_area("或直接输入问题", value=PRESETS[preset], height=100)
    run = st.button("生成决策简报", type="primary", use_container_width=True)
    st.divider()
    st.caption("数据源：本地 DuckDB 派生视图")
    st.caption("用途：线索发现与人工核验，不替代授信或政策认定")

if run:
    with st.spinner("正在运行确定性分析内核并整理证据..."):
        output_dir = Path(tempfile.mkdtemp(prefix="chainlens_report_"))
        result = get_orchestrator().run(question, output_dir=output_dir)
    st.session_state["chainlens_result"] = result

result = st.session_state.get("chainlens_result")
if result is None:
    st.info("从左侧选择一个场景并生成简报。")
else:
    st.subheader(result.title)
    st.write(f"场景：`{result.intent}`　证据：`{len(result.evidence)}` 条　LLM：未使用")

    st.markdown("### 结论")
    for finding in result.findings:
        st.markdown(f"- {finding.text}（证据 `{finding.evidence_id}`）")
        if finding.caveat:
            st.caption(f"限定：{finding.caveat}")

    st.markdown("### 建议行动")
    for action in result.actions:
        st.markdown(f"- {action}")

    st.markdown("### 图表")
    for key, path in result.artifacts.items():
        if key.startswith("chart_") and path.exists():
            st.image(str(path), caption=key.removeprefix("chart_"))

    st.markdown("### 数据明细")
    for key, frame in result.tables.items():
        with st.expander(key, expanded=key in {"financing_gap", "qualification_overview"}):
            st.dataframe(frame.head(100), use_container_width=True, hide_index=True)

    st.markdown("### 证据链")
    st.markdown(result.evidence.to_markdown())

    st.markdown("### 下载")
    columns = st.columns(3)
    for column, kind, label, mime in (
        (columns[0], "markdown", "下载 Markdown", "text/markdown"),
        (columns[1], "html", "下载 HTML", "text/html"),
        (columns[2], "pdf", "下载 PDF", "application/pdf"),
    ):
        path = result.artifacts.get(kind)
        if path and path.exists():
            column.download_button(label, path.read_bytes(), file_name=path.name, mime=mime)
