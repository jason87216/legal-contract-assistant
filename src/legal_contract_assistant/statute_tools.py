"""Reusable statute retrieval tools for GUI, MCP, and LLM tool calling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from .statute_lookup import StatuteLookupService
from .statutes import StatuteArticle


SEARCH_SCOPES = ("curated", "all")


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
            "primary_types": list(self.article.primary_types),
            "curated": self.article.curated,
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
        scope: str = "curated",
    ) -> list[dict[str, Any]]:
        """Rank articles by query terms.

        scope "curated" searches the contract-type candidate ranges used by the
        report; "all" also searches every imported official article.
        """
        if scope not in SEARCH_SCOPES:
            raise ValueError(f"scope must be one of {SEARCH_SCOPES}")
        terms = _extract_terms(query)
        if not terms and contract_mode:
            terms = [contract_mode]
        ranked: list[RetrievedArticle] = []
        articles = self.lookup_service.cache.list_articles(curated_only=scope == "curated")
        for article in articles:
            score, reasons = _score_article(article, terms, contract_mode, query)
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
            scope = str(arguments.get("scope") or "all")
            if scope not in SEARCH_SCOPES:
                return {"error": f"scope must be one of {SEARCH_SCOPES}"}
            return {
                "articles": self.search_statutes(
                    query=str(arguments.get("query", "")),
                    contract_mode=_optional_str(arguments.get("contract_mode")),
                    limit=int(arguments.get("limit", 8) or 8),
                    scope=scope,
                )
            }
        if name == "statute_source_info":
            return self.source_info()
        if name == "retrieve_candidate_articles":
            return self.retrieve_candidate_articles(
                contract_text=str(arguments.get("contract_text", "")),
                contract_mode=_optional_str(arguments.get("contract_mode")),
                limit=int(arguments.get("limit", 12) or 12),
            )
        return {"error": f"Unsupported tool: {name}"}

    def source_info(self) -> dict[str, Any]:
        """Data source, license, data date and article counts per law."""
        return self.lookup_service.cache.source_info()

    def call_tool_json(self, name: str, arguments: dict[str, Any]) -> str:
        return json.dumps(self.call_tool(name, arguments), ensure_ascii=False)


def extract_contract_keywords(contract_text: str, limit: int = 18) -> list[str]:
    """Return legal terms in order of first appearance.

    Chinese contracts have no spaces, so splitting on punctuation yields whole
    clauses such as \u300c\u79df\u8cc3\u623f\u5c4b\u4f4d\u65bc\u9ad8\u96c4\u5e02\u20268\u6a13\u300d that never appear in a statute.
    Contract keywords therefore keep only known legal terms from Chinese text
    (names, addresses and clause numbers are dropped) plus non-Chinese words.
    """
    return _extract_terms(contract_text.strip(), keep_short_chinese=False)[:limit]


def _load_legal_terms() -> tuple[str, ...]:
    seed_path = resources.files(f"{__package__}.data").joinpath("contract_terms_seed.json")
    groups = json.loads(seed_path.read_text(encoding="utf-8"))
    terms = {
        term
        for name, items in groups.items()
        if not name.startswith("_")
        for term in items
    }
    # Longest first, so a term found at the same position as a shorter one
    # (\u5b9a\u578b\u5316\u5951\u7d04 / \u5b9a\u578b\u5316) is listed first.
    return tuple(sorted(terms, key=lambda term: (-len(term), term)))


LEGAL_TERMS = _load_legal_terms()
_CHINESE = re.compile(r"[\u4e00-\u9fff]")


def _legal_terms_in(token: str) -> list[str]:
    found = [
        (match.start(), index, term)
        for index, term in enumerate(LEGAL_TERMS)
        for match in re.finditer(re.escape(term), token)
    ]
    return [term for _, _, term in sorted(found)]


def _extract_terms(text: str, *, keep_short_chinese: bool = True) -> list[str]:
    """Split text into search terms, without duplicates.

    Words without Chinese characters are kept as they are (English words, topic
    codes, article numbers such as 245-1). Chinese runs are split into the
    legal terms they contain. A short Chinese query word (up to four
    characters) is also kept as typed, so a tool query like \u300c\u62bc\u91d1 \u8fd4\u9084\u300d still
    searches \u8fd4\u9084; contract text turns this off because its short tokens are
    mostly names and clause numbers.
    """
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        if term not in seen:
            seen.add(term)
            terms.append(term)

    for token in re.findall(r"[\w\u4e00-\u9fff-]{2,}", text):
        cleaned = token.strip("_-")
        if len(cleaned) < 2 or cleaned.isdigit():
            continue
        if not _CHINESE.search(cleaned):
            add(cleaned)
            continue
        if keep_short_chinese and len(cleaned) <= 4:
            add(cleaned)
        for term in _legal_terms_in(cleaned):
            add(term)
    return terms


# A primary article defines the contract type (民法 租賃 for a lease); a
# secondary one is general contract law or a rare variant (耕作地).
PRIMARY_TYPE_SCORE = 6
SECONDARY_TYPE_SCORE = 2


def _score_article(
    article: StatuteArticle,
    terms: list[str],
    contract_mode: str | None,
    query: str,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    mode = (contract_mode or "").strip()
    if mode and mode in article.primary_types:
        score += PRIMARY_TYPE_SCORE
        reasons.append(f"contract_mode:{mode}:primary")
    elif mode and mode in article.contract_types:
        score += SECONDARY_TYPE_SCORE
        reasons.append(f"contract_mode:{mode}")

    # 只有查詢明確提及完整法規名稱才加分，避免「租賃」替整部條例灌分。
    if article.law_name in query:
        score += 12
        reasons.append(f"law_name:{article.law_name}")

    topics = " ".join(article.topics)
    for term in terms:
        if term == article.article_no:
            score += 12
            reasons.append(f"article_no:{term}")
        if term in topics:
            score += 8
            reasons.append(f"topic:{term}")
        if term in article.text:
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
