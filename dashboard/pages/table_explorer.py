from __future__ import annotations

import sys
from pathlib import Path
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import auth
from dashboard.config import get_settings
from dashboard.data_catalog import build_inventory, parquet_path_for_table
from dashboard.duckdb_client import connect, table_columns
from dashboard.queries import basic_table_summary, missingness, top_values
from dashboard.safety import apply_small_cell_suppression, drop_identifier_columns

settings = get_settings()
auth.require_login(settings)
threshold = int(settings.get("privacy", {}).get("small_cell_threshold", 11))

st.title("Table Explorer")
inventory = build_inventory(settings)
queryable = inventory[inventory["status"] == "queryable"]["table"].dropna().sort_values().tolist()
if not queryable:
    st.warning("No queryable Parquet tables were found. Run the conversion script first.")
    st.stop()

table = st.selectbox("Table", queryable)
path = parquet_path_for_table(settings, table)
if path is None:
    st.stop()

st.subheader("Basic summary")
st.dataframe(apply_small_cell_suppression(basic_table_summary(path, settings), threshold=threshold), use_container_width=True, hide_index=True)

con = connect(settings)
columns = table_columns(con, path)
hidden = set(settings.get("privacy", {}).get("hidden_identifier_columns", []))
visible_columns = [c for c in columns if c.upper() not in hidden]

st.subheader("Column missingness")
miss = missingness(path, settings)
st.dataframe(miss, use_container_width=True, hide_index=True)
if not miss.empty:
    st.plotly_chart(px.bar(miss.head(20), x="column", y="missing_pct", title="Highest missingness columns"), use_container_width=True)

st.subheader("Top values")
column = st.selectbox("Column", visible_columns)
top = drop_identifier_columns(top_values(path, column, settings), settings)
st.dataframe(apply_small_cell_suppression(top, threshold=threshold), use_container_width=True, hide_index=True)
