from src.legal_contract_assistant.main import analyze_contract
from src.legal_contract_assistant.main import generate_review_report
from src.legal_contract_assistant.llm import ModelConfig
from src.legal_contract_assistant.statute_cache import ContractStatuteCache
from src.legal_contract_assistant.statute_lookup import StatuteLookupService
from src.legal_contract_assistant.statutes import StatuteArticle


def test_analyze_contract_empty_input() -> None:
    result = analyze_contract("")
    assert result["summary"] == "No contract text provided."


def test_seeded_contract_statute_cache_returns_common_article(tmp_path) -> None:
    cache = ContractStatuteCache(tmp_path / "statutes.db")
    cache.initialize()

    article = cache.get("民法", "247-1")

    assert article is not None
    assert article.citation == "民法 第 247-1 條"
    assert "顯失公平" in article.text
    assert "sale" in article.contract_types
    assert "standard_terms" in article.topics


def test_lookup_service_fetches_and_caches_missing_article(tmp_path) -> None:
    cache = ContractStatuteCache(tmp_path / "statutes.db")
    cache.initialize(seed=False)

    def fake_live_lookup(law_name: str, article_no: str) -> StatuteArticle:
        return StatuteArticle(
            law_name=law_name,
            pcode="B0000001",
            article_no=article_no,
            text="live text",
            source_url="https://example.test/statute",
            contract_types=("sale",),
        )

    service = StatuteLookupService(cache=cache, live_lookup=fake_live_lookup)

    result = service.lookup("民法", "999")

    assert result.status == "fetched"
    assert result.source == "live"
    assert result.article is not None
    assert cache.get("民法", "999") is not None


def test_each_contract_type_has_at_least_five_seeded_articles(tmp_path) -> None:
    cache = ContractStatuteCache(tmp_path / "statutes.db")
    cache.initialize()
    service = StatuteLookupService(cache=cache)

    assert len(service.search_by_contract_type("sale")) >= 5
    assert len(service.search_by_contract_type("labor")) >= 5
    assert len(service.search_by_contract_type("lease")) >= 5


def test_contract_type_and_topic_lookup_can_hit_seeded_article(tmp_path) -> None:
    cache = ContractStatuteCache(tmp_path / "statutes.db")
    cache.initialize()
    service = StatuteLookupService(cache=cache)

    articles = service.search_by_contract_and_topic("lease", "repair")

    assert any(article.citation == "民法 第 429 條" for article in articles)


def test_seeded_cache_initializes_review_rules(tmp_path) -> None:
    cache = ContractStatuteCache(tmp_path / "statutes.db")
    cache.initialize()

    rules = cache.list_review_rules()

    assert len(rules) >= 50
    assert any(
        rule.risk_theme == "違約金可能過高"
        and ("民法", "252") in rule.legal_basis
        for rule in rules
    )


def test_cli_report_contains_citations_source_url_and_disclaimer() -> None:
    report = generate_review_report(
        "甲方為出租人，乙方為承租人。乙方每月支付租金，房屋修繕由雙方約定。",
        contract_type="lease",
    )

    assert "# 合約審查報告" in report
    assert "整體風險等級" in report
    assert "https://law.moj.gov.tw/" in report
    assert "模型設定：noop/rule-based-report-writer" in report
    assert "不構成正式法律意見" in report


def test_cli_report_can_record_selected_model_without_api_call() -> None:
    report = generate_review_report(
        "買方與賣方約定價金與交付日期。",
        contract_type="sale",
        model_config=ModelConfig(provider="openai", model="gpt-4.1-mini"),
    )

    assert "模型設定：openai/gpt-4.1-mini" in report
    assert "dry-run" in report


def test_openai_compatible_provider_requires_base_url() -> None:
    from src.legal_contract_assistant.llm import OpenAICompatibleLLMProvider

    try:
        OpenAICompatibleLLMProvider(ModelConfig(provider="llama.cpp", model="local-chat"))
    except ValueError as exc:
        assert "base_url" in str(exc)
    else:
        raise AssertionError("Expected missing base_url to fail")


def test_llm_prompts_include_grounding_constraints() -> None:
    from src.legal_contract_assistant.contract_review import ContractReviewService
    from src.legal_contract_assistant.llm import REPORT_SYSTEM_PROMPT, _build_user_prompt

    service = ContractReviewService()
    service.initialize()
    context = service.build_context(
        "甲方為出租人，乙方為承租人。租期一年，房屋修繕由出租人負責。",
        contract_type="lease",
    )
    user_prompt = _build_user_prompt(context)

    assert "不得推翻結構化資料中已抽出的事實" in REPORT_SYSTEM_PROMPT
    assert "合約已明確約定" in REPORT_SYSTEM_PROMPT
    assert "法條只能使用輸入中的 related_articles" in REPORT_SYSTEM_PROMPT
    assert "不得推翻結構化資料中已抽出的事實" in user_prompt
    assert "合約未約定" in user_prompt
    assert "related_articles" in user_prompt


def test_report_generation_accepts_replaceable_llm_provider(tmp_path) -> None:
    from src.legal_contract_assistant.contract_review import ContractReviewService

    class FakeLLMProvider:
        def generate_report(self, context) -> str:  # noqa: ANN001
            return f"fake report: {context.contract_type}"

    cache = ContractStatuteCache(tmp_path / "statutes.db")
    service = ContractReviewService(statute_lookup=StatuteLookupService(cache=cache))
    service.initialize()

    report = service.generate_markdown_report(
        "買方與賣方約定價金與交付日期。",
        contract_type="sale",
        llm_provider=FakeLLMProvider(),
    )

    assert report == "fake report: sale"
