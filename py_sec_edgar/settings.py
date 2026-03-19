from __future__ import annotations

from datetime import datetime
from pathlib import Path
import warnings
from urllib.parse import urljoin

from py_sec_edgar.config import load_config


class Config:
    """Compatibility shim over typed config.

    Legacy modules still import `CONFIG` from this file. This object avoids
    import-time side effects and maps old attribute names to explicit paths.
    """

    def __init__(self) -> None:
        app = load_config()

        self.extract_filing_contents = False
        self.forms_list = list(app.forms)
        self.index_start_date = "1/1/2019"
        self.index_end_date = datetime.now().strftime("%m/%d/%Y")
        self.index_files = ["master.idx"]
        self.VPN_PROVIDER = "PP"
        self.TEST_MODE = False

        self.ticker_list_filter = True
        self.form_list_filter = True

        self.BASE_DIR = str(app.project_root)
        self.REF_DIR = str(app.refdata_root)
        archives_root = Path(app.download_root)
        if archives_root.name.lower() == "archives":
            sec_root = archives_root.parent
        else:
            sec_root = archives_root
        self.SEC_DIR = str(sec_root)
        self.EDGAR_DIR = str(archives_root / "edgar")
        self.DATA_DIR = str(Path(self.EDGAR_DIR) / "data")
        self.MONTHLY_DIR = str(Path(self.EDGAR_DIR) / "monthly")
        self.FULL_INDEX_DIR = str(Path(self.EDGAR_DIR) / "full-index")
        self.DAILY_INDEX_DIR = str(Path(self.EDGAR_DIR) / "daily-index")
        self.FILING_DIR = str(Path(self.EDGAR_DIR) / "filings")
        self.NORMALIZED_REFDATA_DIR = str(app.normalized_refdata_root)

        self.MERGED_IDX_FILEPATH = str(app.merged_index_path)
        self.TICKER_LIST_FILEPATH = str(Path(self.REF_DIR) / "tickers.csv")
        self.TICKER_CIK_FILEPATH = str(Path(self.REF_DIR) / "cik_tickers.csv")
        self.TXT_FILING_DIR = str(Path(self.EDGAR_DIR) / "data" / "CIK" / "FOLDER")

        self.edgar_Archives_url = "https://www.sec.gov/Archives/"
        self.edgar_full_index = urljoin(self.edgar_Archives_url, "edgar/full-index/")
        self.edgar_full_master_url = urljoin(self.edgar_full_index, "master.idx")
        self.edgar_monthly_index = urljoin(self.edgar_Archives_url, "edgar/monthly/")


_CONFIG_SINGLETON: Config | None = None
_CONFIG_WARNING_EMITTED = False


def _emit_config_deprecation_warning_once() -> None:
    global _CONFIG_WARNING_EMITTED
    if _CONFIG_WARNING_EMITTED:
        return
    warnings.warn(
        "py_sec_edgar.settings.CONFIG is deprecated. Prefer explicit get_config().",
        DeprecationWarning,
        stacklevel=3,
    )
    _CONFIG_WARNING_EMITTED = True


def get_config() -> Config:
    global _CONFIG_SINGLETON
    if _CONFIG_SINGLETON is None:
        _CONFIG_SINGLETON = Config()
    return _CONFIG_SINGLETON


def _is_config_initialized() -> bool:
    return _CONFIG_SINGLETON is not None


def _reset_config_for_tests() -> None:
    global _CONFIG_SINGLETON, _CONFIG_WARNING_EMITTED
    _CONFIG_SINGLETON = None
    _CONFIG_WARNING_EMITTED = False


class _LazyConfigProxy:
    def _target(self) -> Config:
        _emit_config_deprecation_warning_once()
        return get_config()

    def __getattr__(self, name: str):
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._target(), name, value)

    def __repr__(self) -> str:
        status = "initialized" if _is_config_initialized() else "uninitialized"
        return f"<LazyConfigProxy {status}>"


CONFIG = _LazyConfigProxy()
