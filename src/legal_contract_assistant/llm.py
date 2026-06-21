"""LLM provider interface for future report generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from .contract_review import ReviewContext


REPORT_SYSTEM_PROMPT = """\
你是台灣法制下的合約審查助手，任務是協助使用者初步檢查合約風險。

限制：
1. 不得自稱律師，不得表示輸出構成正式法律意見。
2. 必須以使用者提供的合約內容、內建法條快取與審查流程為依據。
3. 不得憑空捏造法條、判決、主管機關函釋或引用來源。
4. 資料庫未提供依據時，必須標示「需人工確認」。
5. 必須引用使用到的法條或資料來源。
6. 不得推翻結構化資料中已抽出的事實；若合約文字與結構化資料看似衝突，標示「需人工確認」。
7. 每個風險都要區分狀態：「合約已明確約定」、「合約未約定」或「需人工確認」。
8. 法條只能使用輸入中的 related_articles；不得自由補充未提供的法條、判決或函釋。
"""


@dataclass(frozen=True)
class ModelConfig:
    """Model settings recorded in the review context without calling an API."""

    provider: str = "noop"
    model: str = "rule-based-report-writer"
    temperature: float = 0.0
    max_output_tokens: int = 2000
    base_url: str | None = None

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


class LLMProvider(Protocol):
    """Report-generation boundary that can later be backed by a real model."""

    def generate_report(self, context: "ReviewContext") -> str:
        """Generate a Markdown review report from structured context."""


class NoopLLMProvider:
    """Deterministic report writer that does not call any external API."""

    def __init__(self, model_config: ModelConfig | None = None) -> None:
        self.model_config = model_config or ModelConfig()

    def generate_report(self, context: "ReviewContext") -> str:
        laws = "\n".join(
            f"- {article.citation}: {article.source_url}"
            for article in context.related_articles
        )
        if not laws:
            laws = "- 需人工確認：本地法條快取沒有找到直接相關法條。"

        missing_items = "\n".join(f"- {item}" for item in context.missing_items)
        if not missing_items:
            missing_items = "- 暫未以關鍵字發現明顯缺漏；仍需人工逐條確認。"

        focus_topics = "\n".join(f"- {topic}" for topic in context.focus_topics)
        if not focus_topics:
            focus_topics = "- 需人工確認"

        risk_reasons = "\n".join(f"- {reason}" for reason in context.risk_reasons)
        if not risk_reasons:
            risk_reasons = "- 需人工確認"

        risk_themes = "\n".join(f"- {theme}" for theme in context.risk_themes)
        if not risk_themes:
            risk_themes = "- 需人工確認"

        return f"""# 合約審查報告

## 一、合約基本判斷
- 合約類型：{context.contract_type_label}
- 整體風險等級：{context.risk_level}
- 審查信心：{context.confidence}
- 審查方式：本地 SQLite 法條快取 + 規則式初步判斷
- 模型設定：{context.model_config.label}（dry-run，不呼叫外部 API）

## 二、相關法條
{laws}

## 三、可能缺漏項目
{missing_items}

## 四、初步審查重點
{focus_topics}

## 五、風險等級理由
{risk_reasons}

## 六、命中風險主題
{risk_themes}

## 七、需人工確認事項
- 本報告尚未接入正式 LLM、官方模板、行政函釋或判決資料。
- 法條已附來源 URL，正式使用前仍應回官方頁面核對最新版本。
- 若條款涉及金額、日期、解除條件、違約金或消費者定型化契約，應由人工再次確認。

## 八、免責聲明
本報告僅為合約風險初步檢查，不構成正式法律意見。
"""


class OpenAICompatibleLLMProvider:
    """Calls an OpenAI-compatible chat completions API such as llama.cpp server."""

    def __init__(self, model_config: ModelConfig, api_key: str = "sk-no-key-required") -> None:
        if not model_config.base_url:
            raise ValueError("OpenAICompatibleLLMProvider requires model_config.base_url")
        self.model_config = model_config
        self.api_key = api_key

    def generate_report(self, context: "ReviewContext") -> str:
        body = {
            "model": self.model_config.model,
            "messages": [
                {"role": "system", "content": context.prompt},
                {"role": "user", "content": _build_user_prompt(context)},
            ],
            "temperature": self.model_config.temperature,
            "max_tokens": self.model_config.max_output_tokens,
        }
        url = f"{self.model_config.base_url.rstrip('/')}/chat/completions"
        request = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            raise RuntimeError(
                f"Local model API is unavailable at {self.model_config.base_url}. "
                "Start llama.cpp chat server first."
            ) from exc

        return payload["choices"][0]["message"]["content"]


def _build_user_prompt(context: "ReviewContext") -> str:
    laws = "\n".join(
        f"- {article.citation}: {article.text}\n  Source: {article.source_url}"
        for article in context.related_articles
    )
    missing_items = "\n".join(f"- {item}" for item in context.missing_items)
    focus_topics = "\n".join(f"- {topic}" for topic in context.focus_topics)
    risk_reasons = "\n".join(f"- {reason}" for reason in context.risk_reasons)
    risk_themes = "\n".join(f"- {theme}" for theme in context.risk_themes)

    return f"""請根據以下結構化資料產生 Markdown 合約審查報告。

強制規則：
- 不得推翻結構化資料中已抽出的事實；例如結構化資料或合約文字已列出期限時，不得改稱未定期限。
- 每個風險都要標示狀態：「合約已明確約定」、「合約未約定」或「需人工確認」。
- 法條只能使用下方「相關法條」中的 related_articles；不得自由補充未提供的法條、判決或函釋。

合約類型：{context.contract_type_label}
整體風險等級：{context.risk_level}
審查信心：{context.confidence}

相關法條（related_articles）：
{laws or "- 無"}

可能缺漏項目：
{missing_items or "- 無"}

初步審查重點：
{focus_topics or "- 無"}

風險等級理由：
{risk_reasons or "- 無"}

命中風險主題：
{risk_themes or "- 無"}

合約文字：
{context.contract_text}

請固定包含：
1. 合約基本判斷
2. 相關法條與來源 URL
3. 可能缺漏項目
4. 初步風險分析；每個風險必須包含「狀態」
5. 命中風險主題
6. 需人工確認事項
7. 免責聲明
"""
