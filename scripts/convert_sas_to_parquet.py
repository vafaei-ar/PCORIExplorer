#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def convert_one(path: Path, out_path: Path, chunksize: int) -> None:
    try:
        import pyreadstat
    except ImportError as exc:
        raise SystemExit("pyreadstat is required. Install with: pip install pyreadstat") from exc
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer: pq.ParquetWriter | None = None
    total_rows = 0
    try:
        reader = pyreadstat.read_file_in_chunks(pyreadstat.read_sas7bdat, str(path), chunksize=chunksize, dates_as_pandas_datetime=True)
        for chunk, _meta in reader:
            if chunk.empty:
                continue
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(out_path, table.schema, compression="zstd")
            else:
                table = table.cast(writer.schema, safe=False)
            writer.write_table(table)
            total_rows += len(chunk)
            print(f"  wrote {total_rows:,} rows", flush=True)
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        empty = pa.Table.from_pandas(pd.DataFrame(), preserve_index=False)
        pq.write_table(empty, out_path, compression="zstd")
    print(f"Finished {path.name} -> {out_path} ({total_rows:,} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PCORnet CDM SAS files to queryable Parquet.")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--parquet-root", type=Path, required=True)
    parser.add_argument("--tables", nargs="*", default=None)
    parser.add_argument("--chunksize", type=int, default=250_000)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    sas_files = sorted(args.data_root.glob("*.sas7bdat"))
    if args.tables:
        wanted = {t.lower() for t in args.tables}
        sas_files = [p for p in sas_files if p.stem.lower() in wanted]
    if not sas_files:
        raise SystemExit("No matching SAS files found.")
    args.parquet_root.mkdir(parents=True, exist_ok=True)
    for path in sas_files:
        table = path.stem.lower()
        out_path = args.parquet_root / f"{table}.parquet"
        if out_path.exists() and not args.overwrite:
            print(f"Skipping existing {out_path}. Use --overwrite to replace.")
            continue
        convert_one(path, out_path, args.chunksize)


if __name__ == "__main__":
    main()
