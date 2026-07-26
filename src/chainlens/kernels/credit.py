"""经营性信用分 OCS（Operational Credit Score）。

问题背景
--------
本库 17,576 家企业里只有 124 家有融资记录。剩下 99.3% 不是没有能力，
而是它们的能力从来没有被数据化——银行看不到抵押物之外的东西，
政府看不到名录之外的企业。

OCS 的目标就是：**用公共数据里的"真实经营痕迹"替代抵押物，给企业一个可解释的信用刻度。**

口径原则（重要）
----------------
1. **不使用中标金额做主特征。** 源库 `project_bid_money` 单位不一致
   （均值 2,966 而最大值 91,440,104，同一字段混用元/万元），
   直接求和会得出荒谬结论。所以 OCS 只用**频次、连续性、覆盖年份**这类单位无关的信号。
2. **同群体分位对标。** 绝对值天然利好大企业，与"发现隐形中小企业"的目标相悖，
   因此每个维度取分位数得分，而不是取绝对值。
3. **零信号即零分，不做中位数填充。** 没有记录就是没有记录，不允许算法替企业编造历史。
4. **每一维得分都可拆解、可回放。** 输出保留原始特征列，任何一分都能追到源数据。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..evidence import Evidence
from ..warehouse.access import Warehouse
from ..warehouse.reference import district_name, industry_name

# 维度权重，合计 100
WEIGHTS = {
    "delivery": 35,     # 履约能力：中标频次、连续性、近期活跃
    "continuity": 20,   # 经营持续性：存续年限、登记状态
    "credential": 20,   # 资质信用：资质数量、类型多样性、当前有效性
    "capital": 10,      # 资本实力：注册资本、实缴
    "network": 15,      # 产业网络：协作/竞争网络连接度、股权关联
}

WIN_ROLE_CODE = 30  # 经数据验证：role_code=30 的记录中 75.7% 带中标金额，为结果/中标角色
RECENT_YEARS = 3

FEATURE_SQL = f"""
WITH win AS (
    SELECT
        eid,
        count(DISTINCT project_number) FILTER (WHERE project_number IS NOT NULL) AS win_projects,
        count(*)                                              AS win_records,
        count(DISTINCT bid_year)                              AS win_years,
        max(bid_year)                                         AS last_win_year,
        min(bid_year)                                         AS first_win_year,
        count(DISTINCT area_code)                             AS win_areas
    FROM v_bidding
    WHERE role_code = {WIN_ROLE_CODE}
    GROUP BY eid
),
bid_all AS (
    SELECT eid, count(*) AS bid_records, count(DISTINCT bid_year) AS bid_years
    FROM v_bidding GROUP BY eid
),
qual AS (
    SELECT
        eid,
        count(*)                                          AS qual_total,
        count(*) FILTER (WHERE qual_state = '有效')        AS qual_valid,
        count(DISTINCT qual_type)                         AS qual_kinds,
        max(qual_year)                                    AS last_qual_year
    FROM v_qualification GROUP BY eid
),
fin AS (
    SELECT eid, count(*) AS fin_events, max(round_year) AS last_round_year,
           max(round_name) AS last_round_name
    FROM v_financing GROUP BY eid
),
eq_out AS (SELECT eid, count(DISTINCT invest_eid) AS invest_out FROM v_equity GROUP BY eid),
eq_in  AS (SELECT invest_eid AS eid, count(DISTINCT eid) AS invest_in FROM v_equity GROUP BY invest_eid)
SELECT
    e.eid, e.name, e.status, e.econ_kind, e.start_date, e.age_years,
    e.regist_capi_wan, e.actual_capi_wan, e.district_code, e.industry_code, e.industry_group,
    COALESCE(w.win_projects, 0)   AS win_projects,
    COALESCE(w.win_records, 0)    AS win_records,
    COALESCE(w.win_years, 0)      AS win_years,
    w.last_win_year,
    w.first_win_year,
    COALESCE(w.win_areas, 0)      AS win_areas,
    COALESCE(b.bid_records, 0)    AS bid_records,
    COALESCE(b.bid_years, 0)      AS bid_years,
    COALESCE(q.qual_total, 0)     AS qual_total,
    COALESCE(q.qual_valid, 0)     AS qual_valid,
    COALESCE(q.qual_kinds, 0)     AS qual_kinds,
    q.last_qual_year,
    COALESCE(f.fin_events, 0)     AS fin_events,
    f.last_round_year,
    f.last_round_name,
    COALESCE(o.invest_out, 0)     AS invest_out,
    COALESCE(i.invest_in, 0)      AS invest_in
