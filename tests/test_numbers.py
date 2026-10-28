"""Financial display-number edge cases: deterministic and offline."""
import pytest

from dv.numbers import normalize_baseline, parse, parse_detail


@pytest.mark.parametrize(("text", "expected"), [
    ("1,234", 1234), ("$1,234.50", 1234.5), (" $ 1,234.50 ", 1234.5),
    ("(1,234)", -1234), ("( $ 1,234.5 )", -1234.5), ("-1,234", -1234),
    ("\u22121,234", -1234), ("0", 0), ("(0)", 0), ("+42", 42),
    (".75", 0.75), ("-.75", -0.75), ("123.", 123),
    ("123(1)", 123), ("$1,234(12)", 1234), ("(1,234)(1)", -1234),
    ("1,234.50(2)", 1234.5), ("(1)", -1),
    ("1.2 million", 1.2), ("(1.2 billion)", -1.2),
    ("-", None), ("\u2014", None), ("\u2013", None), ("  —  ", None),
    (None, None), ("", None), ("N/A", None), ("5%", None),
    ("5 percent", None), ("abc123(1)", None), ("123abc", None),
    ("(-123)", None), ("NaN", None), ("inf", None),
    ("1e3", None), ("12..3", None), ("(123", None), ("123)", None),
])
def test_parse(text: str | None, expected: float | None) -> None:
    assert parse(text) == expected


@pytest.mark.parametrize(("text", "scale", "expected"), [
    ("1.2 thousand", "thousands", 1200), ("1.2 million", "millions", 1_200_000),
    ("1.2 billion", "billions", 1_200_000_000), ("1.2k", "thousands", 1200),
    ("1.2m", "millions", 1_200_000), ("1.2bn", "billions", 1_200_000_000),
    ("1.2 BILLION", "billions", 1_200_000_000), ("(1.2bn)", "billions", -1_200_000_000),
])
def test_word_scales(text: str, scale: str, expected: float) -> None:
    parsed = parse_detail(text)
    assert parsed is not None
    assert parsed.word_scale == scale
    assert normalize_baseline(text, None, "revenue") == expected


def test_table_scale_is_applied_once() -> None:
    assert normalize_baseline("123", "in millions", "revenue") == 123_000_000
    assert normalize_baseline("1.2 billion", "billions", "revenue") == 1_200_000_000


def test_baseline_eps_is_never_scaled() -> None:
    assert normalize_baseline("7.46", "millions", "eps_diluted") == 7.46
