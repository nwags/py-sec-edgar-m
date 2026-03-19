from __future__ import annotations

from pathlib import Path

from py_sec_edgar.downloader import DownloadTask, _resolve_download_workers, run_bounded_downloads
from py_sec_edgar.rate_limit import get_shared_rate_limiter


class DummyConfig:
    download_workers = 7


class FakeProxyRequest:
    instances = []
    limiter_ids = []

    def __init__(self, CONFIG=None):
        self.last_failure = None
        self.session = object()
        rps = float(getattr(CONFIG, "max_requests_per_second", 5.0))
        limiter = get_shared_rate_limiter(rps)
        self.__class__.instances.append(self)
        self.__class__.limiter_ids.append(id(limiter))

    def GET_FILE(self, url, filepath):
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        if "http-fail" in url:
            self.last_failure = {
                "reason": "http_error",
                "status_code": 404,
                "error": None,
                "error_class": None,
                "retry_exhausted": True,
            }
            return False
        if "timeout" in url:
            self.last_failure = {
                "reason": "timeout",
                "status_code": None,
                "error": "timed out",
                "error_class": "Timeout",
                "retry_exhausted": True,
            }
            return False
        if "connection" in url:
            self.last_failure = {
                "reason": "connection_error",
                "status_code": None,
                "error": "connection refused",
                "error_class": "ConnectionError",
                "retry_exhausted": True,
            }
            return False
        if "ssl" in url:
            self.last_failure = {
                "reason": "ssl_error",
                "status_code": None,
                "error": "certificate verify failed",
                "error_class": "SSLError",
                "retry_exhausted": True,
            }
            return False
        if "malformed" in url:
            self.last_failure = {
                "reason": "malformed_url",
                "status_code": None,
                "error": "invalid url",
                "error_class": "InvalidURL",
                "retry_exhausted": True,
            }
            return False
        if "localio" in url:
            self.last_failure = {
                "reason": "local_io_error",
                "status_code": None,
                "error": "permission denied",
                "error_class": "OSError",
                "retry_exhausted": True,
            }
            return False
        if "request-exception" in url:
            self.last_failure = {
                "reason": "request_exception",
                "status_code": None,
                "error": "unexpected requests error",
                "error_class": "RequestException",
                "retry_exhausted": True,
            }
            return False

        target.write_bytes(b"ok")
        return True


def test_worker_count_is_config_driven(monkeypatch):
    import py_sec_edgar.downloader as mod

    monkeypatch.setattr(mod, "load_config", lambda: DummyConfig())

    assert _resolve_download_workers(None) == 7
    assert _resolve_download_workers(3) == 3
    assert _resolve_download_workers(0) == 1


def test_run_bounded_downloads_aggregates_success_and_failure(monkeypatch, tmp_path):
    import py_sec_edgar.downloader as mod

    FakeProxyRequest.instances = []
    FakeProxyRequest.limiter_ids = []
    monkeypatch.setattr(mod, "ProxyRequest", FakeProxyRequest)

    tasks = [
        DownloadTask(url="https://example.test/good-1", filepath=str(tmp_path / "a.txt")),
        DownloadTask(url="https://example.test/http-fail-1", filepath=str(tmp_path / "b.txt")),
        DownloadTask(url="https://example.test/good-2", filepath=str(tmp_path / "c.txt")),
    ]

    results = run_bounded_downloads(tasks, max_workers=2, downloader_config=type("Cfg", (), {"max_requests_per_second": 5.0})())

    assert len(results) == 3
    assert len(FakeProxyRequest.instances) == 3
    assert len(set(FakeProxyRequest.limiter_ids)) == 1

    by_name = {Path(r.filepath).name: r for r in results}
    assert by_name["a.txt"].success is True
    assert by_name["c.txt"].success is True
    assert by_name["b.txt"].success is False
    assert by_name["b.txt"].reason == "http_error"
    assert by_name["b.txt"].status_code == 404
    assert by_name["b.txt"].error_class is None
    assert by_name["b.txt"].retry_exhausted is True

    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "c.txt").exists()
    assert not (tmp_path / "b.txt").exists()


def test_run_bounded_downloads_reports_normalized_failure_reasons(monkeypatch, tmp_path):
    import py_sec_edgar.downloader as mod

    FakeProxyRequest.instances = []
    FakeProxyRequest.limiter_ids = []
    monkeypatch.setattr(mod, "ProxyRequest", FakeProxyRequest)

    tasks = [
        DownloadTask(url="https://example.test/timeout", filepath=str(tmp_path / "t.txt")),
        DownloadTask(url="https://example.test/connection", filepath=str(tmp_path / "c.txt")),
        DownloadTask(url="https://example.test/ssl", filepath=str(tmp_path / "s.txt")),
        DownloadTask(url="https://example.test/malformed", filepath=str(tmp_path / "m.txt")),
        DownloadTask(url="https://example.test/localio", filepath=str(tmp_path / "l.txt")),
        DownloadTask(url="https://example.test/request-exception", filepath=str(tmp_path / "r.txt")),
    ]

    results = run_bounded_downloads(tasks, max_workers=3, downloader_config=type("Cfg", (), {"max_requests_per_second": 5.0})())
    reasons = {Path(item.filepath).name: item.reason for item in results}

    assert reasons["t.txt"] == "timeout"
    assert reasons["c.txt"] == "connection_error"
    assert reasons["s.txt"] == "ssl_error"
    assert reasons["m.txt"] == "malformed_url"
    assert reasons["l.txt"] == "local_io_error"
    assert reasons["r.txt"] == "request_exception"
    assert all(item.retry_exhausted is True for item in results)
