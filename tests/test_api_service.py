from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from py_sec_edgar.api.service import (
    FetchResult,
    ProxyRequestFetchClient,
    RetrievalDecision,
    derive_archives_base_url,
    derive_remote_filing_url,
    find_filing_metadata,
    retrieve_filing_content_local_first,
)
from py_sec_edgar.config import load_config
from py_sec_edgar.lookup import local_lookup_filings_path
from py_sec_edgar.resolution_provenance import filing_resolution_provenance_path


class FakeFetchClient:
    def __init__(self, results: list[FetchResult], *, payload: bytes = b"remote payload") -> None:
        self._results = list(results)
        self._payload = payload
        self.calls: list[tuple[str, Path]] = []

    def fetch(self, url: str, destination_path: Path) -> FetchResult:
        self.calls.append((url, destination_path))
        if not self._results:
            raise AssertionError("No fake fetch results left for call.")
        result = self._results.pop(0)
        if result.ok:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_bytes(self._payload)
        return result


def _write_local_lookup(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(local_lookup_filings_path(config), index=False)


def _write_merged_index(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(config.merged_index_path, index=False)


def _create_submission(config, filename: str, content: str = "submission body") -> Path:
    out = config.download_root / Path(filename.lstrip("/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return out


def test_retrieve_filing_content_local_first_local_hit(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    submission = _create_submission(config, "edgar/data/320193/0000320193-25-000010.txt")
    _write_local_lookup(
        config,
        [
            {
                "accession_number": "0000320193-25-000010",
                "filename": "edgar/data/320193/0000320193-25-000010.txt",
                "submission_path": str(tmp_path / "noncanonical.txt"),
                "submission_exists": False,
                "submission_path_count": 1,
            }
        ],
    )

    result = retrieve_filing_content_local_first(config, "0000320193-25-000010")
    assert result.decision == RetrievalDecision.LOCAL_HIT
    assert result.local_path == submission


def test_find_filing_metadata_falls_back_to_merged_index(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged_index(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "SC 13D",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ],
    )

    metadata = find_filing_metadata(config, "0000320193-25-000010")
    assert metadata is not None
    assert metadata.metadata_source == "merged_index"
    assert metadata.filename == "edgar/data/320193/0000320193-25-000010.txt"


def test_retrieve_filing_content_remote_fetch_success_persists_and_second_hit_is_local(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged_index(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "SC 13D",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ],
    )
    fetch_client = FakeFetchClient([FetchResult(ok=True)], payload=b"from sec")

    first = retrieve_filing_content_local_first(
        config,
        "0000320193-25-000010",
        fetch_client=fetch_client,
    )
    assert first.decision == RetrievalDecision.REMOTE_FETCHED_AND_PERSISTED
    assert first.local_path is not None
    assert first.local_path.exists()
    assert first.local_path.read_bytes() == b"from sec"
    assert len(fetch_client.calls) == 1

    second = retrieve_filing_content_local_first(
        config,
        "0000320193-25-000010",
        fetch_client=fetch_client,
    )
    assert second.decision == RetrievalDecision.LOCAL_HIT
    assert second.local_path == first.local_path
    assert len(fetch_client.calls) == 1
    provenance = pd.read_parquet(filing_resolution_provenance_path(config))
    assert len(provenance.index) == 1
    row = provenance.iloc[0]
    assert row["flow"] == "api"
    assert row["decision"] == "remote_fetched_and_persisted"
    assert bool(row["persisted_locally"]) is True


def test_retrieve_filing_content_local_first_not_found(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    result = retrieve_filing_content_local_first(config, "0000320193-25-000010")
    assert result.decision == RetrievalDecision.NOT_FOUND


def test_find_filing_metadata_validates_accession_format(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    with pytest.raises(ValueError, match="Invalid accession number format"):
        find_filing_metadata(config, "invalid-accession")


def test_retrieve_filing_content_remote_fetch_failure_returns_explicit_failure(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged_index(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "SC 13D",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ],
    )
    fetch_client = FakeFetchClient(
        [FetchResult(ok=False, status_code=404, reason="http_error", error="404 Not Found")]
    )

    result = retrieve_filing_content_local_first(
        config,
        "0000320193-25-000010",
        fetch_client=fetch_client,
    )
    assert result.decision == RetrievalDecision.REMOTE_FETCH_FAILED
    assert result.reason == "http_error"
    assert result.status_code == 404
    assert result.local_path is not None
    assert not result.local_path.exists()
    provenance = pd.read_parquet(filing_resolution_provenance_path(config))
    assert len(provenance.index) == 1
    row = provenance.iloc[0]
    assert row["flow"] == "api"
    assert row["decision"] == "remote_fetch_failed"
    assert bool(row["persisted_locally"]) is False
    assert int(row["status_code"]) == 404


def test_derive_archives_base_url_uses_legacy_settings_when_not_present_on_app_config(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert derive_archives_base_url(config) == "https://www.sec.gov/Archives/"
    assert derive_remote_filing_url(config, "edgar/data/320193/0000320193-25-000010.txt").startswith(
        "https://www.sec.gov/Archives/edgar/data/320193/"
    )


def test_proxy_request_fetch_client_is_injectable_wrapper(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    calls: list[tuple[str, str]] = []

    class DummyDownloader:
        def __init__(self, CONFIG=None):
            self.last_failure = None

        def GET_FILE(self, url, filepath):
            calls.append((url, filepath))
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(filepath).write_text("ok", encoding="utf-8")
            return True

    monkeypatch.setattr("py_sec_edgar.api.service.ProxyRequest", DummyDownloader)
    client = ProxyRequestFetchClient(config)
    out = tmp_path / "x.txt"
    result = client.fetch("https://example.test/file.txt", out)
    assert result.ok is True
    assert out.exists()
    assert len(calls) == 1
