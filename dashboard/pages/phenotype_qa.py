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

DEFAULT_IMAGING_PREFIXES = ["70450", "70460", "70470", "70496", "70498", "70551", "70552", "70553", "70544", "70545", "70546", "70547", "70548", "70549"]
DEFAULT_ACUTE_ENC_TYPES = ["IP", "EI", "ED"]


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


def optional_filter(column: str | None, selected: list[str]) -> str:
    if not column or not selected:
        return "1=1"
    values = ", ".join(sql_string(x) for x in selected)
    return f"cast({quote_ident(column)} as varchar) in ({values})"


def date_condition(column: str | None, start_text: str, end_text: str) -> str:
    if not column:
        return "1=1"
    parts = []
    if start_text.strip():
        parts.append(f"cast({quote_ident(column)} as date) >= date {sql_string(start_text.strip())}")
    if end_text.strip():
        parts.append(f"cast({quote_ident(column)} as date) <= date {sql_string(end_text.strip())}")
    return " and ".join(parts) if parts else "1=1"


def safe_display(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    threshold = int(settings.get("privacy", {}).get("small_cell_threshold", 11))
    return apply_small_cell_suppression(
        df,
        count_columns=("n", "patients", "events", "patient_count", "event_count", "encounter_count", "supported_events", "unsupported_events"),
        threshold=threshold,
    )


def show_df(df: pd.DataFrame) -> None:
    st.dataframe(df, width="stretch", hide_index=True)


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
    con = get_connection(settings.get("performance", {}).get("duckdb_memory_limit", "8GB"))
    st.title("Phenotype QA")
    st.caption("Aggregate checks for diagnosis-code cohorts. This page helps decide whether a code-only cohort is plausible enough for deeper validation.")

    diagnosis_path = parquet_path_for_table(settings, "diagnosis")
    encounter_path = parquet_path_for_table(settings, "encounter")
    procedures_path = parquet_path_for_table(settings, "procedures")
    vital_path = parquet_path_for_table(settings, "vital")
    lab_path = parquet_path_for_table(settings, "lab_result_cm")
    med_admin_path = parquet_path_for_table(settings, "med_admin")

    if diagnosis_path is None:
        st.error("diagnosis.parquet was not found.")
        st.stop()

    diagnosis_expr = read_parquet_expr(diagnosis_path)
    diagnosis_cols = table_columns(con, diagnosis_path)
    dx_col = find_column(diagnosis_cols, ["DX"])
    dx_type_col = find_column(diagnosis_cols, ["DX_TYPE"])
    dx_date_col = find_column(diagnosis_cols, ["DX_DATE", "ADMIT_DATE"])
    patid_col = find_column(diagnosis_cols, ["PATID"])
    encid_col = find_column(diagnosis_cols, ["ENCOUNTERID"])
    pdx_col = find_column(diagnosis_cols, ["PDX", "PRIMARY_DX"])
    dx_source_col = find_column(diagnosis_cols, ["DX_SOURCE"])

    if not dx_col or not patid_col:
        st.error("The diagnosis table does not have the expected DX and PATID columns.")
        st.stop()

    with st.sidebar:
        st.header("Candidate phenotype")
        preset = st.selectbox("Concept preset", list(PRESETS.keys()))
        prefixes = parse_prefixes(st.text_area("Diagnosis code prefixes", "\n".join(PRESETS[preset]), height=120))
        dx_type_values = get_distinct_values(con, diagnosis_expr, dx_type_col)
        selected_dx_types = st.multiselect("DX_TYPE filter", dx_type_values, default=[])
        use_dates = st.checkbox("Filter by diagnosis date", value=False)
        start_text = st.text_input("Start date YYYY-MM-DD", value="2010-01-01") if use_dates else ""
        end_text = st.text_input("End date YYYY-MM-DD", value="2026-12-31") if use_dates else ""
        st.header("Support rules")
        acute_text = st.text_input("Acute encounter types", value=", ".join(DEFAULT_ACUTE_ENC_TYPES))
        imaging_text = st.text_area("Neuroimaging PX prefixes", value="\n".join(DEFAULT_IMAGING_PREFIXES), height=120)
        include_large_support = st.checkbox("Run support checks on procedure, vital, lab, and med_admin tables", value=False)
        run_query = st.button("Run phenotype QA", type="primary")

    st.info(
        "All outputs are aggregate. This is not validation against a registry or chart review. It is a QA screen for code-only phenotypes."
    )

    if not run_query:
        st.stop()
    if not prefixes:
        st.warning("Enter at least one diagnosis prefix.")
        st.stop()

    where_parts = [prefix_condition(dx_col, prefixes), optional_filter(dx_type_col, selected_dx_types), date_condition(dx_date_col, start_text, end_text)]
    where_sql = " and ".join(f"({p})" for p in where_parts if p)
    order_col = quote_ident(dx_date_col) if dx_date_col else quote_ident(dx_col)
    enc_expr = read_parquet_expr(encounter_path) if encounter_path else None

    first_event_cte = f"""
    dx_matches as (
      select
        {quote_ident(patid_col)} as PATID,
        {quote_ident(encid_col) if encid_col else 'null'} as ENCOUNTERID,
        {quote_ident(dx_col)} as DX,
        {quote_ident(dx_type_col) if dx_type_col else 'null'} as DX_TYPE,
        {quote_ident(dx_date_col) if dx_date_col else 'null'} as DX_DATE,
        row_number() over (partition by {quote_ident(patid_col)} order by {order_col} nulls last) as rn
      from {diagnosis_expr}
      where {where_sql}
    ),
    first_events as (
      select * from dx_matches where rn = 1
    )
    """

    summary_sql = f"""
    with {first_event_cte}
    select
      count(*) as patient_events,
      count(ENCOUNTERID) as events_with_encounterid,
      count(*) - count(ENCOUNTERID) as events_without_encounterid,
      min(DX_DATE) as min_dx_date,
      max(DX_DATE) as max_dx_date
    from first_events
    """
    summary = con.execute(summary_sql).df()
    total_events = int(summary.loc[0, "patient_events"])
    with_enc = int(summary.loc[0, "events_with_encounterid"])
    without_enc = int(summary.loc[0, "events_without_encounterid"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Candidate patients", compact_int(total_events))
    c2.metric("With encounter ID", compact_int(with_enc))
    c3.metric("Without encounter ID", compact_int(without_enc))
    st.caption(f"First matching diagnosis per patient. Date span: {summary.loc[0, 'min_dx_date']} to {summary.loc[0, 'max_dx_date']}.")

    qa_rows = [
        {"check": "candidate patients", "events": total_events, "pct_of_candidates": 100.0},
        {"check": "has ENCOUNTERID", "events": with_enc, "pct_of_candidates": round(100 * with_enc / total_events, 2) if total_events else 0},
        {"check": "missing ENCOUNTERID", "events": without_enc, "pct_of_candidates": round(100 * without_enc / total_events, 2) if total_events else 0},
    ]

    if enc_expr and encid_col:
        encounter_cols = table_columns(con, encounter_path)
        enc_encid = find_column(encounter_cols, ["ENCOUNTERID"])
        enc_type_col = find_column(encounter_cols, ["ENC_TYPE"])
        admit_col = find_column(encounter_cols, ["ADMIT_DATE"])
        discharge_col = find_column(encounter_cols, ["DISCHARGE_DATE"])
        acute_values = [x.strip() for x in acute_text.split(",") if x.strip()]
        if enc_encid and enc_type_col:
            acute_filter = optional_filter(f"e.{enc_type_col}", [])
            acute_values_sql = ", ".join(sql_string(x) for x in acute_values)
            acute_sql = f"""
            with {first_event_cte}
            select count(*) as n
            from first_events f
            join {enc_expr} e on f.ENCOUNTERID = e.{quote_ident(enc_encid)}
            where cast(e.{quote_ident(enc_type_col)} as varchar) in ({acute_values_sql})
            """
            acute_n = int(con.execute(acute_sql).fetchone()[0]) if acute_values else 0
            qa_rows.append({"check": "acute encounter type", "events": acute_n, "pct_of_candidates": round(100 * acute_n / total_events, 2) if total_events else 0})

            enc_type_sql = f"""
            with {first_event_cte}
            select cast(e.{quote_ident(enc_type_col)} as varchar) as value, count(*) as event_count
            from first_events f
            join {enc_expr} e on f.ENCOUNTERID = e.{quote_ident(enc_encid)}
            group by 1
            order by event_count desc
            """
            enc_type_df = con.execute(enc_type_sql).df()
            st.subheader("Index-event encounter type")
            show_df(safe_display(enc_type_df, settings))
            if not enc_type_df.empty:
                st.plotly_chart(px.bar(enc_type_df, x="value", y="event_count", title="Candidate first events by encounter type"), width="stretch")

        if enc_encid and admit_col and discharge_col:
            date_consistency_sql = f"""
            with {first_event_cte}
            select
              sum(case when f.DX_DATE < e.{quote_ident(admit_col)} then 1 else 0 end) as dx_before_admit,
              sum(case when f.DX_DATE > e.{quote_ident(discharge_col)} then 1 else 0 end) as dx_after_discharge,
              count(*) as linked_events
            from first_events f
            join {enc_expr} e on f.ENCOUNTERID = e.{quote_ident(enc_encid)}
            where f.DX_DATE is not null and e.{quote_ident(admit_col)} is not null and e.{quote_ident(discharge_col)} is not null
            """
            date_df = con.execute(date_consistency_sql).df()
            if not date_df.empty:
                linked = int(date_df.loc[0, "linked_events"] or 0)
                before = int(date_df.loc[0, "dx_before_admit"] or 0)
                after = int(date_df.loc[0, "dx_after_discharge"] or 0)
                qa_rows.append({"check": "DX date before admit", "events": before, "pct_of_candidates": round(100 * before / linked, 2) if linked else 0})
                qa_rows.append({"check": "DX date after discharge", "events": after, "pct_of_candidates": round(100 * after / linked, 2) if linked else 0})

    if pdx_col:
        pdx_sql = f"""
        select cast({quote_ident(pdx_col)} as varchar) as value, count(*) as n
        from {diagnosis_expr}
        where {where_sql}
        group by 1
        order by n desc
        """
        st.subheader("Diagnosis position / primary flag")
        show_df(safe_display(con.execute(pdx_sql).df(), settings))

    if dx_source_col:
        source_sql = f"""
        select cast({quote_ident(dx_source_col)} as varchar) as value, count(*) as n
        from {diagnosis_expr}
        where {where_sql}
        group by 1
        order by n desc
        """
        st.subheader("Diagnosis source")
        show_df(safe_display(con.execute(source_sql).df(), settings))

    if include_large_support and encid_col:
        support_tables = []
        if procedures_path:
            proc_cols = table_columns(con, procedures_path)
            proc_enc = find_column(proc_cols, ["ENCOUNTERID"])
            px_col = find_column(proc_cols, ["PX"])
            if proc_enc:
                proc_expr = read_parquet_expr(procedures_path)
                any_proc_sql = f"""
                with {first_event_cte}, supported as (
                  select distinct f.PATID
                  from first_events f
                  join {proc_expr} p on f.ENCOUNTERID = p.{quote_ident(proc_enc)}
                )
                select count(*) from supported
                """
                n = int(con.execute(any_proc_sql).fetchone()[0])
                qa_rows.append({"check": "same-encounter procedure record", "events": n, "pct_of_candidates": round(100 * n / total_events, 2) if total_events else 0})
                if px_col:
                    imaging_prefixes = parse_prefixes(imaging_text)
                    img_sql = f"""
                    with {first_event_cte}, supported as (
                      select distinct f.PATID
                      from first_events f
                      join {proc_expr} p on f.ENCOUNTERID = p.{quote_ident(proc_enc)}
                      where {prefix_condition('p.' + px_col, imaging_prefixes)}
                    )
                    select count(*) from supported
                    """
                    # quote_ident cannot accept alias-qualified names, so build imaging query separately below.
                    img_clauses = [f"upper(cast(p.{quote_ident(px_col)} as varchar)) like {sql_string(prefix + '%')}" for prefix in imaging_prefixes]
                    img_where = "(" + " or ".join(img_clauses) + ")" if img_clauses else "1=1"
                    img_sql = f"""
                    with {first_event_cte}, supported as (
                      select distinct f.PATID
                      from first_events f
                      join {proc_expr} p on f.ENCOUNTERID = p.{quote_ident(proc_enc)}
                      where {img_where}
                    )
                    select count(*) from supported
                    """
                    n = int(con.execute(img_sql).fetchone()[0])
                    qa_rows.append({"check": "same-encounter neuroimaging PX prefix", "events": n, "pct_of_candidates": round(100 * n / total_events, 2) if total_events else 0})

        for label, path in [("vital", vital_path), ("lab_result_cm", lab_path), ("med_admin", med_admin_path)]:
            if path is None:
                continue
            cols = table_columns(con, path)
            table_enc = find_column(cols, ["ENCOUNTERID"])
            if not table_enc:
                continue
            expr = read_parquet_expr(path)
            sql = f"""
            with {first_event_cte}, supported as (
              select distinct f.PATID
              from first_events f
              join {expr} x on f.ENCOUNTERID = x.{quote_ident(table_enc)}
            )
            select count(*) from supported
            """
            n = int(con.execute(sql).fetchone()[0])
            qa_rows.append({"check": f"same-encounter {label} record", "events": n, "pct_of_candidates": round(100 * n / total_events, 2) if total_events else 0})

    qa_df = pd.DataFrame(qa_rows)
    st.subheader("QA summary")
    show_df(safe_display(qa_df, settings))
    if not qa_df.empty:
        chart_df = qa_df[qa_df["check"] != "candidate patients"].copy()
        st.plotly_chart(px.bar(chart_df, x="pct_of_candidates", y="check", orientation="h", title="QA checks as percent of candidate patients"), width="stretch")

    st.subheader("Interpretation guide")
    st.markdown(
        """
- A high code-only count with many ambulatory encounters may indicate that the cohort includes history/follow-up codes, not only acute stroke events.
- Same-encounter procedure, vital, lab, or medication support is not proof of stroke, but low support can flag weak phenotyping.
- Neuroimaging procedure prefixes are only a rough heuristic and need site-specific validation.
- Final phenotypes should be validated against registry, chart review, or a trusted local cohort before publication.
        """
    )


main()
