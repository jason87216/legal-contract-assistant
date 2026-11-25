"""Review rule seed loading and in-memory helpers."""

from __future__ import annotations

import json
import re
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
    # When and how the legal basis applies, e.g. which article fits which situation.
    basis_note: str = ""
    # "match": the risk is present when pattern is found; "missing": the risk is
    # that the contract never says pattern (e.g. no delivery date).
    kind: str = "match"
    # Evaluate the rule only when the contract also contains this pattern
    # (e.g. a deposit rule only for contracts that mention a deposit).
    requires: str = ""

    @property
    def contract_type(self) -> str:
        """The rule_id prefix: sale, lease, labor ... or shared."""
        return self.rule_id.split("_", 1)[0]

    def search(self, text: str) -> re.Match[str] | None | bool:
        """The match that triggers a "match" rule, True for a triggered "missing"
        rule, and None when the rule does not trigger."""
        if self.requires and not re.search(self.requires, text):
            return None
        found = re.search(self.pattern, text)
        if self.kind == "missing":
            return True if found is None else None
        return found


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
            basis_note=item.get("basis_note", ""),
            kind=item.get("kind", "match"),
            requires=item.get("requires", ""),
        )
        for item in raw_rules
    ]


RULE_KINDS = ("match", "missing")


def load_llm_checklist(contract_type: str | None) -> tuple[str, ...]:
    """Review items the rules cannot judge from wording, left to the model.

    Each item names its related articles so the model knows where to start
    looking (llm_checklist_seed.json); "shared" items apply to every type.
    """
    seed_path = resources.files(f"{__package__}.data").joinpath("llm_checklist_seed.json")
    items = json.loads(seed_path.read_text(encoding="utf-8"))
    lines = []
    for item in items:
        if item["contract_type"] not in (contract_type, "shared"):
            continue
        articles = "、".join(
            f"{a['law_name']} §{a['article_no']}" for a in item.get("related_articles", [])
        )
        lines.append(f"{item['item']}（可參考：{articles}）" if articles else item["item"])
    return tuple(lines)


def rules_for_contract_type(rules: list[ReviewRule], contract_type: str | None) -> list[ReviewRule]:
    """Shared rules plus the rules of this contract type; every rule when the
    type is unknown (the requires pattern still keeps rules on their own type)."""
    typed = {rule.contract_type for rule in rules} - {"shared"}
    if contract_type not in typed:
        return list(rules)
    return [rule for rule in rules if rule.contract_type in (contract_type, "shared")]


@dataclass(frozen=True)
class RuleHit:
    rule: ReviewRule
    match: re.Match[str] | None  # None for a "missing" rule


def triggered_rules(
    text: str, rules: list[ReviewRule], contract_type: str | None = None
) -> list[RuleHit]:
    hits = []
    for rule in rules_for_contract_type(rules, contract_type):
        result = rule.search(text)
        if result is None:
            continue
        hits.append(RuleHit(rule, result if isinstance(result, re.Match) else None))
    return hits


def risk_theme_citations(
    rules: list[ReviewRule],
) -> dict[str, tuple[tuple[str, str], ...]]:
    return {
        rule.risk_theme: rule.legal_basis
        for rule in rules
        if rule.legal_basis
    }


DEFAULT_REVIEW_RULES = load_seed_review_rules()
RISK_THEME_CITATIONS = risk_theme_citations(DEFAULT_REVIEW_RULES)
