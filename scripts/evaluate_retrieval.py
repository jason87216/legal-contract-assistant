"""Evaluate candidate-statute retrieval on the labelled testpack.

Ground truth: for each case with an expected risk theme, the statutes cited by
the review rules of that theme. A case counts as found at rank r when any of
those statutes is the r-th retrieved article.

Variants compare what is searched (the whole contract, or only the clauses a
review rule matched) and where (the curated articles or every imported one).
The testpack was also used to write the rules and the legal-term list, so these
numbers compare variants with each other; they are not an accuracy claim.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.evaluate import NO_HIGH_RISK_THEME, ROOT, THEME_MAP, load_cases
from src.legal_contract_assistant.contract_review import classify_contract_type
from src.legal_contract_assistant.review_rules import DEFAULT_REVIEW_RULES, ReviewRule
from src.legal_contract_assistant.statute_tools import (
    CLAUSE_SPLIT,
    RETRIEVAL_METHODS,
    StatuteRetrievalTool,
    extract_contract_keywords,
)

LIMIT = 12
K_VALUES = (5, 12)
QUERY_KINDS = ("full", "clause")
SCOPES = ("curated", "all")
VARIANT_DESCRIPTIONS = {
    "full_curated": "整份合約的法律用語，搜精選法條（目前報告使用的方式）",
    "full_all": "整份合約的法律用語，搜全部匯入法條",
    "clause_curated": "只用被規則命中的條款，搜精選法條",
    "clause_all": "只用被規則命中的條款，搜全部匯入法條",
}


def citation_key(law_name: str, article_no: str) -> str:
    return f"{law_name}§{article_no}"


def expected_citations_by_theme(rules: list[ReviewRule]) -> dict[str, set[str]]:
    """Testpack theme -> statutes cited by the rules covering it (testpack_theme_map.json)."""
    by_id = {rule.rule_id: rule for rule in rules}
    table: dict[str, set[str]] = {}
    for theme, rule_ids in THEME_MAP["themes"].items():
        for rule_id in rule_ids:
            if rule_id not in by_id:
                continue
            for law_name, article_no in by_id[rule_id].legal_basis:
                table.setdefault(theme, set()).add(citation_key(law_name, article_no))
    return table


def rule_hit_clauses(text: str, rules: list[ReviewRule]) -> list[str]:
    """Clauses matched by any "match" rule. Uses the rules, never the case label."""
    clauses = [clause.strip() for clause in CLAUSE_SPLIT.split(text) if clause.strip()]
    patterns = [rule.pattern for rule in rules if rule.kind == "match"]
    return [clause for clause in clauses if any(re.search(p, clause) for p in patterns)]


def retrieve(
    tool: StatuteRetrievalTool,
    text: str,
    contract_mode: str | None,
    query_kind: str,
    scope: str,
    rules: list[ReviewRule],
    method: str = "keyword",
) -> list[str]:
    queries = [text] if query_kind == "full" else rule_hit_clauses(text, rules)
    best: dict[str, float] = {}
    for query in queries:
        if method == "keyword":
            query = " ".join(extract_contract_keywords(query))
            if not query and query_kind == "clause":
                continue
        result = tool.call_tool("search_statutes", {
            "query": query,
            "contract_mode": contract_mode,
            "limit": LIMIT,
            "scope": scope,
            "method": method,
        })
        if "warning" in result:
            raise VectorEvaluationUnavailable(result["warning"])
        for article in result["articles"]:
            key = citation_key(article["law_name"], article["article_no"])
            best[key] = max(best.get(key, float("-inf")), article["score"])
    if query_kind == "full":
        return list(best)
    ranked = sorted(best, key=lambda key: (-best[key], key))
    return ranked[:LIMIT]


class VectorEvaluationUnavailable(RuntimeError):
    pass


def first_hit_rank(ranked: list[str], expected: set[str]) -> int | None:
    return next((rank for rank, key in enumerate(ranked, 1) if key in expected), None)


def evaluate_retrieval(
    cases: list[dict[str, Any]],
    tool: StatuteRetrievalTool | None = None,
    rules: list[ReviewRule] | None = None,
) -> dict[str, Any]:
    rules = rules or DEFAULT_REVIEW_RULES
    if tool is None:
        tool = StatuteRetrievalTool()
        tool.initialize()
    expected_table = expected_citations_by_theme(rules)
    curated = {
        citation_key(article.law_name, article.article_no)
        for article in tool.lookup_service.cache.list_articles(curated_only=True)
    }

    skipped_methods: dict[str, str] = {}
    variants = {
        (base if method == "keyword" else f"{method}_{base}"): (method, description)
        for method in RETRIEVAL_METHODS
        for base, description in VARIANT_DESCRIPTIONS.items()
    }
    rows: list[dict[str, Any]] = []
    for case in cases:
        theme = case["expected_risk_themes"]
        if theme == NO_HIGH_RISK_THEME or theme not in expected_table:
            continue
        expected = expected_table[theme]
        text = case["contract_text"]
        mode = classify_contract_type(text)
        row: dict[str, Any] = {
            "case_id": case["case_id"],
            "risk_theme": theme,
            "expected": sorted(expected),
            "expected_in_curated": bool(expected & curated),
            "ranks": {},
        }
        for method in RETRIEVAL_METHODS:
            if method in skipped_methods:
                continue
            try:
                for query_kind in QUERY_KINDS:
                    for scope in SCOPES:
                        ranked = retrieve(
                            tool, text, None if mode == "unknown" else mode,
                            query_kind, scope, rules, method,
                        )
                        base = f"{query_kind}_{scope}"
                        variant = base if method == "keyword" else f"{method}_{base}"
                        row["ranks"][variant] = first_hit_rank(ranked, expected)
            except VectorEvaluationUnavailable as exc:
                skipped_methods[method] = str(exc)
        rows.append(row)

    total = len(rows)
    metrics: dict[str, dict[str, Any]] = {}
    for variant, (method, description) in variants.items():
        if method in skipped_methods:
            for row in rows:
                row["ranks"].pop(variant, None)
            continue
        ranks = [row["ranks"][variant] for row in rows]
        metrics[variant] = {
            "description": description,
            "method": method,
            **{
                f"recall_at_{k}": _ratio(sum(1 for r in ranks if r is not None and r <= k), total)
                for k in K_VALUES
            },
            "mrr": round(sum(1 / r for r in ranks if r) / total, 3) if total else 0.0,
        }
    return {
        "evaluation_mode": "offline_retrieval_only",
        "case_count": total,
        "skipped_cases": len(cases) - total,
        "limit": LIMIT,
        "expected_in_curated": _ratio(sum(row["expected_in_curated"] for row in rows), total),
        "metrics": metrics,
        "skipped_methods": skipped_methods,
        "cases": rows,
    }


def _ratio(passed: int, total: int) -> dict[str, Any]:
    return {"passed": passed, "total": total, "rate": round(passed / total, 3) if total else 0.0}


def to_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# 候選法條檢索評測",
        "",
        "離線評測，不呼叫 LLM。標準答案是預期風險主題所屬規則引用的法條；"
        "測試包同時用於撰寫規則與詞表，數字只用來比較不同做法，不代表準確率。",
        "",
        f"- 納入案例：{results['case_count']}（略過無預期風險主題者 {results['skipped_cases']}）",
        f"- 每次取前 {results['limit']} 條",
        f"- 標準答案在精選法條內：{results['expected_in_curated']['passed']}/{results['expected_in_curated']['total']}",
        "",
        "| 做法 | 說明 | R@5 | R@12 | MRR |",
        "| --- | --- | --- | --- | --- |",
    ]
    for variant, metric in results["metrics"].items():
        lines.append(
            f"| {variant} | {metric['description']} | "
            f"{metric['recall_at_5']['rate']:.2f} | {metric['recall_at_12']['rate']:.2f} | {metric['mrr']:.3f} |"
        )
    for method, reason in results.get("skipped_methods", {}).items():
        lines.extend(("", f"- {method}: {reason}"))
    misses = [row for row in results["cases"] if not row["ranks"]["full_curated"]]
    if misses:
        lines += ["", "## 目前做法未找到的案例", "", "| 案例 | 風險主題 | 標準答案 | 在精選內 |", "| --- | --- | --- | --- |"]
        for row in misses:
            lines.append(
                f"| {row['case_id']} | {row['risk_theme']} | {'、'.join(row['expected'])} | "
                f"{'是' if row['expected_in_curated'] else '否'} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testpack", type=Path, default=ROOT / "tw_contract_review_testpack_v1.zip")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()

    results = evaluate_retrieval(load_cases(args.testpack))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "retrieval_evaluation.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = to_markdown(results)
    (args.out_dir / "retrieval_evaluation.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
