"""Review rule seed loading and in-memory helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class ReviewRule:
    rule_id: str
    risk_theme: str
    risk_level: str
    pattern: str
    legal_basis: tuple[tuple[str, str], ...]
    suggestion: str
    source_note: str


def load_seed_review_rules() -> list[ReviewRule]:
    seed_path = resources.files(f"{__package__}.data").joinpath(
        "review_rules_seed.json"
    )
    raw_rules = json.loads(seed_path.read_text(encoding="utf-8"))
    return [
        ReviewRule(
            rule_id=item["rule_id"],
            risk_theme=item["risk_theme"],
            risk_level=item["risk_level"],
            pattern=item["pattern"],
            legal_basis=tuple(
                (basis["law_name"], basis["article_no"])
                for basis in item.get("legal_basis", [])
            ),
            suggestion=item.get("suggestion", ""),
            source_note=item.get("source_note", ""),
        )
        for item in raw_rules
    ]


def risk_theme_patterns(rules: list[ReviewRule]) -> tuple[tuple[str, str], ...]:
    return tuple((rule.risk_theme, rule.pattern) for rule in rules)


def risk_level_patterns(
    rules: list[ReviewRule], risk_level: str
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (rule.risk_theme, rule.pattern)
        for rule in rules
        if rule.risk_level == risk_level
    )


def risk_theme_citations(
    rules: list[ReviewRule],
) -> dict[str, tuple[tuple[str, str], ...]]:
    return {
        rule.risk_theme: rule.legal_basis
        for rule in rules
        if rule.legal_basis
    }


DEFAULT_REVIEW_RULES = load_seed_review_rules()
HIGH_RISK_PATTERNS = risk_level_patterns(DEFAULT_REVIEW_RULES, "高風險")
MEDIUM_RISK_PATTERNS = risk_level_patterns(DEFAULT_REVIEW_RULES, "中風險")
RISK_THEME_PATTERNS = risk_theme_patterns(DEFAULT_REVIEW_RULES)
RISK_THEME_CITATIONS = risk_theme_citations(DEFAULT_REVIEW_RULES)
