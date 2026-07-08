# PCORIExplorer Runbook

## Install

```bash
cd ~/works/pcori/PCORIExplorer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Audit the SAS datamart

```bash
python scripts/audit_pcori_sas.py \
  --data-root ../data/CDM61_Feb022026 \
  --out outputs/audit
```

Send these files back for review:

```text
outputs/audit/table_inventory.csv
outputs/audit/column_inventory.csv
outputs/audit/audit_summary.md
outputs/audit/manifest.json
```

## Convert SAS to Parquet

Do not start with all tables. This datamart is large. Use staged conversion.

Small and core tables first:

```bash
python scripts/convert_sas_to_parquet.py \
  --data-root ../data/CDM61_Feb022026 \
  --parquet-root ../data/pcori_parquet \
  --tables demographic death death_cause encounter condition immunization obs_gen
```

Then analytic code tables:

```bash
python scripts/convert_sas_to_parquet.py \
  --data-root ../data/CDM61_Feb022026 \
  --parquet-root ../data/pcori_parquet \
  --tables diagnosis procedures vital dispensing med_admin
```

Largest tables last:

```bash
python scripts/convert_sas_to_parquet.py \
  --data-root ../data/CDM61_Feb022026 \
  --parquet-root ../data/pcori_parquet \
  --tables lab_result_cm obs_clin prescribing
```

## Verify Parquet row counts

```bash
python scripts/verify_parquet_counts.py \
  --parquet-root ../data/pcori_parquet \
  --audit-table outputs/audit/table_inventory.csv \
  --out outputs/audit/parquet_verify.csv
```

Send back `outputs/audit/parquet_verify.csv` after conversion.

## Profile converted Parquet data

Run aggregate profiling after all converted tables verify successfully. This creates dashboard-ready summaries without exporting raw rows.

```bash
python scripts/profile_parquet_tables.py \
  --parquet-root ../data/pcori_parquet \
  --verify outputs/audit/parquet_verify.csv \
  --out outputs/profile \
  --memory-limit 64GB
```

The profiling output files are:

```text
outputs/profile/table_profile.csv
outputs/profile/date_ranges.csv
outputs/profile/key_missingness.csv
outputs/profile/top_values.csv
outputs/profile/profile_summary.md
```

For a faster smoke test:

```bash
python scripts/profile_parquet_tables.py \
  --parquet-root ../data/pcori_parquet \
  --verify outputs/audit/parquet_verify.csv \
  --out outputs/profile \
  --tables demographic encounter diagnosis \
  --memory-limit 32GB
```

## Run dashboard

```bash
streamlit run dashboard/app.py
```

Open the Data profile page after `outputs/profile` exists.

## Optional path overrides

```bash
export PCORI_DATA_ROOT=/absolute/path/to/CDM61_Feb022026
export PCORI_PARQUET_ROOT=/absolute/path/to/pcori_parquet
export PCORI_AUDIT_DIR=/absolute/path/to/audit
export PCORI_PROFILE_DIR=/absolute/path/to/profile
streamlit run dashboard/app.py
```

## Enable local login

```bash
python scripts/hash_password.py
cp dashboard/config/users.example.yaml dashboard/config/users.yaml
```

Paste the generated hash into `dashboard/config/users.yaml`, then set `auth.enabled: true` in `dashboard/config/dashboard_settings.yaml`.
