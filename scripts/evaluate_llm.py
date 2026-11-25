"""LLM evaluation, phase 1: what the model does with the rule context.

Two arms on the same contracts (eval/llm_cases.json):
- pipeline: the normal flow (rules, statutes, candidate articles, statute tools);
- baseline: the model alone, given only the contract and the same report task.

Every model reply is saved first (run), then scored from the saved files
(score), so scoring can change without calling the model again. Metrics need
no gold labels: citations are checked against the official statute data and
against what the pipeline gave the model; rule findings are the pipeline's own.

    python -m scripts.evaluate_llm run --model gemini-flash-latest
    python -m scripts.evaluate_llm score reports/llm_eval/<run folder>

The API key is read from LCA_GEMINI_API_KEY (environment or .env).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote

from scripts.evaluate import ROOT, load_cases
from src.legal_contract_assistant import llm
from src.legal_contract_assistant.contract_review import MISSING_EXCERPT, ContractReviewService
from src.legal_contract_assistant.llm import GeminiLLMProvider, ModelConfig, NoopLLMProvider
from src.legal_contract_assistant.statute_cache import official_statutes_data
from src.legal_contract_assistant.statute_tools import StatuteRetrievalTool

CASES_FILE = ROOT / "eval" / "llm_cases.json"
GENERATED_DIR = ROOT / "eval" / "generated_cases"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUS = {429, 500, 502, 503, 504}

BASELINE_SYSTEM = "你是熟悉台灣法律的合約審查助手。請以繁體中文撰寫審查報告。"
BASELINE_TASK = """請審查以下合約，產生 Markdown 合約審查報告，內容包含：
1. 合約類型與整體風險等級（高、中、低）；
2. 逐項列出風險條款、風險說明，並引用相關的台灣法條（寫出法規名稱與條號）；
3. 每項風險的修改建議；
4. 需要人工確認的事項。

