from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import auth  # noqa: E402
from dashboard.config import ensure_output_dirs, get_settings  # noqa: E402
from dashboard.data_catalog import build_inventory  # noqa: E402


def main() -> None:
    settings = get_settings()
    ensure_output_dirs(settings)
    st.set_page_config(page_title=settings["app"].get("title", "PCORIExplorer"), page_icon="🧭", layout="wide")
    auth.require_login(settings)
    st.title(settings["app"].get("title", "PCORIExplorer"))
    st.caption(settings["app"].get("subtitle", "Aggregate PCORnet CDM exploration dashboard"))

    inventory = build_inventory(settings)
    queryable = int((inventory["status"] == "queryable").sum()) if "status" in inventory else 0
    sas_only = int((inventory["status"] == "sas only").sum()) if "status" in inventory else 0
    missing = int((inventory["status"] == "missing").sum()) if "status" in inventory else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Expected CDM tables", len(inventory))
    c2.metric("Queryable Parquet tables", queryable)
    c3.metric("SAS-only tables", sas_only)
    c4.metric("Missing expected tables", missing)

    st.markdown("""
    This dashboard is a safe exploration layer for local PCORnet CDM data. It supports
    data inventory, quality checks, table summaries, code search, concept review, and
    aggregate cohort counts. Keep row-level analytic extracts in separate approved scripts.
    """)

    st.subheader("Current paths")
    st.code(
        f"Data root:    {settings['app']['data_root']}\n"
        f"Parquet root: {settings['app']['parquet_root']}\n"
        f"Audit dir:    {settings['app']['audit_dir']}"
    )

    st.subheader("Recommended first run")
    st.code(
        "python scripts/audit_pcori_sas.py --data-root ../data/CDM61_Feb022026 --out outputs/audit\n"
        "python scripts/convert_sas_to_parquet.py --data-root ../data/CDM61_Feb022026 --parquet-root ../data/pcori_parquet\n"
        "streamlit run dashboard/app.py"
    )

    st.subheader("Safety policy")
    threshold = settings.get("privacy", {}).get("small_cell_threshold", 11)
    st.markdown(f"Counts below **{threshold}** are suppressed. Configured identifier fields are hidden in normal views.")

    with st.expander("Detected inventory preview"):
        st.dataframe(inventory, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
