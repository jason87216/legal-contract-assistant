import json
import zipfile
from pathlib import Path

import pytest

from src.legal_contract_assistant.contract_review import classify_contract_type
from src.legal_contract_assistant.contract_review import detect_risk_themes
from src.legal_contract_assistant.contract_review import estimate_risk_level
from src.legal_contract_assistant.contract_review import RISK_THEME_CITATIONS
from src.legal_contract_assistant.contract_review import RISK_THEME_PATTERNS
from src.legal_contract_assistant.contract_review import ContractReviewService
from src.legal_contract_assistant.main import generate_review_report

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


def test_testpack_rule_based_risk_level_matches_manifest() -> None:
    cases = _load_test_cases()

    mismatches = []
    for case in cases:
        risk_level, _reasons = estimate_risk_level(
            case["contract_text"],
            CONTRACT_TYPE_MAP[case["contract_type"]],
            [],
        )
        if risk_level != case["expected_risk_level"]:
            mismatches.append((case["case_id"], case["expected_risk_level"], risk_level))

    assert len(cases) == 90
    assert mismatches == []


def test_testpack_rule_based_risk_theme_recall_matches_manifest() -> None:
    cases = _load_test_cases()

    misses = []
    for case in cases:
        expected = case["expected_risk_themes"]
        actual = detect_risk_themes(case["contract_text"])
        if expected not in actual:
            misses.append((case["case_id"], expected, actual))

    assert len(cases) == 90
    assert misses == []


def test_testpack_expected_themes_have_citation_mapping() -> None:
    cases = _load_test_cases()
    expected_themes = {
        case["expected_risk_themes"]
        for case in cases
        if case["expected_risk_themes"] != "無明顯高風險；仍應人工複核"
    }
    detected_themes = {theme for theme, _pattern in RISK_THEME_PATTERNS}

    assert expected_themes <= detected_themes
    assert expected_themes <= set(RISK_THEME_CITATIONS)


def test_testpack_citation_presence_and_relevance() -> None:
    cases = _load_test_cases()
    service = ContractReviewService()
    service.initialize()

    misses = []
    for case in cases:
        context = service.build_context(
            case["contract_text"],
            contract_type=CONTRACT_TYPE_MAP[case["contract_type"]],
        )
        assert context.related_articles

        expected_theme = case["expected_risk_themes"]
        if expected_theme == "無明顯高風險；仍應人工複核":
            continue

        expected_citations = set(RISK_THEME_CITATIONS[expected_theme])
        actual_citations = {
            (article.law_name, article.article_no)
            for article in context.related_articles
        }
        if expected_citations.isdisjoint(actual_citations):
            misses.append((case["case_id"], expected_theme, sorted(actual_citations)))

    assert misses == []


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
