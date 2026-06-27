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

```bash
python scripts/convert_sas_to_parquet.py \
  --data-root ../data/CDM61_Feb022026 \
  --parquet-root ../data/pcori_parquet
```

For a first test:

```bash
python scripts/convert_sas_to_parquet.py \
  --data-root ../data/CDM61_Feb022026 \
  --parquet-root ../data/pcori_parquet \
  --tables demographic encounter diagnosis
```

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
