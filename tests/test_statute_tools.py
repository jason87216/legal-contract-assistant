from dataclasses import replace
from types import SimpleNamespace

from src.legal_contract_assistant.statute_cache import ContractStatuteCache
from src.legal_contract_assistant.statute_lookup import StatuteLookupService
from src.legal_contract_assistant.statute_tools import StatuteRetrievalTool
from src.legal_contract_assistant.statutes import StatuteArticle


def _tool(tmp_path) -> StatuteRetrievalTool:  # noqa: ANN001
    cache = ContractStatuteCache(tmp_path / "statutes.db")
    service = StatuteLookupService(cache=cache)
    tool = StatuteRetrievalTool(service)
    tool.initialize()
    return tool


def test_search_statutes_returns_scored_articles(tmp_path) -> None:
    tool = _tool(tmp_path)

    articles = tool.search_statutes("repair maintenance", contract_mode="lease")

    assert articles
    assert articles[0]["source_url"].startswith("https://law.moj.gov.tw/")
    assert articles[0]["score"] > 0
    assert articles[0]["match_reason"]


def test_retrieve_candidate_articles_extracts_keywords_and_articles(tmp_path) -> None:
    tool = _tool(tmp_path)

    result = tool.retrieve_candidate_articles(
        "tenant repair maintenance rent deposit",
        contract_mode="lease",
    )

    assert result["contract_mode"] == "lease"
    assert result["keywords"]
    assert result["articles"]


def test_lookup_article_returns_structured_miss(tmp_path) -> None:
    tool = _tool(tmp_path)

    result = tool.lookup_article("不存在的法律", "999")

    assert result["found"] is False
    assert result["status"] == "miss"


def test_contract_keywords_are_legal_terms_not_whole_clauses() -> None:
    from src.legal_contract_assistant.statute_tools import extract_contract_keywords

    text = (
        "出租人甲方：李佳蓉；承租人乙方：林怡君。\n"
        "第一條【租賃標的】租賃房屋位於高雄市左營區博愛二路300號8樓。\n"
        "第三條【租金、押金與付款】每月租金新臺幣 32,000 元整，押金二個月。"
    )

    keywords = extract_contract_keywords(text)

    assert keywords[:4] == ["出租人", "承租人", "租賃", "房屋"]
    assert {"租金", "押金", "付款"} <= set(keywords)
    assert len(keywords) == len(set(keywords))
    # Names, addresses and clause numbers are not search terms.
    assert not any(word in keywords for word in ("李佳蓉", "林怡君", "第一條"))
    assert all(len(keyword) <= 8 for keyword in keywords)


def test_contract_keywords_keep_non_chinese_words() -> None:
    from src.legal_contract_assistant.statute_tools import extract_contract_keywords

    assert extract_contract_keywords("tenant must pay rent 民法 第 245-1 條") == [
        "tenant",
        "must",
        "pay",
        "rent",
        "民法",
        "245-1",
    ]


def test_statute_query_keeps_short_words_and_finds_terms_inside_long_ones(tmp_path) -> None:
    from src.legal_contract_assistant.statute_tools import _extract_terms

    assert _extract_terms("押金 返還 working_hours") == ["押金", "返還", "working_hours"]
    assert _extract_terms("出租人應負擔修繕費用") == ["出租人", "修繕"]


def test_lease_contract_candidates_have_distinct_scores(tmp_path) -> None:
    tool = _tool(tmp_path)

    result = tool.retrieve_candidate_articles(
        "承租人應按月支付租金，租賃物之修繕由出租人負擔，押金於返還房屋後退還。",
        contract_mode="lease",
    )

    scores = [article["score"] for article in result["articles"]]
    assert len(set(scores)) > 1
    assert "修繕" in result["articles"][0]["topics"]


def _articles_tool(articles: list[StatuteArticle]) -> StatuteRetrievalTool:
    cache = SimpleNamespace(list_articles=lambda **kwargs: articles)
    return StatuteRetrievalTool(SimpleNamespace(cache=cache))


def _article(law_name: str, text: str, article_no: str = "1") -> StatuteArticle:
    return StatuteArticle(
        law_name=law_name,
        pcode="test",
        article_no=article_no,
        text=text,
        source_url="https://example.invalid/",
        contract_types=("lease",),
        primary_types=("lease",),
    )


def test_law_name_substring_does_not_outweigh_unannotated_text() -> None:
    tool = _articles_tool([
        _article("租賃住宅市場發展及管理條例", "無關內容"),
        _article("民法", "租賃物之修繕由出租人負擔。"),
    ])

    articles = tool.search_statutes("租賃 修繕", contract_mode="lease")

    assert articles[0]["law_name"] == "民法"
    assert articles[0]["score"] == 14
    assert articles[1]["score"] == 6
    assert all("law_name:" not in article["match_reason"] for article in articles)


def test_explicit_law_name_is_counted_once_even_without_extracted_terms() -> None:
    tool = _articles_tool([
        _article("租賃住宅市場發展及管理條例", "無關內容"),
        _article("測試特別條例", "無關內容"),
    ])

    articles = tool.search_statutes("租賃住宅市場發展及管理條例")
    assert len(articles) == 1
    assert articles[0]["score"] == 12
    assert articles[0]["match_reason"] == "law_name:租賃住宅市場發展及管理條例"

    articles = tool.search_statutes("測試特別條例")
    assert len(articles) == 1
    assert articles[0]["score"] == 12
    assert articles[0]["match_reason"] == "law_name:測試特別條例"


def test_repair_ranking_does_not_depend_on_topic_annotations(tmp_path, monkeypatch) -> None:
    tool = _tool(tmp_path)
    articles = tool.lookup_service.cache.list_articles(curated_only=True)
    monkeypatch.setattr(
        tool.lookup_service.cache,
        "list_articles",
        lambda **kwargs: [replace(article, topics=()) for article in articles],
    )

    result = tool.retrieve_candidate_articles(
        "承租人應按月支付租金，租賃物之修繕由出租人負擔，押金於返還房屋後退還。",
        contract_mode="lease",
    )

    assert result["articles"][0]["law_name"] == "民法"
    assert result["articles"][0]["article_no"] in {"429", "430"}
    assert all("topic:" not in article["match_reason"] for article in result["articles"])


def test_search_scores_are_stable_under_repetition_and_candidate_order() -> None:
    articles = [
        _article("民法", "修繕", "430"),
        _article("民法", "修繕修繕修繕", "429"),
    ]
    tool = _articles_tool(articles)
    result = tool.search_statutes("修繕", contract_mode="lease")

    articles.reverse()
    assert tool.search_statutes("修繕 修繕", contract_mode="lease") == result
    assert [article["article_no"] for article in result] == ["429", "430"]
    assert [article["score"] for article in result] == [10, 10]
