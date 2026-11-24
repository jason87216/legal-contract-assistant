"""Regression checks for the offline retrieval evaluator."""

from scripts.evaluate import ROOT, load_cases
from scripts.evaluate_retrieval import (
    VARIANT_DESCRIPTIONS,
    evaluate_retrieval,
    first_hit_rank,
    rule_hit_clauses,
    to_markdown,
)
from src.legal_contract_assistant.review_rules import DEFAULT_REVIEW_RULES


def test_first_hit_rank_is_one_based_and_none_when_missing() -> None:
    assert first_hit_rank(["a", "b", "c"], {"b"}) == 2
    assert first_hit_rank(["a", "b"], {"z"}) is None


def test_rule_hit_clauses_use_rule_regex_patterns() -> None:
    rule = next(rule for rule in DEFAULT_REVIEW_RULES if rule.pattern == "備貨完成後盡速")
    text = f"第一條【標的】\n商用咖啡機一組。\n\n第二條【交付】\n甲方於{rule.pattern}交付。"
    clauses = rule_hit_clauses(text, [rule])
    assert clauses == [f"第二條【交付】\n甲方於{rule.pattern}交付。"]


def test_evaluation_reports_every_variant_with_denominators() -> None:
    cases = load_cases(ROOT / "tw_contract_review_testpack_v1.zip")
    results = evaluate_retrieval(cases)

    assert results["evaluation_mode"] == "offline_retrieval_only"
    assert results["case_count"] + results["skipped_cases"] == 90
    assert set(results["metrics"]) == set(VARIANT_DESCRIPTIONS)
    for metric in results["metrics"].values():
        assert metric["recall_at_5"]["passed"] <= metric["recall_at_12"]["passed"] <= results["case_count"]
        assert 0 <= metric["mrr"] <= 1
    assert "不代表準確率" in to_markdown(results)
