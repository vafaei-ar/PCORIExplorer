#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def parquet_path_for_table(parquet_root: Path, table: str) -> Path | None:
    for candidate in [parquet_root / f"{table}.parquet", parquet_root / table, parquet_root / table.upper()]:
        if candidate.exists():
            return candidate
    return None


def parquet_expr(path: Path) -> str:
    if path.is_dir():
        return f"read_parquet({sql_string(path / '*.parquet')}, union_by_name=true)"
    return f"read_parquet({sql_string(path)}, union_by_name=true)"


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify converted Parquet row counts against audit metadata.")
    parser.add_argument("--parquet-root", type=Path, required=True)
    parser.add_argument("--audit-table", type=Path, default=Path("outputs/audit/table_inventory.csv"))
    parser.add_argument("--out", type=Path, default=Path("outputs/audit/parquet_verify.csv"))
    parser.add_argument("--tables", nargs="*", default=None)
    args = parser.parse_args()

    audit = pd.read_csv(args.audit_table)
    if args.tables:
        wanted = {t.lower() for t in args.tables}
        audit = audit[audit["table"].str.lower().isin(wanted)]

    con = duckdb.connect(database=":memory:")
    rows = []
    for row in audit.itertuples(index=False):
        table = str(row.table).lower()
        path = parquet_path_for_table(args.parquet_root, table)
        if path is None:
            rows.append({"table": table, "metadata_rows": int(row.metadata_rows), "parquet_rows": None, "status": "missing_parquet", "parquet_path": ""})
            continue
        try:
            n = con.execute(f"select count(*) from {parquet_expr(path)}").fetchone()[0]
            expected = int(row.metadata_rows)
            status = "ok" if n == expected else "row_mismatch"
            rows.append({"table": table, "metadata_rows": expected, "parquet_rows": int(n), "status": status, "parquet_path": str(path)})
            print(f"{table}: {n:,} rows ({status})")
        except Exception as exc:
            rows.append({"table": table, "metadata_rows": int(row.metadata_rows), "parquet_rows": None, "status": "error", "parquet_path": str(path), "error": repr(exc)})
    out = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
