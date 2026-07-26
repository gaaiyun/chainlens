"""Excel -> Parquet -> DuckDB 本地数据底座构建。

设计目标：
1. 任何人 clone 仓库后，只要拿到原始 Excel，一条命令就能重建完整数据底座。
2. 不依赖任何远程数据库、不依赖任何密钥，评审可离线复现。
3. 中间落 Parquet，重跑时秒级完成，避免反复解析大 Excel。
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = Path("G:/text2sql_0705")
DEFAULT_WAREHOUSE = REPO_ROOT / "data" / "warehouse" / "chainlens.duckdb"
DEFAULT_PARQUET_DIR = REPO_ROOT / "data" / "warehouse" / "parquet"


@dataclass(frozen=True)
class SourceTable:
    """一张源表的加载规格。"""

    name: str
    file: str
    engine: str | None = None
    datetime_columns: tuple[str, ...] = ()
    epoch_ms_columns: tuple[str, ...] = ()
    code_columns: tuple[str, ...] = ()
    numeric_columns: tuple[str, ...] = ()
    drop_columns: tuple[str, ...] = field(default_factory=tuple)


SOURCES: tuple[SourceTable, ...] = (
    SourceTable(
        name="enterprise",
        file="znjz_gzldata_step1.xls",
        engine="xlrd",
        datetime_columns=("start_date", "check_date", "revoke_date", "logout_date", "row_update_time"),
        epoch_ms_columns=("created_time",),
        code_columns=("province_code", "district_code", "econ_kind_code"),
        numeric_columns=("regist_capi_new", "actual_capi"),
        drop_columns=("logo_url", "url"),
    ),
    SourceTable(
        name="enterprise_industry",
        file="znjz_gzldata_step2.xlsx",
        datetime_columns=("start_date", "ci_start_date"),
        code_columns=("province_code", "district_code", "industry_code"),
        drop_columns=("logo_url", "url", "scope"),
    ),
    SourceTable(
        name="financing",
        file="znjz_gzldata_step3.xlsx",
        datetime_columns=("round_date", "publish_date"),
        code_columns=("province_code", "district_code"),
        numeric_columns=("amount", "estimated_amount", "post_money"),
        drop_columns=("logo_url", "url", "scope", "investors_json"),
    ),
    SourceTable(
        name="equity",
        file="znjz_gzldata_step4.xlsx",
        datetime_columns=("invest_start_date", "should_con_date"),
        numeric_columns=("stock_percent", "should_capi_conv", "should_capi", "real_capi"),
    ),
    SourceTable(
        name="bidding",
        file="znjz_gzldata_step5.xlsx",
        datetime_columns=("publish_time",),
        code_columns=("area_code",),
        numeric_columns=("project_bid_money",),
    ),
    SourceTable(
        name="qualification",
        file="znjz_gzldata_step6.xlsx",
        datetime_columns=("ct_publish_date", "ct_check_date", "ct_end_date"),
        code_columns=("ct_district_code",),
    ),
)


def _to_code(series: pd.Series) -> pd.Series:
    """把被 pandas 读成 float/int 的行政区划、行业代码还原成字符串。"""
    out = series.copy()
    if pd.api.types.is_float_dtype(out) or pd.api.types.is_integer_dtype(out):
        out = out.astype("Int64").astype("string")
    else:
        out = out.astype("string").str.strip()
        out = out.str.replace(r"\.0$", "", regex=True)
    return out.replace({"<NA>": pd.NA, "": pd.NA, "nan": pd.NA})


def _to_datetime(series: pd.Series, epoch_ms: bool = False) -> pd.Series:
    if epoch_ms:
        numeric = pd.to_numeric(series, errors="coerce")
        return pd.to_datetime(numeric, unit="ms", errors="coerce")
    return pd.to_datetime(series, errors="coerce")


def normalize(df: pd.DataFrame, spec: SourceTable) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for col in spec.drop_columns:
        if col in df.columns:
            df = df.drop(columns=[col])

    for col in spec.epoch_ms_columns:
        if col in df.columns:
            df[col] = _to_datetime(df[col], epoch_ms=True)

    for col in spec.datetime_columns:
        if col in df.columns and col not in spec.epoch_ms_columns:
            df[col] = _to_datetime(df[col])

    for col in spec.code_columns:
        if col in df.columns:
            df[col] = _to_code(df[col])

    for col in spec.numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 统一去掉纯空列，减小体积
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        df = df.drop(columns=empty_cols)

    return df


def load_source(spec: SourceTable, raw_dir: Path) -> pd.DataFrame:
    path = raw_dir / spec.file
    if not path.exists():
        raise FileNotFoundError(f"缺少源文件: {path}")
    read_kwargs: dict[str, object] = {}
    if spec.engine:
        read_kwargs["engine"] = spec.engine
    df = pd.read_excel(path, **read_kwargs)
    return normalize(df, spec)


def build_parquet(raw_dir: Path, parquet_dir: Path, force: bool = False) -> dict[str, Path]:
    parquet_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for spec in SOURCES:
        target = parquet_dir / f"{spec.name}.parquet"
        if target.exists() and not force:
            print(f"[skip] {spec.name} 已存在 -> {target.name}")
            written[spec.name] = target
            continue
        t0 = time.time()
        df = load_source(spec, raw_dir)
        df.to_parquet(target, index=False)
        print(f"[ok]   {spec.name}: {len(df):>7,} 行 x {df.shape[1]:>2} 列  ({time.time() - t0:.1f}s)")
        written[spec.name] = target
    return written


DERIVED_VIEWS = """
-- 企业主档：一企一行，只保留分析必需字段
CREATE OR REPLACE VIEW v_enterprise AS
SELECT
    e.eid,
    e.name,
    e.credit_no,
    e.status,
    e.new_status_code,
    e.econ_kind,
    e.regist_capi_new           AS regist_capi_wan,
    e.actual_capi               AS actual_capi_wan,
    e.start_date,
    CAST(date_diff('day', e.start_date, CURRENT_DATE) / 365.25 AS DOUBLE) AS age_years,
    e.province_code,
    e.district_code,
    e.belong_org,
    e.scope,
    i.industry_code,
    substr(i.industry_code, 1, 1) AS industry_section,
    substr(i.industry_code, 1, 3) AS industry_group
