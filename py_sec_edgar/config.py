from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    normalized_refdata_root: Path
    user_agent: str
    request_timeout_connect: float
    request_timeout_read: float
    max_requests_per_second: float
    download_workers: int
    extract_workers: int
    forms: List[str]

    @classmethod
    def from_project_root(cls, project_root: Path | str) -> "AppConfig":
        root = Path(project_root).resolve()
        refdata_root = root / "refdata"
        return cls(
            project_root=root,
            refdata_root=refdata_root,
            raw_refdata_root=refdata_root / "sec_sources",
            normalized_refdata_root=refdata_root / "normalized",
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


def load_config(project_root: Path | str | None = None) -> AppConfig:
    if project_root is None:
        project_root = Path(__file__).resolve().parents[1]
    return AppConfig.from_project_root(project_root)


def now_utc_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
