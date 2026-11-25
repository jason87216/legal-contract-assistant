"""承攬 (work), 委任 (mandate) and 借貸 (loan): classification, rules and checklist.

The sample contracts are hand-written checks of the draft rules, not a test set.
"""

import pytest

from src.legal_contract_assistant.contract_review import (
    CONTRACT_TYPES,
    ContractReviewService,
    classify_contract_type,
)
from src.legal_contract_assistant.statute_cache import ContractStatuteCache
from src.legal_contract_assistant.statute_lookup import StatuteLookupService

CLEAN = {
    "work": (
        "定作人甲方委託承攬人乙方製作公司官網，工作內容依附件規格書。"
        "乙方應於115年10月31日前完工並交付成果，甲方應於交付後十日內依規格書驗收。"
        "報酬新臺幣三十萬元，驗收合格後十日內給付。"
        "工作有瑕疵者，甲方得定相當期限請求乙方修補，保固期間自驗收合格起一年。"
        "成果之著作財產權於報酬付清時歸甲方所有。"
        "任一方違約經催告仍不履行者，他方得解除契約。"
    ),
    "mandate": (
        "委任人甲方委任受任人乙方處理公司登記事務，委任事務範圍以附件所列事項為限。"
        "乙方應每月以書面報告處理進度，委任關係終止時應提出結案報告。"
        "報酬每月新臺幣二萬元，於次月五日前給付；規費等必要費用由甲方預付。"
        "乙方非經甲方書面同意，不得使第三人代為處理委任事務。"
        "任一方得以三十日前書面通知終止本契約。"
    ),
    "loan": (
        "貸與人甲方借款予借款人乙方新臺幣五十萬元，於簽約當日全額匯入乙方帳戶。"
        "借款利率為年息百分之五，乙方應自115年9月起每月十日分期還款，共二十四期。"
        "乙方遲延還款者，按年息百分之五計付遲延利息。"
    ),
}

RISKY = {
    "work": (
        "定作人甲方委託承攬人乙方完成工作。驗收以甲方滿意為準。"
        "甲方得隨時終止本契約，乙方不得請求任何賠償。"
        "報酬於業主付款後始給付乙方。"
    ),
    "mandate": (
        "委任人甲方委任受任人乙方全權處理一切事務。"
        "甲方提前終止者，仍應給付全年顧問費。乙方得自行委由第三人處理。"
    ),
    "loan": (
        "出借人甲方借款予借款人乙方新臺幣十萬元，利息於撥款時自借款中先行扣除。"
        "逾期未付之利息滾入本金計算。甲方得視市場情況調高利率。"
    ),
}

EXPECTED = {
    "work": {
        "work_medium_acceptance_at_owner_discretion",
        "work_high_termination_without_compensation",
        "work_high_pay_when_paid",
        "work_medium_missing_completion_date",
    },
    "mandate": {
        "mandate_medium_overbroad_authority",
        "mandate_high_full_fee_on_termination",
        "mandate_medium_free_subdelegation",
        "mandate_medium_missing_report_duty",
        "mandate_medium_missing_scope",
    },
    "loan": {
        "loan_high_interest_deducted_upfront",
        "loan_high_compound_interest",
        "loan_high_lender_unilateral_rate",
        "loan_medium_missing_repayment_date",
    },
}


@pytest.fixture(scope="module")
def service(tmp_path_factory) -> ContractReviewService:
    path = tmp_path_factory.mktemp("types") / "c.db"
    service = ContractReviewService(StatuteLookupService(ContractStatuteCache(path)))
    service.initialize()
    return service


def test_new_types_are_listed_once() -> None:
    assert {"work", "mandate", "loan"} <= set(CONTRACT_TYPES)


@pytest.mark.parametrize("kind", ["work", "mandate", "loan"])
def test_classifier_recognizes_new_types(kind: str) -> None:
    assert classify_contract_type(CLEAN[kind]) == kind
    assert classify_contract_type(RISKY[kind]) == kind


@pytest.mark.parametrize("kind", ["work", "mandate", "loan"])
def test_clean_contract_triggers_no_rule(service, kind: str) -> None:
    context = service.build_context(CLEAN[kind], contract_type=kind)

    assert [f.rule_id for f in context.risk_findings] == []
    assert context.risk_level == "低風險"
    assert context.missing_items == ()


@pytest.mark.parametrize("kind", ["work", "mandate", "loan"])
def test_risky_contract_triggers_its_rules(service, kind: str) -> None:
    context = service.build_context(RISKY[kind], contract_type=kind)
    fired = {f.rule_id for f in context.risk_findings}

    assert EXPECTED[kind] <= fired
    assert all(rule_id.split("_", 1)[0] in (kind, "shared") for rule_id in fired)
    assert context.risk_level == "高風險"
    for finding in context.risk_findings:
        assert finding.articles, finding.rule_id


@pytest.mark.parametrize("kind", ["work", "mandate", "loan"])
def test_new_types_have_checklist_and_statute_candidates(service, kind: str) -> None:
    context = service.build_context(CLEAN[kind], contract_type=kind)

    assert context.llm_checklist
    assert context.candidate_articles
    assert any(kind in article["primary_types"] for article in context.candidate_articles)
