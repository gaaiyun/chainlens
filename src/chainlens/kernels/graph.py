"""产业协作网络：从 59 万条招投标记录里把"谁和谁在一起干活"重建出来。

方法
----
同一条招投标公告（`u_id`）下出现的多家企业，构成一次真实的同台记录。
按角色组合区分边的语义：

| 角色对 | 语义 |
| --- | --- |
| 20 ↔ 30 | 采购方 ↔ 中标方，供需关系 |
| 30 ↔ 30 | 同一结果公告下的多个中标方，联合体/分包协作 |
| 51 ↔ 51 | 同台投标，竞争关系 |
| 其他 | 弱关联，仅计入共现 |

这是本项目最核心的**数据融合增值**：单看任何一条招投标记录都只是一则公告，
把 59 万条按公告聚合起来，才浮现出一张区域产业协作网络。
这张网络在任何单一政务系统里都不存在。

工程约束
--------
- 只保留同公告企业数在 [2, 25] 区间的记录。超过 25 家的多为集中招标批次，
  连成完全图会产生虚假稠密结构。
- 边按共现次数加权，只保留权重 ≥ 1 的边，节点度数用于信用分的网络维度。
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations

import networkx as nx
import pandas as pd

from ..evidence import Evidence
from ..warehouse.access import Warehouse
from ..warehouse.reference import district_name, industry_name

MAX_CLIQUE = 25
MIN_CLIQUE = 2

COOCCUR_SQL = f"""
WITH sized AS (
    SELECT u_id
    FROM v_bidding
    WHERE u_id IS NOT NULL
    GROUP BY u_id
    HAVING count(DISTINCT eid) BETWEEN {MIN_CLIQUE} AND {MAX_CLIQUE}
)
SELECT b.u_id, b.eid, b.role_code, b.bid_year
FROM v_bidding b
JOIN sized s ON b.u_id = s.u_id
WHERE b.eid IS NOT NULL
"""

NODE_SQL = """
SELECT eid, name, status, district_code, industry_code, regist_capi_wan, age_years
FROM v_enterprise
"""

ROLE_BUYER = 20.0
ROLE_WINNER = 30.0
ROLE_BIDDER = 51.0


def _edge_semantic(role_a: float, role_b: float) -> str:
    pair = {role_a, role_b}
    if pair == {ROLE_BUYER, ROLE_WINNER}:
        return "供需"
    if pair == {ROLE_WINNER}:
        return "协作"
    if pair == {ROLE_BIDDER}:
        return "竞争"
    return "共现"


def build_industry_network(wh: Warehouse) -> tuple[dict[str, object], list[Evidence]]:
    raw = wh.query(COOCCUR_SQL, enforce_limit=False).df
    nodes_meta = wh.query(NODE_SQL, enforce_limit=False).df.set_index("eid")

    edge_weight: Counter[tuple[str, str]] = Counter()
    edge_kind: dict[tuple[str, str], Counter[str]] = {}

    for _, group in raw.groupby("u_id", sort=False):
        members = group.drop_duplicates("eid")[["eid", "role_code"]].values.tolist()
        if len(members) < 2:
            continue
        for (eid_a, role_a), (eid_b, role_b) in combinations(members, 2):
            key = (eid_a, eid_b) if eid_a < eid_b else (eid_b, eid_a)
            edge_weight[key] += 1
            edge_kind.setdefault(key, Counter())[_edge_semantic(role_a, role_b)] += 1

    graph = nx.Graph()
    for (a, b), weight in edge_weight.items():
        kind = edge_kind[(a, b)].most_common(1)[0][0]
        graph.add_edge(a, b, weight=weight, kind=kind)

    # ---- 节点指标 ---------------------------------------------------------
    degree = dict(graph.degree())
    strength = dict(graph.degree(weight="weight"))
    try:
        core = nx.core_number(graph)
    except Exception:
        core = {n: 0 for n in graph}

    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    giant = components[0] if components else set()

    node_rows = []
    for node in graph.nodes:
        meta = nodes_meta.loc[node] if node in nodes_meta.index else None
        node_rows.append(
            {
                "eid": node,
                "name": (meta["name"] if meta is not None else None),
                "district_name": district_name(meta["district_code"]) if meta is not None else "未知",
                "industry_name": industry_name(meta["industry_code"]) if meta is not None else "未知",
                "degree": degree.get(node, 0),
                "strength": strength.get(node, 0),
                "core": core.get(node, 0),
                "in_giant": node in giant,
            }
        )
    node_df = pd.DataFrame(node_rows).sort_values("degree", ascending=False).reset_index(drop=True)

    edge_rows = [
        {"source": a, "target": b, "weight": w, "kind": edge_kind[(a, b)].most_common(1)[0][0]}
        for (a, b), w in edge_weight.items()
    ]
    edge_df = pd.DataFrame(edge_rows)

    kind_summary = (
        edge_df.groupby("kind")
        .agg(边数=("weight", "count"), 共现次数=("weight", "sum"))
        .reset_index()
        .sort_values("边数", ascending=False)
        if not edge_df.empty
        else pd.DataFrame(columns=["kind", "边数", "共现次数"])
    )

    stats = {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "components": len(components),
        "giant_size": len(giant),
        "density": round(nx.density(graph), 6) if graph.number_of_nodes() > 1 else 0.0,
        "avg_degree": round(2 * graph.number_of_edges() / graph.number_of_nodes(), 2)
        if graph.number_of_nodes()
        else 0.0,
    }

    evidence = [
        Evidence(
            kernel="graph.IndustryNetwork",
            claim="从招投标公告重建的产业协作网络节点数",
            value=stats["nodes"],
            unit=" 家企业",
            sql=COOCCUR_SQL.strip(),
            row_count=int(len(raw)),
            confidence=0.85,
            caveats=(
                "同公告共现是协作/竞争的代理变量，不等同于确权的合同关系",
                f"已剔除同公告企业数超过 {MAX_CLIQUE} 家的集中招标批次，避免虚假稠密",
            ),
        ),
        Evidence(
            kernel="graph.IndustryNetwork",
            claim="网络关系边数",
            value=stats["edges"],
            unit=" 条",
            sql="按 u_id 聚合后两两组合去重计数",
            row_count=stats["edges"],
            confidence=0.85,
        ),
        Evidence(
            kernel="graph.IndustryNetwork",
            claim="最大连通子图覆盖企业数",
            value=stats["giant_size"],
            unit=" 家",
            sql="networkx.connected_components 取最大分量",
            row_count=stats["giant_size"],
            confidence=0.9,
            caveats=("最大连通子图规模反映区域产业耦合程度，越大说明协作网络越完整",),
        ),
    ]

    return (
        {
            "stats": stats,
            "nodes": node_df,
            "edges": edge_df,
            "kind_summary": kind_summary,
            "graph": graph,
        },
        evidence,
    )


def extract_subgraph_for_viz(
    network: dict[str, object], top_n: int = 160, min_weight: int = 2
) -> dict[str, list[dict[str, object]]]:
    """给前端用的可视化子图：取度数最高的节点及其之间的强边。"""
    node_df: pd.DataFrame = network["nodes"]  # type: ignore[assignment]
    edge_df: pd.DataFrame = network["edges"]  # type: ignore[assignment]
    if node_df.empty or edge_df.empty:
        return {"nodes": [], "links": []}

    keep = set(node_df.head(top_n)["eid"])
    sub_edges = edge_df[
        edge_df["source"].isin(keep) & edge_df["target"].isin(keep) & (edge_df["weight"] >= min_weight)
    ]
    used = set(sub_edges["source"]) | set(sub_edges["target"])
    sub_nodes = node_df[node_df["eid"].isin(used)]

    return {
        "nodes": [
            {
                "id": r.eid,
                "name": r.name or r.eid[:8],
                "value": int(r.degree),
                "category": r.industry_name,
                "district": r.district_name,
            }
            for r in sub_nodes.itertuples()
        ],
        "links": [
            {"source": r.source, "target": r.target, "value": int(r.weight), "kind": r.kind}
            for r in sub_edges.itertuples()
        ],
    }
