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


def compact_int(value: int | float | None) -> str:
    if value is None or pd.isna(value):
        return ""
    value = float(value)
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def add_quality_flags(date_ranges: pd.DataFrame, key_missingness: pd.DataFrame) -> pd.DataFrame:
    flags = []
    if not date_ranges.empty:
        df = date_ranges.copy()
        df["min_dt"] = pd.to_datetime(df.get("min_value"), errors="coerce")
        df["max_dt"] = pd.to_datetime(df.get("max_value"), errors="coerce")
        today = pd.Timestamp.today().normalize()
        for row in df.itertuples(index=False):
            table = getattr(row, "table", "")
            column = getattr(row, "column_name", "")
            min_dt = getattr(row, "min_dt", pd.NaT)
            max_dt = getattr(row, "max_dt", pd.NaT)
            non_null_pct = float(getattr(row, "non_null_pct", 0) or 0)
            col_upper = str(column).upper()
            if pd.notna(min_dt):
                if col_upper == "BIRTH_DATE" and min_dt.year < 1900:
                    flags.append({"severity": "review", "table": table, "field": column, "issue": f"Birth date before 1900: {min_dt.date()}"})
                elif col_upper != "BIRTH_DATE" and min_dt.year < 2000:
                    flags.append({"severity": "review", "table": table, "field": column, "issue": f"Clinical date before 2000: {min_dt.date()}"})
            if pd.notna(max_dt) and max_dt > today + pd.Timedelta(days=366):
                flags.append({"severity": "review", "table": table, "field": column, "issue": f"Date extends >1 year into the future: {max_dt.date()}"})
            if non_null_pct < 50:
                flags.append({"severity": "informational", "table": table, "field": column, "issue": f"Low date completeness: {non_null_pct:.1f}% non-null"})
    if not key_missingness.empty and "missing_pct" in key_missingness.columns:
        miss = key_missingness.copy()
        for row in miss[miss["missing_pct"] >= 90].itertuples(index=False):
            flags.append({
                "severity": "informational",
                "table": getattr(row, "table", ""),
                "field": getattr(row, "column_name", ""),
                "issue": f"High missingness: {float(getattr(row, 'missing_pct', 0) or 0):.1f}%",
            })
    return pd.DataFrame(flags)


def download_button(label: str, df: pd.DataFrame, filename: str) -> None:
    if df.empty:
        return
    st.download_button(label, data=df.to_csv(index=False), file_name=filename, mime="text/csv")


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
            "python scripts/profile_parquet_tables.py --parquet-root ../data/pcori_parquet --out outputs/profile --verify outputs/audit/parquet_verify.csv --memory-limit 64GB"
        )
        st.stop()

    if "row_count" in table_profile.columns:
        table_profile = table_profile.sort_values("row_count", ascending=False)
    profiled = int((table_profile.get("status", "") == "profiled").sum()) if "status" in table_profile else len(table_profile)
    total_rows = int(table_profile.get("row_count", pd.Series(dtype="float64")).fillna(0).sum())
    total_size_gb = table_profile.get("parquet_size_mb", pd.Series(dtype="float64")).fillna(0).sum() / 1024
    distinct_patient_cols = [c for c in table_profile.columns if "distinct_patid" in c]
    patient_metric = ""
    if distinct_patient_cols:
        patient_metric = compact_int(table_profile[distinct_patient_cols[0]].fillna(0).max())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Profiled tables", profiled)
    c2.metric("Rows", compact_int(total_rows))
    c3.metric("Parquet size", f"{total_size_gb:.1f} GB")
    c4.metric("Approx patients", patient_metric or "see table")
    st.caption(f"Full row count: {total_rows:,}. Patient count is approximate unless profiling is rerun with --exact-distinct.")

    st.info(
        "This page uses aggregate outputs only. Counts and percentages are for exploration and data-quality review, not final cohort definitions."
    )

    flags = add_quality_flags(date_ranges, key_missingness)
    if not flags.empty:
        st.subheader("Data-quality flags")
        st.dataframe(flags, use_container_width=True, hide_index=True)

    st.subheader("Table profile")
    visible_cols = [c for c in ["table", "domain", "label", "row_count", "n_columns", "parquet_size_mb", "status"] if c in table_profile.columns]
    hidden_cols = [c for c in table_profile.columns if c not in visible_cols]
    display_df = table_profile[visible_cols + hidden_cols]
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "row_count": st.column_config.NumberColumn("Rows", format="%d"),
            "parquet_size_mb": st.column_config.NumberColumn("Parquet MB", format="%.2f"),
        },
    )
    download_button("Download table profile", table_profile, "table_profile.csv")
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
        download_button("Download date ranges", date_ranges, "date_ranges.csv")

    st.subheader("Key missingness")
    if key_missingness.empty:
        st.info("No key-missingness output found.")
    else:
        missing_df = key_missingness.sort_values(["missing_pct", "table", "column_name"], ascending=[False, True, True])
        st.dataframe(missing_df, use_container_width=True, hide_index=True)
        download_button("Download key missingness", key_missingness, "key_missingness.csv")

    st.subheader("Top grouped values")
    if top_values.empty:
        st.info("No top-value output found.")
    else:
        tables = sorted(top_values["table"].dropna().unique().tolist())
        selected_table = st.selectbox("Table", tables)
        subset = top_values[top_values["table"] == selected_table]
        cols = sorted(subset["column_name"].dropna().unique().tolist())
        selected_col = st.selectbox("Column", cols)
        filtered = subset[subset["column_name"] == selected_col]
        st.dataframe(filtered, use_container_width=True, hide_index=True)
        download_button("Download all top values", top_values, "top_values.csv")


main()
