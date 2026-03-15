from __future__ import annotations

import re
from datetime import date, datetime

QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


class QuarterError(ValueError):
    pass


def parse_quarter(value: str) -> tuple[int, int]:
    match = QUARTER_RE.match(value)
    if not match:
        raise QuarterError(f"Invalid quarter format: {value}")
    return int(match.group(1)), int(match.group(2))


def sort_quarters(values: list[str]) -> list[str]:
    unique = sorted(set(values), key=parse_quarter)
    return unique


def next_quarter(value: str) -> str:
    year, quarter = parse_quarter(value)
    if quarter == 4:
        return f"{year + 1}-Q1"
    return f"{year}-Q{quarter + 1}"


def quarter_minus_one(value: str) -> str:
    year, quarter = parse_quarter(value)
    if quarter == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{quarter - 1}"


def quarter_to_dates(value: str) -> tuple[date, date]:
    year, quarter = parse_quarter(value)

    if quarter == 1:
        return date(year, 1, 1), date(year, 3, 31)
    if quarter == 2:
        return date(year, 4, 1), date(year, 6, 30)
    if quarter == 3:
        return date(year, 7, 1), date(year, 9, 30)
    return date(year, 10, 1), date(year, 12, 31)


def date_to_quarter(value: date) -> str:
    if value.month <= 3:
        q = 1
    elif value.month <= 6:
        q = 2
    elif value.month <= 9:
        q = 3
    else:
        q = 4
    return f"{value.year}-Q{q}"


def parse_datetime_to_quarter(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return date_to_quarter(parsed.date())
