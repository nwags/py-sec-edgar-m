from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd

from py_sec_edgar.filing import parse_filing_header


def test_parse_filing_header_is_compatible_with_current_pandas() -> None:
    raw_html = Path("tests/fixtures/filings/sc13d_sample.txt").read_text(encoding="utf-8")
    header = parse_filing_header(raw_html)

    assert isinstance(header, pd.DataFrame)
    assert set(["GROUP", "KEY", "VALUE"]).issubset(set(header.columns))


def test_filing_module_does_not_reference_removed_pandas_np_namespace() -> None:
    import py_sec_edgar.filing as filing_module

    source = inspect.getsource(filing_module)
    assert "pd.np" not in source
    assert "pandas.np" not in source
