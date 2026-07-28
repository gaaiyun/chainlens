"""LangGraph runtime for bounded autonomous NL2SQL analysis."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, TypedDict

import pandas as pd
from langgraph.graph import END, StateGraph

from ..evidence import Evidence, EvidenceLedger
from ..warehouse.access import UnsafeQueryError, Warehouse, validate_sql
from .contracts import AgentTrace, AnalysisResult, ChartSpec, Finding
from .llm import LLMConfigurationError
from .reporting import compose_markdown
from .schema_context import (
    SCHEMA_CONTEXT,
    generation_prompt,
    plan_common_question,
    repair_prompt,
)


@dataclass(frozen=True)
class SQLPlan:
    title: str
    sql: str
    chart: dict[str, str] | None = None


class AutonomousAnalysisError(RuntimeError):
    def __init__(self, message: str, *, trace: list[AgentTrace] | None = None) -> None:
        super().__init__(message)
        self.trace = trace or []


class AutonomousState(TypedDict, total=False):
    question: str
    schema: str
    plan: SQLPlan
    safe_sql: str
    safety: dict[str, Any]
    frame: pd.DataFrame
    trace: list[AgentTrace]
    attempts: int
    last_error: str
    execution_ok: bool
    result: AnalysisResult
    planner: str


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)


def parse_sql_plan(text: str) -> SQLPlan:
    raw = (text or "").strip()
    match = _FENCE.match(raw)
    if match:
        raw = match.group(1).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM 未返回有效 JSON 计划") from exc
    if not isinstance(payload, dict):
        raise ValueError("SQL 计划 JSON 必须是对象")
    title = str(payload.get("title") or "").strip()
    sql = str(payload.get("sql") or "").strip()
    chart = payload.get("chart")
    if not title or not sql:
        raise ValueError("SQL 计划缺少 title 或 sql")
    if chart is not None and not isinstance(chart, dict):
        raise ValueError("chart 必须是对象或 null")
    normalized_chart = None
    if chart:
        normalized_chart = {
            "kind": str(chart.get("kind") or "bar"),
            "x": str(chart.get("x") or ""),
            "y": str(chart.get("y") or ""),
            "title": str(chart.get("title") or title),
        }
    return SQLPlan(title=title, sql=sql, chart=normalized_chart)


def enforce_autonomous_sql(sql: str, max_limit: int = 500) -> tuple[str, dict[str, Any]]:
    if re.search(
        r"\bSELECT\s+(?:DISTINCT\s+)?(?:[A-Za-z_][\w$]*\.)?\*",
        sql,
        re.IGNORECASE,
    ):
        raise UnsafeQueryError("自主分析拒绝 SELECT *，必须显式列出字段")
    try:
        safe = validate_sql(sql)
    except UnsafeQueryError as exc:
        raise UnsafeQueryError(str(exc)) from exc
    modifications: list[str] = []
    match = _LIMIT.search(safe)
    if match is None:
        safe = f"{safe}\nLIMIT {max_limit}"
        modifications.append(f"自动添加 LIMIT {max_limit}")
    elif int(match.group(1)) > max_limit:
        safe = _LIMIT.sub(f"LIMIT {max_limit}", safe)
        modifications.append(f"LIMIT 截断为 {max_limit}")
    return safe, {
        "is_safe": True,
        "errors": [],
        "modifications": modifications,
        "safe_sql": safe,
    }


def _display_value(value: Any) -> str:
    if pd.isna(value):
        return "空值"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


class AutonomousAnalysisAgent:
    def __init__(
        self,
        *,
        warehouse: Warehouse,
        llm: Any,
        max_retries: int = 2,
        max_limit: int = 500,
    ) -> None:
        self.warehouse = warehouse
        self.llm = llm
        self.max_retries = max_retries
        self.max_limit = max_limit
        self._plan_cache: dict[str, SQLPlan] = {}
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(AutonomousState)
        graph.add_node("retrieve_schema", self._retrieve_schema)
        graph.add_node("generate_sql", self._generate_sql)
        graph.add_node("validate_sql", self._validate_sql)
        graph.add_node("execute_sql", self._execute_sql)
        graph.add_node("repair_sql", self._repair_sql)
        graph.add_node("profile_result", self._profile_result)
        graph.add_node("compose_result", self._compose_result)
        graph.set_entry_point("retrieve_schema")
        graph.add_edge("retrieve_schema", "generate_sql")
        graph.add_edge("generate_sql", "validate_sql")
        graph.add_conditional_edges(
            "validate_sql",
            self._after_validate,
            {"execute": "execute_sql", "repair": "repair_sql", "end": END},
        )
        graph.add_conditional_edges(
            "execute_sql",
            self._after_execute,
            {"profile": "profile_result", "repair": "repair_sql", "end": END},
        )
        graph.add_edge("repair_sql", "validate_sql")
        graph.add_edge("profile_result", "compose_result")
        graph.add_edge("compose_result", END)
        return graph.compile()

    def run(self, question: str) -> AnalysisResult:
        state = self._graph.invoke(
            {
                "question": question.strip(),
                "trace": [],
                "attempts": 0,
                "execution_ok": False,
            }
        )
        result = state.get("result")
        if result is None:
            raise AutonomousAnalysisError(
                state.get("last_error") or "自主分析失败",
                trace=state.get("trace") or [],
            )
        return result

    def _retrieve_schema(self, state: AutonomousState) -> dict[str, Any]:
        trace = state["trace"]
        trace.append(AgentTrace("SchemaAgent", "passed", "加载 5 个白名单分析视图"))
        return {"schema": SCHEMA_CONTEXT, "trace": trace}

    def _generate_sql(self, state: AutonomousState) -> dict[str, Any]:
        trace = state["trace"]
        common = plan_common_question(state["question"])
        if common is not None:
            planned = SQLPlan(
                title=str(common["title"]),
                sql=str(common["sql"]),
                chart=common.get("chart"),
            )
            trace.append(
                AgentTrace(
                    "SQLGenerationAgent",
                    "passed",
                    "命中已验证的确定性 SQL 模板",
                )
            )
            return {
                "plan": planned,
                "planner": "deterministic_template",
                "trace": trace,
                "last_error": "",
            }
        cache_key = state["question"].strip().lower()
        if cache_key in self._plan_cache:
            trace.append(
                AgentTrace("SQLGenerationAgent", "passed", "复用进程内已验证 SQL 计划")
            )
            return {
                "plan": self._plan_cache[cache_key],
                "planner": "llm_cache",
                "trace": trace,
                "last_error": "",
            }
        try:
            plan = parse_sql_plan(self.llm.complete(generation_prompt(state["question"])))
            trace.append(AgentTrace("SQLGenerationAgent", "passed", "生成结构化 SQL 计划"))
            return {"plan": plan, "planner": "llm", "trace": trace, "last_error": ""}
        except LLMConfigurationError:
            raise
        except Exception as exc:
            message = f"计划生成失败: {exc}"
            trace.append(AgentTrace("SQLGenerationAgent", "failed", message))
            return {"trace": trace, "last_error": message}

    def _validate_sql(self, state: AutonomousState) -> dict[str, Any]:
        trace = state["trace"]
        plan = state.get("plan")
        if plan is None:
            return {"last_error": state.get("last_error") or "缺少 SQL 计划"}
        try:
            safe_sql, safety = enforce_autonomous_sql(plan.sql, self.max_limit)
            trace.append(AgentTrace("SQLSafetyAgent", "passed", "SELECT/白名单/LIMIT 校验通过"))
            return {
                "safe_sql": safe_sql,
                "safety": safety,
                "trace": trace,
                "last_error": "",
            }
        except LLMConfigurationError:
            raise
        except Exception as exc:
            message = f"SQL 安全校验失败: {exc}"
            trace.append(AgentTrace("SQLSafetyAgent", "failed", message))
            return {
                "safety": {"is_safe": False, "errors": [str(exc)], "safe_sql": None},
                "trace": trace,
                "last_error": message,
            }

    def _after_validate(self, state: AutonomousState) -> str:
        if state.get("safety", {}).get("is_safe"):
            return "execute"
        return "repair" if int(state.get("attempts", 0)) < self.max_retries else "end"

    def _execute_sql(self, state: AutonomousState) -> dict[str, Any]:
        trace = state["trace"]
        try:
            query = self.warehouse.query(state["safe_sql"], enforce_limit=False)
            trace.append(
                AgentTrace(
                    "SQLExecutionAgent",
                    "passed",
                    f"执行完成，返回 {query.row_count} 行",
                )
            )
            return {
                "frame": query.df,
                "execution_ok": True,
                "trace": trace,
                "last_error": "",
            }
        except Exception as exc:
            message = f"SQL 执行失败: {type(exc).__name__}: {exc}"
            trace.append(AgentTrace("SQLExecutionAgent", "failed", message))
            return {"execution_ok": False, "trace": trace, "last_error": message}

    def _after_execute(self, state: AutonomousState) -> str:
        if state.get("execution_ok"):
            return "profile"
        return "repair" if int(state.get("attempts", 0)) < self.max_retries else "end"

    def _repair_sql(self, state: AutonomousState) -> dict[str, Any]:
        trace = state["trace"]
        attempts = int(state.get("attempts", 0)) + 1
        previous = state.get("plan")
        previous_text = json.dumps(
            {
                "title": previous.title if previous else "",
                "sql": previous.sql if previous else "",
                "chart": previous.chart if previous else None,
            },
            ensure_ascii=False,
        )
        try:
            repaired = parse_sql_plan(
                self.llm.complete(
                    repair_prompt(
                        state["question"],
                        previous_text,
                        state.get("last_error") or "未知错误",
                    )
                )
            )
            trace.append(AgentTrace("RepairSQLAgent", "passed", f"完成第 {attempts} 次修复"))
            return {
                "plan": repaired,
                "planner": "llm_repair",
                "attempts": attempts,
                "execution_ok": False,
                "trace": trace,
                "last_error": "",
            }
        except Exception as exc:
            message = f"SQL 修复失败: {exc}"
            trace.append(AgentTrace("RepairSQLAgent", "failed", message))
            return {"attempts": attempts, "trace": trace, "last_error": message}

    def _profile_result(self, state: AutonomousState) -> dict[str, Any]:
        trace = state["trace"]
        frame = state["frame"]
        trace.append(
            AgentTrace(
                "ResultProfiler",
                "passed",
                f"识别 {len(frame.columns)} 列、{len(frame)} 行",
            )
        )
        return {"trace": trace}

    def _compose_result(self, state: AutonomousState) -> dict[str, Any]:
        trace = state["trace"]
        frame = state["frame"]
        plan = state["plan"]
        safe_sql = state["safe_sql"]
        if state.get("planner") in {"llm", "llm_repair"}:
            self._plan_cache[state["question"].strip().lower()] = plan
        ledger = EvidenceLedger()
        findings: list[Finding] = []
        charts: list[ChartSpec] = []

        row_evidence = ledger.add(
            Evidence(
                kernel="autonomous.SQLResult",
                claim="查询结果行数",
                value=len(frame),
                unit=" 行",
                sql=safe_sql,
                row_count=len(frame),
                confidence=1.0,
                caveats=("结果受当前问题筛选条件与 LIMIT 上限约束",),
            )
        )
        if frame.empty:
            findings.append(
                Finding(
                    text="当前数据库中没有匹配记录，未生成进一步业务结论。",
                    evidence_id=row_evidence.evidence_id,
                    caveat="空结果不代表现实中不存在，只表示当前数据源未命中。",
                )
            )
        else:
            findings.append(
                Finding(
                    text=f"本次安全查询返回 {len(frame):,} 行结果。",
                    evidence_id=row_evidence.evidence_id,
                    caveat="结果只覆盖当前数据库和查询条件。",
                )
            )

        chart = plan.chart or {}
        x = chart.get("x", "")
        y = chart.get("y", "")
        if (
            not frame.empty
            and x in frame.columns
            and y in frame.columns
            and pd.api.types.is_numeric_dtype(frame[y])
        ):
            numeric = pd.to_numeric(frame[y], errors="coerce")
            valid = numeric.dropna()
            if not valid.empty:
                top_index = valid.idxmax()
                label = frame.loc[top_index, x]
                value = valid.loc[top_index]
                top_evidence = ledger.add(
                    Evidence(
                        kernel="autonomous.ResultProfiler",
                        claim=f"{y}最高的{x}",
                        value=_display_value(value),
                        unit="",
                        sql=safe_sql,
                        row_count=len(frame),
                        confidence=1.0,
                        caveats=("最高项仅在当前查询返回结果内比较",),
                    )
                )
                findings.append(
                    Finding(
                        text=(
                            f"在当前结果中，{x}为“{_display_value(label)}”的"
                            f"{y}最高，为 {_display_value(value)}。"
                        ),
                        evidence_id=top_evidence.evidence_id,
                        caveat="这是描述性排序，不表示因果关系。",
                    )
                )
                kind = chart.get("kind", "bar")
                charts.append(
                    ChartSpec(
                        chart_id="autonomous_primary",
                        title=chart.get("title") or plan.title,
                        kind="line" if kind == "line" else "bar",
                        data_key="query_result",
                        x=x,
                        y=y,
                    )
                )

        result = AnalysisResult(
            question=state["question"],
            intent="autonomous",
            title=plan.title,
            tables={"query_result": frame},
            findings=findings,
            actions=[
                "将结果作为数据核验和业务初筛依据，重要决策需回看原始记录。",
                "需要扩大范围时调整问题中的时间、地区或行业条件后重新查询。",
            ],
            charts=charts,
            evidence=ledger,
            trace=trace,
            metadata={
                "engine": "langgraph-autonomous-sql",
                "workflow_backend": "langgraph",
                "llm_used": state.get("planner") != "deterministic_template",
                "planner": state.get("planner") or "llm",
                "llm_provider": getattr(
                    self.llm,
                    "last_provider",
                    getattr(self.llm, "name", type(self.llm).__name__),
                ),
                "sql": plan.sql,
                "safe_sql": safe_sql,
                "safety": state["safety"],
                "repair_attempts": int(state.get("attempts", 0)),
                "result_profile": {
                    "rows": len(frame),
                    "columns": [str(column) for column in frame.columns],
                },
            },
        )
        result.report_markdown = compose_markdown(result)
        trace.append(AgentTrace("ReportAgent", "passed", "生成确定性 Markdown 报告"))
        return {"result": result, "trace": trace}
