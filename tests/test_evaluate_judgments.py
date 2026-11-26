"""The judgment set is well formed and the scoring runs.

No score floor on purpose: the set is held out, and a floor would invite tuning
the rules on it.
"""

from collections import Counter

from scripts.evaluate_judgments import evaluate_judgments, load_clauses, to_markdown
from src.legal_contract_assistant.review_rules import load_seed_review_rules


def test_judgment_set_shape() -> None:
    clauses = load_clauses()
    assert len(clauses) == 30
    assert len({c["id"] for c in clauses}) == 30
    assert Counter(c["contract_type"] for c in clauses) == {t: 5 for t in ("lease", "labor", "sale", "work", "mandate", "loan")}
    rule_ids = {rule.rule_id for rule in load_seed_review_rules()}
    for clause in clauses:
        assert clause["label"] in ("risk", "normal")
        assert clause["rule_scope"] in ("rule", "llm", "skip")
        assert set(clause["expected_rules"]) <= rule_ids, clause["id"]
        assert clause["label"] == "risk" or not clause["expected_rules"], clause["id"]
        assert clause["case"] and clause["clause"], clause["id"]


def test_scoring_report() -> None:
    result = evaluate_judgments()
    summary = result["summary"]
    assert summary["risk_scored"] + summary["normal_scored"] + summary["not_scored"] == 30
    assert "判決條款評測" in to_markdown(result)
