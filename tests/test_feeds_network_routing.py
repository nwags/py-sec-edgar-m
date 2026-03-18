from __future__ import annotations

from datetime import datetime

import pytest

pandas = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import py_sec_edgar.feeds as feeds
from py_sec_edgar.settings import get_config


class FakeResponse:
    def __init__(self, text: str):
        self.text = text


class FakeProxyRequest:
    def __init__(self):
        self.calls = []

    def GET_RESPONSE(self, url, stream=False):
        self.calls.append(("GET_RESPONSE", url, stream))
        return FakeResponse(
            '<html><body><a href="xbrlrss-2025-01.xml">a</a><a href="xbrlrss-2024-12.xml">b</a></body></html>'
        )

    def GET_FILE(self, url, filepath):
        self.calls.append(("GET_FILE", url, filepath))
        return True


def test_download_edgar_filings_xbrl_rss_files_routes_to_get_file(monkeypatch, tmp_path):
    fake = FakeProxyRequest()
    monkeypatch.setattr(feeds, "ProxyRequest", lambda: fake)
    monkeypatch.setattr(feeds, "CONFIG", get_config())
    monkeypatch.setattr(feeds.pd, "date_range", lambda start, end, freq=None: [datetime(2025, 1, 1)])
    monkeypatch.setattr(feeds.os.path, "exists", lambda path: False)
    monkeypatch.setattr(feeds.CONFIG, "MONTHLY_DIR", str(tmp_path))

    feeds.download_edgar_filings_xbrl_rss_files()

    assert any(call[0] == "GET_FILE" for call in fake.calls)


def test_download_and_flatten_monthly_routes_to_safe_downloader(monkeypatch, tmp_path):
    fake = FakeProxyRequest()
    monkeypatch.setattr(feeds, "ProxyRequest", lambda: fake)
    monkeypatch.setattr(feeds, "CONFIG", get_config())
    monkeypatch.setattr(feeds.CONFIG, "MONTHLY_DIR", str(tmp_path / "monthly"))
    monkeypatch.setattr(feeds.CONFIG, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(feeds.CONFIG, "edgar_monthly_index", "https://www.sec.gov/Archives/edgar/monthly/")
    monkeypatch.setattr(feeds.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(feeds.pd.DataFrame, "to_excel", lambda self, *args, **kwargs: None, raising=False)

    feeds.download_and_flatten_monthly_xbrl_filings_list()

    assert any(call[0] == "GET_RESPONSE" for call in fake.calls)
    assert any(call[0] == "GET_FILE" for call in fake.calls)


def test_feeds_has_no_direct_requests_get_calls():
    source = feeds.__loader__.get_source(feeds.__name__)
    assert "requests.get(" not in source
