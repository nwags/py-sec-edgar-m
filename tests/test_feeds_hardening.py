from __future__ import annotations

from pathlib import Path

import pytest

pandas = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import py_sec_edgar.feeds as feeds
from py_sec_edgar.settings import get_config


def _set_cfg(monkeypatch, tmp_path: Path):
    cfg = get_config()
    monkeypatch.setattr(feeds, "CONFIG", cfg)
    monkeypatch.setattr(cfg, "REF_DIR", str(tmp_path / "refdata"))
    monkeypatch.setattr(cfg, "MERGED_IDX_FILEPATH", str(tmp_path / "refdata" / "merged_idx_files.pq"))
    monkeypatch.setattr(cfg, "TICKER_LIST_FILEPATH", str(tmp_path / "refdata" / "tickers.csv"))
    monkeypatch.setattr(cfg, "edgar_Archives_url", "https://www.sec.gov/Archives/")
    return cfg


def _write_normalized_filter_inputs(ref_root: Path) -> None:
    normalized_root = ref_root / "normalized"
    normalized_root.mkdir(parents=True, exist_ok=True)
    pandas.DataFrame(
        [{"issuer_cik": "0000320193", "ticker": "AAPL", "issuer_name": "Apple"}]
    ).to_parquet(normalized_root / "issuers.parquet", index=False)
    pandas.DataFrame(
        [{"entity_cik": "0000320193", "entity_name": "Apple Inc.", "is_issuer": True}]
    ).to_parquet(normalized_root / "entities.parquet", index=False)


def test_load_filings_feed_raises_for_missing_merged_idx(monkeypatch, tmp_path):
    cfg = _set_cfg(monkeypatch, tmp_path)
    _write_normalized_filter_inputs(Path(cfg.REF_DIR))
    Path(cfg.TICKER_LIST_FILEPATH).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.TICKER_LIST_FILEPATH).write_text("AAPL\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        feeds.load_filings_feed(ticker_list_filter=False, form_list_filter=False)


def test_load_filings_feed_raises_for_missing_required_columns(monkeypatch, tmp_path):
    cfg = _set_cfg(monkeypatch, tmp_path)
    ref_root = Path(cfg.REF_DIR)
    _write_normalized_filter_inputs(ref_root)
    ref_root.mkdir(parents=True, exist_ok=True)
    Path(cfg.TICKER_LIST_FILEPATH).write_text("AAPL\n", encoding="utf-8")

    pandas.DataFrame([{"CIK": "320193", "Date Filed": "2025-01-01"}]).to_parquet(
        cfg.MERGED_IDX_FILEPATH, index=False
    )

    with pytest.raises(ValueError, match="missing required columns"):
        feeds.load_filings_feed(ticker_list_filter=False, form_list_filter=False)


def test_merge_idx_files_raises_when_no_csv_files(monkeypatch, tmp_path):
    cfg = get_config()
    monkeypatch.setattr(feeds, "CONFIG", cfg)
    monkeypatch.setattr(cfg, "FULL_INDEX_DIR", str(tmp_path / "full-index"))

    with pytest.raises(FileNotFoundError, match="No .csv index files found"):
        feeds.merge_idx_files()


def test_convert_idx_to_csv_filters_separator_rows(tmp_path):
    idx_path = tmp_path / "master.idx"
    header = "\n".join(["header"] * 10) + "\n"
    body = (
        "320193|Apple Inc|8-K|2025-01-10|edgar/data/320193/a.txt\n"
        "----|----|----|----|----\n"
    )
    idx_path.write_text(header + body, encoding="utf-8")

    feeds.convert_idx_to_csv(str(idx_path))
    out = pandas.read_csv(str(idx_path).replace(".idx", ".csv"))
    assert len(out.index) == 1
    assert out.iloc[0]["CIK"] == 320193


def test_update_full_index_feed_converts_existing_idx_and_merges(monkeypatch, tmp_path):
    cfg = get_config()
    monkeypatch.setattr(feeds, "CONFIG", cfg)
    monkeypatch.setattr(cfg, "FULL_INDEX_DIR", str(tmp_path / "full-index"))
    monkeypatch.setattr(cfg, "REF_DIR", str(tmp_path / "refdata"))
    monkeypatch.setattr(cfg, "index_start_date", "01/01/2025", raising=False)
    monkeypatch.setattr(cfg, "index_end_date", "03/31/2025", raising=False)
    monkeypatch.setattr(cfg, "index_files", ["master.idx"], raising=False)
    monkeypatch.setattr(cfg, "edgar_full_master_url", "https://example.test/master.idx", raising=False)
    monkeypatch.setattr(cfg, "edgar_Archives_url", "https://example.test/", raising=False)
    monkeypatch.setattr(cfg, "download_workers", 1, raising=False)

    qtr_idx = Path(cfg.FULL_INDEX_DIR) / "2025" / "QTR1" / "master.idx"
    qtr_idx.parent.mkdir(parents=True, exist_ok=True)
    qtr_idx.write_text("already-there", encoding="utf-8")

    latest_idx = Path(cfg.FULL_INDEX_DIR) / "master.idx"

    class FakeProxyRequest:
        def GET_FILE(self, url, filepath):
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(filepath).write_text("downloaded", encoding="utf-8")
            return True

    monkeypatch.setattr(feeds, "ProxyRequest", lambda: FakeProxyRequest())
    monkeypatch.setattr(feeds, "run_bounded_downloads", lambda *args, **kwargs: [])

    converted = []
    monkeypatch.setattr(feeds, "convert_idx_to_csv", lambda filepath: converted.append(str(filepath)))

    merged = {"called": False}
    monkeypatch.setattr(feeds, "merge_idx_files", lambda: merged.__setitem__("called", True))

    feeds.update_full_index_feed(save_idx_as_csv=True, skip_if_exists=True)

    assert str(latest_idx) in converted
    assert str(qtr_idx) in converted
    assert merged["called"] is True
