"""Reusable statute retrieval tools for GUI, MCP, and LLM tool calling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .statute_lookup import StatuteLookupService
from .statutes import StatuteArticle


@dataclass(frozen=True)
class RetrievedArticle:
    article: StatuteArticle
    score: int
    match_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "law_name": self.article.law_name,
            "article_no": self.article.article_no,
            "citation": self.article.citation,
            "text": self.article.text,
            "source_url": self.article.source_url,
            "contract_types": list(self.article.contract_types),
            "topics": list(self.article.topics),
            "score": self.score,
            "match_reason": self.match_reason,
        }


class StatuteRetrievalTool:
    """Tool facade over the local statute cache.

    The LLM never talks to SQLite directly. It can only request one of these
    bounded tools, and every returned citation keeps its source URL.
    """

    def __init__(self, lookup_service: StatuteLookupService | None = None) -> None:
        self.lookup_service = lookup_service or StatuteLookupService()

    def initialize(self) -> None:
        self.lookup_service.initialize()

    def lookup_article(self, law_name: str, article_no: str) -> dict[str, Any]:
        result = self.lookup_service.lookup(
            law_name,
            article_no,
            allow_live_query=False,
        )
        if result.article is None:
            return {
                "found": False,
                "status": result.status,
                "source": result.source,
                "law_name": law_name,
                "article_no": article_no,
            }
        return {
            "found": True,
            "status": result.status,
            "source": result.source,
            "article": RetrievedArticle(result.article, 100, "exact_article").to_dict(),
        }

    def search_statutes(
        self,
        query: str,
        contract_mode: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        terms = _extract_terms(query)
        if not terms and contract_mode:
            terms = [contract_mode]
        ranked: list[RetrievedArticle] = []
        for article in self.lookup_service.cache.list_articles():
            score, reasons = _score_article(article, terms, contract_mode)
            if score > 0:
                ranked.append(
                    RetrievedArticle(
                        article=article,
                        score=score,
                        match_reason=", ".join(reasons),
                    )
                )

        ranked.sort(key=lambda item: (-item.score, item.article.law_name, item.article.article_no))
        return [item.to_dict() for item in ranked[: _safe_limit(limit)]]

    def retrieve_candidate_articles(
        self,
        contract_text: str,
        contract_mode: str | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        keywords = extract_contract_keywords(contract_text)
        query = " ".join(keywords)
        articles = self.search_statutes(query, contract_mode=contract_mode, limit=limit)
        return {
            "contract_mode": contract_mode or "unknown",
            "keywords": keywords,
            "articles": articles,
        }

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "lookup_article":
            return self.lookup_article(
                law_name=str(arguments.get("law_name", "")),
                article_no=str(arguments.get("article_no", "")),
            )
        if name == "search_statutes":
            return {
                "articles": self.search_statutes(
                    query=str(arguments.get("query", "")),
                    contract_mode=_optional_str(arguments.get("contract_mode")),
                    limit=int(arguments.get("limit", 8) or 8),
                )
            }
        if name == "retrieve_candidate_articles":
            return self.retrieve_candidate_articles(
                contract_text=str(arguments.get("contract_text", "")),
                contract_mode=_optional_str(arguments.get("contract_mode")),
                limit=int(arguments.get("limit", 12) or 12),
            )
        return {"error": f"Unsupported tool: {name}"}

    def call_tool_json(self, name: str, arguments: dict[str, Any]) -> str:
        return json.dumps(self.call_tool(name, arguments), ensure_ascii=False)


def extract_contract_keywords(contract_text: str, limit: int = 18) -> list[str]:
    normalized = contract_text.strip()
    raw_terms = _extract_terms(normalized)
    seen: set[str] = set()
    keywords: list[str] = []
    for term in raw_terms:
        if term in seen:
            continue
        seen.add(term)
        keywords.append(term)
        if len(keywords) >= limit:
            break
    return keywords


def _extract_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[\w\u4e00-\u9fff-]{2,}", text):
        cleaned = token.strip("_-")
        if len(cleaned) >= 2 and not cleaned.isdigit():
            terms.append(cleaned)
    return terms


def _score_article(
    article: StatuteArticle,
    terms: list[str],
    contract_mode: str | None,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    mode = (contract_mode or "").strip()
    if mode and mode in article.contract_types:
        score += 6
        reasons.append(f"contract_mode:{mode}")

    haystacks = {
        "law_name": article.law_name,
        "article_no": article.article_no,
        "topics": " ".join(article.topics),
        "text": article.text,
    }
    for term in terms:
        if term in haystacks["law_name"] or term == haystacks["article_no"]:
            score += 12
            reasons.append(f"law_or_article:{term}")
        if term in haystacks["topics"]:
            score += 8
            reasons.append(f"topic:{term}")
        if term in haystacks["text"]:
            score += 4
            reasons.append(f"text:{term}")
    return score, reasons


def _safe_limit(limit: int) -> int:
    return max(1, min(int(limit or 8), 30))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
