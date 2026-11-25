"""Regression guard: the rules keep handling every generated case they handle today."""

import pytest

from scripts.evaluate_generated import evaluate_generated, to_markdown


@pytest.fixture(scope="module")
def result() -> dict:
    return evaluate_generated()


def test_generated_cases_parse_and_name_real_rules(result) -> None:
    assert result["cases"] == 110
    assert result["bad_lines"] == []
    assert not result["problems"].get("format")


@pytest.mark.parametrize("kind", ["clean", "risk", "near_miss"])
def test_no_regression_on_generated_cases(result, kind) -> None:
    # Confusable contracts are left out on purpose: the user picks the contract
    # type, and the keyword classifier is not expected to read them.
    assert result["problems"].get(kind, []) == []


def test_markdown_report(result) -> None:
    assert "回歸檢查" in to_markdown(result)
