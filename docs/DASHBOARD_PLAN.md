# PCORIExplorer Dashboard Plan

## Purpose

Build a secure, aggregate-first dashboard for the local PCORnet CDM datamart. Researchers should be able to see data availability, table structure, code frequencies, and rough cohort feasibility without writing SQL.

## Current v0.1 scope

1. Audit local SAS files and produce table and column inventories.
2. Convert SAS tables to Parquet for fast DuckDB queries.
3. Show table availability and conversion status.
4. Explore queryable tables using aggregate summaries.
5. Search reusable clinical code prefixes through configured CDM code columns.
6. Store reusable concept definitions in YAML.

## Design rules

- Data stays outside Git.
- Dashboard outputs are aggregate-first.
- Small cells are suppressed by default.
- Configured identifier fields are hidden from normal views.
- Row-level extracts should stay in separate approved analysis scripts.
- Concepts and cohort definitions should be version-controlled YAML files.

## Architecture

```text
../data/CDM61_Feb022026/*.sas7bdat
  -> scripts/audit_pcori_sas.py
  -> outputs/audit/*.csv

../data/CDM61_Feb022026/*.sas7bdat
  -> scripts/convert_sas_to_parquet.py
  -> ../data/pcori_parquet/*.parquet
  -> Streamlit + DuckDB dashboard
```

## Next hardening step

After the first audit outputs are available, check actual field names against `dashboard/config/cdm_tables.yaml`. Then improve table-specific summaries, code search, and cohort logic around the real schema.
