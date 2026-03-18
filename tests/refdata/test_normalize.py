from py_sec_edgar.refdata.normalize import normalize_cik, normalize_ticker


def test_normalize_ticker_uppercase_and_trim() -> None:
    assert normalize_ticker(" aapl ") == "AAPL"
    assert normalize_ticker("brk-b") == "BRK-B"
    assert normalize_ticker("") is None
    assert normalize_ticker(None) is None


def test_normalize_cik_zero_pad_and_digits_only() -> None:
    assert normalize_cik("320193") == "0000320193"
    assert normalize_cik("0000320193") == "0000320193"
    assert normalize_cik(":0001438823:") == "0001438823"
    assert normalize_cik("abc") is None
    assert normalize_cik(None) is None
