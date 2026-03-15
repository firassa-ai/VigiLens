from __future__ import annotations

from datetime import date

import pytest

from app.utils.quarters import QuarterError, next_quarter, quarter_minus_one, quarter_to_dates, sort_quarters


def test_sort_quarters_deduplicates_and_orders() -> None:
    assert sort_quarters(["2018-Q4", "2018-Q2", "2018-Q1", "2018-Q2"]) == [
        "2018-Q1",
        "2018-Q2",
        "2018-Q4",
    ]


def test_next_quarter_rollover() -> None:
    assert next_quarter("2018-Q4") == "2019-Q1"


def test_quarter_minus_one_rollover() -> None:
    assert quarter_minus_one("2019-Q1") == "2018-Q4"


def test_quarter_to_dates() -> None:
    assert quarter_to_dates("2018-Q3") == (date(2018, 7, 1), date(2018, 9, 30))


def test_invalid_quarter_raises() -> None:
    with pytest.raises(QuarterError):
        next_quarter("2018-05")
