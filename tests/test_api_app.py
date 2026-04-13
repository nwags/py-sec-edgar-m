from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from httpx import ASGITransport, AsyncClient

from py_sec_edgar.api.app import create_app
from py_sec_edgar.api.service import FetchResult, FilingRetrievalService
from py_sec_edgar.config import load_config


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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
    out = config.normalized_refdata_root / "local_lookup_filings.parquet"
    pd.DataFrame(rows).to_parquet(out, index=False)


def _write_merged_index(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(config.merged_index_path, index=False)


def _create_submission(config, filename: str, content: str = "submission text") -> Path:
    out = config.download_root / Path(filename.lstrip("/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return out


@pytest.mark.anyio
async def test_create_app_and_health_endpoint(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    transport = ASGITransport(app=create_app(config))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "py-sec-edgar-api"}


@pytest.mark.anyio
async def test_get_filing_metadata_returns_merged_index_metadata_when_local_file_missing(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/filings/0000320193-25-000010")
    assert response.status_code == 200
    payload = response.json()
    assert payload["accession_number"] == "0000320193-25-000010"
    assert payload["metadata_source"] == "merged_index"
    assert payload["metadata_surface"] == "sec_archives_full_or_daily_index_merged"
    assert payload["local_content_available"] is False
    assert payload["submission_path"].endswith("edgar/data/320193/0000320193-25-000010.txt")
    assert payload["resolution_meta"]["resolution_mode"] == "local_only"
    assert payload["resolution_meta"]["remote_attempted"] is False


@pytest.mark.anyio
async def test_get_filing_content_returns_local_file(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    submission = _create_submission(
        config,
        "edgar/data/320193/0000320193-25-000010.txt",
        content="local filing payload",
    )
    _write_local_lookup(
        config,
        [
            {
                "accession_number": "0000320193-25-000010",
                "filename": "edgar/data/320193/0000320193-25-000010.txt",
                "submission_path": str(submission),
                "submission_exists": True,
                "submission_path_count": 1,
            }
        ],
    )
    transport = ASGITransport(app=create_app(config))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/filings/0000320193-25-000010/content")
    assert response.status_code == 200
    assert response.text == "local filing payload"
    assert response.headers["x-m-cache-resolution-mode"] == "resolve_if_missing"
    assert response.headers["x-m-cache-served-from"] == "local_cache"
    assert response.headers["x-m-cache-remote-attempted"] == "false"


@pytest.mark.anyio
async def test_get_filing_content_remote_fallback_persists_and_second_call_is_local(tmp_path: Path) -> None:
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
    fetch_client = FakeFetchClient([FetchResult(ok=True)], payload=b"persisted from remote")
    service = FilingRetrievalService(config, fetch_client=fetch_client)
    transport = ASGITransport(app=create_app(config, retrieval_service=service))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.get("/filings/0000320193-25-000010/content")
        second = await client.get("/filings/0000320193-25-000010/content")

    assert first.status_code == 200
    assert first.content == b"persisted from remote"
    assert first.headers["x-m-cache-remote-attempted"] == "true"
    assert first.headers["x-m-cache-served-from"] == "remote_then_persisted"
    assert second.status_code == 200
    assert second.content == b"persisted from remote"
    assert len(fetch_client.calls) == 1
    persisted_path = config.download_root / Path("edgar/data/320193/0000320193-25-000010.txt")
    assert persisted_path.exists()


@pytest.mark.anyio
async def test_get_filing_content_unresolved_accession_returns_404(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    transport = ASGITransport(app=create_app(config))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/filings/0000320193-25-000010/content")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_filing_content_remote_fetch_failure_returns_502(tmp_path: Path) -> None:
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
        [FetchResult(ok=False, status_code=404, reason="http_error", error="404 from SEC")]
    )
    service = FilingRetrievalService(config, fetch_client=fetch_client)
    transport = ASGITransport(app=create_app(config, retrieval_service=service))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/filings/0000320193-25-000010/content")
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["reason"] == "http_error"
    assert detail["status_code"] == 404
    assert detail["resolution_meta"]["resolution_mode"] == "resolve_if_missing"
    assert detail["resolution_meta"]["remote_attempted"] is True


@pytest.mark.anyio
async def test_get_filing_content_supports_local_only_mode_without_remote_side_effect(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/filings/0000320193-25-000010/content?resolution_mode=local_only")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["resolution_meta"]["resolution_mode"] == "local_only"
    assert detail["resolution_meta"]["remote_attempted"] is False
    assert detail["resolution_meta"]["reason_code"] == "local_miss"


@pytest.mark.anyio
async def test_get_filing_metadata_can_request_explicit_content_resolution_meta(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/filings/0000320193-25-000010?resolve_content=true&resolution_mode=local_only"
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["resolution_meta"]["resolution_mode"] == "local_only"
    assert payload["resolution_meta"]["remote_attempted"] is False


@pytest.mark.anyio
async def test_api_content_lan_cache_smoke_flow(tmp_path: Path) -> None:
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
    fetch_client = FakeFetchClient([FetchResult(ok=True)], payload=b"smoke payload")
    service = FilingRetrievalService(config, fetch_client=fetch_client)
    transport = ASGITransport(app=create_app(config, retrieval_service=service))
    expected_path = config.download_root / Path("edgar/data/320193/0000320193-25-000010.txt")

    assert not expected_path.exists()
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.get("/filings/0000320193-25-000010/content")
        second = await client.get("/filings/0000320193-25-000010/content")

    assert first.status_code == 200
    assert second.status_code == 200
    assert expected_path.exists()
    assert len(fetch_client.calls) == 1
