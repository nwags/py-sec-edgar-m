from __future__ import annotations

from pathlib import Path

import pytest
import requests

from py_sec_edgar.download import ProxyRequest


class DummyResponse:
    def __init__(self, status_code=200, body=b"ok", headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {"Content-Type": "text/plain"}

    def iter_content(self, chunk_size=1024):
        if self._body:
            yield self._body


class DummySession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, stream=True, headers=None, proxies=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "stream": stream,
                "headers": headers,
                "proxies": proxies,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class DummyCompatConfig:
    user_agent = "UnitTestAgent/1.0"
    request_timeout_connect = 1
    request_timeout_read = 2


class DummyLimiter:
    def __init__(self):
        self.wait_calls = 0

    def wait(self):
        self.wait_calls += 1
        return 0.0


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("py_sec_edgar.download.time.sleep", lambda *_: None)


def test_retry_on_transient_status_then_success(tmp_path: Path):
    session = DummySession(
        [
            DummyResponse(status_code=429),
            DummyResponse(status_code=200, body=b"payload", headers={"Content-Type": "text/plain"}),
        ]
    )
    downloader = ProxyRequest(session=session)
    downloader.retry_counter = 3

    target = tmp_path / "file.txt"
    ok = downloader.GET_FILE("https://example.test/file", str(target))

    assert ok is True
    assert target.read_bytes() == b"payload"
    assert len(session.calls) == 2


def test_no_file_persisted_on_failed_status(tmp_path: Path):
    session = DummySession([DummyResponse(status_code=404)])
    downloader = ProxyRequest(session=session)

    target = tmp_path / "file.txt"
    ok = downloader.GET_FILE("https://example.test/file", str(target))

    assert ok is False
    assert not target.exists()
    assert not target.with_suffix(".txt.tmp").exists()
    assert downloader.last_failure["reason"] == "http_error"
    assert downloader.last_failure["status_code"] == 404


def test_no_file_persisted_on_html_error_page(tmp_path: Path):
    session = DummySession(
        [DummyResponse(status_code=200, body=b"<html>error</html>", headers={"Content-Type": "text/html"})]
    )
    downloader = ProxyRequest(session=session)

    target = tmp_path / "file.txt"
    ok = downloader.GET_FILE("https://example.test/file", str(target))

    assert ok is False
    assert not target.exists()
    assert downloader.last_failure["reason"] == "http_error"


def test_retry_on_request_exception_bounded(tmp_path: Path):
    session = DummySession(
        [
            requests.Timeout("timeout"),
            requests.ConnectionError("conn"),
            DummyResponse(status_code=200, body=b"done", headers={"Content-Type": "text/plain"}),
        ]
    )
    downloader = ProxyRequest(session=session)
    downloader.retry_counter = 3

    target = tmp_path / "file.idx"
    ok = downloader.GET_FILE("https://example.test/file", str(target))

    assert ok is True
    assert target.exists()
    assert len(session.calls) == 3


def test_proxy_compatibility_mode_opt_in(monkeypatch, tmp_path: Path):
    csv_path = tmp_path / "proxy.csv"
    csv_path.write_text("IP\n10.0.0.1\n", encoding="utf-8")

    monkeypatch.setenv("PP_USERNAME", "u")
    monkeypatch.setenv("PP_PASSWORD", "p")
    monkeypatch.setenv("PP_SERVER_LIST", str(csv_path))

    session = DummySession([DummyResponse(status_code=200, body=b"ok")])
    downloader = ProxyRequest(CONFIG=DummyCompatConfig(), session=session)

    target = tmp_path / "file.txt"
    ok = downloader.GET_FILE("https://example.test/file", str(target))

    assert ok is True
    assert downloader.use_proxy is True
    assert session.calls[0]["proxies"] is not None


def test_get_file_invokes_rate_limiter(tmp_path: Path):
    limiter = DummyLimiter()
    session = DummySession([DummyResponse(status_code=200, body=b"ok")])
    downloader = ProxyRequest(session=session, rate_limiter=limiter)

    target = tmp_path / "file.txt"
    assert downloader.GET_FILE("https://example.test/file", str(target)) is True
    assert limiter.wait_calls == 1


def test_get_response_invokes_rate_limiter():
    limiter = DummyLimiter()
    session = DummySession([DummyResponse(status_code=200, body=b"ok")])
    downloader = ProxyRequest(session=session, rate_limiter=limiter)

    response = downloader.GET_RESPONSE("https://example.test/index")
    assert response is not None
    assert limiter.wait_calls == 1
