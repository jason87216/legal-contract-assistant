"""Contract review workflow built on the local statute cache."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .review_rules import DEFAULT_REVIEW_RULES
from .review_rules import ReviewRule
from .review_rules import risk_level_patterns
from .review_rules import risk_theme_citations
from .review_rules import risk_theme_patterns
from .statute_lookup import StatuteLookupService
from .statute_tools import StatuteRetrievalTool
from .statutes import StatuteArticle

if TYPE_CHECKING:
    from .llm import LLMProvider, ModelConfig

CONTRACT_TYPE_LABELS = {
    "sale": "買賣",
    "labor": "勞動",
    "lease": "租賃",
    "unknown": "無法判斷",
}

REVIEW_PERSPECTIVE_LABELS = {
    "neutral": "中立審查",
    "party_a": "甲方立場",
    "party_b": "乙方立場",
}

CONTRACT_TYPE_KEYWORDS = {
    "labor": ("雇主", "勞工", "薪資", "工資", "加班", "工作時間", "職務", "離職"),
    "lease": ("出租人", "承租人", "租金", "押金", "租賃", "房屋", "修繕", "租期"),
    "sale": ("買方", "賣方", "價金", "標的物", "交付", "驗收", "瑕疵", "保固"),
}

REQUIRED_KEYWORDS = {
    "sale": {
        "標的物": ("標的", "商品", "貨物"),
        "價金或付款方式": ("價金", "付款", "款項"),
        "交付或驗收": ("交付", "交貨", "驗收"),
        "瑕疵或保固責任": ("瑕疵", "保固", "退換"),
        "終止或解除": ("終止", "解除"),
    },
    "labor": {
        "職稱或工作內容": ("職稱", "職務", "工作內容"),
        "工作地點": ("工作地點", "地點"),
        "工時或休假": ("工時", "工作時間", "休假", "例假"),
        "薪資或加班費": ("薪資", "工資", "加班費"),
        "離職或終止": ("離職", "終止", "資遣"),
    },
    "lease": {
        "租賃標的": ("房屋", "租賃物", "地址"),
        "租金": ("租金", "租費"),
        "押金": ("押金", "保證金"),
        "修繕責任": ("修繕", "維修"),
        "租期或終止": ("租期", "終止", "期限"),
    },
}

TOPIC_KEYWORDS = {
    "penalty": ("違約金", "賠償"),
    "termination": ("終止", "解除", "離職", "資遣"),
    "standard_terms": ("定型化", "不得異議", "概不負責"),
    "warranty": ("瑕疵", "保固", "退換"),
    "working_hours": ("工時", "工作時間", "加班"),
    "wage": ("薪資", "工資", "加班費"),
    "repair": ("修繕", "維修"),
    "rent": ("租金", "押金"),
}

# Public rule constants are derived from seed data so tests and callers keep the
# same import surface while review rules can also be stored in SQLite.
HIGH_RISK_PATTERNS = risk_level_patterns(DEFAULT_REVIEW_RULES, "高風險")
MEDIUM_RISK_PATTERNS = risk_level_patterns(DEFAULT_REVIEW_RULES, "中風險")
RISK_THEME_PATTERNS = risk_theme_patterns(DEFAULT_REVIEW_RULES)
RISK_THEME_CITATIONS = risk_theme_citations(DEFAULT_REVIEW_RULES)


@dataclass(frozen=True)
class ReviewContext:
    contract_text: str
    contract_type: str
    confidence: str
    related_articles: tuple[StatuteArticle, ...]
    missing_items: tuple[str, ...]
    focus_topics: tuple[str, ...]
    risk_level: str
    risk_reasons: tuple[str, ...]
    risk_themes: tuple[str, ...]
    prompt: str
    model_config: "ModelConfig"
    contract_mode: str = "unknown"
    extracted_keywords: tuple[str, ...] = ()
    candidate_articles: tuple[dict, ...] = ()
    review_perspective: str = "neutral"

    @property
    def contract_type_label(self) -> str:
        return CONTRACT_TYPE_LABELS.get(self.contract_type, self.contract_type)

    @property
    def review_perspective_label(self) -> str:
        return REVIEW_PERSPECTIVE_LABELS.get(
            self.review_perspective,
            self.review_perspective,
        )


@dataclass(frozen=True)
class ContractReviewService:
    statute_lookup: StatuteLookupService = field(default_factory=StatuteLookupService)

    def initialize(self) -> None:
        self.statute_lookup.initialize()

    def build_context(
        self,
        contract_text: str,
        contract_type: str | None = None,
        review_perspective: str = "neutral",
    ) -> ReviewContext:
        normalized = contract_text.strip()
        detected_type = contract_type or "unknown"
        confidence = "high" if contract_type else "low"
        focus_topics = detect_focus_topics(normalized)
        missing_items = detect_missing_items(normalized, detected_type)
        retrieval_tool = StatuteRetrievalTool(self.statute_lookup)
        candidate_result = retrieval_tool.retrieve_candidate_articles(
            normalized,
            contract_mode=None if detected_type == "unknown" else detected_type,
            limit=12,
        )
        review_rules = self.statute_lookup.cache.list_review_rules() or DEFAULT_REVIEW_RULES
        risk_level, risk_reasons = estimate_risk_level(
            normalized, detected_type, missing_items, review_rules
        )
        risk_themes = detect_risk_themes(normalized, review_rules)
        articles = collect_related_articles(
            self.statute_lookup,
            detected_type,
            focus_topics,
            risk_themes,
            risk_theme_citations(review_rules),
            candidate_result.get("articles", []),
        )

        from .llm import REPORT_SYSTEM_PROMPT, ModelConfig

        return ReviewContext(
            contract_text=normalized,
            contract_type=detected_type,
            confidence=confidence,
            related_articles=tuple(articles),
            missing_items=tuple(missing_items),
            focus_topics=tuple(focus_topics),
            risk_level=risk_level,
            risk_reasons=tuple(risk_reasons),
            risk_themes=tuple(risk_themes),
            prompt=REPORT_SYSTEM_PROMPT,
            model_config=ModelConfig(),
            contract_mode=detected_type,
            extracted_keywords=tuple(candidate_result.get("keywords", [])),
            candidate_articles=tuple(candidate_result.get("articles", [])),
            review_perspective=review_perspective,
        )

    def generate_markdown_report(
        self,
        contract_text: str,
        contract_type: str | None = None,
        review_perspective: str = "neutral",
        llm_provider: "LLMProvider | None" = None,
        model_config: "ModelConfig | None" = None,
    ) -> str:
        from .llm import NoopLLMProvider

        context = self.build_context(
            contract_text,
            contract_type=contract_type,
            review_perspective=review_perspective,
        )
        if model_config is not None:
            context = ReviewContext(
                contract_text=context.contract_text,
                contract_type=context.contract_type,
                confidence=context.confidence,
                related_articles=context.related_articles,
                missing_items=context.missing_items,
                focus_topics=context.focus_topics,
                risk_level=context.risk_level,
                risk_reasons=context.risk_reasons,
                risk_themes=context.risk_themes,
                prompt=context.prompt,
                model_config=model_config,
                contract_mode=context.contract_mode,
                extracted_keywords=context.extracted_keywords,
                candidate_articles=context.candidate_articles,
                review_perspective=context.review_perspective,
            )
        provider = llm_provider or NoopLLMProvider(model_config=context.model_config)
        return provider.generate_report(context)


def classify_contract_type(contract_text: str) -> str:
    contract_text = strip_frontmatter(contract_text)
    scores = {
        contract_type: sum(1 for keyword in keywords if keyword in contract_text)
        for contract_type, keywords in CONTRACT_TYPE_KEYWORDS.items()
    }
    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    return best_type if best_score > 0 else "unknown"


def detect_focus_topics(contract_text: str) -> list[str]:
    contract_text = strip_frontmatter(contract_text)
    return [
        topic
        for topic, keywords in TOPIC_KEYWORDS.items()
        if any(keyword in contract_text for keyword in keywords)
    ]


def detect_missing_items(contract_text: str, contract_type: str) -> list[str]:
    contract_text = strip_frontmatter(contract_text)
    required = REQUIRED_KEYWORDS.get(contract_type, {})
    return [
        item
        for item, keywords in required.items()
        if not any(keyword in contract_text for keyword in keywords)
    ]


def estimate_risk_level(
    contract_text: str,
    contract_type: str,
    missing_items: list[str],
    rules: list[ReviewRule] | None = None,
) -> tuple[str, list[str]]:
    del contract_type
    cleaned = extract_review_clause(strip_frontmatter(contract_text))
    high_patterns = risk_level_patterns(rules, "高風險") if rules else HIGH_RISK_PATTERNS
    medium_patterns = (
        risk_level_patterns(rules, "中風險") if rules else MEDIUM_RISK_PATTERNS
    )
    high_reasons = _matching_reasons(cleaned, high_patterns)
    if high_reasons:
        return "高風險", high_reasons

    medium_reasons = _matching_reasons(cleaned, medium_patterns)
    if medium_reasons:
        return "中風險", medium_reasons

    if len(missing_items) >= 3:
        return "中風險", ["多個必要條款未以關鍵字明確呈現"]

    return "低風險", ["無明顯高風險；仍應人工複核"]


def detect_risk_themes(
    contract_text: str, rules: list[ReviewRule] | None = None
) -> list[str]:
    clause = extract_review_clause(strip_frontmatter(contract_text))
    patterns = risk_theme_patterns(rules) if rules else RISK_THEME_PATTERNS
    themes = _matching_reasons(clause, patterns)
    if themes:
        return themes
    return ["無明顯高風險；仍應人工複核"]


def strip_frontmatter(contract_text: str) -> str:
    return re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", contract_text, flags=re.S)


def extract_review_clause(contract_text: str) -> str:
    match = re.search(r"第[七八]條【特殊約定】\s*(.*)", contract_text, flags=re.S)
    return match.group(1).strip() if match else contract_text


def _matching_reasons(text: str, patterns: tuple[tuple[str, str], ...]) -> list[str]:
    return [reason for reason, pattern in patterns if re.search(pattern, text)]


def collect_related_articles(
    statute_lookup: StatuteLookupService,
    contract_type: str,
    topics: list[str],
    risk_themes: list[str] | None = None,
    citation_map: dict[str, tuple[tuple[str, str], ...]] | None = None,
    candidate_articles: list[dict] | None = None,
) -> list[StatuteArticle]:
    seen: set[tuple[str, str]] = set()
    articles: list[StatuteArticle] = []
    citations = citation_map or RISK_THEME_CITATIONS

    for theme in risk_themes or []:
        for law_name, article_no in citations.get(theme, ()):
            result = statute_lookup.lookup(law_name, article_no, allow_live_query=False)
            if result.article is None:
                continue
            key = (result.article.law_name, result.article.article_no)
            if key not in seen:
                seen.add(key)
                articles.append(result.article)

    for topic in topics:
        for article in statute_lookup.search_by_contract_and_topic(contract_type, topic):
            key = (article.law_name, article.article_no)
            if key not in seen:
                seen.add(key)
                articles.append(article)

    for candidate in candidate_articles or []:
        law_name = str(candidate.get("law_name", ""))
        article_no = str(candidate.get("article_no", ""))
        result = statute_lookup.lookup(law_name, article_no, allow_live_query=False)
        if result.article is None:
            continue
        key = (result.article.law_name, result.article.article_no)
        if key not in seen:
            seen.add(key)
            articles.append(result.article)

    if len(articles) < 5:
        for article in statute_lookup.search_by_contract_type(contract_type):
            key = (article.law_name, article.article_no)
            if key not in seen:
                seen.add(key)
                articles.append(article)
            if len(articles) >= 8:
                break

    return articles[:8]
