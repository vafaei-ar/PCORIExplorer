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
from dashboard.data_catalog import parquet_path_for_table  # noqa: E402
from dashboard.duckdb_client import connect, quote_ident, read_parquet_expr, table_columns, find_column, sql_string  # noqa: E402
from dashboard.safety import apply_small_cell_suppression  # noqa: E402


PRESETS = {
    "Ischemic stroke, exploratory": ["I63", "433", "434", "436"],
    "TIA, exploratory": ["G45"],
    "Hemorrhagic stroke, exploratory": ["I60", "I61", "I62"],
    "Any cerebrovascular disease, broad": ["I60", "I61", "I62", "I63", "I64", "I65", "I66", "I67", "I68", "I69", "G45"],
    "Custom": [],
}


@st.cache_resource(show_spinner=False)
def get_connection(memory_limit: str):
    return connect({"performance": {"duckdb_memory_limit": memory_limit}})


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


def parse_prefixes(text: str) -> list[str]:
    prefixes = []
    for item in text.replace(",", "\n").splitlines():
        val = item.strip().upper().replace("'", "")
        if val:
            prefixes.append(val)
    return sorted(set(prefixes))


def prefix_condition(column: str, prefixes: list[str]) -> str:
    if not prefixes:
        return "1=1"
    clauses = [f"upper(cast({quote_ident(column)} as varchar)) like {sql_string(prefix + '%')}" for prefix in prefixes]
    return "(" + " or ".join(clauses) + ")"


def date_condition(column: str | None, start_text: str, end_text: str) -> str:
    if not column:
        return "1=1"
    clauses = []
    start_text = (start_text or "").strip()
    end_text = (end_text or "").strip()
    if start_text:
        clauses.append(f"cast({quote_ident(column)} as date) >= date {sql_string(start_text)}")
    if end_text:
        clauses.append(f"cast({quote_ident(column)} as date) <= date {sql_string(end_text)}")
    return " and ".join(clauses) if clauses else "1=1"


def optional_filter(column: str | None, selected: list[str]) -> str:
    if not column or not selected:
        return "1=1"
    values = ", ".join(sql_string(x) for x in selected)
    return f"cast({quote_ident(column)} as varchar) in ({values})"


