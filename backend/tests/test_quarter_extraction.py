from __future__ import annotations

from app.utils.quarter_extraction import extract_quarters_from_text


def test_extract_single_quarter_token() -> None:
    text = "VigiLens Quarter Digest - 2018-Q1"
    assert extract_quarters_from_text(text) == {"2018-Q1"}


def test_extract_expands_quarter_range() -> None:
    text = "Coverage from 2022-Q1 through 2023-Q2"
    assert extract_quarters_from_text(text) == {
        "2022-Q1",
        "2022-Q2",
        "2022-Q3",
        "2022-Q4",
        "2023-Q1",
        "2023-Q2",
    }


def test_extract_mixed_punctuation_range() -> None:
    text = "Safety digest covering 2020-Q3 to 2021-Q1 and references 2019-Q4."
    assert extract_quarters_from_text(text) == {
        "2019-Q4",
        "2020-Q3",
        "2020-Q4",
        "2021-Q1",
    }


def test_extract_supports_q_then_year_token() -> None:
    text = "VigiLens Q4 2022 Safety Report on Semaglutide."
    assert extract_quarters_from_text(text) == {"2022-Q4"}


def test_extract_supports_q_pair_same_year() -> None:
    text = "Signal updates for Q2 and Q3 2022 show rising GI trends."
    assert extract_quarters_from_text(text) == {"2022-Q2", "2022-Q3"}


def test_extract_supports_q_range_same_year() -> None:
    text = "Review covered Q2 through Q4 2021 in detail."
    assert extract_quarters_from_text(text) == {"2021-Q2", "2021-Q3", "2021-Q4"}


def test_extract_supports_message_id_quarter_pattern() -> None:
    text = "message_id=vigl_semaglutide_2021Q4_digest"
    assert extract_quarters_from_text(text) == {"2021-Q4"}
