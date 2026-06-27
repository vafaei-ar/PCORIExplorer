from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


def connect(settings: dict | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:", read_only=False)
    if settings:
        memory = settings.get("performance", {}).get("duckdb_memory_limit")
        if memory:
            con.execute(f"SET memory_limit='{memory}'")
    return con


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sql_string(value: str | Path) -> str:
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def read_parquet_expr(path: str | Path) -> str:
    return f"read_parquet({sql_string(path)}, union_by_name=true)"


def table_columns(con: duckdb.DuckDBPyConnection, parquet_path: str | Path) -> list[str]:
    sql = f"DESCRIBE SELECT * FROM {read_parquet_expr(parquet_path)} LIMIT 0"
    return con.execute(sql).df()["column_name"].astype(str).tolist()


def find_column(columns: list[str], candidates: list[str]) -> str | None:
    upper = {c.upper(): c for c in columns}
    for candidate in candidates:
        if candidate.upper() in upper:
            return upper[candidate.upper()]
    return None


def run_df(con: duckdb.DuckDBPyConnection, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    return con.execute(sql, params or {}).df()