def safe_display(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    threshold = int(settings.get("privacy", {}).get("small_cell_threshold", 11))
    return apply_small_cell_suppression(
        df,
        count_columns=("n", "rows", "diagnosis_rows", "patient_count", "encounter_count", "approx_patients", "approx_encounters"),
        threshold=threshold,
    )


def get_distinct_values(con, expr: str, column: str | None, limit: int = 200) -> list[str]:
    if not column:
        return []
    sql = f"""
    select cast({quote_ident(column)} as varchar) as value, count(*) as n
    from {expr}
    where {quote_ident(column)} is not null
    group by 1
    order by n desc
    limit {int(limit)}
    """
    try:
        df = con.execute(sql).df()
        return [str(x) for x in df["value"].dropna().tolist()]
    except Exception:
        return []


def main() -> None:
    settings = get_settings()
    memory = settings.get("performance", {}).get("duckdb_memory_limit", "8GB")
    con = get_connection(memory)
    st.title("Cohort explorer")
    st.caption("Build aggregate diagnosis-code cohorts from the converted PCORnet CDM Parquet data.")

    diagnosis_path = parquet_path_for_table(settings, "diagnosis")
    demographic_path = parquet_path_for_table(settings, "demographic")
    encounter_path = parquet_path_for_table(settings, "encounter")

    if diagnosis_path is None:
        st.error("diagnosis.parquet was not found. Convert and verify the diagnosis table first.")
        st.stop()

    diagnosis_expr = read_parquet_expr(diagnosis_path)
    diagnosis_cols = table_columns(con, diagnosis_path)
    dx_col = find_column(diagnosis_cols, ["DX"])
    dx_type_col = find_column(diagnosis_cols, ["DX_TYPE"])
    dx_date_col = find_column(diagnosis_cols, ["DX_DATE", "ADMIT_DATE"])
    patid_col = find_column(diagnosis_cols, ["PATID"])
    encid_col = find_column(diagnosis_cols, ["ENCOUNTERID"])

    if not dx_col or not patid_col:
        st.error("The diagnosis table does not have the expected DX and PATID columns.")
        st.stop()

    with st.sidebar:
        st.header("Cohort definition")
        preset = st.selectbox("Concept preset", list(PRESETS.keys()))
        default_prefixes = "\n".join(PRESETS[preset])
        prefixes_text = st.text_area("Code prefixes", value=default_prefixes, height=120)
        prefixes = parse_prefixes(prefixes_text)
        st.caption("Prefixes are matched as starts-with, e.g., I63 matches I63.*")

        dx_type_values = get_distinct_values(con, diagnosis_expr, dx_type_col)
        selected_dx_types = st.multiselect("DX_TYPE filter", dx_type_values, default=[])
        use_dates = st.checkbox("Filter by diagnosis date", value=False)
        start_text = st.text_input("Start date YYYY-MM-DD", value="2010-01-01") if use_dates else ""
        end_text = st.text_input("End date YYYY-MM-DD", value="2026-12-31") if use_dates else ""
        run_breakdowns = st.checkbox("Run demographic and encounter breakdowns", value=False)
        run_query = st.button("Run cohort", type="primary")

    st.info(
        "This page returns aggregate counts only. It does not display patient identifiers or export row-level data. "
        "Counts are exploratory and depend on the chosen code prefixes and filters."
    )
    st.warning("This is not a validated computable phenotype. Treat it as a fast code-count explorer for feasibility and QA.")

    if not run_query:
        st.stop()
    if not prefixes:
        st.warning("Enter at least one code prefix or choose a preset.")
        st.stop()

    where_parts = [prefix_condition(dx_col, prefixes), optional_filter(dx_type_col, selected_dx_types), date_condition(dx_date_col, start_text, end_text)]
    where_sql = " and ".join(f"({x})" for x in where_parts if x)

    distinct_patient_expr = f"approx_count_distinct({quote_ident(patid_col)})"
    distinct_enc_expr = f"approx_count_distinct({quote_ident(encid_col)})" if encid_col else "null"
    date_min_expr = f"min({quote_ident(dx_date_col)})" if dx_date_col else "null"
    date_max_expr = f"max({quote_ident(dx_date_col)})" if dx_date_col else "null"

    summary_sql = f"""
    select
      count(*) as diagnosis_rows,
      {distinct_patient_expr} as approx_patients,
      {distinct_enc_expr} as approx_encounters,
      {date_min_expr} as min_dx_date,
      {date_max_expr} as max_dx_date
    from {diagnosis_expr}
    where {where_sql}
    """

    with st.spinner("Running cohort summary..."):
        summary = con.execute(summary_sql).df()

    if summary.empty:
        st.warning("No rows returned.")
        st.stop()

    diagnosis_rows = int(summary.loc[0, "diagnosis_rows"])
    approx_patients = int(summary.loc[0, "approx_patients"])
    approx_encounters = summary.loc[0, "approx_encounters"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Diagnosis rows", compact_int(diagnosis_rows))
    c2.metric("Approx patients", compact_int(approx_patients))
    if pd.notna(approx_encounters):
        c3.metric("Approx encounters", compact_int(int(approx_encounters)))
    c4.metric("Date span", f"{summary.loc[0, 'min_dx_date']} to {summary.loc[0, 'max_dx_date']}")
    st.caption(f"Full counts: {diagnosis_rows:,} diagnosis rows; approx {approx_patients:,} patients.")

    st.subheader("Cohort definition")
    st.json({"preset": preset, "prefixes": prefixes, "dx_type_filter": selected_dx_types, "date_column": dx_date_col, "date_filter": [start_text, end_text] if use_dates else []})

    dx_type_expr = f"cast({quote_ident(dx_type_col)} as varchar)" if dx_type_col else "''"
    code_sql = f"""
    select
      cast({quote_ident(dx_col)} as varchar) as dx,
      {dx_type_expr} as dx_type,
      count(*) as diagnosis_rows,
      approx_count_distinct({quote_ident(patid_col)}) as approx_patients
    from {diagnosis_expr}
    where {where_sql}
    group by 1, 2
    order by diagnosis_rows desc
    limit 100
    """
    code_df = con.execute(code_sql).df()
    st.subheader("Top diagnosis codes")
    st.dataframe(safe_display(code_df, settings), use_container_width=True, hide_index=True)
    if not code_df.empty:
        st.plotly_chart(px.bar(code_df.head(25), x="dx", y="diagnosis_rows", color="dx_type", title="Top matching diagnosis codes"), use_container_width=True)

    if not run_breakdowns:
        st.stop()

    cohort_cte = f"""
    cohort_patients as (
      select distinct {quote_ident(patid_col)} as PATID
      from {diagnosis_expr}
      where {where_sql}
    )
    """

    if demographic_path is not None:
        dem_expr = read_parquet_expr(demographic_path)
        dem_cols = table_columns(con, demographic_path)
        dem_patid = find_column(dem_cols, ["PATID"])
        breakdown_cols = [c for c in [find_column(dem_cols, ["SEX"]), find_column(dem_cols, ["RACE"]), find_column(dem_cols, ["HISPANIC"]), find_column(dem_cols, ["RUCA_CODE"])] if c]
        if dem_patid and breakdown_cols:
            st.subheader("Demographic breakdown")
            tabs = st.tabs(breakdown_cols)
            for tab, col in zip(tabs, breakdown_cols):
                with tab:
                    sql = f"""
                    with {cohort_cte}
                    select cast(d.{quote_ident(col)} as varchar) as value, count(*) as patient_count
                    from cohort_patients c
                    join {dem_expr} d on c.PATID = d.{quote_ident(dem_patid)}
                    group by 1
                    order by patient_count desc
                    """
                    df = con.execute(sql).df()
                    st.dataframe(safe_display(df, settings), use_container_width=True, hide_index=True)
                    if not df.empty:
                        st.plotly_chart(px.bar(df, x="value", y="patient_count", title=f"Cohort by {col}"), use_container_width=True)

    if encounter_path is not None and encid_col:
        enc_expr = read_parquet_expr(encounter_path)
        enc_cols = table_columns(con, encounter_path)
        enc_encid = find_column(enc_cols, ["ENCOUNTERID"])
        enc_type = find_column(enc_cols, ["ENC_TYPE"])
        facility_type = find_column(enc_cols, ["FACILITY_TYPE"])
        admit_date = find_column(enc_cols, ["ADMIT_DATE"])
        if enc_encid:
            st.subheader("Encounter breakdown")
            cohort_enc_cte = f"""
            cohort_encounters as (
              select distinct {quote_ident(encid_col)} as ENCOUNTERID
              from {diagnosis_expr}
              where {where_sql} and {quote_ident(encid_col)} is not null
            )
            """
            enc_break_cols = [c for c in [enc_type, facility_type] if c]
            for col in enc_break_cols:
                sql = f"""
                with {cohort_enc_cte}
                select cast(e.{quote_ident(col)} as varchar) as value, count(*) as encounter_count
                from cohort_encounters c
                join {enc_expr} e on c.ENCOUNTERID = e.{quote_ident(enc_encid)}
                group by 1
                order by encounter_count desc
                """
                df = con.execute(sql).df()
                st.markdown(f"**{col}**")
                st.dataframe(safe_display(df, settings), use_container_width=True, hide_index=True)
            if admit_date:
                sql = f"""
                with {cohort_enc_cte}
                select year(e.{quote_ident(admit_date)}) as admit_year, count(*) as encounter_count
                from cohort_encounters c
                join {enc_expr} e on c.ENCOUNTERID = e.{quote_ident(enc_encid)}
                where e.{quote_ident(admit_date)} is not null
                group by 1
                order by 1
                """
                df = con.execute(sql).df()
                st.markdown("**Admission year**")
                st.dataframe(safe_display(df, settings), use_container_width=True, hide_index=True)
                if not df.empty:
                    st.plotly_chart(px.line(df, x="admit_year", y="encounter_count", markers=True, title="Cohort encounters by admission year"), use_container_width=True)


main()
