"""PDF Tickets: corrections of OCR text in the ticket header."""
from billing_automation.pdf_tickets.text_fixes import _fix_number, _fix_value, _norm_time, to_ascii


def test_letters_that_look_like_digits():
    assert _fix_number("$o.oo") == "$0.00"
    assert _fix_number("1O/12/26") == "10/12/26"
    assert _fix_number("HELLO") == "HELLO"


def test_time_normalization():
    assert _norm_time("1 1 .-OO A", False) == "11:00 A"
    assert _norm_time("II:OOAM", True) == "11:00AM"
    assert _norm_time("hello", True) is None


def test_dates_lose_inner_spaces():
    assert _fix_value("DOB", "1 1/12/2025") == "11/12/2025"


def test_icd10_code():
    assert _fix_value("LAST PRIMARY DX", "El I.59") == "E11.59"
    assert _fix_value("LAST PRIMARY DX", "110") == "I10"


def test_amount_without_spaces():
    assert _fix_value("CHART BALANCE", "$1 ,030.00") == "$1,030.00"


def test_patient_name_keeps_letters_only():
    assert _fix_value("LAST NAME", "|DOE") == "DOE"


def test_to_ascii():
    assert to_ascii("Łódź") == "Lodz"
