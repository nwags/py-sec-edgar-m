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
        if "fail" in url:
            self.last_failure = {
                "reason": "not_found",
                "status_code": 404,
                "error": None,
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
        DownloadTask(url="https://example.test/fail-1", filepath=str(tmp_path / "b.txt")),
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
    assert by_name["b.txt"].reason == "not_found"
    assert by_name["b.txt"].status_code == 404

    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "c.txt").exists()
    assert not (tmp_path / "b.txt").exists()