FROM v_enterprise e
LEFT JOIN win     w ON e.eid = w.eid
LEFT JOIN bid_all b ON e.eid = b.eid
LEFT JOIN qual    q ON e.eid = q.eid
LEFT JOIN fin     f ON e.eid = f.eid
LEFT JOIN eq_out  o ON e.eid = o.eid
LEFT JOIN eq_in   i ON e.eid = i.eid
"""


def _pct(series: pd.Series) -> pd.Series:
    """正值内部做分位，零/缺失直接得 0——不给没有记录的企业编造分数。"""
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    out = pd.Series(0.0, index=s.index, dtype="float64")
    positive = s > 0
    if positive.sum() > 1:
        out.loc[positive] = s[positive].rank(pct=True)
    elif positive.sum() == 1:
        out.loc[positive] = 1.0
    return out


@dataclass
class CreditResult:
    scores: pd.DataFrame
    evidence: list[Evidence]
    current_year: int


def compute_credit_scores(wh: Warehouse) -> CreditResult:
    result = wh.query(FEATURE_SQL, enforce_limit=False)
    df = result.df.copy()
    evidence: list[Evidence] = []

    current_year = int(pd.Timestamp.today().year)
    recent_floor = current_year - RECENT_YEARS + 1

    # ---- 1. 履约能力 -----------------------------------------------------
    df["recent_active"] = (df["last_win_year"].fillna(0) >= recent_floor).astype(float)
    df["win_span"] = (df["last_win_year"].fillna(0) - df["first_win_year"].fillna(0)).clip(lower=0)
    delivery = (
        0.40 * _pct(df["win_projects"])
        + 0.20 * _pct(df["win_years"])
        + 0.15 * _pct(df["win_span"])
        + 0.15 * df["recent_active"]
        + 0.10 * _pct(df["win_areas"])
    )
    df["score_delivery"] = delivery * WEIGHTS["delivery"]

    # ---- 2. 经营持续性 ---------------------------------------------------
    age = pd.to_numeric(df["age_years"], errors="coerce").fillna(0).clip(0, 30)
    alive = df["status"].fillna("").str.contains("存续|在营|开业|在册", regex=True).astype(float)
    abnormal = df["status"].fillna("").str.contains("注销|吊销|解散|清算", regex=True).astype(float)
    continuity = (0.55 * (age / 30.0) + 0.45 * alive) * (1 - 0.8 * abnormal)
    df["score_continuity"] = continuity.clip(0, 1) * WEIGHTS["continuity"]

    # ---- 3. 资质信用 -----------------------------------------------------
    qual_fresh = (df["last_qual_year"].fillna(0) >= current_year - 2).astype(float)
    credential = (
        0.35 * _pct(df["qual_total"])
        + 0.30 * _pct(df["qual_valid"])
        + 0.20 * _pct(df["qual_kinds"])
        + 0.15 * qual_fresh
    )
    df["score_credential"] = credential * WEIGHTS["credential"]

    # ---- 4. 资本实力 -----------------------------------------------------
    capi = pd.to_numeric(df["regist_capi_wan"], errors="coerce").fillna(0).clip(lower=0)
    paid = pd.to_numeric(df["actual_capi_wan"], errors="coerce").fillna(0).clip(lower=0)
    capital = 0.70 * _pct(np.log1p(capi)) + 0.30 * (paid > 0).astype(float)
    df["score_capital"] = capital * WEIGHTS["capital"]

    # ---- 5. 产业网络 -----------------------------------------------------
    df["equity_links"] = df["invest_out"] + df["invest_in"]
    network = (
        0.45 * _pct(df["bid_records"])
        + 0.30 * _pct(df["equity_links"])
        + 0.25 * _pct(df["bid_years"])
    )
    df["score_network"] = network * WEIGHTS["network"]

    score_cols = [f"score_{k}" for k in WEIGHTS]
    df["ocs"] = df[score_cols].sum(axis=1).round(2)
    df["ocs_rank"] = df["ocs"].rank(ascending=False, method="min").astype(int)
    df["ocs_pct"] = (df["ocs"].rank(pct=True) * 100).round(1)

    df["grade"] = pd.cut(
        df["ocs"],
        bins=[-0.01, 20, 35, 50, 65, 100],
        labels=["D", "C", "B", "A", "AA"],
    ).astype(str)

    df["industry_name"] = df["industry_code"].map(industry_name)
    df["district_name"] = df["district_code"].map(district_name)
    df["has_financing"] = df["fin_events"] > 0

    # ---- 证据 ------------------------------------------------------------
    evidence.append(
        Evidence(
            kernel="credit.OCS",
            claim="纳入信用评分的企业总数",
            value=int(len(df)),
            unit=" 家",
            sql=FEATURE_SQL.strip(),
            row_count=int(len(df)),
            confidence=1.0,
            caveats=(
                "评分基于工商、招投标、资质、股权四类公开数据，不含财务报表与征信数据",
                "中标金额字段单位不一致，已从评分特征中剔除",
            ),
        )
    )
    evidence.append(
        Evidence(
            kernel="credit.OCS",
            claim="有真实中标记录的企业数",
            value=int((df["win_projects"] > 0).sum()),
            unit=" 家",
            sql=f"SELECT count(DISTINCT eid) FROM v_bidding WHERE role_code = {WIN_ROLE_CODE}",
            row_count=int((df["win_projects"] > 0).sum()),
            confidence=1.0,
            caveats=("role_code=30 经数据验证为结果/中标角色（该角色 75.7% 记录带中标金额）",),
        )
    )
    evidence.append(
        Evidence(
            kernel="credit.OCS",
            claim="有融资记录的企业数",
            value=int(df["has_financing"].sum()),
            unit=" 家",
            sql="SELECT count(DISTINCT eid) FROM v_financing",
            row_count=int(df["has_financing"].sum()),
            confidence=1.0,
        )
    )

    return CreditResult(scores=df, evidence=evidence, current_year=current_year)


# --------------------------------------------------------------------------
# 隐形冠军：有经营痕迹、有信用分，却从未进入资本视野的企业
# --------------------------------------------------------------------------

def find_hidden_champions(
    credit: CreditResult,
    *,
    min_ocs: float = 45.0,
    min_win_projects: int = 3,
    top_n: int = 300,
) -> tuple[pd.DataFrame, list[Evidence]]:
    df = credit.scores
    mask = (
        (~df["has_financing"])
        & (df["ocs"] >= min_ocs)
        & (df["win_projects"] >= min_win_projects)
        & (df["status"].fillna("").str.contains("存续|在营|开业|在册", regex=True))
    )
    champions = df.loc[mask].sort_values("ocs", ascending=False).head(top_n).copy()
    champions["gap_reason"] = np.where(
        champions["qual_valid"] > 0,
        "有有效资质 + 持续中标，但零融资记录",
        "持续中标但无有效资质背书，属于典型的「能干活、没标签」企业",
    )

    total_pool = int(mask.sum())
    evidence = [
        Evidence(
            kernel="credit.HiddenChampion",
            claim=f"OCS≥{min_ocs} 且中标项目≥{min_win_projects} 但零融资记录的企业数",
            value=total_pool,
            unit=" 家",
            sql=(
                "SELECT count(*) FROM (OCS 评分表) "
                f"WHERE fin_events = 0 AND ocs >= {min_ocs} AND win_projects >= {min_win_projects} "
                "AND status LIKE '%存续%'"
            ),
            row_count=total_pool,
            confidence=0.9,
            caveats=(
                "零融资记录不等于未获融资，只代表在本数据源中不可见",
                "该名单用于线索发现，不构成投资或授信建议",
            ),
        )
    ]
    return champions, evidence


def financing_gap_summary(credit: CreditResult) -> tuple[pd.DataFrame, list[Evidence]]:
    """按信用等级看融资可及性——回答"高分企业是不是真的拿到钱了"。"""
    df = credit.scores
    summary = (
        df.groupby("grade", observed=True)
        .agg(
            企业数=("eid", "count"),
            有融资企业数=("has_financing", "sum"),
            平均OCS=("ocs", "mean"),
            平均中标项目=("win_projects", "mean"),
            平均有效资质=("qual_valid", "mean"),
        )
        .reset_index()
    )
    summary["融资覆盖率%"] = (summary["有融资企业数"] / summary["企业数"] * 100).round(2)
    summary["平均OCS"] = summary["平均OCS"].round(1)
    summary["平均中标项目"] = summary["平均中标项目"].round(1)
    summary["平均有效资质"] = summary["平均有效资质"].round(2)
    order = {"AA": 0, "A": 1, "B": 2, "C": 3, "D": 4}
    summary = summary.sort_values("grade", key=lambda s: s.map(order)).reset_index(drop=True)

    top_grades = summary[summary["grade"].isin(["AA", "A"])]
    covered = int(top_grades["有融资企业数"].sum())
    total = int(top_grades["企业数"].sum())
    rate = round(covered / total * 100, 2) if total else 0.0

    evidence = [
        Evidence(
            kernel="credit.FinancingGap",
            claim="A 级及以上企业的融资覆盖率",
            value=rate,
            unit="%",
            sql="SELECT grade, count(*), sum(has_financing) FROM (OCS 评分表) GROUP BY grade",
            row_count=total,
            confidence=0.95,
            caveats=("融资记录来自公开融资事件库，未覆盖银行信贷与政府补助",),
        )
    ]
    return summary, evidence
