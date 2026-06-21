"""Lookup service that reads common contract statutes from cache first."""

from __future__ import annotations

from collections.abc import Callable

from .moj_client import MojLawClient
from .statute_cache import ContractStatuteCache
from .statutes import StatuteArticle, StatuteLookupResult

LiveLookup = Callable[[str, str], StatuteArticle]


class StatuteLookupService:
    """Cache-first statute lookup with optional live fallback."""

    def __init__(
        self,
        cache: ContractStatuteCache | None = None,
        live_lookup: LiveLookup | None = None,
    ) -> None:
        self.cache = cache or ContractStatuteCache()
        self.live_lookup = live_lookup

    @classmethod
    def with_moj_fallback(cls, cache: ContractStatuteCache | None = None) -> "StatuteLookupService":
        client = MojLawClient()
        return cls(cache=cache, live_lookup=client.lookup_article)

    def initialize(self) -> None:
        self.cache.initialize(seed=True)

    def lookup(
        self,
        law_name: str,
        article_no: str,
        *,
        allow_live_query: bool = True,
    ) -> StatuteLookupResult:
        cached = self.cache.get(law_name, article_no)
        if cached is not None:
            return StatuteLookupResult(article=cached, status="hit", source="cache")

        if not allow_live_query or self.live_lookup is None:
            return StatuteLookupResult(article=None, status="miss", source="cache")

        article = self.live_lookup(law_name, article_no)
        self.cache.upsert(article)
        return StatuteLookupResult(article=article, status="fetched", source="live")

    def search_common_topics(self, topic: str) -> list[StatuteArticle]:
        return self.cache.search_by_topic(topic)

    def search_by_contract_type(self, contract_type: str) -> list[StatuteArticle]:
        return self.cache.search_by_contract_type(contract_type)

    def search_by_contract_and_topic(
        self, contract_type: str, topic: str
    ) -> list[StatuteArticle]:
        return self.cache.search_by_contract_and_topic(contract_type, topic)
