"""只读数据访问层：白名单 + SELECT-only + 自动 LIMIT + 查询留痕。

任何 Agent、任何内核都必须经过这里访问数据。不允许直接 duckdb.connect。
这样才能保证"每一条结论都能回放它的 SQL"，也才能在对外开放时守住边界。
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .mysql import MySQLSettings, configure_mysql_source, materialize_analysis_views

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO_ROOT / "data" / "warehouse" / "chainlens.duckdb"

# 分析层只允许触碰派生视图，不允许直接读原始表——原始表含冗余个人字段
ALLOWED_OBJECTS: frozenset[str] = frozenset(
    {
        "v_enterprise",
        "v_bidding",
        "v_financing",
        "v_equity",
        "v_qualification",
    }
)

# 派生结果表由内核写入，允许二次读取
REGISTERED_PREFIX = "t_"

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|export|import|"
    r"install|load|pragma|set|call|grant|revoke|truncate|replace|vacuum)\b",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([`\"]?)([A-Za-z_][\w$]*)\1", re.IGNORECASE)
_HAS_LIMIT = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_CTE_NAME = re.compile(r"(?:with|,)\s+([A-Za-z_][\w$]*)\s+as\s*\(", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    """SQL 未通过安全校验。"""


@dataclass(frozen=True)
class QueryResult:
    df: pd.DataFrame
    sql: str
    elapsed_ms: float

    @property
    def row_count(self) -> int:
        return len(self.df)


def validate_sql(sql: str, extra_objects: frozenset[str] | None = None) -> str:
    """校验并在必要时补 LIMIT，返回可执行 SQL。"""
    if not sql or not sql.strip():
        raise UnsafeQueryError("SQL 为空")

    cleaned = re.sub(r"--[^\n]*", " ", sql)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL).strip().rstrip(";")

    if ";" in cleaned:
        raise UnsafeQueryError("拒绝多语句执行")

    head = cleaned.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise UnsafeQueryError("只允许 SELECT / WITH 查询")

    if _FORBIDDEN.search(cleaned):
        raise UnsafeQueryError("SQL 含有被禁止的写操作关键字")

    allowed = set(ALLOWED_OBJECTS)
    if extra_objects:
        allowed |= set(extra_objects)
    allowed |= {name.lower() for name in _CTE_NAME.findall(cleaned)}

    referenced = {name.lower() for _, name in _TABLE_REF.findall(cleaned)}
    illegal = {
        name
        for name in referenced
        if name not in allowed and not name.startswith(REGISTERED_PREFIX)
    }
    if illegal:
        raise UnsafeQueryError(
            f"引用了非白名单对象: {', '.join(sorted(illegal))}；"
            f"允许的对象: {', '.join(sorted(ALLOWED_OBJECTS))}"
        )

    return cleaned


class Warehouse:
    """线程安全的只读仓库句柄。"""

    def __init__(self, db_path: str | Path | None = None, default_limit: int = 5000) -> None:
        self.default_limit = default_limit
        self._lock = threading.Lock()
        self._log: list[dict[str, Any]] = []
        mysql = MySQLSettings.from_environment() if db_path is None else None
        if mysql is not None:
            self.db_path: Path | None = None
            self.backend = "mysql"
            self._con = duckdb.connect()
            configure_mysql_source(self._con, mysql)
            materialize_analysis_views(self._con)
        else:
            self.db_path = Path(db_path or DEFAULT_DB)
            if not self.db_path.exists():
                raise FileNotFoundError(
                    f"数据底座不存在: {self.db_path}\n"
                    "请先运行: python -m chainlens.warehouse.etl"
                )
            self.backend = "duckdb"
            self._con = duckdb.connect(str(self.db_path), read_only=True)

    # -- 查询 ---------------------------------------------------------------

    def query(
        self,
        sql: str,
        *,
        limit: int | None = None,
        enforce_limit: bool = True,
        extra_objects: frozenset[str] | None = None,
    ) -> QueryResult:
        safe = validate_sql(sql, extra_objects=extra_objects)
        if enforce_limit and not _HAS_LIMIT.search(safe):
            safe = f"{safe}\nLIMIT {limit or self.default_limit}"

        t0 = time.perf_counter()
        with self._lock:
            df = self._con.execute(safe).fetchdf()
        elapsed = (time.perf_counter() - t0) * 1000
        self._log.append({"sql": safe, "rows": len(df), "ms": round(elapsed, 1)})
        return QueryResult(df=df, sql=safe, elapsed_ms=elapsed)

    def scalar(self, sql: str) -> Any:
        result = self.query(sql, enforce_limit=False)
        if result.df.empty:
            return None
        return result.df.iloc[0, 0]

    # -- 元信息 -------------------------------------------------------------

    def objects(self) -> list[str]:
        return sorted(ALLOWED_OBJECTS)

    def columns(self, obj: str) -> list[str]:
        if obj not in ALLOWED_OBJECTS:
            raise UnsafeQueryError(f"不允许查看 {obj}")
        return list(self.query(f"SELECT * FROM {obj} LIMIT 0", enforce_limit=False).df.columns)

    @property
    def query_log(self) -> list[dict[str, Any]]:
        return list(self._log)

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
