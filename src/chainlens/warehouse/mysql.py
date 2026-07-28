"""只读 MySQL 数据源适配器。

远程 MySQL 只提供事实数据。DuckDB 仍负责执行确定性内核使用的分析 SQL，
这样线上和离线共享同一套 v_* 视图契约与计算口径。
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("uvicorn.error")


class SQLConnection(Protocol):
    def execute(self, statement: str): ...


@dataclass(frozen=True)
class MySQLSettings:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_environment(cls) -> "MySQLSettings | None":
        suffix = "SCENARIO_1_3"
        host_key = f"DB_HOST_{suffix}"
        host = os.getenv(host_key, "").strip()
        if not host:
            return None

        values = {
            "database": os.getenv(f"DB_NAME_{suffix}", "").strip(),
            "user": os.getenv(f"DB_USER_{suffix}", "").strip(),
            "password": os.getenv(f"DB_PASSWORD_{suffix}", ""),
        }
        missing = [
            f"DB_{name.upper()}_{suffix}"
            for name, value in values.items()
            if not value
        ]
        if missing:
            raise ValueError(f"MySQL 配置不完整，缺少: {', '.join(missing)}")

        port_text = os.getenv(f"DB_PORT_{suffix}", "3306").strip()
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError(f"DB_PORT_{suffix} 必须是整数") from exc

        return cls(
            host=host,
            port=port,
            database=values["database"],
            user=values["user"],
            password=values["password"],
        )


def sql_string(value: str) -> str:
    """Return a DuckDB SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def sql_identifier(value: str) -> str:
    """Return a quoted DuckDB identifier."""
    return '"' + value.replace('"', '""') + '"'


def _analysis_views(database: str) -> str:
    source = f"source_mysql.{sql_identifier(database)}"
    return f"""
CREATE OR REPLACE TEMP VIEW v_enterprise AS
SELECT
    e.eid,
    e.name,
    e.credit_no,
    e.status,
    e.new_status_code,
    e.econ_kind,
    e.regist_capi_new AS regist_capi_wan,
    e.actual_capi AS actual_capi_wan,
    e.start_date,
    CAST(date_diff('day', e.start_date, CURRENT_DATE) / 365.25 AS DOUBLE) AS age_years,
    e.province_code,
    e.district_code,
    e.belong_org,
    e.scope,
    i.industry_code,
    substr(i.industry_code, 1, 1) AS industry_section,
    substr(i.industry_code, 1, 3) AS industry_group
FROM {source}."企业基本信息" e
LEFT JOIN {source}."企业行业代码" i USING (eid);

CREATE OR REPLACE TEMP VIEW v_bidding AS
SELECT
    cbid_eid AS eid,
    name,
    cbid_id AS bid_id,
    u_id,
    role1 AS role_code,
    title,
    publish_time,
    CAST(year(publish_time) AS INTEGER) AS bid_year,
    area_code,
    notice_type_main,
    notice_type_sub,
    project_number,
    project_bid_money
FROM {source}."招投标信息"
WHERE cbid_eid IS NOT NULL;

CREATE OR REPLACE TEMP VIEW v_financing AS
SELECT
    eid,
    ename AS name,
    id AS finance_id,
    round AS round_name,
    round_type,
    round_date,
    CAST(year(round_date) AS INTEGER) AS round_year,
    amount,
    estimated_amount,
    COALESCE(amount, estimated_amount) AS amount_filled,
    currency,
    investors
FROM {source}."融资数据"
WHERE eid IS NOT NULL;

CREATE OR REPLACE TEMP VIEW v_equity AS
SELECT
    cinv_eid AS eid,
    name,
    invest_eid,
    invest_name,
    invest_status,
    invest_start_date,
    stock_percent,
    should_capi_conv,
    real_capi
FROM {source}."企业投资股东信息"
WHERE cinv_eid IS NOT NULL;

CREATE OR REPLACE TEMP VIEW v_qualification AS
SELECT
    ct_eid AS eid,
    name,
    ct_id AS qual_id,
    ct_name AS qual_name,
    ct_type AS qual_type,
    ct_level AS qual_level,
    CAST(ct_year AS INTEGER) AS qual_year,
    ct_publish_date,
    ct_district AS qual_district,
    ct_district_code,
    ct_valid_start,
    ct_valid_end,
    ct_state AS qual_state
FROM {source}."商标资质信息"
WHERE ct_eid IS NOT NULL;
"""


def configure_mysql_source(connection: SQLConnection, settings: MySQLSettings) -> None:
    """Attach MySQL read-only and expose the canonical analysis views."""
    connection.execute("INSTALL mysql")
    connection.execute("LOAD mysql")
    connection.execute(
        f"""
CREATE SECRET chainlens_mysql (
    TYPE mysql,
    HOST {sql_string(settings.host)},
    PORT {settings.port},
    DATABASE {sql_string(settings.database)},
    USER {sql_string(settings.user)},
    PASSWORD {sql_string(settings.password)}
)
""".strip()
    )
    connection.execute(
        "ATTACH '' AS source_mysql "
        "(TYPE mysql, SECRET chainlens_mysql, READ_ONLY)"
    )
    connection.execute(_analysis_views(settings.database))


def materialize_analysis_views(connection: SQLConnection) -> None:
    """Copy the small analysis contract into local DuckDB tables.

    The MySQL extension is reliable for simple scans, but complex CTEs over
    remote relations are not a suitable production execution surface. Keeping
    the remote source read-only and materializing only the five approved views
    makes the kernels deterministic and keeps query latency predictable.
    """
    for view_name in (
        "v_enterprise",
        "v_bidding",
        "v_financing",
        "v_equity",
        "v_qualification",
    ):
        cache_name = f"chainlens_cache_{view_name}"
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE {cache_name} AS SELECT * FROM {view_name}"
        )
        connection.execute(f"DROP VIEW IF EXISTS {view_name}")
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW {view_name} AS SELECT * FROM {cache_name}"
        )
        logger.info("Materialized analysis view: %s", view_name)
