from __future__ import annotations

from datetime import datetime
from pathlib import Path

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


def test_load_filings_feed_uses_ref_dir_derived_normalized_root_when_normalized_attr_is_stale(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", "/tmp/py-sec-edgar-smoke")

    cfg = get_config()
    monkeypatch.setattr(feeds, "CONFIG", cfg)

    ref_root = tmp_path / "refdata"
    normalized_root = ref_root / "normalized"
    normalized_root.mkdir(parents=True, exist_ok=True)

    # Intentionally stale path that should be ignored by feed runtime context.
    monkeypatch.setattr(cfg, "NORMALIZED_REFDATA_DIR", "/tmp/py-sec-edgar-smoke/refdata/normalized", raising=False)

    monkeypatch.setattr(cfg, "REF_DIR", str(ref_root), raising=False)
    monkeypatch.setattr(cfg, "MERGED_IDX_FILEPATH", str(ref_root / "merged_idx_files.pq"), raising=False)
    monkeypatch.setattr(cfg, "TICKER_LIST_FILEPATH", str(ref_root / "tickers.csv"), raising=False)
    monkeypatch.setattr(cfg, "edgar_Archives_url", "https://www.sec.gov/Archives/", raising=False)
    monkeypatch.setattr(cfg, "forms_list", ["8-K"], raising=False)

    pandas.DataFrame([{"issuer_cik": "0000320193", "ticker": "AAPL", "issuer_name": "Apple"}]).to_parquet(
        normalized_root / "issuers.parquet",
        index=False,
    )
    pandas.DataFrame([{"entity_cik": "0000320193", "entity_name": "Apple Inc.", "is_issuer": True}]).to_parquet(
        normalized_root / "entities.parquet",
        index=False,
    )
    pandas.DataFrame(
        [
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": "2025-01-10",
                "Filename": "edgar/data/320193/a.txt",
            }
        ]
    ).to_parquet(Path(cfg.MERGED_IDX_FILEPATH), index=False)
    Path(cfg.TICKER_LIST_FILEPATH).write_text("AAPL\n", encoding="utf-8")

    df = feeds.load_filings_feed(ticker_list_filter=False, form_list_filter=False)
    assert len(df.index) == 1
    assert df.iloc[0]["CIK"] == "320193"
