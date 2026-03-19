from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from typing import List


DEFAULT_SPECIAL_SITUATIONS_FORMS: List[str] = [
    "SC 13D",
    "SC 13D/A",
    "SC 13G",
    "SC 13G/A",
    "3",
    "4",
    "5",
    "8-K",
    "8-K/A",
    "6-K",
    "DEF 14A",
    "DEFA14A",
    "PRE 14A",
    "S-4",
    "S-4/A",
    "F-4",
    "F-4/A",
    "425",
    "SC TO-T",
    "SC TO-T/A",
    "SC TO-I",
    "SC TO-I/A",
    "SC 14D9",
    "SC 14D9/A",
    "SC 13E-3",
    "SC 13E-3/A",
    "13F-HR",
    "13F-HR/A",
    "13F-NT",
    "13F-NT/A",
    "NT 10-K",
    "NT 10-Q",
    "144",
]


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    refdata_root: Path
    raw_refdata_root: Path
    canonical_raw_refdata_root: Path
    normalized_refdata_root: Path
    download_root: Path
    merged_index_path: Path
    user_agent: str
    request_timeout_connect: float
    request_timeout_read: float
    max_requests_per_second: float
    download_workers: int
    extract_workers: int
    forms: List[str]

    @classmethod
    def from_project_root(
        cls,
        project_root: Path | str,
        *,
        use_env_overrides: bool = True,
    ) -> "AppConfig":
        root = Path(project_root).resolve()
        refdata_root = root / "refdata"
        normalized_refdata_root = refdata_root / "normalized"
        download_root = root / ".sec_cache" / "Archives"
        merged_index_path = refdata_root / "merged_idx_files.pq"

        if use_env_overrides:
            normalized_refdata_root = _path_from_env("PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT") or normalized_refdata_root
            download_root = _path_from_env("PY_SEC_EDGAR_DOWNLOAD_ROOT") or download_root
            merged_index_path = _path_from_env("PY_SEC_EDGAR_MERGED_INDEX_PATH") or merged_index_path
        return cls(
            project_root=root,
            refdata_root=refdata_root,
            raw_refdata_root=refdata_root / "sec_sources",
            canonical_raw_refdata_root=get_canonical_raw_refdata_root(),
            normalized_refdata_root=normalized_refdata_root.resolve(),
            download_root=download_root.resolve(),
            merged_index_path=merged_index_path.resolve(),
            user_agent="py-sec-edgar/0.1.0 (research@example.com)",
            request_timeout_connect=10.0,
            request_timeout_read=30.0,
            max_requests_per_second=5.0,
            download_workers=4,
            extract_workers=1,
            forms=list(DEFAULT_SPECIAL_SITUATIONS_FORMS),
        )

    def ensure_runtime_dirs(self) -> None:
        self.refdata_root.mkdir(parents=True, exist_ok=True)
        self.raw_refdata_root.mkdir(parents=True, exist_ok=True)
        self.normalized_refdata_root.mkdir(parents=True, exist_ok=True)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.merged_index_path.parent.mkdir(parents=True, exist_ok=True)


def load_config(project_root: Path | str | None = None) -> AppConfig:
    use_env_overrides = project_root is None
    if project_root is None:
        project_root = _path_from_env("PY_SEC_EDGAR_PROJECT_ROOT") or Path(__file__).resolve().parents[1]
    return AppConfig.from_project_root(project_root, use_env_overrides=use_env_overrides)


def get_canonical_raw_refdata_root() -> Path:
    """Deterministic bundled raw SEC source locator (independent of CWD)."""
    return (Path(__file__).resolve().parents[1] / "refdata" / "sec_sources").resolve()


def now_utc_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _path_from_env(name: str) -> Path | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    return Path(value).expanduser()
