"""Check the generated cases (eval/generated_cases) against the rules.

    python -m scripts.evaluate_generated [--out reports/generated_cases.md]

Per contract type: clean contracts that trigger a rule, risk cases whose
target rule does not fire, near misses that fire their target, and confusable
contracts the classifier gets wrong. Labels are the generator's (Antigravity)
and the rules were tuned on these cases, so this is a regression check, not an
accuracy measure. A failure can be a rule gap or a wrong label, so each one
lists the clause.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.evaluate import ROOT
from src.legal_contract_assistant.contract_review import ContractReviewService, classify_contract_type

CASES_DIR = ROOT / "eval" / "generated_cases"
KINDS = ("clean", "risk", "near_miss", "confusable")
TITLES = {
    "clean": "正常合約誤報",
    "risk": "風險漏抓",
    "near_miss": "相近寫法誤報",
    "confusable": "混淆案例分類錯誤",
    "classifier": "其他案例分類錯誤",
    "format": "格式問題",
}


def load_generated(folder: Path = CASES_DIR) -> tuple[list[dict[str, Any]], list[str]]:
    cases, bad_lines = [], []
    for path in sorted(folder.glob("cases_*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as error:
                bad_lines.append(f"{path.name}:{number} {error}")
    return cases, bad_lines


def evaluate_generated(folder: Path = CASES_DIR, service: ContractReviewService | None = None) -> dict[str, Any]:
    if service is None:
        service = ContractReviewService()
        service.initialize()
    cases, bad_lines = load_generated(folder)
    rule_ids = {rule.rule_id for rule in service.statute_lookup.cache.list_review_rules()}

    stats: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    per_rule: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])  # risk ok/total, near ok/total
    problems: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        kind, ctype = case.get("kind"), case.get("contract_type")
        text, target = case.get("contract_text", ""), case.get("target_rule") or ""
        if kind not in KINDS:
            problems["format"].append(f"{case.get('case_id')}：未知 kind {kind}")
            continue
        if target and target not in rule_ids:
            problems["format"].append(f"{case['case_id']}：規則代號 {target} 不存在")
        predicted = classify_contract_type(text)
        context = service.build_context(text, contract_type=ctype)
        fired = {f.rule_id: f.clause_excerpt for f in context.risk_findings}
        if kind == "clean":
            ok = not fired
            detail = "；".join(f"{k}「{v}」" for k, v in fired.items())
        elif kind == "risk":
            ok = target in fired
            per_rule[target][0] += ok
            per_rule[target][1] += 1
            detail = f"目標未命中；命中：{'、'.join(fired) or '無'}"
        elif kind == "near_miss":
            ok = target not in fired
            per_rule[target][2] += ok
            per_rule[target][3] += 1
            detail = f"目標誤報「{fired.get(target, '')}」"
        else:
            ok = predicted == ctype
            detail = f"分類成 {predicted}"
        stats[ctype][kind][0] += ok
        stats[ctype][kind][1] += 1
        if kind != "confusable" and predicted != ctype:
            problems["classifier"].append(f"{case['case_id']}：標 {ctype}，分類成 {predicted}")
        if not ok:
            problems[kind].append(f"{case['case_id']}（{case.get('wording_note', '')}）：{detail}")

    return {
        "cases": len(cases),
        "bad_lines": bad_lines,
        "stats": {ctype: {k: list(v) for k, v in kinds.items()} for ctype, kinds in stats.items()},
        "per_rule": {rule_id: list(v) for rule_id, v in per_rule.items()},
        "problems": {key: list(v) for key, v in problems.items()},
    }


def to_markdown(result: dict[str, Any]) -> str:
    out = [f"# 產生案例檢查（{result['cases']} 筆）", ""]
    out += ["規則曾依這批案例調整，這是回歸檢查，不是準確率。", ""]
    if result["bad_lines"]:
        out += ["## 無法解析的行", ""] + [f"- {line}" for line in result["bad_lines"]] + [""]
    out += ["| 類型 | 正常無誤報 | 風險命中 | 相近不誤報 | 混淆分類正確 |", "| --- | --- | --- | --- | --- |"]
    for ctype, kinds in sorted(result["stats"].items()):
        cell = lambda k: f"{kinds[k][0]}/{kinds[k][1]}" if k in kinds else "—"  # noqa: E731
        out.append(f"| {ctype} | {cell('clean')} | {cell('risk')} | {cell('near_miss')} | {cell('confusable')} |")
    out += ["", "| 規則 | 風險命中 | 相近不誤報 |", "| --- | --- | --- |"]
    for rule_id, (ro, rt, no, nt) in sorted(result["per_rule"].items()):
        out.append(f"| `{rule_id}` | {ro}/{rt} | {no}/{nt} |")
    for key, title in TITLES.items():
        if result["problems"].get(key):
            out += ["", f"## {title}", ""] + [f"- {p}" for p in result["problems"][key]]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default=str(CASES_DIR))
    parser.add_argument("--out", default=str(ROOT / "reports" / "generated_cases.md"))
    args = parser.parse_args()
    markdown = to_markdown(evaluate_generated(Path(args.cases)))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
