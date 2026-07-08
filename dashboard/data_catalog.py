from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from dashboard.config import get_cdm_tables


def scan_sas_files(data_root: str | Path) -> pd.DataFrame:
    root = Path(data_root)
    rows = []
    if not root.exists():
        return pd.DataFrame(columns=["table", "sas_path", "sas_exists", "sas_size_mb"])
    for path in sorted(root.glob("*.sas7bdat")):
        rows.append({"table": path.stem.lower(), "sas_path": str(path), "sas_exists": True, "sas_size_mb": round(path.stat().st_size / (1024**2), 2)})
    return pd.DataFrame(rows)


def scan_parquet_files(parquet_root: str | Path) -> pd.DataFrame:
    root = Path(parquet_root)
    rows = []
    if not root.exists():
        return pd.DataFrame(columns=["table", "parquet_path", "parquet_exists", "parquet_size_mb"])
    for path in sorted(root.glob("*.parquet")):
        rows.append({"table": path.stem.lower(), "parquet_path": str(path), "parquet_exists": True, "parquet_size_mb": round(path.stat().st_size / (1024**2), 2)})
    for path in sorted(root.glob("*/*.parquet")):
        table = path.parent.name.lower()
        size_mb = round(sum(p.stat().st_size for p in path.parent.glob("*.parquet")) / (1024**2), 2)
        rows.append({"table": table, "parquet_path": str(path.parent), "parquet_exists": True, "parquet_size_mb": size_mb})
    if not rows:
        return pd.DataFrame(columns=["table", "parquet_path", "parquet_exists", "parquet_size_mb"])
    return pd.DataFrame(rows).drop_duplicates("table")


def load_audit_inventory(audit_dir: str | Path) -> pd.DataFrame:
    path = Path(audit_dir) / "table_inventory.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_column_inventory(audit_dir: str | Path) -> pd.DataFrame:
    path = Path(audit_dir) / "column_inventory.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def build_inventory(settings: dict[str, Any]) -> pd.DataFrame:
    app = settings["app"]
    cdm_tables = get_cdm_tables()
    expected = pd.DataFrame([
        {"table": t, "label": s.get("label", t.upper()), "domain": s.get("domain", ""), "description": s.get("description", ""), "expected_file": s.get("expected_file", f"{t}.sas7bdat")}
        for t, s in cdm_tables.items()
    ])
    sas_df = scan_sas_files(app["data_root"])
    pq_df = scan_parquet_files(app["parquet_root"])
    audit_df = load_audit_inventory(app["audit_dir"])
    out = expected.merge(sas_df, on="table", how="outer")
    out = out.merge(pq_df, on="table", how="left") if not pq_df.empty else out.assign(parquet_exists=False, parquet_path="", parquet_size_mb=None)
    if not audit_df.empty:
        cols = [c for c in audit_df.columns if c not in out.columns or c == "table"]
        out = out.merge(audit_df[cols], on="table", how="left")
    for col in ["sas_exists", "parquet_exists"]:
        if col in out.columns:
            out[col] = out[col].fillna(False).astype(bool)
    out["status"] = out.apply(lambda r: "queryable" if r.get("parquet_exists", False) else ("sas only" if r.get("sas_exists", False) else "missing"), axis=1)
    return out.sort_values(["domain", "table"]).reset_index(drop=True)


def parquet_path_for_table(settings: dict[str, Any], table: str) -> Path | None:
    root = Path(settings["app"]["parquet_root"])
    for candidate in [root / f"{table}.parquet", root / table, root / table.upper()]:
        if candidate.exists():
            return candidate
    return None
