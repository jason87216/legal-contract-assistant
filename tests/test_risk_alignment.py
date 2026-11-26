"""Each matched risk must carry its own clause, articles and suggestion."""

from src.legal_contract_assistant.contract_review import (
    ContractReviewService,
    clause_excerpt,
)
from src.legal_contract_assistant.statute_cache import ContractStatuteCache
from src.legal_contract_assistant.statute_lookup import StatuteLookupService

# Triggers several lease rules. The first (出租人得隨時或立即終止租約) cites three
# articles, which used to shift every later risk onto the wrong article when
# pairing by position.
CONTRACT = (
    "第一條【租賃標的】房屋位於臺北市。\n"
    "第八條【特殊約定】\n"
    "甲方如有自用需要，得立即終止契約，乙方不得請求補償。"
    "所有修繕費用均由乙方自行負擔，甲方不負任何責任。"
)


def _service(tmp_path) -> ContractReviewService:  # noqa: ANN001
    service = ContractReviewService(StatuteLookupService(ContractStatuteCache(tmp_path / "c.db")))
    service.initialize()
    return service


def test_each_finding_uses_its_own_rule_basis(tmp_path) -> None:
    service = _service(tmp_path)
    rules = {rule.risk_theme: rule for rule in service.statute_lookup.cache.list_review_rules()}

    context = service.build_context(CONTRACT, contract_type="lease")

    assert [finding.theme for finding in context.risk_findings] == list(context.risk_themes)
    assert len(context.risk_findings) >= 2
    for finding in context.risk_findings:
        expected = [f"{law} 第 {no} 條" for law, no in rules[finding.theme].legal_basis]
        assert [article.citation for article in finding.articles] == expected
        assert finding.suggestion == rules[finding.theme].suggestion


def test_finding_quotes_the_triggering_sentence(tmp_path) -> None:
    context = _service(tmp_path).build_context(CONTRACT, contract_type="lease")

    excerpts = {finding.rule_id: finding.clause_excerpt for finding in context.risk_findings}
    assert (
        excerpts["lease_high_landlord_terminate_at_will"]
        == "甲方如有自用需要，得立即終止契約，乙方不得請求補償。"
    )
    # A "missing" rule has no clause to quote.
    assert excerpts["lease_medium_missing_inventory"] == "（合約中未見相關約定）"


def test_report_lists_clause_articles_and_rule_suggestion_per_risk(tmp_path) -> None:
    service = _service(tmp_path)
    context = service.build_context(CONTRACT, contract_type="lease")
    report = service.generate_markdown_report(CONTRACT, contract_type="lease")

    for finding in context.risk_findings:
        assert f"問題：{finding.theme}（{finding.level}）" in report
        assert f"觸發條款：「{finding.clause_excerpt}」" in report
        assert f"對應法條：{finding.citations}" in report
        assert f"修改建議：{finding.suggestion}" in report
    assert "補明確義務、期限、通知方式" not in report


def test_party_perspectives_give_per_risk_advice(tmp_path) -> None:
    service = _service(tmp_path)
    tenant = service.generate_markdown_report(CONTRACT, "lease", review_perspective="party_b")
    landlord = service.generate_markdown_report(CONTRACT, "lease", review_perspective="party_a")
    neutral = service.generate_markdown_report(CONTRACT, "lease")

    theme = "出租人得隨時或立即終止租約"
    assert f"- {theme}：談判時要求修改或刪除，可援引租賃住宅市場發展及管理條例 第 10 條" in tenant
    assert f"- {theme}：若要保留此約定，應先確認是否符合租賃住宅市場發展及管理條例 第 10 條" in landlord
    assert "逐項：" not in neutral


def test_report_without_matched_rules_has_no_borrowed_citation(tmp_path) -> None:
    report = _service(tmp_path).generate_markdown_report(
        "出租人與承租人約定租金每月一萬元，押金二個月，租期一年，租期屆滿返還押金。"
        "修繕由出租人負責。附屬設備清單如附件。",
        "lease",
    )

    assert "1. 問題：未命中風險規則；仍應人工複核" in report
    section = report.split("## 八、逐項修改建議")[1].split("## 九")[0]
    assert "法條" not in section


