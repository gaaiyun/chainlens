"""ChainLens 的确定性分析编排器。

这里的 Agent 是有明确职责的工作节点，不是让模型自由发挥的黑箱：
意图识别决定调用哪个内核，分析节点只消费结构化结果，报告节点只做表达，
Critic 节点在交付前拦截缺失证据。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..evidence import Evidence, EvidenceLedger
from ..kernels.credit import CreditResult, compute_credit_scores, financing_gap_summary, find_hidden_champions
from ..kernels.graph import build_industry_network
from ..kernels.qualification import analyze_qualification_cliff
from ..kernels.region import analyze_regions
from ..warehouse.access import Warehouse
from .autonomous import AutonomousAnalysisAgent
from .contracts import AgentTrace, AnalysisResult, ChartSpec, Finding
from .llm import LazyProvider, build_llm
from .reporting import write_artifacts


@dataclass
class _KernelCache:
    credit: CreditResult | None = None
    qualification: tuple[dict[str, pd.DataFrame], list[Evidence]] | None = None
    network: tuple[dict[str, object], list[Evidence]] | None = None


class ChainLensOrchestrator:
    """把中文问题路由到确定性内核，并产出可审计报告。"""

    def __init__(
        self,
        warehouse: Warehouse | None = None,
        *,
        autonomous_llm: object | None = None,
    ) -> None:
        self.warehouse = warehouse or Warehouse()
        self._owns_warehouse = warehouse is None
        self._cache = _KernelCache()
        self._autonomous_llm = autonomous_llm
        self._autonomous_runtime: AutonomousAnalysisAgent | None = None

    @staticmethod
    def classify(question: str) -> str:
        """基于可审计规则分类，避免把关键路由交给不可控的模型。"""
        text = (question or "").strip()
        if not text:
            raise ValueError("问题不能为空")
        if (
            any(keyword in text for keyword in ("融资盲区", "授信", "隐形冠军", "OCS", "数据黑户"))
            or ("融资" in text and any(keyword in text for keyword in ("没有", "无融资", "看不见")))
        ):
            return "financing"
        if any(keyword in text for keyword in ("续期", "到期", "过期", "资质悬崖")):
            return "qualification"
        if any(keyword in text for keyword in ("产业协作网络", "关键节点", "共现", "供应链关系")):
            return "network"
        if any(keyword in text for keyword in ("产业健康", "行业空转", "区县体检")):
            return "region"
        return "autonomous"

    def _autonomous_agent(self) -> AutonomousAnalysisAgent:
        if self._autonomous_runtime is None:
            llm = self._autonomous_llm or LazyProvider(build_llm)
            self._autonomous_runtime = AutonomousAnalysisAgent(
                warehouse=self.warehouse,
                llm=llm,
            )
        return self._autonomous_runtime

    @staticmethod
    def quality_gate(evidence: EvidenceLedger | Iterable[Evidence]) -> None:
        ledger = evidence if isinstance(evidence, EvidenceLedger) else EvidenceLedger()
        if not isinstance(evidence, EvidenceLedger):
            ledger.extend(evidence)
        if len(ledger) == 0:
            raise ValueError("报告缺少证据链，拒绝交付")
        if ledger.unverifiable:
            ids = ", ".join(item.evidence_id for item in ledger.unverifiable)
            raise ValueError(f"报告存在不可核查证据: {ids}")

    def _credit(self) -> CreditResult:
        if self._cache.credit is None:
            self._cache.credit = compute_credit_scores(self.warehouse)
        return self._cache.credit

    def _qualification(self) -> tuple[dict[str, pd.DataFrame], list[Evidence]]:
        if self._cache.qualification is None:
            self._cache.qualification = analyze_qualification_cliff(self.warehouse)
        return self._cache.qualification

    def _network(self) -> tuple[dict[str, object], list[Evidence]]:
        if self._cache.network is None:
            self._cache.network = build_industry_network(self.warehouse)
        return self._cache.network

    @staticmethod
    def _evidence_id(items: Iterable[Evidence], claim_part: str) -> str:
        for item in items:
            if claim_part in item.claim:
                return item.evidence_id
        raise ValueError(f"找不到结论证据: {claim_part}")

    def _run_financing(self) -> tuple[dict[str, pd.DataFrame], list[Finding], list[str], list[ChartSpec], list[Evidence]]:
        credit = self._credit()
        champions, champion_evidence = find_hidden_champions(credit)
        gap, gap_evidence = financing_gap_summary(credit)
        all_evidence = [*credit.evidence, *champion_evidence, *gap_evidence]
        champion_count = int(champion_evidence[0].value or 0)
        top_rate = gap.loc[gap["grade"].isin(["AA", "A"]), "融资覆盖率%"]
        rate_text = f"{float(top_rate.mean()):.2f}%" if not top_rate.empty else "暂无"
        findings = [
            Finding(
                text=f"按当前公开数据口径，筛出 {champion_count:,} 家有持续中标痕迹但无融资记录的企业线索。",
                evidence_id=champion_evidence[0].evidence_id,
                caveat="零融资记录只表示当前数据源不可见，不等于企业从未获得融资。",
            ),
            Finding(
                text=f"OCS 为 A/AA 的企业，其公开融资覆盖率均值为 {rate_text}。",
                evidence_id=gap_evidence[0].evidence_id,
                caveat="公开融资事件不等于银行信贷，不能替代授信尽调。",
            ),
        ]
        actions = [
            "将候选企业名单交给园区、银行或担保机构做二次核验，补充财务、纳税和实际订单材料。",
            "优先核验同时具备有效资质和持续中标记录的企业，形成可追踪的增信线索池。",
        ]
        charts = [
            ChartSpec("financing_by_grade", "不同信用等级的公开融资覆盖率", "bar", "financing_gap", "grade", "融资覆盖率%"),
            ChartSpec("champion_ocs", "融资盲区企业的 OCS 排名", "bar", "hidden_champions", "name", "ocs"),
        ]
        tables = {"financing_gap": gap, "hidden_champions": champions.head(50)}
        return tables, findings, actions, charts, all_evidence

    def _run_qualification(self) -> tuple[dict[str, pd.DataFrame], list[Finding], list[str], list[ChartSpec], list[Evidence]]:
        result, evidence = self._qualification()
        overview = result["overview"]
        lapsed = result["lapsed_firms"]
        upcoming = result["upcoming"]
        attention_count = int(
            overview.loc[overview["类别"] == "已过期（需关注）", "数量"].iloc[0]
        )
        findings = [
            Finding(
                text=f"剔除年度类制度性到期后，仍有 {attention_count:,} 条多年期资质记录需要关注。",
                evidence_id=self._evidence_id(evidence, "真实过期"),
                caveat="资质续期可能存在数据延迟，需以主管部门和企业原件复核。",
            ),
            Finding(
                text=f"未来 12 个月内到期的多年期资质清单共有 {len(upcoming):,} 条。",
                evidence_id=self._evidence_id(evidence, "未来 12 个月"),
                caveat="提醒用于减少漏续期风险，不代表资质一定会失效。",
            ),
        ]
        actions = [
            "按到期天数排序推送提醒，先核验 90 天内到期且与招投标业务相关的资质。",
            "对曾经有效但当前全部失效的企业建立续期回访名单，区分制度性年度到期和真实失效。",
        ]
        charts = [
            ChartSpec("qualification_by_type", "各资质类型的有效率", "bar", "by_type", "type_label", "有效率%"),
        ]
        tables = {
            "qualification_overview": overview,
            "upcoming": upcoming.head(100),
            "by_type": result["by_type"],
        }
        return tables, findings, actions, charts, [*evidence]

    def _run_network(self) -> tuple[dict[str, pd.DataFrame], list[Finding], list[str], list[ChartSpec], list[Evidence]]:
        result, evidence = self._network()
        stats = result["stats"]
        nodes: pd.DataFrame = result["nodes"]  # type: ignore[assignment]
        findings = [
            Finding(
                text=f"从招投标公告共现关系重建出 {stats['nodes']:,} 个企业节点和 {stats['edges']:,} 条关系边。",
                evidence_id=self._evidence_id(evidence, "节点数"),
                caveat="同公告共现是协作/竞争代理变量，不等同于已确权合同关系。",
            ),
            Finding(
                text=f"最大连通子图覆盖 {stats['giant_size']:,} 家企业，占网络节点 {stats['giant_size'] / stats['nodes'] * 100:.1f}%。",
                evidence_id=self._evidence_id(evidence, "最大连通"),
                caveat="网络覆盖度受公告公开程度和同公告企业数过滤规则影响。",
            ),
        ]
        actions = [
            "优先查看度数和加权强度最高的企业，核验其是否承担产业链枢纽、采购组织或联合体角色。",
            "对关键节点的上下游关系做人工核验，避免把竞争共现误判为合作关系。",
        ]
        charts = [ChartSpec("network_kinds", "产业网络关系类型", "bar", "kind_summary", "kind", "边数")]
        tables = {
            "network_stats": pd.DataFrame([stats]),
            "kind_summary": result["kind_summary"],
            "core_nodes": nodes.head(50),
        }
        return tables, findings, actions, charts, [*evidence]

    def _run_region(self) -> tuple[dict[str, pd.DataFrame], list[Finding], list[str], list[ChartSpec], list[Evidence]]:
        result, evidence = analyze_regions(self.warehouse, self._credit())
        by_district = result["by_district"]
        scored = by_district.dropna(subset=["产业健康指数"]).sort_values("产业健康指数", ascending=False)
        hollow = result["hollow_industries"]
        best = scored.iloc[0]["区县"] if not scored.empty else "暂无"
        findings = [
            Finding(
                text=f"在企业数达到最小样本门槛的区县中，产业健康指数最高的区县为 {best}。",
                evidence_id=self._evidence_id(evidence, "产业健康指数"),
                caveat="指数是本数据集内的相对排序，不具备跨数据集直接比较意义。",
            ),
            Finding(
                text=f"发现 {len(hollow):,} 个企业数较多但中标企业占比较低的行业，作为空转预警线索。",
                evidence_id=self._evidence_id(evidence, "空转预警"),
                caveat="低中标占比也可能因为行业不以招投标为主要交易方式，需要结合行业属性判断。",
            ),
        ]
        actions = [
            "对健康指数较低且企业规模较大的区县拆解融资、资质和中标覆盖率，形成针对性扶持清单。",
            "对空转行业先补充税收、产值或专利等缺失维度，再决定是否采取产业政策行动。",
        ]
        charts = [ChartSpec("district_health", "区县产业健康指数", "bar", "district_health", "区县", "产业健康指数")]
        tables = {
            "district_health": scored.head(50),
            "industry_hollow": hollow.head(50),
            "founding_trend": result["founding_trend"],
            "bidding_trend": result["bidding_trend"],
        }
        return tables, findings, actions, charts, [*evidence]

    def _run_overview(self) -> tuple[dict[str, pd.DataFrame], list[Finding], list[str], list[ChartSpec], list[Evidence]]:
        financing = self._run_financing()
        qualification = self._run_qualification()
        network = self._run_network()
        region = self._run_region()
        tables = {
            "financing_gap": financing[0]["financing_gap"],
            "qualification_overview": qualification[0]["qualification_overview"],
            "network_stats": network[0]["network_stats"],
            "district_health": region[0]["district_health"],
        }
        return (
            tables,
            [*financing[1][:1], *qualification[1][:1], *network[1][:1], *region[1][:1]],
            [
                "先从融资盲区和资质到期提醒两个低成本动作开始，形成可交付的企业服务闭环。",
                "对网络枢纽和区域差异进行人工核验，再决定是否进入政策或金融协同流程。",
            ],
            [
                ChartSpec("district_health", "区县产业健康指数", "bar", "district_health", "区县", "产业健康指数"),
            ],
            [*financing[4], *qualification[4], *network[4], *region[4]],
        )

    def run(self, question: str, output_dir: str | Path | None = None) -> AnalysisResult:
        trace: list[AgentTrace] = []
        try:
            intent = self.classify(question)
            trace.append(AgentTrace("IntentAgent", "passed", f"路由到 {intent}"))
            if intent == "autonomous":
                result = self._autonomous_agent().run(question)
                result.trace.insert(0, trace[0])
                if output_dir is not None:
                    result.artifacts = write_artifacts(result, output_dir)
                    result.trace.append(
                        AgentTrace(
                            "ArtifactAgent",
                            "passed",
                            f"写入 {len(result.artifacts)} 个产物",
                        )
                    )
                return result
            runners = {
                "financing": self._run_financing,
                "qualification": self._run_qualification,
                "network": self._run_network,
                "region": self._run_region,
            }
            tables, findings, actions, charts, evidence = runners[intent]()
            trace.append(AgentTrace("KernelAgent", "passed", f"生成 {len(tables)} 个结果表"))
            ledger = EvidenceLedger()
            ledger.extend(evidence)
            self.quality_gate(ledger)
            trace.append(AgentTrace("CriticAgent", "passed", f"检查 {len(ledger)} 条证据"))
            title = {
                "financing": "智能制造企业融资可见性分析",
                "qualification": "智能制造企业资质续期风险分析",
                "network": "智能制造产业协作网络分析",
                "region": "智能制造区域产业健康分析",
            }[intent]
            result = AnalysisResult(
                question=question,
                intent=intent,
                title=title,
                tables=tables,
                findings=findings,
                actions=actions,
                charts=charts,
                evidence=ledger,
                trace=trace,
                metadata={"engine": "deterministic-kernels", "llm_used": False},
            )
            from .reporting import compose_markdown

            result.report_markdown = compose_markdown(result)
            trace.append(AgentTrace("ReportAgent", "passed", "生成 Markdown 报告"))
            if output_dir is not None:
                result.artifacts = write_artifacts(result, output_dir)
                trace.append(AgentTrace("ArtifactAgent", "passed", f"写入 {len(result.artifacts)} 个产物"))
            trace.append(AgentTrace("CriticAgent", "passed", "交付前质量门通过"))
            return result
        except Exception as exc:
            trace.append(AgentTrace("Pipeline", "failed", f"{type(exc).__name__}: {exc}"))
            raise

    def close(self) -> None:
        if self._owns_warehouse:
            self.warehouse.close()
