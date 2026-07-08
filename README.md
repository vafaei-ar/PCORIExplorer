# PCORIExplorer

Aggregate dashboard toolkit for local PCORnet CDM SAS data.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/audit_pcori_sas.py --data-root ../data/CDM61_Feb022026 --out outputs/audit
python scripts/convert_sas_to_parquet.py --data-root ../data/CDM61_Feb022026 --parquet-root ../data/pcori_parquet
streamlit run dashboard/app.py
```

The repository stores code only. Keep CDM data outside Git.
