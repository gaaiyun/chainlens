"""区域产业体检：把 133 个区县 × 175 个行业的家底摊开看。

政府侧的真实痛点不是"我们有多少家企业"，而是：
- 我这个区的产业到底是活的还是挂着的？
- 哪些行业只有壳、没有单？
- 哪些区县的企业有能力却拿不到资源？

这个内核输出四类可直接用于决策的指标，全部可下钻到企业名单。
"""

from __future__ import annotations

import pandas as pd

from ..evidence import Evidence
from ..kernels.credit import CreditResult
from ..warehouse.access import Warehouse
from ..warehouse.reference import city_name, district_name, industry_name

MIN_FIRMS_FOR_INDEX = 20  # 样本过小的区县/行业不计算指数，只列出，避免小样本噪声


def _health_index(frame: pd.DataFrame) -> pd.Series:
    """区域产业健康指数 = 活跃度 40% + 信用水平 30% + 资质覆盖 20% + 资本渗透 10%。

    四个分项都先在区县之间做分位归一，指数本身只有相对意义，不做跨库比较。
    """
    parts = {
        "活跃度": frame["中标企业占比"],
        "信用水平": frame["平均OCS"],
        "资质覆盖": frame["资质覆盖率"],
        "资本渗透": frame["融资覆盖率"],
    }
    weights = {"活跃度": 0.40, "信用水平": 0.30, "资质覆盖": 0.20, "资本渗透": 0.10}
    index = pd.Series(0.0, index=frame.index)
    for key, series in parts.items():
        ranked = series.rank(pct=True)
        index += ranked * weights[key]
    return (index * 100).round(1)


