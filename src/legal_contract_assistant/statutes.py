"""Shared statute data structures."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StatuteArticle:
    """A single Taiwan statute article relevant to contract review."""

    law_name: str
    pcode: str
    article_no: str
    text: str
    source_url: str
    contract_types: tuple[str, ...] = field(default_factory=tuple)
    topics: tuple[str, ...] = field(default_factory=tuple)
    cached_at: str | None = None

    @property
    def citation(self) -> str:
        return f"{self.law_name} 第 {self.article_no} 條"


@dataclass(frozen=True)
class StatuteLookupResult:
    """Result wrapper that tells callers whether data came from cache or live lookup."""

    article: StatuteArticle | None
    status: str
    source: str

    @property
    def found(self) -> bool:
        return self.article is not None
