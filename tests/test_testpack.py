import json
import zipfile
from pathlib import Path

import pytest

from scripts.evaluate import NO_HIGH_RISK_THEME, THEME_MAP, evaluate_cases
from src.legal_contract_assistant.contract_review import classify_contract_type
from src.legal_contract_assistant.main import generate_review_report
from src.legal_contract_assistant.review_rules import DEFAULT_REVIEW_RULES

TESTPACK = Path("tw_contract_review_testpack_v1.zip")
TESTPACK_ROOT = "tw_contract_review_testpack_v1"
CONTRACT_TYPE_MAP = {
    "買賣": "sale",
    "勞動": "labor",
    "租賃": "lease",
}
EVALUATION_INDICATORS = (
    "contract_type_accuracy",
    "risk_level_accuracy",
    "risk_theme_recall",
    "citation_presence",
    "citation_relevance",
    "manual_review_flag",
    "report_structure",
)


def _load_test_cases() -> list[dict[str, str]]:
    if not TESTPACK.exists():
        pytest.skip("tw_contract_review_testpack_v1.zip is not available")

    with zipfile.ZipFile(TESTPACK) as archive:
        raw = archive.read(f"{TESTPACK_ROOT}/test_cases.jsonl").decode("utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def test_testpack_contract_type_classifier_matches_manifest() -> None:
    cases = _load_test_cases()

    mismatches = [
        (case["case_id"], case["contract_type"], classify_contract_type(case["contract_text"]))
        for case in cases
        if classify_contract_type(case["contract_text"])
        != CONTRACT_TYPE_MAP[case["contract_type"]]
    ]

    assert len(cases) == 90
    assert mismatches == []


def test_evaluation_indicators_are_declared() -> None:
    assert EVALUATION_INDICATORS == (
        "contract_type_accuracy",
        "risk_level_accuracy",
        "risk_theme_recall",
        "citation_presence",
        "citation_relevance",
        "manual_review_flag",
        "report_structure",
    )


def test_theme_map_covers_every_testpack_label() -> None:
    labels = {
        case["expected_risk_themes"]
        for case in _load_test_cases()
        if case["expected_risk_themes"] != NO_HIGH_RISK_THEME
    }
    rule_ids = {rule.rule_id for rule in DEFAULT_REVIEW_RULES}

    assert labels <= set(THEME_MAP["themes"]) | set(THEME_MAP["_not_rule_checked"])
    assert not set(THEME_MAP["themes"]) & set(THEME_MAP["_not_rule_checked"])
    assert {i for ids in THEME_MAP["themes"].values() for i in ids} <= rule_ids


@pytest.fixture(scope="module")
def evaluation() -> dict:
    return evaluate_cases(_load_test_cases())


def test_low_risk_cases_trigger_no_rule(evaluation) -> None:
    stray = [
        (row["case_id"], row["actual_themes"])
        for row in evaluation["cases"]
        if row["expected_risk_level"] == "低風險" and row["actual_themes"] != [NO_HIGH_RISK_THEME]
    ]
    assert stray == []


def test_rule_recall_and_citations_do_not_regress(evaluation) -> None:
    # Floors at the rewrite's first measurement; raise them when rules improve.
    metrics = evaluation["metrics"]
    assert metrics["risk_theme_recall"]["passed"] >= 80
    assert metrics["citation_relevance"]["passed"] >= 50
    assert metrics["citation_presence"]["rate"] == 1


@pytest.mark.parametrize(
    ("case_id", "contract_type"),
    [
        ("sale_01", "sale"),
        ("labor_01", "labor"),
        ("lease_01", "lease"),
    ],
)
def test_testpack_sample_reports_have_required_review_sections(
    case_id: str, contract_type: str
) -> None:
    cases = {case["case_id"]: case for case in _load_test_cases()}

    report = generate_review_report(
        cases[case_id]["contract_text"],
        contract_type=contract_type,
    )

    assert "# 合約審查報告" in report
    assert "## 一、合約基本判斷" in report
    assert "## 二、相關法條" in report
    assert "https://law.moj.gov.tw/" in report
    assert "命中風險主題" in report
    assert "需人工確認" in report
    assert "不構成正式法律意見" in report
