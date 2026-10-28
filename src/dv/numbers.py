"""Strict financial display-number parsing; no inference or answer-key access."""
import math
import re

from dv.models import DataModel

MULTIPLIERS = {"units": 1.0, "thousands": 1_000.0, "millions": 1_000_000.0, "billions": 1_000_000_000.0}
WORD_SCALES = {"thousand": "thousands", "thousands": "thousands", "k": "thousands",
               "million": "millions", "millions": "millions", "m": "millions",
               "billion": "billions", "billions": "billions", "bn": "billions"}


class ParsedNumber(DataModel):
    value: float
    word_scale: str | None


def parse_detail(text: str | None) -> ParsedNumber | None:
    if text is None:
        return None
    value = text.strip().replace("\u2212", "-")
    if not value or value in {"-", "\u2014", "\u2013"} or "%" in value:
        return None
    # A suffix footnote is separate from a parenthesized negative number.
    footnote = re.fullmatch(r"(.+\d(?:\.\d+)?\)?)(\(\d+\))", value)
    if footnote and parse_detail(footnote.group(1)) is not None:
        value = footnote.group(1)
    word_scale = None
    scale_match = re.search(r"(?<=\d)\s*(thousands?|millions?|billions?|bn|k|m)\b", value, re.I)
    if scale_match:
        word_scale = WORD_SCALES[scale_match.group(1).lower()]
        value = value[:scale_match.start()] + value[scale_match.end():]
    value = re.sub(r"[$,\s]", "", value)
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
        if value.startswith(("+", "-")):
            return None
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value) is None:
        return None
    number = float(value)
    if negative:
        number = -number
    if not math.isfinite(number):
        return None
    return ParsedNumber(value=number, word_scale=word_scale)


def parse(text: str | None) -> float | None:
    parsed = parse_detail(text)
    return parsed.value if parsed else None


def scale_name(text: str | None) -> str | None:
    if not text:
        return None
    normalized = text.strip().lower()
    if normalized in {"units", "unit", "dollars", "usd", "usd/share", "usd/shares", "per share"}:
        return "units"
    words = re.findall(r"[a-z]+", normalized)
    scales = {WORD_SCALES[word] for word in words if word in WORD_SCALES}
    return scales.pop() if len(scales) == 1 else None


def normalize_baseline(value: str | None, scale: str | None, metric: str) -> float | None:
    parsed = parse_detail(value)
    if parsed is None:
        return None
    if metric == "eps_diluted":
        return parsed.value
    selected_scale = parsed.word_scale or scale_name(scale) or "units"
    return parsed.value * MULTIPLIERS[selected_scale]