def analyze_regions(wh: Warehouse, credit: CreditResult) -> tuple[dict[str, pd.DataFrame], list[Evidence]]:
    df = credit.scores.copy()
    df["有中标"] = df["win_projects"] > 0
    df["有资质"] = df["qual_total"] > 0
    df["有有效资质"] = df["qual_valid"] > 0
    df["有融资"] = df["has_financing"]

    # ---- 区县维度 ---------------------------------------------------------
    by_district = (
        df.groupby("district_code", dropna=False)
        .agg(
            企业数=("eid", "count"),
            中标企业数=("有中标", "sum"),
            资质企业数=("有资质", "sum"),
            融资企业数=("有融资", "sum"),
            平均OCS=("ocs", "mean"),
            中位注册资本=("regist_capi_wan", "median"),
            平均存续年限=("age_years", "mean"),
            中标项目总数=("win_projects", "sum"),
        )
        .reset_index()
    )
    by_district["区县"] = by_district["district_code"].map(district_name)
    by_district["城市"] = by_district["district_code"].map(city_name)
    by_district["中标企业占比"] = (by_district["中标企业数"] / by_district["企业数"] * 100).round(2)
    by_district["资质覆盖率"] = (by_district["资质企业数"] / by_district["企业数"] * 100).round(2)
    by_district["融资覆盖率"] = (by_district["融资企业数"] / by_district["企业数"] * 100).round(2)
    by_district["平均OCS"] = by_district["平均OCS"].round(1)
    by_district["平均存续年限"] = by_district["平均存续年限"].round(1)

    scored = by_district[by_district["企业数"] >= MIN_FIRMS_FOR_INDEX].copy()
    scored["产业健康指数"] = _health_index(scored)
    by_district = by_district.merge(
        scored[["district_code", "产业健康指数"]], on="district_code", how="left"
    ).sort_values("企业数", ascending=False).reset_index(drop=True)

    # ---- 城市维度 ---------------------------------------------------------
    by_city = (
        by_district.groupby("城市")
        .agg(
            企业数=("企业数", "sum"),
            中标企业数=("中标企业数", "sum"),
            资质企业数=("资质企业数", "sum"),
            融资企业数=("融资企业数", "sum"),
            中标项目总数=("中标项目总数", "sum"),
        )
        .reset_index()
    )
    by_city["中标企业占比"] = (by_city["中标企业数"] / by_city["企业数"] * 100).round(2)
    by_city["资质覆盖率"] = (by_city["资质企业数"] / by_city["企业数"] * 100).round(2)
    by_city["融资覆盖率"] = (by_city["融资企业数"] / by_city["企业数"] * 100).round(2)
    by_city = by_city.sort_values("企业数", ascending=False).reset_index(drop=True)

    # ---- 行业维度 ---------------------------------------------------------
    by_industry = (
        df.groupby("industry_code", dropna=False)
        .agg(
            企业数=("eid", "count"),
            中标企业数=("有中标", "sum"),
            资质企业数=("有资质", "sum"),
            融资企业数=("有融资", "sum"),
            平均OCS=("ocs", "mean"),
            中标项目总数=("win_projects", "sum"),
        )
        .reset_index()
    )
    by_industry["行业"] = by_industry["industry_code"].map(industry_name)
    by_industry["中标企业占比"] = (by_industry["中标企业数"] / by_industry["企业数"] * 100).round(2)
    by_industry["资质覆盖率"] = (by_industry["资质企业数"] / by_industry["企业数"] * 100).round(2)
    by_industry["融资覆盖率"] = (by_industry["融资企业数"] / by_industry["企业数"] * 100).round(2)
    by_industry["平均OCS"] = by_industry["平均OCS"].round(1)
    by_industry = by_industry.sort_values("企业数", ascending=False).reset_index(drop=True)

    # ---- 空转预警：企业多、但几乎没有真实交易痕迹的行业 --------------------
    hollow = by_industry[
        (by_industry["企业数"] >= 50) & (by_industry["中标企业占比"] < 10)
    ].sort_values("企业数", ascending=False).reset_index(drop=True)

    # ---- 成立与中标趋势 ---------------------------------------------------
    founding = wh.query(
        """
        SELECT CAST(year(start_date) AS INTEGER) AS 年份, count(*) AS 新设企业数
        FROM v_enterprise WHERE start_date IS NOT NULL AND year(start_date) >= 2000
        GROUP BY 1 ORDER BY 1
        """,
        enforce_limit=False,
    ).df

    bidding_trend = wh.query(
        """
        SELECT bid_year AS 年份,
               count(*) AS 招投标记录数,
               count(DISTINCT eid) AS 参与企业数,
               count(DISTINCT eid) FILTER (WHERE role_code = 30) AS 中标企业数
        FROM v_bidding WHERE bid_year IS NOT NULL AND bid_year >= 2012
        GROUP BY 1 ORDER BY 1
        """,
        enforce_limit=False,
    ).df

    evidence = [
        Evidence(
            kernel="region.Health",
            claim="纳入产业健康指数的区县数",
            value=int(len(scored)),
            unit=" 个",
            sql=f"按 district_code 聚合，仅保留企业数 >= {MIN_FIRMS_FOR_INDEX} 的区县",
            row_count=int(len(by_district)),
            confidence=0.9,
            caveats=("指数为区县间相对排序，不具备跨数据集可比性",),
        ),
        Evidence(
            kernel="region.Health",
            claim="企业数≥50 但中标企业占比<10% 的行业数（空转预警）",
            value=int(len(hollow)),
            unit=" 个",
            sql="按 industry_code 聚合后筛选 企业数>=50 且 中标企业占比<10",
            row_count=int(len(hollow)),
            confidence=0.8,
            caveats=(
                "低中标占比也可能因该行业本身不以招投标为主要交易方式，需结合行业属性判断",
            ),
        ),
        Evidence(
            kernel="region.Health",
            claim="企业主体覆盖的区县数",
            value=int(df["district_code"].nunique()),
            unit=" 个",
            sql="SELECT count(DISTINCT district_code) FROM v_enterprise",
            row_count=int(df["district_code"].nunique()),
            confidence=1.0,
        ),
    ]

    return (
        {
            "by_district": by_district,
            "by_city": by_city,
            "by_industry": by_industry,
            "hollow_industries": hollow,
            "founding_trend": founding,
            "bidding_trend": bidding_trend,
        },
        evidence,
    )
