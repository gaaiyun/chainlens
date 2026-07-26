from __future__ import annotations

import pandas as pd
import pytest

from chainlens.kernels.credit import CreditResult, compute_credit_scores, financing_gap_summary, find_hidden_champions
from chainlens.kernels.graph import build_industry_network
from chainlens.kernels.qualification import analyze_qualification_cliff
from chainlens.kernels.region import analyze_regions
from chainlens.warehouse.access import Warehouse


@pytest.fixture(scope="session")
def warehouse() -> Warehouse:
    wh = Warehouse()
    yield wh
    wh.close()


@pytest.fixture(scope="session")
def credit(warehouse: Warehouse) -> CreditResult:
    return compute_credit_scores(warehouse)


@pytest.fixture(scope="session")
def qualification(warehouse: Warehouse) -> tuple[dict[str, pd.DataFrame], list]:
    return analyze_qualification_cliff(warehouse)


@pytest.fixture(scope="session")
def network(warehouse: Warehouse) -> tuple[dict[str, object], list]:
    return build_industry_network(warehouse)


def test_credit_scores_are_bounded_and_evidenced(credit: CreditResult) -> None:
    scores = credit.scores

    assert len(scores) >= 10_000
    assert scores["eid"].is_unique
    assert scores["ocs"].between(0, 100).all()
    assert scores["grade"].isin({"D", "C", "B", "A", "AA"}).all()
    assert all(item.is_verifiable for item in credit.evidence)
    assert all(item.sql.strip() for item in credit.evidence)


def test_hidden_champions_obey_screening_rule(credit: CreditResult) -> None:
    champions, evidence = find_hidden_champions(credit, top_n=50)

    assert len(champions) <= 50
    assert (~champions["has_financing"]).all()
    assert (champions["ocs"] >= 45).all()
    assert (champions["win_projects"] >= 3).all()
    assert champions["gap_reason"].notna().all()
    assert len(evidence) == 1
    assert evidence[0].is_verifiable


def test_financing_gap_has_one_row_per_observed_grade(credit: CreditResult) -> None:
    summary, evidence = financing_gap_summary(credit)

    assert not summary.empty
    assert summary["grade"].is_unique
    assert summary["融资覆盖率%"].between(0, 100).all()
    assert int(summary["企业数"].sum()) == len(credit.scores)
    assert len(evidence) == 1


def test_qualification_cliff_keeps_expiry_categories_separate(
    qualification: tuple[dict[str, pd.DataFrame], list],
) -> None:
    result, evidence = qualification
    overview = result["overview"]
    lapsed = result["lapsed_firms"]
    upcoming = result["upcoming"]

    assert set(overview["类别"]) >= {
        "资质记录总数",
        "当前有效",
        "已过期（制度性年度到期）",
        "已过期（需关注）",
    }
    assert int(overview.loc[overview["类别"] == "资质记录总数", "数量"].iloc[0]) >= 10_000
    assert (lapsed["有效数"] == 0).all()
    assert (lapsed["多年期过期数"] > 0).all()
    assert upcoming["days_to_expiry"].ge(0).all()
    assert upcoming["days_to_expiry"].le(365).all()
    assert len(evidence) == 4
    assert all(item.is_verifiable for item in evidence)


def test_industry_network_has_valid_simple_edges(
    network: tuple[dict[str, object], list],
) -> None:
    result, evidence = network
    stats = result["stats"]
    nodes = result["nodes"]
    edges = result["edges"]

    assert stats["nodes"] == len(nodes)
    assert stats["edges"] == len(edges)
    assert (edges["source"] != edges["target"]).all()
    assert (edges["weight"] >= 1).all()
    assert set(edges["kind"]).issubset({"供需", "协作", "竞争", "共现"})
    assert stats["giant_size"] <= stats["nodes"]
    assert len(evidence) == 3


def test_region_analysis_reconciles_enterprise_counts(
    warehouse: Warehouse,
    credit: CreditResult,
) -> None:
    result, evidence = analyze_regions(warehouse, credit)
    by_district = result["by_district"]
    by_city = result["by_city"]
    by_industry = result["by_industry"]

    assert int(by_district["企业数"].sum()) == len(credit.scores)
    assert int(by_city["企业数"].sum()) == len(credit.scores)
    assert int(by_industry["企业数"].sum()) == len(credit.scores)
    scored = by_district["产业健康指数"].dropna()
    assert scored.between(0, 100).all()
    assert set(result["founding_trend"].columns) == {"年份", "新设企业数"}
    assert {"年份", "招投标记录数", "参与企业数", "中标企业数"} <= set(
        result["bidding_trend"].columns
    )
    assert len(evidence) == 3
