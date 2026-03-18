from py_sec_edgar.utilities import generate_folder_names_years_quarters


def test_generate_folder_names_years_quarters_uses_current_quarter_frequency():
    out = generate_folder_names_years_quarters("01/01/2025", "12/31/2025")
    assert ("2025", "QTR1") in out
    assert ("2025", "QTR2") in out
    assert ("2025", "QTR3") in out
    assert ("2025", "QTR4") in out
