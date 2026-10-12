"""AUTO-WORK: correction of OCR'd dates and names."""
from billing_automation.auto_work.screen_ocr import (clean_ocr_name, correct_ocr_field, fix_month_in_date,
                                                    parse_date_positional)


def test_value_in_range_is_kept():
    assert correct_ocr_field("05", 1, 31) == ("05", False)


def test_four_read_instead_of_one_is_fixed():
    assert correct_ocr_field("14", 1, 12) == ("11", True)
    assert correct_ocr_field("34", 1, 31) == ("31", True)


def test_year_in_wrong_century_is_fixed():
    assert correct_ocr_field("2104", 1901, 2029) == ("2004", True)


def test_positional_parsing_ignores_misread_separators():
    assert parse_date_positional("01/15/1984") == ("01", "15", "1984")
    assert parse_date_positional("0111511984") == ("01", "15", "1984")   # '/' read as '1'
    assert parse_date_positional("01151984") == ("01", "15", "1984")     # separators lost
    assert parse_date_positional("abc") is None


def test_fix_month_in_date():
    assert fix_month_in_date("14/34/2001") == "11/31/2001"
    assert fix_month_in_date("03/07/1990") == "03/07/1990"


def test_clean_ocr_name_removes_junk_everywhere():
    assert clean_ocr_name("SM|ITH_ [JOHN]") == "SMITH JOHN"
