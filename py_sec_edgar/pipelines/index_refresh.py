from __future__ import annotations

from py_sec_edgar.config import AppConfig
import py_sec_edgar.feeds as feeds


def run_index_refresh(
    config: AppConfig,
    *,
    save_idx_as_csv: bool = True,
    skip_if_exists: bool = True,
) -> None:
    # Keep behavior explicit and routed through a pipeline entrypoint.
    config.ensure_runtime_dirs()
    feeds.update_full_index_feed(save_idx_as_csv=save_idx_as_csv, skip_if_exists=skip_if_exists)
