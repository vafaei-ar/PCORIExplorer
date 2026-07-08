#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_sas_metadata(path: Path) -> tuple[int | None, list[str], dict[str, Any]]:
    try:
        import pyreadstat
    except ImportError as exc:
        raise SystemExit("pyreadstat is required. Install with: pip install pyreadstat") from exc
    try:
        _, meta = pyreadstat.read_sas7bdat(str(path), metadataonly=True)
    except TypeError:
        _, meta = pyreadstat.read_sas7bdat(str(path), row_limit=0)
    columns = list(getattr(meta, "column_names", []) or [])
    labels = dict(zip(columns, getattr(meta, "column_labels", []) or []))
    return getattr(meta, "number_rows", None), columns, {"labels": labels}


def dataframe_to_markdown_safe(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except ImportError:
        return "```text\n" + df.to_string(index=False) + "\n```"


def audit(data_root: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    table_rows = []
    column_rows = []
    files = sorted(data_root.glob("*.sas7bdat"))
    if not files:
        raise SystemExit(f"No .sas7bdat files found under {data_root}")
    for path in files:
        table = path.stem.lower()
        print(f"Auditing {table}: {path}")
        try:
            n_rows, columns, meta = read_sas_metadata(path)
            status = "ok"
            error = ""
        except Exception as exc:
            n_rows, columns, meta = None, [], {}
            status = "error"
            error = repr(exc)
        table_rows.append({"table": table, "sas_path": str(path), "sas_size_mb": round(path.stat().st_size / (1024**2), 2), "metadata_rows": n_rows, "n_columns": len(columns), "status": status, "error": error})
        labels = meta.get("labels", {})
        for ordinal, col in enumerate(columns, start=1):
            column_rows.append({"table": table, "ordinal": ordinal, "column_name": col, "column_name_upper": col.upper(), "label": labels.get(col, "")})
    table_df = pd.DataFrame(table_rows).sort_values("table")
    column_df = pd.DataFrame(column_rows).sort_values(["table", "ordinal"])
    table_df.to_csv(out / "table_inventory.csv", index=False)
    column_df.to_csv(out / "column_inventory.csv", index=False)
    (out / "table_inventory.json").write_text(table_df.to_json(orient="records", indent=2), encoding="utf-8")
    summary_table = dataframe_to_markdown_safe(table_df)
    lines = ["# PCORI CDM SAS audit summary", "", f"Data root: `{data_root}`", f"Tables found: {len(table_df)}", f"Total SAS size GB: {table_df['sas_size_mb'].sum() / 1024:.2f}", "", summary_table]
    (out / "audit_summary.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({"data_root": str(data_root), "tables": table_rows}, indent=2), encoding="utf-8")
    print(f"Wrote audit outputs to {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit PCORnet CDM SAS files without reading full data.")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("outputs/audit"))
    args = parser.parse_args()
    audit(args.data_root, args.out)


if __name__ == "__main__":
    main()
