from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from py_sec_edgar.config import AppConfig


_MAX_PROVENANCE_ROWS = 200000

RESOLUTION_PROVENANCE_COLUMNS = [
    "event_time",
    "flow",
    "provider_id",
    "accession_number",
    "filename",
    "filing_cik",
    "form_type",
    "filing_date",
    "metadata_surface",
    "content_surface",
    "decision",
    "remote_url",
    "local_path",
    "persisted_locally",
    "status_code",
    "reason",
    "error",
    "error_class",
]


def filing_resolution_provenance_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "filing_resolution_provenance.parquet"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=RESOLUTION_PROVENANCE_COLUMNS)
    df = pd.read_parquet(path)
    for col in RESOLUTION_PROVENANCE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RESOLUTION_PROVENANCE_COLUMNS]


def append_resolution_provenance_events(config: AppConfig, rows: list[dict[str, object]]) -> int:
    path = filing_resolution_provenance_path(config)
    current = _load_or_empty(path)
    if rows:
        current = pd.concat([current, pd.DataFrame(rows)], ignore_index=True)
    if len(current.index) > _MAX_PROVENANCE_ROWS:
        current = current.tail(_MAX_PROVENANCE_ROWS).reset_index(drop=True)
    current.to_parquet(path, index=False)
    return int(len(current.index))