合約全文：
{contract}
"""

# Common short names models use for imported laws.
LAW_ALIASES = {
    "勞基法": "勞動基準法",
    "消保法": "消費者保護法",
    "民訴法": "民事訴訟法",
    "勞保條例": "勞工保險條例",
    "勞退條例": "勞工退休金條例",
    "就服法": "就業服務法",
    "性平法": "性別平等工作法",
    "租賃條例": "租賃住宅市場發展及管理條例",
    "租賃住宅條例": "租賃住宅市場發展及管理條例",
    "勞基法施行細則": "勞動基準法施行細則",
}
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_NUM = r"[0-9０-９]+|[零〇一二兩三四五六七八九十百千]+"
ARTICLE_RE = re.compile(
    rf"第\s*(?P<main>{_NUM})\s*(?:-\s*(?P<dash>[0-9０-９]+)\s*)?條(?:\s*之\s*(?P<sub>{_NUM}))?"
    rf"|§\s*(?P<smain>[0-9]+)(?:\s*-\s*(?P<ssub>[0-9]+))?"
)


def chinese_to_int(text: str) -> int:
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if text.isdigit():
        return int(text)
    total, digit = 0, 0
    for char in text:
        if char in _CN_DIGITS:
            digit = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            total += (digit or 1) * _CN_UNITS[char]
            digit = 0
    return total + digit


def law_names() -> list[str]:
    """Imported law names plus aliases, longest first so 施行細則 wins over 勞動基準法."""
    names = [law["law_name"] for law in official_statutes_data()["laws"]]
    return sorted(set(names) | set(LAW_ALIASES), key=len, reverse=True)


# Characters allowed between a law name and its article number: part of a
# citation list such as "民法第348條至第351條、第354條第1項".
_CITATION_GAP = re.compile(r"[\s第條之至及與、,，0-9０-９零〇一二兩三四五六七八九十百千\-~～§項款]*")
_OTHER_LAW = re.compile(r"([一-鿿]{2,14}(?:法|條例|細則|辦法|規則|準則))[\s第條之至及與、,，0-9０-９零〇一二兩三四五六七八九十百千\-~～§項款]*$")


def extract_citations(text: str) -> list[dict[str, Any]]:
    """Every "<law> 第 N 條" in the text, with the law resolved from the words before it.

    The law is the closest known law name before the article number, joined to
    it only by citation-list characters ("民法第348條至第351條" gives two 民法
    citations); "同法" or "本法" reuses the previous law. A law-like name that is
    not imported is kept as unknown (law_name=None, other_law=name). Article
    numbers with no law before them, such as contract clauses (第五條), are skipped.
    """
    names = law_names()
    citations: list[dict[str, Any]] = []
    previous_law: str | None = None
    for match in ARTICLE_RE.finditer(text):
        before = text[max(0, match.start() - 30):match.start()]
        law, best = None, -1
        for name in names:
            position = before.rfind(name)
            if position > best and _CITATION_GAP.fullmatch(before[position + len(name):]):
                best, law = position, name
        other_law = None
        if law is None:
            if re.search(r"(同法|本法|同條例|同細則)" + _CITATION_GAP.pattern + "$", before):
                law = previous_law
            elif (generic := _OTHER_LAW.search(before)) is not None:
                other_law = generic.group(1)
            else:
                continue
        law = LAW_ALIASES.get(law, law) if law else None
        if match.group("smain"):
            main, sub = match.group("smain"), match.group("ssub")
        else:
            main, sub = match.group("main"), match.group("dash") or match.group("sub")
        article_no = str(chinese_to_int(main)) + (f"-{chinese_to_int(sub)}" if sub else "")
        citations.append({"law_name": law, "other_law": other_law, "article_no": article_no, "text": match.group(0)})
        if law:
            previous_law = law
    return citations


def official_articles() -> set[tuple[str, str]]:
    return {(law["law_name"], a["article_no"]) for law in official_statutes_data()["laws"] for a in law["articles"]}


def classify_citations(
    citations: list[dict[str, Any]], provided: set[tuple[str, str]], official: set[tuple[str, str]]
) -> dict[str, int]:
    """provided: given to the model (context or tool results); exists: real but not given;
    nonexistent: the law is imported but has no such article; unknown_law: cannot be checked."""
    imported = {law for law, _ in official}
    counts = {"provided": 0, "exists_not_provided": 0, "nonexistent": 0, "unknown_law": 0}
    for citation in {(c["law_name"] or c.get("other_law"), c["article_no"]) for c in citations}:
        law, article_no = citation
        if law is None or law not in imported:
            counts["unknown_law"] += 1
        elif citation in provided:
            counts["provided"] += 1
        elif citation in official:
            counts["exists_not_provided"] += 1
        else:
            counts["nonexistent"] += 1
    return counts


def finding_covered(report: str, finding: dict[str, Any], cited: set[tuple[str, str]]) -> bool:
    """Approximate: the report names the risk theme, cites one of the rule's articles,
    or quotes 8 characters of the triggering clause."""
    if finding["theme"] in report:
        return True
    if cited & {tuple(basis) for basis in finding["legal_basis"]}:
        return True
    def letters(text: str) -> str:
        return re.sub(r"[\W_]", "", text)

    excerpt = letters(finding["excerpt"])
    if finding["excerpt"] == MISSING_EXCERPT or len(excerpt) < 8:
        return False
    flat = letters(report)
    return any(excerpt[i:i + 8] in flat for i in range(0, len(excerpt) - 7, 2))


# ---------------------------------------------------------------- model calls


@dataclass
class CallStats:
    requests: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    retries: int = 0


@dataclass
class Throttle:
    """At most `rpm` HTTP requests per minute, retrying rate limits and server errors."""

    rpm: float
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    last: float = field(default=-1e9)
    stats: CallStats = field(default_factory=CallStats)

    def wrap(self, post: Callable[..., dict]) -> Callable[..., dict]:
        def throttled(url: str, headers: dict[str, str], body: dict) -> dict:
            for attempt in range(6):
                wait = self.last + 60.0 / self.rpm - self.clock()
                if wait > 0:
                    self.sleep(wait)
                self.last = self.clock()
                started = self.clock()
                try:
                    payload = post(url, headers, body)
                except RuntimeError as error:
                    status = getattr(error.__cause__, "code", None)
                    if status in RETRY_STATUS and attempt < 5:
                        self.stats.retries += 1
                        self.sleep(min(120.0, 15.0 * 2**attempt))
                        continue
                    raise
                usage = payload.get("usageMetadata", {})
                self.stats.requests += 1
                self.stats.prompt_tokens += int(usage.get("promptTokenCount", 0))
                self.stats.output_tokens += int(usage.get("candidatesTokenCount", 0))
                self.stats.seconds += self.clock() - started
                return payload
            raise RuntimeError("retries exhausted")

        return throttled


class RecordingTool:
    """Statute tool proxy that records every article the model received from a tool."""

    def __init__(self, tool: StatuteRetrievalTool) -> None:
        self._tool = tool
        self.articles: set[tuple[str, str]] = set()
        self.calls: list[str] = []

    def _record(self, value: Any) -> None:
        if isinstance(value, dict):
            if "law_name" in value and "article_no" in value:
                self.articles.add((str(value["law_name"]), str(value["article_no"])))
            for item in value.values():
                self._record(item)
        elif isinstance(value, list):
            for item in value:
                self._record(item)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(name)
        result = self._tool.call_tool(name, arguments)
        self._record(result)
        return result

    def call_tool_json(self, name: str, arguments: dict[str, Any]) -> str:
        return json.dumps(self.call_tool(name, arguments), ensure_ascii=False)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._tool, name)


def read_api_key() -> str:
    key = os.environ.get("LCA_GEMINI_API_KEY", "")
    env_file = ROOT / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "LCA_GEMINI_API_KEY":
                key = value.strip().strip('"').strip("'")
    return key


def load_selected_cases(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    selection = json.loads(path.read_text(encoding="utf-8"))["cases"]
    testpack = {c["case_id"]: c for c in load_cases(ROOT / "tw_contract_review_testpack_v1.zip")}
    generated = {}
    for file in sorted(GENERATED_DIR.glob("cases_*.jsonl")):
        for line in file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                case = json.loads(line)
                generated[case["case_id"]] = case
    cases = []
    for item in selection:
        source = testpack if item["source"] == "testpack" else generated
        cases.append({**item, "contract_text": source[item["case_id"]]["contract_text"]})
    return cases


def _baseline_report(model: str, api_key: str, contract: str, temperature: float) -> str:
    url = f"{GEMINI_URL}/models/{quote(model, safe='')}:generateContent?key={quote(api_key, safe='')}"
    payload = llm._post_json(
        url,
        headers={"Content-Type": "application/json"},
        body={
            "systemInstruction": {"parts": [{"text": BASELINE_SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": BASELINE_TASK.format(contract=contract)}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 8192},
        },
    )
    parts = (payload.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()


def run(args: argparse.Namespace) -> Path:
    api_key = "" if args.provider == "noop" else read_api_key()
    if args.provider == "gemini" and not api_key:
        raise SystemExit("LCA_GEMINI_API_KEY is not set (environment or .env).")
    out = (
        Path(args.resume)
        if args.resume
        else Path(args.out_dir) / f"{datetime.now():%Y%m%d-%H%M%S}-{args.model.replace('/', '_')}"
    )
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    throttle = Throttle(rpm=args.rpm)
    original_post = llm._post_json
    llm._post_json = throttle.wrap(original_post)  # count tokens and pace every request
    try:
        _run_cases(args, api_key, out, raw_dir, throttle)
    finally:
        llm._post_json = original_post
    return out


def _run_cases(args: argparse.Namespace, api_key: str, out: Path, raw_dir: Path, throttle: Throttle) -> None:
    if args.provider == "noop":
        args.skip_baseline = True  # the baseline needs a real model
    service = ContractReviewService()
    service.initialize()
    cases = load_selected_cases(Path(args.cases))[: args.limit or None]
    config = ModelConfig(provider=args.provider, model=args.model, temperature=args.temperature)
    if not (out / "run.json").exists():
        (out / "run.json").write_text(json.dumps({
            "model": args.model, "provider": args.provider, "runs": args.runs, "temperature": args.temperature,
            "cases": [c["case_id"] for c in cases], "started": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    for case in cases:
        context = service.build_context(case["contract_text"], contract_type=case["contract_type"])
        context = replace(context, model_config=config)
        provided = {(a.law_name, a.article_no) for a in context.related_articles}
        provided |= {(str(a["law_name"]), str(a["article_no"])) for a in context.candidate_articles}
        findings = [
            {
                "rule_id": f.rule_id, "theme": f.theme, "level": f.level, "excerpt": f.clause_excerpt,
                "legal_basis": [[a.law_name, a.article_no] for a in f.articles],
            }
            for f in context.risk_findings
        ]
        arms = [("pipeline", run_no) for run_no in range(1, args.runs + 1)]
        if not args.skip_baseline:
            arms.append(("baseline", 1))
        for arm, run_no in arms:
            path = raw_dir / f"{case['case_id']}__{arm}__{run_no}.json"
            if path.exists():
                continue
            before = CallStats(**vars(throttle.stats))
            tool = RecordingTool(StatuteRetrievalTool(service.statute_lookup))
            record: dict[str, Any] = {
                "case_id": case["case_id"], "contract_type": case["contract_type"],
                "expected_risk_level": case["expected_risk_level"], "arm": arm, "run": run_no,
                "rule_risk_level": context.risk_level, "findings": findings,
            }
            try:
                if arm == "pipeline":
                    provider = (
                        NoopLLMProvider(model_config=config)
                        if args.provider == "noop"
                        else GeminiLLMProvider(config, api_key=api_key, tool_runner=None if args.no_tools else tool)
                    )
                    record["report"] = provider.generate_report(context)
                    record["tool_calls"] = list(tool.calls)
                    record["provided"] = sorted(provided | tool.articles)
                else:
                    record["report"] = _baseline_report(args.model, api_key, case["contract_text"], args.temperature)
                    record["tool_calls"] = []
                    record["provided"] = []
                record["error"] = None
            except Exception as error:  # noqa: BLE001 - record and continue with the next case
                record.update(report="", tool_calls=list(tool.calls), provided=[], error=f"{type(error).__name__}: {error}")
            stats = throttle.stats
            record["usage"] = {
                "requests": stats.requests - before.requests,
                "prompt_tokens": stats.prompt_tokens - before.prompt_tokens,
                "output_tokens": stats.output_tokens - before.output_tokens,
                "seconds": round(stats.seconds - before.seconds, 2),
                "retries": stats.retries - before.retries,
            }
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{case['case_id']} {arm} #{run_no}: {'ERROR ' + record['error'] if record['error'] else 'ok'}")


# ---------------------------------------------------------------- scoring


def _jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def score(folder: Path) -> dict[str, Any]:
    official = official_articles()
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "raw").glob("*.json"))]
    per_arm: dict[str, dict[str, Any]] = {}
    stability: dict[str, list[tuple[float, float]]] = {}
    by_case_runs: dict[str, list[dict[str, Any]]] = {}

    for record in records:
        arm = per_arm.setdefault(record["arm"], {
            "reports": 0, "errors": 0, "citations": {"provided": 0, "exists_not_provided": 0, "nonexistent": 0, "unknown_law": 0},
            "findings": 0, "findings_covered": 0, "tool_calls": 0, "requests": 0, "prompt_tokens": 0,
            "output_tokens": 0, "seconds": 0.0, "nonexistent_examples": [],
        })
        usage = record.get("usage", {})
        for key in ("requests", "prompt_tokens", "output_tokens"):
            arm[key] += usage.get(key, 0)
        arm["seconds"] += usage.get("seconds", 0.0)
        if record.get("error"):
            arm["errors"] += 1
            continue
        arm["reports"] += 1
        citations = extract_citations(record["report"])
        cited = {(c["law_name"], c["article_no"]) for c in citations if c["law_name"]}
        provided = {tuple(p) for p in record["provided"]}
        for key, value in classify_citations(citations, provided, official).items():
            arm["citations"][key] += value
        for law, no in sorted(cited):
            if (law, no) not in official and law in {l for l, _ in official} and len(arm["nonexistent_examples"]) < 10:
                arm["nonexistent_examples"].append(f"{record['case_id']}: {law} 第 {no} 條")
        covered = sum(finding_covered(record["report"], f, cited) for f in record["findings"])
        arm["findings"] += len(record["findings"])
        arm["findings_covered"] += covered
        arm["tool_calls"] += len(record.get("tool_calls", []))
        if record["arm"] == "pipeline":
            by_case_runs.setdefault(record["case_id"], []).append(
                {"cited": cited, "covered": {f["rule_id"] for f in record["findings"] if finding_covered(record["report"], f, cited)}}
            )

    for case_id, runs in by_case_runs.items():
        pairs = list(combinations(runs, 2))
        if pairs:
            stability[case_id] = [
                (_jaccard(a["cited"], b["cited"]), _jaccard(a["covered"], b["covered"])) for a, b in pairs
            ]

    summary: dict[str, Any] = {"folder": str(folder), "arms": {}}
    for name, arm in per_arm.items():
        total = sum(arm["citations"].values())
        rate = lambda n, d: round(n / d, 4) if d else None  # noqa: E731
        summary["arms"][name] = {
            **arm,
            "citation_total": total,
            "nonexistent_rate": rate(arm["citations"]["nonexistent"], total),
            "outside_provided_rate": rate(arm["citations"]["exists_not_provided"], total) if name == "pipeline" else None,
            "unknown_law_rate": rate(arm["citations"]["unknown_law"], total),
            "finding_coverage": rate(arm["findings_covered"], arm["findings"]),
            "tokens_per_report": rate(arm["prompt_tokens"] + arm["output_tokens"], arm["reports"]),
            "seconds_per_report": rate(arm["seconds"], arm["reports"]),
        }
    pairs = [pair for values in stability.values() for pair in values]
    summary["stability"] = {
        "cases": len(stability),
        "citation_jaccard": round(sum(p[0] for p in pairs) / len(pairs), 4) if pairs else None,
        "covered_risk_jaccard": round(sum(p[1] for p in pairs) / len(pairs), 4) if pairs else None,
    }
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "summary.md").write_text(to_markdown(summary), encoding="utf-8")
    return summary


def to_markdown(summary: dict[str, Any]) -> str:
    pct = lambda v: "—" if v is None else f"{v * 100:.1f}%"  # noqa: E731
    lines = [
        "# LLM 評測第一階段", "",
        "pipeline＝規則、法條與工具；baseline＝只給合約全文。指標不需標準答案，見 docs/EVALUATION_PLAN.md。", "",
        "| 指標 | pipeline | baseline |", "| --- | --- | --- |",
    ]
    arms = summary["arms"]
    get = lambda name, key: arms.get(name, {}).get(key)  # noqa: E731
    rows = [
        ("報告數（失敗）", lambda n: f"{get(n, 'reports')}（{get(n, 'errors')}）" if n in arms else "—"),
        ("引用法條數", lambda n: str(get(n, "citation_total")) if n in arms else "—"),
        ("不存在的法條（編造）", lambda n: pct(get(n, "nonexistent_rate"))),
        ("存在但未提供", lambda n: pct(get(n, "outside_provided_rate"))),
        ("法規不在資料庫，無法查核", lambda n: pct(get(n, "unknown_law_rate"))),
        ("規則風險有寫進報告", lambda n: pct(get(n, "finding_coverage"))),
        ("工具呼叫次數", lambda n: str(get(n, "tool_calls")) if n in arms else "—"),
        ("每份 token", lambda n: str(get(n, "tokens_per_report")) if n in arms else "—"),
        ("每份秒數", lambda n: str(get(n, "seconds_per_report")) if n in arms else "—"),
    ]
    for label, cell in rows:
        lines.append(f"| {label} | {cell('pipeline')} | {cell('baseline')} |")
    stability = summary["stability"]
    lines += [
        "", f"穩定性（pipeline 同一合約多次執行的兩兩相似度，{stability['cases']} 份）：",
        f"引用法條 {pct(stability['citation_jaccard'])}，寫進報告的規則風險 {pct(stability['covered_risk_jaccard'])}。",
    ]
    for name in ("pipeline", "baseline"):
        examples = arms.get(name, {}).get("nonexistent_examples") or []
        if examples:
            lines += ["", f"{name} 不存在的法條（最多 10 筆）：", *[f"- {e}" for e in examples]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="call the model and save every reply")
    run_parser.add_argument("--model", default="gemini-flash-latest")
    run_parser.add_argument("--provider", choices=("gemini", "noop"), default="gemini")
    run_parser.add_argument("--runs", type=int, default=3, help="pipeline runs per contract (stability)")
    run_parser.add_argument("--rpm", type=float, default=8.0, help="requests per minute")
    run_parser.add_argument("--temperature", type=float, default=0.2)
    run_parser.add_argument("--limit", type=int, default=0, help="only the first N contracts")
    run_parser.add_argument("--cases", default=str(CASES_FILE))
    run_parser.add_argument("--out-dir", default=str(ROOT / "reports" / "llm_eval"))
    run_parser.add_argument("--skip-baseline", action="store_true")
    run_parser.add_argument("--no-tools", action="store_true", help="pipeline without statute tools")
    run_parser.add_argument("--resume", default="", help="continue a stopped run folder; saved replies are skipped")
    score_parser = sub.add_parser("score", help="score a saved run folder")
    score_parser.add_argument("folder")
    args = parser.parse_args()
    if args.command == "run":
        folder = run(args)
        print(to_markdown(score(folder)))
        print(f"saved: {folder}")
    else:
        print(to_markdown(score(Path(args.folder))))


if __name__ == "__main__":
    main()
