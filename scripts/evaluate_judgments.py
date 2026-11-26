"""Score the rules on clauses quoted in court judgments (eval/judgment_clauses.jsonl).

    python -m scripts.evaluate_judgments [--out reports/judgment_clauses.md]

Each clause is checked on its own, with the rules of its contract type.
"missing" rules (the risk is a term the contract never states) are left out,
because one clause never contains the rest of the contract; a missing rule
counts only when a label expects it. Clauses whose risk the rules hand to the
LLM (rule_scope "llm"), or that the user chose not to score (rule_scope
"skip"), are listed but not scored.

Metrics:
- risk clauses caught: an expected rule fires;
- normal clauses with a false alarm: any rule fires;
- court articles covered: of the articles the court applied to a caught risk
  clause, the share named in the legal basis of the rules that fired.

The labels are Claude Code's, reviewed by the user on 2026-11-26. After that
review some rules were changed to catch these clauses, so this is a tuning set,
not a held-out test set.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.evaluate import ROOT
from src.legal_contract_assistant.review_rules import load_seed_review_rules, rules_for_contract_type

CLAUSES = ROOT / "eval" / "judgment_clauses.jsonl"


def load_clauses(path: Path = CLAUSES) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fired_rules(clause: dict[str, Any], rules) -> dict[str, Any]:
    """rule_id -> rule for the rules that fire on this clause alone."""
    expected = set(clause["expected_rules"])
    fired = {}
    for rule in rules_for_contract_type(rules, clause["contract_type"]):
        if rule.kind == "missing" and rule.rule_id not in expected:
            continue
        if rule.search(clause["clause"]) is not None:
            fired[rule.rule_id] = rule
    return fired


def evaluate_judgments(path: Path = CLAUSES) -> dict[str, Any]:
    rules = load_seed_review_rules()
    rows = []
    for clause in load_clauses(path):
        fired = fired_rules(clause, rules)
        expected = set(clause["expected_rules"])
        court = {(a["law_name"], a["article_no"]) for a in clause["court_articles"]}
        basis = {pair for rule in fired.values() for pair in rule.legal_basis}
        if clause["rule_scope"] != "rule":
            outcome = "not_scored"
        elif clause["label"] == "risk":
            outcome = "caught" if expected & set(fired) else "missed"
        else:
            outcome = "false_alarm" if fired else "clean"
        rows.append({
            "id": clause["id"],
            "contract_type": clause["contract_type"],
            "label": clause["label"],
            "outcome": outcome,
            "expected": sorted(expected),
            "fired": sorted(fired),
            "court_articles": sorted(court),
            "court_covered": sorted(court & basis),
            "clause": clause["clause"],
            "note": clause.get("note", ""),
        })
    return {"rows": rows, "summary": summarize(rows)}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def count(label, outcome, ctype=None):
        return sum(1 for r in rows if r["label"] == label and r["outcome"] == outcome
                   and (ctype is None or r["contract_type"] == ctype))

    types = sorted({r["contract_type"] for r in rows})
    per_type = {
        t: {
            "risk_caught": count("risk", "caught", t),
            "risk_scored": count("risk", "caught", t) + count("risk", "missed", t),
            "normal_false_alarm": count("normal", "false_alarm", t),
            "normal_scored": count("normal", "false_alarm", t) + count("normal", "clean", t),
        }
        for t in types
    }
    caught = [r for r in rows if r["outcome"] == "caught" and r["court_articles"]]
    court_total = sum(len(r["court_articles"]) for r in caught)
    court_hit = sum(len(r["court_covered"]) for r in caught)
    fired_total = sum(len(r["fired"]) for r in rows if r["outcome"] in ("caught", "missed", "false_alarm", "clean"))
    fired_expected = sum(len(set(r["fired"]) & set(r["expected"])) for r in rows if r["label"] == "risk")
    return {
        "per_type": per_type,
        "risk_caught": sum(v["risk_caught"] for v in per_type.values()),
        "risk_scored": sum(v["risk_scored"] for v in per_type.values()),
        "normal_false_alarm": sum(v["normal_false_alarm"] for v in per_type.values()),
        "normal_scored": sum(v["normal_scored"] for v in per_type.values()),
        "rule_hits": fired_total,
        "rule_hits_expected": fired_expected,
        "court_articles": court_total,
        "court_articles_covered": court_hit,
        "not_scored": sum(1 for r in rows if r["outcome"] == "not_scored"),
    }


def _ratio(a: int, b: int) -> str:
    return f"{a}/{b}（{a / b:.0%}）" if b else "—"


def to_markdown(result: dict[str, Any]) -> str:
    s = result["summary"]
    out = [
        "# 判決條款評測",
        "",
        "判決書引述的條款逐條跑規則。標註由 Claude Code 完成、使用者已審核；審核後依這批條款調整過規則，屬調整集，不是未見過的測試集。",
        "",
        "| 指標 | 結果 |",
        "| --- | --- |",
        f"| 風險條款被抓到（預期規則有觸發） | {_ratio(s['risk_caught'], s['risk_scored'])} |",
        f"| 正常條款誤報（任一規則觸發） | {_ratio(s['normal_false_alarm'], s['normal_scored'])} |",
        f"| 觸發的規則中屬於預期規則 | {_ratio(s['rule_hits_expected'], s['rule_hits'])} |",
        f"| 抓到的風險條款：法院適用條文被規則法條涵蓋 | {_ratio(s['court_articles_covered'], s['court_articles'])} |",
        f"| 不計分（交給 LLM 檢查或使用者決定不計） | {s['not_scored']} 條 |",
        "",
        "| 類型 | 風險抓到 | 正常誤報 |",
        "| --- | --- | --- |",
    ]
    for ctype, v in s["per_type"].items():
        out.append(f"| {ctype} | {_ratio(v['risk_caught'], v['risk_scored'])} | {_ratio(v['normal_false_alarm'], v['normal_scored'])} |")
    labels = {"missed": "漏抓", "false_alarm": "誤報", "caught": "抓到", "clean": "正常", "not_scored": "不計分"}
    out += ["", "## 逐條結果", "", "| 條款 | 標註 | 結果 | 預期規則 | 觸發規則 | 法院條文（規則涵蓋） |", "| --- | --- | --- | --- | --- | --- |"]
    for r in result["rows"]:
        court = "、".join(f"{law}§{no}" + ("✓" if [law, no] in [list(c) for c in r["court_covered"]] else "")
                         for law, no in r["court_articles"]) or "—"
        out.append(
            f"| {r['id']} | {r['label']} | {labels[r['outcome']]} | {'、'.join(r['expected']) or '—'} "
            f"| {'、'.join(r['fired']) or '—'} | {court} |"
        )
    problems = [r for r in result["rows"] if r["outcome"] in ("missed", "false_alarm")]
    if problems:
        out += ["", "## 漏抓與誤報的條款", ""]
        for r in problems:
            note = f"（{r['note']}）" if r["note"] else ""
            out.append(f"- **{r['id']}** {labels[r['outcome']]}{note}：{r['clause']}")
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clauses", default=str(CLAUSES))
    parser.add_argument("--out", default=str(ROOT / "reports" / "judgment_clauses.md"))
    args = parser.parse_args()
    markdown = to_markdown(evaluate_judgments(Path(args.clauses)))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
