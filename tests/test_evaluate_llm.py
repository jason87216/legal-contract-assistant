"""The LLM evaluation runs end to end with a fake Gemini reply; no API key or network."""

import argparse
import json
from urllib.error import HTTPError

import pytest

from scripts import evaluate_llm as ev
from src.legal_contract_assistant import llm


def test_chinese_numbers() -> None:
    assert ev.chinese_to_int("二百四十七") == 247
    assert ev.chinese_to_int("五百十一") == 511
    assert ev.chinese_to_int("十五") == 15
    assert ev.chinese_to_int("２５２") == 252


def test_citations_resolve_laws_and_skip_contract_clauses() -> None:
    text = (
        "依民法第二百五十二條及第247條之1、勞基法第9-1條規定；同法第15-1條亦同。"
        "合約第五條約定違約金。票據法第123條另有規定。民法§429-1。"
    )
    found = [(c["law_name"] or c["other_law"], c["article_no"]) for c in ev.extract_citations(text)]

    assert found == [
        ("民法", "252"),
        ("民法", "247-1"),
        ("勞動基準法", "9-1"),
        ("勞動基準法", "15-1"),
        ("票據法", "123"),
        ("民法", "429-1"),
    ]


def test_citation_classes() -> None:
    citations = [
        {"law_name": "民法", "other_law": None, "article_no": "429"},
        {"law_name": "民法", "other_law": None, "article_no": "430"},
        {"law_name": "民法", "other_law": None, "article_no": "99999"},
        {"law_name": None, "other_law": "票據法", "article_no": "123"},
    ]
    official = {("民法", "429"), ("民法", "430")}

    counts = ev.classify_citations(citations, {("民法", "429")}, official)

    assert counts == {"provided": 1, "exists_not_provided": 1, "nonexistent": 1, "unknown_law": 1}


def test_finding_coverage_uses_theme_article_or_clause() -> None:
    finding = {"theme": "修繕責任全部轉嫁承租人", "legal_basis": [["民法", "429"]],
               "excerpt": "所有修繕費用均由乙方自行負擔，甲方不負任何責任。"}

    assert ev.finding_covered("……修繕責任全部轉嫁承租人……", finding, set())
    assert ev.finding_covered("見民法第429條", finding, {("民法", "429")})
    assert ev.finding_covered("條款「修繕費用均由乙方自行負擔」顯失公平", finding, set())
    assert not ev.finding_covered("押金過高", finding, set())


def test_throttle_retries_rate_limits() -> None:
    calls = []
    sleeps = []

    def post(url, headers, body):  # noqa: ANN001
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("busy") from HTTPError(url, 429, "Too Many Requests", {}, None)
        return {"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}}

    throttle = ev.Throttle(rpm=60, sleep=sleeps.append, clock=lambda: 0.0)
    payload = throttle.wrap(post)("u", {}, {})

    assert payload["usageMetadata"]["promptTokenCount"] == 10
    assert len(calls) == 2 and throttle.stats.retries == 1
    assert throttle.stats.prompt_tokens == 10 and throttle.stats.output_tokens == 5
    assert any(s >= 15 for s in sleeps)


def _fake_gemini(url, headers, body):  # noqa: ANN001
    text = "## 風險\n修繕責任依民法第429條由出租人負擔；另參考民法第99999條。合約第三條約定租金。"
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
    }


def test_run_and_score_end_to_end(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(llm, "_post_json", _fake_gemini)
    monkeypatch.setenv("LCA_GEMINI_API_KEY", "fake-key")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [
        {"source": "testpack", "case_id": "lease_21", "contract_type": "lease", "expected_risk_level": "高風險"},
        {"source": "generated", "case_id": "loan_clean_1", "contract_type": "loan", "expected_risk_level": "低風險"},
    ]}), encoding="utf-8")
    args = argparse.Namespace(
        model="gemini-test", provider="gemini", runs=2, rpm=60000, temperature=0.0, limit=0,
        cases=str(cases), out_dir=str(tmp_path / "out"), skip_baseline=False, no_tools=False, resume="",
    )

    folder = ev.run(args)
    summary = ev.score(folder)

    assert llm._post_json is _fake_gemini  # the throttle wrapper is removed after the run
    assert len(list((folder / "raw").glob("*.json"))) == 6  # 2 contracts x (2 pipeline + 1 baseline)
    pipeline, baseline = summary["arms"]["pipeline"], summary["arms"]["baseline"]
    assert pipeline["reports"] == 4 and baseline["reports"] == 2
    assert pipeline["citations"]["nonexistent"] == 4 and baseline["citations"]["nonexistent"] == 2
    assert pipeline["tool_calls"] >= 4  # the forced statute search runs before every report
    assert pipeline["prompt_tokens"] > 0
    assert summary["stability"]["citation_jaccard"] == 1.0
    assert "LLM 評測第一階段" in (folder / "summary.md").read_text(encoding="utf-8")

    # A resumed run skips saved replies.
    args.resume = str(folder)
    ev.run(args)
    assert len(list((folder / "raw").glob("*.json"))) == 6


def test_selected_cases_cover_every_type_and_level() -> None:
    cases = ev.load_selected_cases()

    assert len(cases) == 18
    assert {(c["contract_type"], c["expected_risk_level"]) for c in cases} == {
        (t, lv) for t in ("sale", "lease", "labor", "work", "mandate", "loan") for lv in ("低風險", "中風險", "高風險")
    }
    assert all(c["contract_text"] for c in cases)


def test_missing_key_stops_before_calling(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("LCA_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ev, "ROOT", tmp_path)  # no .env here
    args = argparse.Namespace(model="m", provider="gemini", out_dir=str(tmp_path), resume="")
    with pytest.raises(SystemExit):
        ev.run(args)
