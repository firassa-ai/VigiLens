from __future__ import annotations

import re

from app.utils.quarters import next_quarter, parse_quarter

QUARTER_TOKEN_RE = re.compile(r"(\d{4})\s*[-/]?\s*Q([1-4])", re.IGNORECASE)
QUARTER_TOKEN_ALT_RE = re.compile(r"\bQ([1-4])\s*[-/]?\s*(\d{4})\b", re.IGNORECASE)
MESSAGE_ID_TOKEN_RE = re.compile(r"\b(?:\w+_)*(\d{4})Q([1-4])(?:_\w+)*\b", re.IGNORECASE)
QUARTER_RANGE_RE = re.compile(
    r"(\d{4})\s*[-/]?\s*Q([1-4])\s*(?:through|to|–|—|-)\s*(\d{4})\s*[-/]?\s*Q([1-4])",
    re.IGNORECASE,
)
QUARTER_RANGE_ALT_RE = re.compile(
    r"\bQ([1-4])\s*(?:through|to|–|—|-)\s*Q([1-4])\s*(\d{4})\b",
    re.IGNORECASE,
)
QUARTER_PAIR_ALT_RE = re.compile(
    r"\bQ([1-4])\s*(?:and|,)\s*Q([1-4])\s*(\d{4})\b",
    re.IGNORECASE,
)


def expand_quarter_range(start_quarter: str, end_quarter: str) -> list[str]:
    start = parse_quarter(start_quarter)
    end = parse_quarter(end_quarter)
    if start > end:
        return []

    out: list[str] = []
    cursor = start_quarter
    while parse_quarter(cursor) <= end:
        out.append(cursor)
        cursor = next_quarter(cursor)
    return out


def extract_quarters_from_text(text: str) -> set[str]:
    quarters: set[str] = set()

    for match in QUARTER_RANGE_RE.finditer(text):
        start_quarter = f"{match.group(1)}-Q{match.group(2)}"
        end_quarter = f"{match.group(3)}-Q{match.group(4)}"
        for quarter in expand_quarter_range(start_quarter, end_quarter):
            quarters.add(quarter)

    for match in QUARTER_RANGE_ALT_RE.finditer(text):
        year = match.group(3)
        q1 = int(match.group(1))
        q2 = int(match.group(2))
        start_q = min(q1, q2)
        end_q = max(q1, q2)
        for qn in range(start_q, end_q + 1):
            quarters.add(f"{year}-Q{qn}")

    for match in QUARTER_PAIR_ALT_RE.finditer(text):
        year = match.group(3)
        q1 = int(match.group(1))
        q2 = int(match.group(2))
        quarters.add(f"{year}-Q{q1}")
        quarters.add(f"{year}-Q{q2}")

    for match in QUARTER_TOKEN_RE.finditer(text):
        quarters.add(f"{match.group(1)}-Q{match.group(2)}")

    for match in QUARTER_TOKEN_ALT_RE.finditer(text):
        quarters.add(f"{match.group(2)}-Q{match.group(1)}")

    for match in MESSAGE_ID_TOKEN_RE.finditer(text):
        quarters.add(f"{match.group(1)}-Q{match.group(2)}")

    return quarters
