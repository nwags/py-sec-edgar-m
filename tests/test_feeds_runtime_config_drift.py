from __future__ import annotations

from datetime import datetime

import pytest

pandas = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import py_sec_edgar.feeds as feeds
from py_sec_edgar.settings import get_config


class FakeProxyRequest:
    def __init__(self):
        self.calls = []

    def GET_FILE(self, url, filepath):
        self.calls.append((url, filepath))
        return True


def test_generate_daily_index_paths_use_current_config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(feeds, "CONFIG", get_config())
    monkeypatch.setattr(feeds.CONFIG, "DAILY_INDEX_DIR", str(tmp_path / "daily"))

    files = feeds.generate_daily_index_urls_and_filepaths(pandas.Timestamp("2025-01-15"))

    assert len(files) == 5
    assert all(str(tmp_path / "daily") in local for _, local in files)


def test_update_daily_files_no_uninitialized_state(monkeypatch, tmp_path):
    fake = FakeProxyRequest()
    monkeypatch.setattr(feeds, "ProxyRequest", lambda: fake)

    class FakeDates(list):
        @property
        def weekday(self):
            import pandas as pd

            return pd.Series([0 for _ in self])

        def sort_values(self, ascending=False):
            return self

        def __getitem__(self, item):
            if isinstance(item, slice):
                return FakeDates(super().__getitem__(item))
            if hasattr(item, "tolist"):
                vals = item.tolist()
                return FakeDates([d for d, keep in zip(self, vals) if keep])
            return super().__getitem__(item)

    monkeypatch.setattr(feeds.pd, "date_range", lambda start, end: FakeDates([datetime(2025, 1, 15)]))
    monkeypatch.setattr(feeds, "generate_daily_index_urls_and_filepaths", lambda day: [("https://x", str(tmp_path / "a.idx"))])
    monkeypatch.setattr(feeds.os.path, "exists", lambda path: False)

    feeds.update_daily_files()

    assert len(fake.calls) == 1


def test_parse_monthly_graceful_when_legacy_paths_missing(monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(feeds, "CONFIG", cfg)
    monkeypatch.setattr(cfg, "tickercheck", None, raising=False)
    monkeypatch.setattr(cfg, "cik_ticker", None, raising=False)

    # Should return cleanly without raising when legacy config drift exists.
    assert feeds.parse_monthly() is None