FROM enterprise e
LEFT JOIN enterprise_industry i USING (eid);

-- 招投标事实：剔除空主体行，补齐年份
CREATE OR REPLACE VIEW v_bidding AS
SELECT
    cbid_eid                    AS eid,
    name,
    cbid_id                     AS bid_id,
    u_id,
    role1                       AS role_code,
    title,
    publish_time,
    CAST(year(publish_time) AS INTEGER) AS bid_year,
    area_code,
    notice_type_main,
    notice_type_sub,
    project_number,
    project_bid_money
FROM bidding
WHERE cbid_eid IS NOT NULL;

-- 融资事实
CREATE OR REPLACE VIEW v_financing AS
SELECT
    cf_eid                      AS eid,
    ename                       AS name,
    cf_id                       AS finance_id,
    "round"                     AS round_name,
    round_type,
    round_date,
    CAST(year(round_date) AS INTEGER) AS round_year,
    amount,
    estimated_amount,
    COALESCE(amount, estimated_amount) AS amount_filled,
    currency,
    investors
FROM financing
WHERE cf_eid IS NOT NULL;

-- 股权事实：eid 为投资方，invest_eid 为被投方
CREATE OR REPLACE VIEW v_equity AS
SELECT
    cinv_eid                    AS eid,
    name,
    invest_eid,
    invest_name,
    invest_status,
    invest_start_date,
    stock_percent,
    should_capi_conv,
    real_capi
FROM equity
WHERE cinv_eid IS NOT NULL;

-- 资质事实
CREATE OR REPLACE VIEW v_qualification AS
SELECT
    ct_eid                      AS eid,
    name,
    ct_id                       AS qual_id,
    ct_name                     AS qual_name,
    ct_type                     AS qual_type,
    ct_level                    AS qual_level,
    CAST(ct_year AS INTEGER)    AS qual_year,
    ct_publish_date,
    ct_district                 AS qual_district,
    ct_district_code,
    ct_valid_start,
    ct_valid_end,
    ct_state                    AS qual_state
FROM qualification
WHERE ct_eid IS NOT NULL;
"""


def build_duckdb(parquet_dir: Path, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        for spec in SOURCES:
            src = (parquet_dir / f"{spec.name}.parquet").as_posix()
            con.execute(f"CREATE OR REPLACE TABLE {spec.name} AS SELECT * FROM read_parquet('{src}')")
            n = con.execute(f"SELECT count(*) FROM {spec.name}").fetchone()[0]
            print(f"[db]   {spec.name}: {n:,} 行")
        con.execute(DERIVED_VIEWS)
        print("[db]   派生视图已创建: v_enterprise / v_bidding / v_financing / v_equity / v_qualification")
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 ChainLens 本地数据底座")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR), help="原始 Excel 目录")
    parser.add_argument("--db", default=str(DEFAULT_WAREHOUSE), help="DuckDB 输出路径")
    parser.add_argument("--parquet-dir", default=str(DEFAULT_PARQUET_DIR), help="Parquet 中间目录")
    parser.add_argument("--force", action="store_true", help="强制重新解析 Excel")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    parquet_dir = Path(args.parquet_dir)
    db_path = Path(args.db)

    print(f"原始目录: {raw_dir}")
    build_parquet(raw_dir, parquet_dir, force=args.force)
    build_duckdb(parquet_dir, db_path)
    print(f"完成: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
