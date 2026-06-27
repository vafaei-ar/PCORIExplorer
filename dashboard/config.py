from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_path(value: str | Path | None, *, base: Path | None = None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base or PROJECT_ROOT) / path


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return loaded


def get_settings() -> dict[str, Any]:
    settings = load_yaml(PROJECT_ROOT / "dashboard" / "config" / "dashboard_settings.yaml")
    app = settings.setdefault("app", {})
    app["project_root"] = str(PROJECT_ROOT)
    data_root = os.environ.get("PCORI_DATA_ROOT", app.get("default_data_root"))
    parquet_root = os.environ.get("PCORI_PARQUET_ROOT", app.get("default_parquet_root"))
    audit_dir = os.environ.get("PCORI_AUDIT_DIR", app.get("default_audit_dir"))
    app["data_root"] = str(_resolve_path(data_root, base=PROJECT_ROOT))
    app["parquet_root"] = str(_resolve_path(parquet_root, base=PROJECT_ROOT))
    app["audit_dir"] = str(_resolve_path(audit_dir, base=PROJECT_ROOT))
    return settings


def get_cdm_tables() -> dict[str, Any]:
    data = load_yaml(PROJECT_ROOT / "dashboard" / "config" / "cdm_tables.yaml")
    return data.get("tables", {})


def ensure_output_dirs(settings: dict[str, Any] | None = None) -> None:
    settings = settings or get_settings()
    Path(settings["app"]["audit_dir"]).mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "outputs" / "concepts").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "outputs" / "queries").mkdir(parents=True, exist_ok=True)
