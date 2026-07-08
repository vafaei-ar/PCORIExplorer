from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

DEFAULT_IDENTIFIER_COLUMNS = {
    "PATID",
    "ENCOUNTERID",
    "PROVIDERID",
    "MEDADMINID",
    "PRESCRIBINGID",
    "DISPENSINGID",
    "LAB_RESULT_CM_ID",
    "PROCEDURESID",
    "DIAGNOSISID",
    "CONDITIONID",
    "VITALID",
    "VX_RECORD_ID",
    "IMMUNIZATIONID",
}


def identifier_columns(settings: dict | None = None) -> set[str]:
    configured = []
    if settings:
        configured = settings.get("privacy", {}).get("hidden_identifier_columns", [])
    return DEFAULT_IDENTIFIER_COLUMNS | {str(x).upper() for x in configured}


def drop_identifier_columns(df: pd.DataFrame, settings: dict | None = None) -> pd.DataFrame:
    hidden = identifier_columns(settings)
    keep = [col for col in df.columns if col.upper() not in hidden]
    return df.loc[:, keep].copy()


def suppress_count_value(value: int | float | None, threshold: int = 11) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value)
    if 0 < n < threshold:
        return f"<{threshold}"
    return str(n)


def apply_small_cell_suppression(
    df: pd.DataFrame,
    count_columns: Iterable[str] = ("n", "count", "row_count", "person_count", "distinct_patients"),
    threshold: int = 11,
) -> pd.DataFrame:
    out = df.copy()
    lower_map = {c.lower(): c for c in out.columns}
    for candidate in count_columns:
        col = lower_map.get(candidate.lower())
        if col is not None:
            out[col] = out[col].map(lambda x: suppress_count_value(x, threshold)).astype("string")
    return out
