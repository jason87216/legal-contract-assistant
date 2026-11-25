"""Evaluate the 90-case labelled Taiwan contract testpack using offline rules.

This deliberately does NOT measure generative-LLM quality. It reports transparent
rule / citation / dry-run report indicators with per-case denominators.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from src.legal_contract_assistant.contract_review import (
    ContractReviewService,
    classify_contract_type,
)
from src.legal_contract_assistant.llm import NoopLLMProvider
from src.legal_contract_assistant.review_rules import DEFAULT_REVIEW_RULES

ROOT = Path(__file__).resolve().parents[1]
TESTPACK_ROOT = "tw_contract_review_testpack_v1"
CONTRACT_TYPES = {"買賣": "sale", "勞動": "labor", "租賃": "lease"}

METRIC_DESCRIPTIONS = {
    "contract_type_accuracy": "分類器與標註類別一致（獨立分類器，非 Web auto 模式）",
    "risk_level_accuracy": "審查上下文風險等級符合標註（只計規則負責判斷的案例）",
    "risk_theme_recall": "預期風險由對應的新規則命中；無風險案例須沒有規則命中",
    "citation_presence": "相關法條列表非空；不代表法律引用正確",
    "citation_relevance": "預期風險主題已定義的法條映射，至少命中一條（代理指標）",
    "manual_review_flag": "dry-run 報告包含人工覆核及免責提醒",
    "report_structure": "dry-run 報告包含必要標題與固定段落",
}
REQUIRED_REPORT_MARKERS = (
    "# 合約審查報告",
    "## 一、合約基本判斷",
    "## 二、相關法條",
    "## 三、合約簡介",
    "## 四、可能缺漏項目",
    "## 五、初步審查重點",
    "## 六、風險等級理由",
    "## 七、命中風險主題",
    "## 八、逐項修改建議",
    "## 十、需人工確認事項",
    "## 十一、免責聲明",
)
NO_HIGH_RISK_THEME = "無明顯高風險；仍應人工複核"
THEME_MAP = json.loads(Path(__file__).with_name("testpack_theme_map.json").read_text(encoding="utf-8"))


def expected_rule_ids(theme: str) -> list[str] | None:
    """New rules covering a testpack theme; None when the rules do not check it.

    The testpack labels use the old rule themes; themes that moved to the LLM
    checklist or were dropped are not measured as rule recall.
    """
    return THEME_MAP["themes"].get(theme)


def rule_citations(rule_ids: list[str]) -> set[tuple[str, str]]:
    wanted = set(rule_ids)
    return {basis for rule in DEFAULT_REVIEW_RULES if rule.rule_id in wanted for basis in rule.legal_basis}


def load_cases(zip_path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(zip_path) as archive:
        payload = archive.read(f"{TESTPACK_ROOT}/test_cases.jsonl").decode("utf-8")
    cases = [json.loads(line) for line in payload.splitlines() if line.strip()]
    if len(cases) != 90:
        raise ValueError(f"Expected 90 cases, found {len(cases)}")
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case_id in evaluation pack")
    return cases


def evaluate_cases(cases: list[dict[str, Any]], service: ContractReviewService | None = None) -> dict[str, Any]:
    service = service or ContractReviewService()
    service.initialize()
    writer = NoopLLMProvider()
    outcomes: list[dict[str, Any]] = []

    for case in cases:
        text = case["contract_text"]
        label_type = CONTRACT_TYPES[case["contract_type"]]
        expected_theme = case["expected_risk_themes"]
        context = service.build_context(text, contract_type=label_type)
        report = writer.generate_report(context)
        actual_citations = {(article.law_name, article.article_no) for article in context.related_articles}
        fired = {finding.rule_id for finding in context.risk_findings}
        no_risk = expected_theme == NO_HIGH_RISK_THEME
        expected_rules = expected_rule_ids(expected_theme)
        rule_checked = no_risk or expected_rules is not None
        # N/A for the "no obvious risk" sentinel and for themes left to the LLM.
        citation_gold = rule_citations(expected_rules) if expected_rules else None
        citation_match = bool(actual_citations & citation_gold) if citation_gold else None
        if no_risk:
            theme_hit: bool | None = not fired
        elif expected_rules is not None:
            theme_hit = bool(fired & set(expected_rules))
        else:
            theme_hit = None

        results: dict[str, bool | None] = {
            "contract_type_accuracy": classify_contract_type(text) == label_type,
            "risk_level_accuracy": (
                context.risk_level == case["expected_risk_level"] if rule_checked else None
            ),
            "risk_theme_recall": theme_hit,
            "citation_presence": bool(context.related_articles),
            "citation_relevance": citation_match,
            "manual_review_flag": (
                "## 十、需人工確認事項" in report and "不構成正式法律意見" in report
            ),
            "report_structure": all(marker in report for marker in REQUIRED_REPORT_MARKERS),
        }
        outcomes.append({
            "case_id": case["case_id"],
            "contract_type": label_type,
            "expected_risk_level": case["expected_risk_level"],
            "actual_risk_level": context.risk_level,
            "expected_theme": expected_theme,
            "actual_themes": list(context.risk_themes),
            "rule_checked": rule_checked,
            "citation_count": len(context.related_articles),
            "checks": results,
        })

    metrics: dict[str, dict[str, Any]] = {}
    for name, description in METRIC_DESCRIPTIONS.items():
        relevant = [row for row in outcomes if row["checks"][name] is not None]
        passed = sum(row["checks"][name] is True for row in relevant)
        metrics[name] = {
            "description": description,
            "passed": passed,
            "total": len(relevant),
            "rate": round(passed / len(relevant), 4) if relevant else None,
            "failed_case_ids": [row["case_id"] for row in relevant if row["checks"][name] is False],
        }
    return {
        "evaluation_mode": "offline_rules_and_dry_run_only",
        "case_count": len(cases),
        "contract_type_counts": dict(Counter(CONTRACT_TYPES[case["contract_type"]] for case in cases)),
        "metrics": metrics,
        "cases": outcomes,
    }


def to_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# 台灣合約審查 90 筆標註案例評估",
        "",
        f"- 案例數：{results['case_count']}",
        "- 評估模式：本機規則 + 法條檢索 + dry-run 報告（**不呼叫 LLM**）",
        "- 注意：本報告不能代表生成模型、真實法律準確率或實際法律意見品質。",
        "",
        "| 指標 | 通過／適用案例 | 比率 | 定義 |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, metric in results["metrics"].items():
        percent = f"{metric['rate'] * 100:.1f}%" if metric["rate"] is not None else "不適用"
        lines.append(
            f"| `{name}` | {metric['passed']}/{metric['total']} | {percent} | {metric['description']} |"
        )
    lines.extend([
        "",
        "## 解讀限制",
        "",
        "- 測試包的標籤沿用舊規則的風險主題；`scripts/testpack_theme_map.json` 記錄每個舊主題由哪些新規則負責。"
        + "改交 LLM 或刪除的主題（" + "、".join(THEME_MAP["_not_rule_checked"]) + "）不計入規則的風險等級與主題命中。",
        "- 每筆案例只有一個預期風險主題，因此 `risk_theme_recall` 是單一標籤命中率，並非完整多標籤召回率。",
        "- `citation_relevance` 僅檢查規則內的法條映射命中，不是由律師人工評分的引用正確率。",
        "- `citation_presence` 只是有無引用；不能推論引用完整、最新或法律上適當。",
        "- `manual_review_flag` 與 `report_structure` 評估固定報告模板的涵蓋情況，不是 AI 文筆品質。",
        "- 這 90 筆資料已被既有規則測試使用；本評估可能與規則設計相互對齊，**不能視為獨立、未見過的測試資料**。未來需另外保留未參與調整的案例。",
        "",
        "## 未通過案例（每項最多列 20 筆）",
        "",
    ])
    for name, metric in results["metrics"].items():
        failures = metric["failed_case_ids"]
        lines.append(f"- `{name}`：{', '.join(failures[:20]) if failures else '無'}" + (" …" if len(failures) > 20 else ""))
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testpack", type=Path, default=ROOT / "tw_contract_review_testpack_v1.zip")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()

    cases = load_cases(args.testpack)
    results = evaluate_cases(cases)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "evaluation.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown = to_markdown(results)
    (args.out_dir / "evaluation.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
