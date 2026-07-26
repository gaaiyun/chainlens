"""资质悬崖：谁的"通行证"正在失效。

数据事实：本库 14,486 条资质记录里，11,738 条状态为"过期"，过期率 81%。
但直接把 81% 说成风险是错的——其中 110002 属于年度类认定，
有效期终点几乎全是当年 12 月 31 日，逐年失效是制度设计，不是企业问题。

这个内核做三件事：
1. 把"制度性到期"和"真实失效"分开，避免用一个吓人的数字误导决策。
2. 找出**曾经有效、现在全部过期**的企业——它们最可能是"忘了续期"而不是"不够格"。
3. 找出**未来 12 个月内到期**的资质，形成可直接推送的提醒清单。

社会价值：一张过期的资质，可能直接让企业失去投标资格、错过政策申报窗口。
这类损失完全可以用一条提醒避免，但前提是有人把这些数据连起来看。
"""

from __future__ import annotations

import pandas as pd

from ..evidence import Evidence
from ..warehouse.access import Warehouse
from ..warehouse.reference import credential_is_annual, credential_label, district_name

QUAL_SQL = """
SELECT
    q.eid,
    e.name,
    e.status,
    e.district_code,
    e.industry_code,
    q.qual_type,
    q.qual_level,
    q.qual_year,
    q.qual_state,
    q.ct_valid_start,
    q.ct_valid_end,
    try_strptime(q.ct_valid_end, '%Y-%m-%d')   AS valid_end_ts,
    try_strptime(q.ct_valid_start, '%Y-%m-%d') AS valid_start_ts
FROM v_qualification q
LEFT JOIN v_enterprise e ON q.eid = e.eid
"""


def analyze_qualification_cliff(wh: Warehouse) -> tuple[dict[str, pd.DataFrame], list[Evidence]]:
    res = wh.query(QUAL_SQL, enforce_limit=False)
    df = res.df.copy()
    evidence: list[Evidence] = []

    df["is_annual"] = df["qual_type"].map(credential_is_annual)
    df["type_label"] = df["qual_type"].map(credential_label)
    df["district_name"] = df["district_code"].map(district_name)

    today = pd.Timestamp.today().normalize()
    horizon = today + pd.Timedelta(days=365)
    df["valid_end_ts"] = pd.to_datetime(df["valid_end_ts"], errors="coerce")

    df["days_to_expiry"] = (df["valid_end_ts"] - today).dt.days

    total = len(df)
    expired = int((df["qual_state"] == "过期").sum())
    expired_structural = int(((df["qual_state"] == "过期") & df["is_annual"]).sum())
    expired_real = expired - expired_structural

    # ---- 1. 状态总览 ------------------------------------------------------
    overview = pd.DataFrame(
        [
            {"类别": "资质记录总数", "数量": total, "说明": "含全部类型与年份"},
            {"类别": "当前有效", "数量": int((df["qual_state"] == "有效").sum()), "说明": "在有效期内"},
            {"类别": "已过期（制度性年度到期）", "数量": expired_structural,
             "说明": "年度类认定按年失效，不代表企业能力下降"},
            {"类别": "已过期（需关注）", "数量": expired_real,
             "说明": "多年期资质到期未见续期记录，存在真实失效风险"},
            {"类别": "已撤销", "数量": int((df["qual_state"] == "撤销").sum()), "说明": "被主管部门撤销"},
        ]
    )

    # ---- 2. 全面失效企业：曾经有，现在一张有效的都没有 ---------------------
    per_firm = (
        df.groupby(["eid", "name", "district_name"], dropna=False)
        .agg(
            资质总数=("qual_type", "count"),
            有效数=("qual_state", lambda s: int((s == "有效").sum())),
            需关注过期数=("qual_state", "count"),
            最近年份=("qual_year", "max"),
        )
        .reset_index()
    )
    real_expired = (
        df[(df["qual_state"] == "过期") & (~df["is_annual"])]
        .groupby("eid")
        .size()
        .rename("多年期过期数")
    )
    per_firm = per_firm.merge(real_expired, on="eid", how="left")
    per_firm["多年期过期数"] = per_firm["多年期过期数"].fillna(0).astype(int)
    per_firm = per_firm.drop(columns=["需关注过期数"])

    lapsed = (
        per_firm[(per_firm["有效数"] == 0) & (per_firm["多年期过期数"] > 0)]
        .sort_values(["多年期过期数", "资质总数"], ascending=False)
        .reset_index(drop=True)
    )

    # ---- 3. 未来 12 个月到期清单 -----------------------------------------
    upcoming = df[
        (df["valid_end_ts"].notna())
        & (df["valid_end_ts"] >= today)
        & (df["valid_end_ts"] <= horizon)
        & (~df["is_annual"])
    ].copy()
    upcoming = upcoming[
        ["eid", "name", "district_name", "type_label", "qual_level", "ct_valid_start", "ct_valid_end", "days_to_expiry"]
    ].sort_values("days_to_expiry").reset_index(drop=True)

    # ---- 4. 按类型拆解 ----------------------------------------------------
    by_type = (
        df.groupby("type_label")
        .agg(
            记录数=("eid", "count"),
            企业数=("eid", "nunique"),
            有效数=("qual_state", lambda s: int((s == "有效").sum())),
        )
        .reset_index()
        .sort_values("记录数", ascending=False)
    )
    by_type["有效率%"] = (by_type["有效数"] / by_type["记录数"] * 100).round(1)

    # ---- 证据 -------------------------------------------------------------
    evidence.extend(
        [
            Evidence(
                kernel="qualification.Cliff",
                claim="资质记录总体过期率",
                value=round(expired / total * 100, 1) if total else 0.0,
                unit="%",
                sql="SELECT qual_state, count(*) FROM v_qualification GROUP BY qual_state",
                row_count=total,
                confidence=1.0,
                caveats=("该比例包含年度类认定的制度性到期，不能直接解读为风险",),
            ),
            Evidence(
                kernel="qualification.Cliff",
                claim="剔除年度类认定后的真实过期记录数",
                value=expired_real,
                unit=" 条",
                sql=(
                    "SELECT count(*) FROM v_qualification "
                    "WHERE qual_state = '过期' AND qual_type NOT IN (110002)"
                ),
                row_count=expired_real,
                confidence=0.85,
                caveats=("年度类判定依据有效期中位数推断，见 warehouse/reference.py",),
            ),
            Evidence(
                kernel="qualification.Cliff",
                claim="资质曾有效但当前无任何有效资质的企业数",
                value=int(len(lapsed)),
                unit=" 家",
                sql="按 eid 聚合资质状态，筛选 有效数=0 且 多年期过期数>0",
                row_count=int(len(lapsed)),
                confidence=0.9,
                caveats=("续期记录可能存在数据延迟，名单用于核实提醒而非处罚依据",),
            ),
            Evidence(
                kernel="qualification.Cliff",
                claim="未来 12 个月内到期的多年期资质数",
                value=int(len(upcoming)),
                unit=" 条",
                sql=(
                    "SELECT count(*) FROM v_qualification "
                    "WHERE try_strptime(ct_valid_end,'%Y-%m-%d') BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL 365 DAY"
                ),
                row_count=int(len(upcoming)),
                confidence=0.95,
            ),
        ]
    )

    return (
        {
            "overview": overview,
            "lapsed_firms": lapsed,
            "upcoming": upcoming,
            "by_type": by_type,
        },
        evidence,
    )
