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

## Run dashboard

```bash
streamlit run dashboard/app.py
```

## Optional path overrides

```bash
export PCORI_DATA_ROOT=/absolute/path/to/CDM61_Feb022026
export PCORI_PARQUET_ROOT=/absolute/path/to/pcori_parquet
export PCORI_AUDIT_DIR=/absolute/path/to/audit
streamlit run dashboard/app.py
```

## Enable local login

```bash
python scripts/hash_password.py
cp dashboard/config/users.example.yaml dashboard/config/users.yaml
```

Paste the generated hash into `dashboard/config/users.yaml`, then set `auth.enabled: true` in `dashboard/config/dashboard_settings.yaml`.
