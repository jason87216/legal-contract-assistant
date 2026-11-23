"""Each matched risk must carry its own clause, articles and suggestion."""

from src.legal_contract_assistant.contract_review import (
    ContractReviewService,
    clause_excerpt,
)
from src.legal_contract_assistant.statute_cache import ContractStatuteCache
from src.legal_contract_assistant.statute_lookup import StatuteLookupService

# Triggers two lease rules. The first (單方解約條款) cites two articles, which used
# to shift every later risk onto the wrong article when pairing by position.
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

    excerpts = {finding.theme: finding.clause_excerpt for finding in context.risk_findings}
    assert excerpts["單方解約條款"] == "甲方如有自用需要，得立即終止契約，乙方不得請求補償。"


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

    assert "- 單方解約條款：談判時要求修改或刪除，可援引民法 第 450 條" in tenant
    assert "- 單方解約條款：若要保留此約定，應先確認是否符合民法 第 450 條" in landlord
    assert "逐項：" not in neutral


def test_report_without_matched_rules_has_no_borrowed_citation(tmp_path) -> None:
    report = _service(tmp_path).generate_markdown_report("押金二個月，租期一年。", "lease")

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
    "第八條【特殊約定】\n"
    "乙方離職後三年內不得於臺灣地區從事與甲方相同或類似之工作，甲方無須另給補償。"
)


def test_noncompete_cites_specific_articles_with_basis_note(tmp_path) -> None:
    service = _service(tmp_path)
    context = service.build_context(NONCOMPETE, contract_type="labor")
    report = service.generate_markdown_report(NONCOMPETE, contract_type="labor")

    finding = next(f for f in context.risk_findings if f.rule_id == "labor_high_noncompete")
    assert [article.citation for article in finding.articles] == [
        "勞動基準法 第 9-1 條",
        "勞動基準法施行細則 第 7-1 條",
        "勞動基準法施行細則 第 7-2 條",
        "勞動基準法施行細則 第 7-3 條",
    ]
    assert "勞動基準法 第 1 條" not in finding.citations
    assert f"   - 適用說明：{finding.basis_note}" in report
    assert "期間最長二年" in finding.basis_note


def test_rules_without_basis_note_show_no_note_line(tmp_path) -> None:
    report = _service(tmp_path).generate_markdown_report(CONTRACT, contract_type="lease")

    assert "適用說明" not in report
