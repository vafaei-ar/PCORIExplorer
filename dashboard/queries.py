from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard.duckdb_client import connect, find_column, quote_ident, read_parquet_expr, table_columns

DATE_CANDIDATES = ["ADMIT_DATE", "DISCHARGE_DATE", "DX_DATE", "PX_DATE", "MEASURE_DATE", "RESULT_DATE", "DISPENSE_DATE", "RX_ORDER_DATE", "RX_START_DATE", "RX_END_DATE", "MEDADMIN_START_DATE", "REPORT_DATE", "RESOLVE_DATE", "ONSET_DATE", "DEATH_DATE", "VX_ADMIN_DATE", "OBSCLIN_START_DATE", "OBSGEN_START_DATE", "BIRTH_DATE"]


def basic_table_summary(parquet_path: str | Path, settings: dict) -> pd.DataFrame:
    con = connect(settings)
    expr = read_parquet_expr(parquet_path)
    columns = table_columns(con, parquet_path)
    select_parts = ["count(*) as row_count"]
    patid_col = find_column(columns, ["PATID"])
    if patid_col:
        select_parts.append(f"approx_count_distinct({quote_ident(patid_col)}) as distinct_patients")
    for col in DATE_CANDIDATES:
        actual = find_column(columns, [col])
        if actual:
            q = quote_ident(actual)
            select_parts.append(f"min({q}) as min_{actual.lower()}")
            select_parts.append(f"max({q}) as max_{actual.lower()}")
    return con.execute(f"select {', '.join(select_parts)} from {expr}").df()


def top_values(parquet_path: str | Path, column: str, settings: dict, limit: int | None = None) -> pd.DataFrame:
    con = connect(settings)
    limit = limit or int(settings.get("performance", {}).get("max_top_values", 30))
    expr = read_parquet_expr(parquet_path)
    columns = table_columns(con, parquet_path)
    actual = find_column(columns, [column])
    if actual is None:
        return pd.DataFrame(columns=["value", "n", "distinct_patients"])
    q = quote_ident(actual)
    patid_col = find_column(columns, ["PATID"])
    distinct_sql = f", approx_count_distinct({quote_ident(patid_col)}) as distinct_patients" if patid_col else ""
    sql = f"""
        select cast({q} as varchar) as value, count(*) as n {distinct_sql}
        from {expr}
        where {q} is not null and trim(cast({q} as varchar)) <> ''
        group by 1
        order by n desc
        limit {int(limit)}
    """
    return con.execute(sql).df()


def missingness(parquet_path: str | Path, settings: dict) -> pd.DataFrame:
    con = connect(settings)
    expr = read_parquet_expr(parquet_path)
    columns = table_columns(con, parquet_path)
    selected = columns[: int(settings.get("performance", {}).get("max_columns_for_missingness", 40))]
    row_count = con.execute(f"select count(*) from {expr}").fetchone()[0]
    if row_count == 0:
        return pd.DataFrame({"column": selected, "missing_n": 0, "missing_pct": 0.0})
    parts = []
    for col in selected:
        q = quote_ident(col)
        parts.append(f"sum(case when {q} is null or trim(cast({q} as varchar)) = '' then 1 else 0 end) as {quote_ident(col)}")
    wide = con.execute(f"select {', '.join(parts)} from {expr}").df()
    rows = []
    for col in selected:
        n = int(wide.iloc[0][col])
        rows.append({"column": col, "missing_n": n, "missing_pct": round(100 * n / row_count, 2)})
    return pd.DataFrame(rows).sort_values("missing_pct", ascending=False)


def code_prefix_counts(parquet_path: str | Path, code_column: str, prefixes: list[str], settings: dict, type_column: str | None = None) -> pd.DataFrame:
    con = connect(settings)
    expr = read_parquet_expr(parquet_path)
    columns = table_columns(con, parquet_path)
    actual_code = find_column(columns, [code_column])
    if actual_code is None:
        return pd.DataFrame()
    clean_prefixes = [p.strip().upper() for p in prefixes if p.strip()]
    if not clean_prefixes:
        return pd.DataFrame()
    qcode = quote_ident(actual_code)
    conditions = [f"upper(cast({qcode} as varchar)) like $p{i}" for i, _p in enumerate(clean_prefixes)]
    params = {f"p{i}": p + "%" for i, p in enumerate(clean_prefixes)}
    patid_col = find_column(columns, ["PATID"])
    type_expr = "null as code_type"
    group_type = ""
    if type_column:
        actual_type = find_column(columns, [type_column])
        if actual_type:
            type_expr = f"cast({quote_ident(actual_type)} as varchar) as code_type"
            group_type = ", 2"
    distinct_sql = f", approx_count_distinct({quote_ident(patid_col)}) as distinct_patients" if patid_col else ""
    sql = f"""
        select cast({qcode} as varchar) as code, {type_expr}, count(*) as n {distinct_sql}
        from {expr}
        where {' or '.join(conditions)}
        group by 1{group_type}
        order by n desc
        limit 200
    """
    return con.execute(sql, params).df()
