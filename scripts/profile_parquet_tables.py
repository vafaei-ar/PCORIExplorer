#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


def parquet_path_for_table(parquet_root: Path, table: str) -> Path | None:
    for candidate in [parquet_root / f"{table}.parquet", parquet_root / table, parquet_root / table.upper()]:
        if candidate.exists():
            return candidate
    return None


def parquet_expr(path: Path) -> str:
    if path.is_dir():
        return f"read_parquet({sql_string(path / '*.parquet')}, union_by_name=true)"
    return f"read_parquet({sql_string(path)}, union_by_name=true)"


def table_columns(con: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    df = con.execute(f"describe select * from {parquet_expr(path)} limit 0").df()
    return [str(x) for x in df["column_name"].tolist()]


def actual_column(columns: list[str], wanted: str) -> str | None:
    by_upper = {c.upper(): c for c in columns}
    return by_upper.get(wanted.upper())


def file_size_mb(path: Path) -> float:
    if path.is_file():
        return round(path.stat().st_size / (1024**2), 2)
    return round(sum(p.stat().st_size for p in path.rglob("*.parquet")) / (1024**2), 2)


def suppress_count(n: int | None, threshold: int) -> str:
    if n is None:
        return ""
    if 0 < n < threshold:
        return f"<{threshold}"
    return str(int(n))


def load_row_counts(path: Path | None) -> dict[str, int]:
    if path is None or not path.exists():
        return {}
    df = pd.read_csv(path)
    out = {}
    for row in df.itertuples(index=False):
        try:
            out[str(row.table).lower()] = int(row.parquet_rows)
        except Exception:
            continue
    return out


def distinct_expr(col: str, exact: bool) -> str:
    func = "count(distinct" if exact else "approx_count_distinct("
    if exact:
        return f"count(distinct {qident(col)})"
    return f"approx_count_distinct({qident(col)})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile converted PCORnet Parquet tables using aggregate-only queries.")
    parser.add_argument("--parquet-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("outputs/profile"))
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "dashboard" / "config" / "cdm_tables.yaml")
    parser.add_argument("--verify", type=Path, default=Path("outputs/audit/parquet_verify.csv"))
    parser.add_argument("--tables", nargs="*", default=None)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--small-cell-threshold", type=int, default=11)
    parser.add_argument("--exact-distinct", action="store_true", help="Use exact count(distinct). Default uses approximate distinct for speed.")
    parser.add_argument("--memory-limit", default="16GB")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    config = read_yaml(args.config).get("tables", {})
    if args.tables:
        wanted = {t.lower() for t in args.tables}
        config = {k: v for k, v in config.items() if k.lower() in wanted}
    verified_counts = load_row_counts(args.verify)

    con = duckdb.connect(database=":memory:")
    con.execute(f"set memory_limit={sql_string(args.memory_limit)}")

    table_rows: list[dict[str, Any]] = []
    date_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    top_rows: list[dict[str, Any]] = []

    for table, spec in config.items():
        table = table.lower()
        path = parquet_path_for_table(args.parquet_root, table)
        if path is None:
            table_rows.append({"table": table, "status": "missing_parquet"})
            continue
        print(f"Profiling {table}: {path}", flush=True)
        expr = parquet_expr(path)
        columns = table_columns(con, path)
        row_count = verified_counts.get(table)
        if row_count is None:
            row_count = int(con.execute(f"select count(*) from {expr}").fetchone()[0])

        patid_col = actual_column(columns, str(spec.get("person_id", "PATID"))) or actual_column(columns, "PATID")
        enc_col = actual_column(columns, str(spec.get("encounter_id", "ENCOUNTERID"))) or actual_column(columns, "ENCOUNTERID")
        table_row = {
            "table": table,
            "domain": spec.get("domain", ""),
            "label": spec.get("label", table.upper()),
            "row_count": row_count,
            "n_columns": len(columns),
            "parquet_size_mb": file_size_mb(path),
            "status": "profiled",
        }
        if patid_col:
            table_row["approx_distinct_patid" if not args.exact_distinct else "distinct_patid"] = int(con.execute(f"select {distinct_expr(patid_col, args.exact_distinct)} from {expr}").fetchone()[0])
        if enc_col:
            table_row["approx_distinct_encounterid" if not args.exact_distinct else "distinct_encounterid"] = int(con.execute(f"select {distinct_expr(enc_col, args.exact_distinct)} from {expr}").fetchone()[0])
        table_rows.append(table_row)

        date_cols = [c for c in spec.get("date_columns", []) if actual_column(columns, str(c))]
        for configured_col in date_cols:
            col = actual_column(columns, str(configured_col))
            if not col:
                continue
            try:
                q = f"select min({qident(col)}) as min_date, max({qident(col)}) as max_date, count({qident(col)}) as non_null_n from {expr}"
                result = con.execute(q).fetchone()
                non_null = int(result[2] or 0)
                date_rows.append({
                    "table": table,
                    "column_name": col,
                    "non_null_n": non_null,
                    "non_null_pct": round(100 * non_null / row_count, 4) if row_count else 0,
                    "min_value": str(result[0]) if result[0] is not None else "",
                    "max_value": str(result[1]) if result[1] is not None else "",
                })
            except Exception as exc:
                date_rows.append({"table": table, "column_name": col, "error": repr(exc)})

        profile_cols = []
        for key in ["required_columns", "primary_key", "date_columns", "code_columns", "code_type_columns", "geography_columns"]:
            for col in spec.get(key, []) or []:
                actual = actual_column(columns, str(col))
                if actual and actual not in profile_cols:
                    profile_cols.append(actual)
        for col in profile_cols:
            try:
                missing = int(con.execute(f"select count(*) - count({qident(col)}) from {expr}").fetchone()[0])
                missing_rows.append({
                    "table": table,
                    "column_name": col,
                    "missing_count_display": suppress_count(missing, args.small_cell_threshold),
                    "missing_pct": round(100 * missing / row_count, 4) if row_count else 0,
                })
            except Exception as exc:
                missing_rows.append({"table": table, "column_name": col, "error": repr(exc)})

        code_cols = [actual_column(columns, str(c)) for c in spec.get("code_columns", []) or []]
        code_cols = [c for c in code_cols if c]
        for col in code_cols:
            try:
                q = f"""
                select cast({qident(col)} as varchar) as value, count(*) as n
                from {expr}
                where {qident(col)} is not null
                group by 1
                order by n desc
                limit {int(args.top_n)}
                """
                top_df = con.execute(q).df()
                for rank, r in enumerate(top_df.itertuples(index=False), start=1):
                    n = int(r.n)
                    top_rows.append({
                        "table": table,
                        "column_name": col,
                        "rank": rank,
                        "value": str(r.value),
                        "count_display": suppress_count(n, args.small_cell_threshold),
                        "pct": round(100 * n / row_count, 4) if row_count else 0,
                    })
            except Exception as exc:
                top_rows.append({"table": table, "column_name": col, "error": repr(exc)})

    table_df = pd.DataFrame(table_rows)
    date_df = pd.DataFrame(date_rows)
    missing_df = pd.DataFrame(missing_rows)
    top_df = pd.DataFrame(top_rows)

    table_df.to_csv(args.out / "table_profile.csv", index=False)
    date_df.to_csv(args.out / "date_ranges.csv", index=False)
    missing_df.to_csv(args.out / "key_missingness.csv", index=False)
    top_df.to_csv(args.out / "top_values.csv", index=False)

    total_rows = int(table_df.get("row_count", pd.Series(dtype="float64")).fillna(0).sum()) if not table_df.empty else 0
    total_size_gb = float(table_df.get("parquet_size_mb", pd.Series(dtype="float64")).fillna(0).sum()) / 1024 if not table_df.empty else 0
    lines = [
        "# PCORI Parquet profile summary",
        "",
        f"Tables profiled: {int((table_df['status'] == 'profiled').sum()) if 'status' in table_df else 0}",
        f"Total rows: {total_rows:,}",
        f"Total Parquet size: {total_size_gb:.2f} GB",
        "",
        "Outputs:",
        "- table_profile.csv",
        "- date_ranges.csv",
        "- key_missingness.csv",
        "- top_values.csv",
    ]
    (args.out / "profile_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote profile outputs to {args.out}")


if __name__ == "__main__":
    main()
