import sys
from contextlib import closing
from dataclasses import replace

import pytest

from src.legal_contract_assistant.statute_cache import OFFICIAL_VERSION_KEY, ContractStatuteCache
from src.legal_contract_assistant.statute_lookup import StatuteLookupService
from src.legal_contract_assistant.statute_tools import StatuteRetrievalTool
from src.legal_contract_assistant.statutes import StatuteArticle
from src.legal_contract_assistant.vector_index import VectorIndex


class FakeEmbedder:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        np = pytest.importorskip("numpy")
        self.calls.append(texts)
        return np.array([
            (1, 0) if "semantic" in text else (0, 1)
            for text in texts
        ])


@pytest.fixture
def articles():
    base = StatuteArticle("Example", "a", "1", "exact", "https://example.com",
                          contract_types=("lease",), topics=("exact",))
    return [
        base,
        replace(base, article_no="2", text="semantic", topics=(), primary_types=("lease",)),
        replace(base, article_no="3", text="semantic", topics=(), curated=False),
        replace(base, article_no="4", text="semantic", topics=()),
    ]


def test_build_reload_and_invalidate(tmp_path, articles):
    pytest.importorskip("numpy")
    initial = FakeEmbedder()
    VectorIndex(tmp_path, initial, "fake").prepare(articles, "v1")
    assert initial.calls[0][0] == "Example 1 exact exact"

    fresh = FakeEmbedder()
    reloaded = VectorIndex(tmp_path, fresh, "fake")
    reloaded.prepare(articles, "v1")
    assert fresh.calls == []
    assert reloaded.scores(["semantic"])[0][("Example", "2")] == 1
    reloaded.prepare(articles, "v2")
    VectorIndex(tmp_path, fresh, "other").prepare(articles, "v2")
    assert fresh.calls == [["semantic"], initial.calls[0], initial.calls[0]]
    assert len(list(tmp_path.glob("vectors-*.npz"))) == 3


@pytest.fixture
def service(tmp_path, articles, monkeypatch):
    monkeypatch.delenv("LCA_RETRIEVAL_METHOD", raising=False)
    cache = ContractStatuteCache(tmp_path / "statutes.db")
    cache.initialize()
    with closing(cache._connect()) as conn, conn:
        conn.execute("DELETE FROM statute_articles")
    cache.upsert_many(articles)
    cache.set_metadata(OFFICIAL_VERSION_KEY, "test")
    return StatuteLookupService(cache=cache)


def test_rankings_scope_and_environment(service, monkeypatch):
    pytest.importorskip("numpy")
    tool = StatuteRetrievalTool(service, embedder=FakeEmbedder())
    monkeypatch.setenv("LCA_RETRIEVAL_METHOD", "vector")

    def numbers(**kwargs):
        return [row["article_no"] for row in tool.search_statutes("semantic exact", "lease", **kwargs)]

    assert numbers() == ["2", "4", "1"]
    assert numbers(scope="all") == ["2", "3", "4", "1"]
    assert numbers(method="keyword")[0] == "1"
    assert numbers(method="hybrid") == ["2", "1", "4"]


def test_candidates_embed_each_clause_and_keep_best(service):
    pytest.importorskip("numpy")
    fake = FakeEmbedder()
    tool = StatuteRetrievalTool(service, embedder=fake)
    first, second = "\u7b2c\u4e00\u689d semantic", "\u7b2c\u4e8c\u689d exact"
    result = tool.retrieve_candidate_articles(f"{first}\n{second}", "lease", limit=2, method="vector")
    assert fake.calls[-1] == [first, second]
    assert result["retrieval_method"] == "vector"
    assert [row["article_no"] for row in result["articles"]] == ["2", "1"]


@pytest.mark.parametrize("method", ["vector", "hybrid"])
def test_missing_extra_falls_back(service, monkeypatch, method):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    tool = StatuteRetrievalTool(service)
    keyword = tool.search_statutes("exact")
    fallback = tool.call_tool("search_statutes", {"query": "exact", "scope": "curated", "method": method})
    assert fallback["retrieval_method"] == "keyword"
    assert "ModuleNotFoundError" in fallback["warning"]
    assert [a["article_no"] for a in fallback["articles"]] == [a["article_no"] for a in keyword]
    empty = tool.call_tool("search_statutes", {"query": "", "method": method})
    assert empty["articles"] == []
    assert "warning" in empty




def test_failed_index_build_uses_whole_contract_keyword_query(service):
    pytest.importorskip("numpy")

    class BrokenEmbedder:
        def encode(self, texts):
            raise OSError("model unavailable")

    tool = StatuteRetrievalTool(service, embedder=BrokenEmbedder())
    text = "semantic\n\nexact"
    result = tool.retrieve_candidate_articles(text, method="hybrid")
    keyword = tool.retrieve_candidate_articles(text, method="keyword")
    assert result["retrieval_method"] == "keyword"
    assert "OSError" in result["warning"]
    assert [row["article_no"] for row in result["articles"]] == [
        row["article_no"] for row in keyword["articles"]
    ]
