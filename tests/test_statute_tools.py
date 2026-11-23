from src.legal_contract_assistant.statute_cache import ContractStatuteCache
from src.legal_contract_assistant.statute_lookup import StatuteLookupService
from src.legal_contract_assistant.statute_tools import StatuteRetrievalTool


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
    assert "repair" in result["articles"][0]["topics"]
