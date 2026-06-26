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