def test_clause_excerpt_trims_long_sentences_around_the_match() -> None:
    text = "前言。" + "甲" * 200 + "不得解除契約" + "乙" * 200 + "。結尾"
    start = text.index("不得解除契約")

    excerpt = clause_excerpt(text, start, start + 6, max_length=40)

    assert "不得解除契約" in excerpt
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert len(excerpt) == 42


def test_every_rule_citation_resolves_to_an_official_article(tmp_path) -> None:
    service = _service(tmp_path)

    unresolved = [
        (rule.rule_id, law_name, article_no)
        for rule in service.statute_lookup.cache.list_review_rules()
        for law_name, article_no in rule.legal_basis
        if service.statute_lookup.lookup(law_name, article_no, allow_live_query=False).article
        is None
    ]

    assert unresolved == []


NONCOMPETE = (
    "甲方（雇主）僱用乙方（勞工）。\n"
    "第八條【特殊約定】\n"
    "乙方離職後三年內不得於臺灣地區從事與甲方相同或類似之工作，甲方無須另給補償。"
)


def test_noncompete_cites_specific_articles_with_basis_note(tmp_path) -> None:
    service = _service(tmp_path)
    context = service.build_context(NONCOMPETE, contract_type="labor")
    report = service.generate_markdown_report(NONCOMPETE, contract_type="labor")

    finding = next(f for f in context.risk_findings if f.rule_id == "labor_high_noncompete_unlawful")
    assert [article.citation for article in finding.articles] == [
        "勞動基準法 第 9-1 條",
        "勞動基準法施行細則 第 7-2 條",
        "勞動基準法施行細則 第 7-3 條",
    ]
    assert "勞動基準法 第 1 條" not in finding.citations
    assert f"   - 適用說明：{finding.basis_note}" in report
    assert "二年" in finding.basis_note


def test_missing_rules_fire_only_when_the_wording_is_absent(tmp_path) -> None:
    service = _service(tmp_path)
    base = "出租人與承租人約定租金每月一萬元，押金二個月。"

    without = service.build_context(base, contract_type="lease")
    with_return = service.build_context(base + "租期屆滿返還押金。", contract_type="lease")

    assert "lease_medium_missing_deposit_return" in {f.rule_id for f in without.risk_findings}
    assert "lease_medium_missing_deposit_return" not in {f.rule_id for f in with_return.risk_findings}


def test_rules_are_limited_to_the_selected_contract_type(tmp_path) -> None:
    # A labor rule must not fire on a lease even when the wording matches.
    text = "出租人與承租人約定租金。雇主僱用勞工，乙方於試用期間不給薪。"

    context = _service(tmp_path).build_context(text, contract_type="lease")

    assert all(not f.rule_id.startswith("labor_") for f in context.risk_findings)


def test_llm_checklist_goes_to_the_prompt_and_dry_run_report(tmp_path) -> None:
    from src.legal_contract_assistant.llm import _build_user_prompt

    service = _service(tmp_path)
    context = service.build_context(CONTRACT, contract_type="lease")
    report = service.generate_markdown_report(CONTRACT, contract_type="lease")

    assert context.llm_checklist
    assert all(item in _build_user_prompt(context) for item in context.llm_checklist)
    assert f"規則未判斷，請人工檢查：{context.llm_checklist[0]}" in report


def test_penalty_clauses_are_high_risk_but_limits_on_them_are_not(tmp_path) -> None:
    service = _service(tmp_path)

    def penalty(text: str) -> list[str]:
        context = service.build_context("買方與賣方約定價金。" + text, contract_type="sale")
        return [f.clause_excerpt for f in context.risk_findings if f.rule_id == "shared_high_penalty"]

    assert penalty("違約金如顯失公平，雙方同意得由法院酌減。") == []
    assert penalty("違約金不得超過契約總價百分之十。") == []
    assert penalty("違約金如顯失公平得酌減。乙方遲延者每日按價金千分之一計付違約金。") == [
        "乙方遲延者每日按價金千分之一計付違約金。"
    ]
