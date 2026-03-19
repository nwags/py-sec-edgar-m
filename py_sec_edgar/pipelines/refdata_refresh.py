from __future__ import annotations

from pathlib import Path
import time
from typing import Dict

from py_sec_edgar.config import AppConfig
from py_sec_edgar.refdata.builder import build_all_tables, write_tables_to_parquet
from py_sec_edgar.refdata.sources import load_all_sources, resolve_raw_sources_root


def run_refdata_refresh(config: AppConfig) -> Dict[str, object]:
    started_at = time.monotonic()
    config.ensure_runtime_dirs()
    sources_root, checked_roots = resolve_raw_sources_root(
        config.raw_refdata_root,
        config.canonical_raw_refdata_root,
    )
    sources = load_all_sources(sources_root)
    tables = build_all_tables(sources)
    written = write_tables_to_parquet(tables, config.normalized_refdata_root)
    artifact_paths = [str(path) for _, path in sorted(written.items())]
    return {
        "written": written,
        "raw_sources_root_used": str(sources_root),
        "raw_sources_root_fallback_used": sources_root.resolve() != config.raw_refdata_root.resolve(),
        "raw_sources_roots_checked": [str(path) for path in checked_roots],
        "artifact_count": int(len(written)),
        "artifact_paths": artifact_paths,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "activity_events": [
            {"stage": "refdata_refresh", "status": "success", "item": path, "detail": "artifact_written"}
            for path in artifact_paths
        ],
    }
