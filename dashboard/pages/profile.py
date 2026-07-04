from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.config import get_settings  # noqa: E402


@st.cache_data(show_spinner=False)
def read_csv_if_exists(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def main() -> None:
    settings = get_settings()
    profile_dir = Path(settings["app"].get("profile_dir", ROOT / "outputs" / "profile"))
    st.title("Data profile")
    st.caption("Aggregate profiling outputs generated from converted PCORnet Parquet tables.")

    table_profile = read_csv_if_exists(str(profile_dir / "table_profile.csv"))
    date_ranges = read_csv_if_exists(str(profile_dir / "date_ranges.csv"))
    key_missingness = read_csv_if_exists(str(profile_dir / "key_missingness.csv"))
    top_values = read_csv_if_exists(str(profile_dir / "top_values.csv"))

    if table_profile.empty:
        st.warning("No profile outputs found yet.")
        st.code(
            "python scripts/profile_parquet_tables.py --parquet-root ../data/pcori_parquet --out outputs/profile --verify outputs/audit/parquet_verify.csv"
        )
        st.stop()

    profiled = int((table_profile.get("status", "") == "profiled").sum()) if "status" in table_profile else len(table_profile)
    total_rows = int(table_profile.get("row_count", pd.Series(dtype="float64")).fillna(0).sum())
    total_size_gb = table_profile.get("parquet_size_mb", pd.Series(dtype="float64")).fillna(0).sum() / 1024

    c1, c2, c3 = st.columns(3)
    c1.metric("Profiled tables", profiled)
    c2.metric("Rows", f"{total_rows:,}")
    c3.metric("Parquet size", f"{total_size_gb:.1f} GB")

    st.subheader("Table profile")
    st.dataframe(table_profile, use_container_width=True, hide_index=True)
    if "row_count" in table_profile.columns:
        chart_df = table_profile.sort_values("row_count", ascending=False).head(15)
        st.plotly_chart(px.bar(chart_df, x="table", y="row_count", title="Rows by table"), use_container_width=True)

    st.subheader("Date ranges")
    if date_ranges.empty:
        st.info("No date-range output found.")
    else:
        table_filter = st.multiselect("Filter date ranges by table", sorted(date_ranges["table"].dropna().unique().tolist()))
        df = date_ranges if not table_filter else date_ranges[date_ranges["table"].isin(table_filter)]
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("Key missingness")
    if key_missingness.empty:
        st.info("No key-missingness output found.")
    else:
        missing_df = key_missingness.sort_values(["missing_pct", "table", "column_name"], ascending=[False, True, True])
        st.dataframe(missing_df, use_container_width=True, hide_index=True)

    st.subheader("Top grouped values")
    if top_values.empty:
        st.info("No top-value output found.")
    else:
        tables = sorted(top_values["table"].dropna().unique().tolist())
        selected_table = st.selectbox("Table", tables)
        subset = top_values[top_values["table"] == selected_table]
        cols = sorted(subset["column_name"].dropna().unique().tolist())
        selected_col = st.selectbox("Column", cols)
        st.dataframe(subset[subset["column_name"] == selected_col], use_container_width=True, hide_index=True)


main()
