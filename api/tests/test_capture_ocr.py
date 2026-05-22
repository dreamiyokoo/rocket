"""OCR candidate selection regression tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capture.ocr import choose_pill_value, parse_ocr_number


def test_choose_pill_value_prefers_gray_when_close_for_yellow_digits():
    value, raw_text = choose_pill_value(
        "yellow",
        [
            {"variant": "base", "raw_text": "9.99", "value": 9.99, "has_decimal": True, "confidence": 88.0},
            {"variant": "gray", "raw_text": "5.95", "value": 5.95, "has_decimal": True, "confidence": 80.0},
        ],
    )

    assert value == 5.95
    assert raw_text == "5.95"


def test_parse_ocr_number_rejects_plain_three_digit_false_positive():
    assert parse_ocr_number("247") is None


def test_parse_ocr_number_accepts_truncated_501():
    assert parse_ocr_number("501") == 501.0