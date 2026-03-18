from __future__ import annotations

from pathlib import Path
from typing import Dict

from py_sec_edgar.config import AppConfig
from py_sec_edgar.refdata.builder import build_all_tables, write_tables_to_parquet
from py_sec_edgar.refdata.sources import load_all_sources


def run_refdata_refresh(config: AppConfig) -> Dict[str, Path]:
    config.ensure_runtime_dirs()
    sources = load_all_sources(config.raw_refdata_root)
    tables = build_all_tables(sources)
    return write_tables_to_parquet(tables, config.normalized_refdata_root)
