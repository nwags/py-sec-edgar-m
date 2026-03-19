from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable

from py_sec_edgar.config import load_config
from py_sec_edgar.download import ProxyRequest


@dataclass(frozen=True)
class DownloadTask:
    url: str
    filepath: str


@dataclass(frozen=True)
class DownloadResult:
    url: str
    filepath: str
    success: bool
    reason: str | None
    status_code: int | None
    error: str | None
    error_class: str | None
    retry_exhausted: bool


def _resolve_download_workers(max_workers: int | None) -> int:
    if max_workers is not None:
        return max(1, int(max_workers))
    config = load_config()
    return max(1, int(config.download_workers))


def _run_single_download(task: DownloadTask, downloader_config=None) -> DownloadResult:
    downloader = ProxyRequest(CONFIG=downloader_config)
    try:
        success = downloader.GET_FILE(task.url, task.filepath)
        failure = downloader.last_failure or {}
        return DownloadResult(
            url=task.url,
            filepath=task.filepath,
            success=bool(success),
            reason=failure.get("reason"),
            status_code=failure.get("status_code"),
            error=failure.get("error"),
            error_class=failure.get("error_class"),
            retry_exhausted=bool(failure.get("retry_exhausted", not bool(success))),
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        error_text = str(exc)
        if len(error_text) > 240:
            error_text = error_text[:240]
        return DownloadResult(
            url=task.url,
            filepath=task.filepath,
            success=False,
            reason="request_exception",
            status_code=None,
            error=error_text,
            error_class=type(exc).__name__,
            retry_exhausted=True,
        )


def run_bounded_downloads(
    tasks: Iterable[DownloadTask],
    *,
    max_workers: int | None = None,
    downloader_config=None,
) -> list[DownloadResult]:
    work = list(tasks)
    if not work:
        return []

    worker_count = _resolve_download_workers(max_workers)
    results: list[DownloadResult] = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_run_single_download, task, downloader_config): task
            for task in work
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # pragma: no cover - defensive guard
                error_text = str(exc)
                if len(error_text) > 240:
                    error_text = error_text[:240]
                results.append(
                    DownloadResult(
                        url=task.url,
                        filepath=task.filepath,
                        success=False,
                        reason="request_exception",
                        status_code=None,
                        error=error_text,
                        error_class=type(exc).__name__,
                        retry_exhausted=True,
                    )
                )

    # Deterministic ordering for downstream processing.
    results.sort(key=lambda item: item.filepath)
    return results
