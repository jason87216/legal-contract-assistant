"""Regression checks for the offline labelled-case evaluator."""

from scripts.evaluate import (
    METRIC_DESCRIPTIONS,
    ROOT,
    evaluate_cases,
    load_cases,
    to_markdown,
)


def test_published_testpack_has_90_unique_cases() -> None:
    cases = load_cases(ROOT / "tw_contract_review_testpack_v1.zip")
    assert len(cases) == 90
    assert len({case["case_id"] for case in cases}) == 90


def test_evaluation_outputs_explicit_denominators_and_no_private_text() -> None:
    cases = load_cases(ROOT / "tw_contract_review_testpack_v1.zip")
    results = evaluate_cases(cases[:3])

    assert results["evaluation_mode"] == "offline_rules_and_dry_run_only"
    assert results["case_count"] == 3
    assert set(results["metrics"]) == set(METRIC_DESCRIPTIONS)
    for metric in results["metrics"].values():
        assert 0 <= metric["passed"] <= metric["total"] <= 3
    markdown = to_markdown(results)
    assert "不呼叫 LLM" in markdown
    assert "citation_relevance" in markdown
    assert "3000 years" not in markdown
    assert cases[0]["contract_text"] not in markdown
