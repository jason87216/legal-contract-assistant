"""LLM provider interface for future report generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import quote
from urllib.error import URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from .contract_review import ReviewContext
    from .statute_tools import StatuteRetrievalTool


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


REPORT_SYSTEM_PROMPT += """

工具查詢規則：
1. 不得直接寫「無直接相關法條」或同義句。
2. 若 related_articles 或 candidate_articles 沒有足夠對應某個風險，必須先使用法條查詢工具補查。
3. 工具查詢仍未命中時，只能寫「本地快取與工具查詢未命中精確法條，需人工補查」，不得宣稱沒有相關法條。
4. 每個風險的引用法條只能來自 related_articles、candidate_articles 或工具查詢結果。
"""


@dataclass(frozen=True)
class ModelConfig:
    """Model settings recorded in the review context without calling an API."""

    provider: str = "noop"
    model: str = "rule-based-report-writer"
    temperature: float = 0.0
    max_output_tokens: int = 8192
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
        self.last_stop_reason: str | None = None
        self.last_generation_warning: str | None = None

    def generate_report(self, context: "ReviewContext") -> str:
        contract_intro = _contract_intro(context)
        detailed_suggestions = _detailed_suggestions(context)
        perspective_section = _perspective_section(context)
        laws = "\n".join(
            f"- {article.citation}: {article.source_url}"
            for article in context.related_articles
        )
        if not laws:
            laws = "- 本地快取與工具查詢未命中精確法條，需人工補查。"

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
- 審查立場：{context.review_perspective_label}
- 整體風險等級：{context.risk_level}
- 審查信心：{context.confidence}
- 審查方式：本地 SQLite 法條快取 + 規則式初步判斷
- 模型設定：{context.model_config.label}（dry-run，不呼叫外部 API）

## 二、相關法條
{laws}

## 三、合約簡介
{contract_intro}

## 四、可能缺漏項目
{missing_items}

## 五、初步審查重點
{focus_topics}

## 六、風險等級理由
{risk_reasons}

## 七、命中風險主題
{risk_themes}

## 八、逐項修改建議
{detailed_suggestions}

## 九、{_perspective_section_title(context)}
{perspective_section}

## 十、需人工確認事項
- 本報告尚未接入正式 LLM、官方模板、行政函釋或判決資料。
- 法條已附來源 URL，正式使用前仍應回官方頁面核對最新版本。
- 若條款涉及金額、日期、解除條件、違約金或消費者定型化契約，應由人工再次確認。

## 十一、免責聲明
本報告僅為合約風險初步檢查，不構成正式法律意見。
"""


def _contract_intro(context: "ReviewContext") -> str:
    return "\n".join(
        [
            f"- 合約模式：{context.contract_type_label}",
            "- 可能目的：依使用者貼上的文字初步判斷，仍需人工確認實際交易目的。",
            "- 主要義務：請核對甲乙方給付、付款、履行期限、終止與違約責任是否完整。",
            "- 付款/期間/終止：若合約文字未明確約定，報告中應標示「合約未明確約定」。",
        ]
    )


def _detailed_suggestions(context: "ReviewContext") -> str:
    themes = context.risk_themes or ("需人工確認",)
    suggestions = []
    for index, theme in enumerate(themes, start=1):
        citation = (
            context.related_articles[index - 1].citation
            if index - 1 < len(context.related_articles)
            else "本地快取與工具查詢未命中精確法條，需人工補查"
        )
        suggestions.append(
            "\n".join(
                [
                    f"{index}. 問題：{theme}",
                    "   - 合約狀態：需人工確認",
                    f"   - 相關法條：{citation}",
                    "   - 修改方向：補明確義務、期限、通知方式、違約效果與例外條件，避免單方解釋。",
                ]
            )
        )
    return "\n".join(suggestions)


def _perspective_section_title(context: "ReviewContext") -> str:
    if context.review_perspective == "party_a":
        return "甲方明確修改範例"
    if context.review_perspective == "party_b":
        return "乙方維護權益建議"
    return "中立修改建議"


def _perspective_section(context: "ReviewContext") -> str:
    if context.review_perspective == "party_a":
        return "\n".join(
            [
                "- 建議條款範例：乙方如未依約履行，甲方得以書面通知限期改善；逾期未改善者，甲方得解除或終止契約，並請求因此所生之合理損害。",
                "- 建議條款範例：雙方應明定驗收、通知、付款與違約金計算方式，避免僅以概括文字約定。",
                "- 注意：違約金、免責與單方終止條款仍需符合誠信原則與相關強制規定。",
            ]
        )
    if context.review_perspective == "party_b":
        return "\n".join(
            [
                "- 談判重點：要求甲方明確列出給付內容、履行期限、費用負擔、終止條件與通知方式。",
                "- 補充條款：保留合理改善期間、異議通知期間、證據保存方式與不可歸責事由。",
                "- 應拒絕條款：過度概括授權、無上限賠償、單方任意終止、排除全部責任或放棄法定權利。",
            ]
        )
    return "\n".join(
        [
            "- 建議雙方補明確付款、履行期限、終止條件、違約效果與爭議處理方式。",
            "- 對金額、日期、通知方式與例外條件應以可驗證文字寫入合約。",
            "- 若任一方權利義務明顯失衡，應重新協商並由人工確認合法性。",
        ]
    )


class OpenAICompatibleLLMProvider:
    """Calls an OpenAI-compatible chat completions API such as llama.cpp server."""

    def __init__(
        self,
        model_config: ModelConfig,
        api_key: str = "sk-no-key-required",
        tool_runner: "StatuteRetrievalTool | None" = None,
    ) -> None:
        if not model_config.base_url:
            raise ValueError("OpenAICompatibleLLMProvider requires model_config.base_url")
        self.model_config = model_config
        self.api_key = api_key
        self.tool_runner = tool_runner
        self.last_stop_reason: str | None = None
        self.last_generation_warning: str | None = None
        self.last_tool_call_count = 0

    def generate_report(self, context: "ReviewContext") -> str:
        if self.tool_runner is not None:
            return self._generate_report_with_tools(context)

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
        payload = _post_json(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            body=body,
        )
        choice = payload["choices"][0]
        content = choice["message"]["content"]
        self.last_stop_reason = choice.get("finish_reason")
        self.last_generation_warning = _generation_warning(
            provider="OpenAI-compatible",
            stop_reason=self.last_stop_reason,
            normal_reasons={"stop", None},
        )
        return _append_generation_warning(content, self.last_generation_warning)

    def _generate_report_with_tools(self, context: "ReviewContext") -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": context.prompt},
            {"role": "user", "content": _build_user_prompt(context)},
        ]
        initial_tool_result = _required_statute_tool_search(self.tool_runner, context)
        self.last_tool_call_count += 1
        messages.append(
            {
                "role": "user",
                "content": _format_required_tool_result(initial_tool_result),
            }
        )
        tools = _openai_tool_definitions()
        url = f"{self.model_config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        final_content = ""
        for _ in range(2):
            payload = _post_json(
                url,
                headers=headers,
                body={
                    "model": self.model_config.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": self.model_config.temperature,
                    "max_tokens": self.model_config.max_output_tokens,
                },
            )
            choice = payload["choices"][0]
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls") or []
            self.last_stop_reason = choice.get("finish_reason")
            if not tool_calls:
                final_content = message.get("content", "") or ""
                break

            messages.append(message)
            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                name = function.get("name", "")
                arguments = _loads_json_object(function.get("arguments", "{}"))
                result = self.tool_runner.call_tool_json(name, arguments)
                self.last_tool_call_count += 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": result,
                    }
                )

        if not final_content:
            raise RuntimeError("Model did not return a final report after tool calls.")

        self.last_generation_warning = _generation_warning(
            provider="OpenAI-compatible",
            stop_reason=self.last_stop_reason,
            normal_reasons={"stop", None},
        )
        return _append_generation_warning(final_content, self.last_generation_warning)


class AnthropicLLMProvider:
    """Calls Anthropic's Messages API."""

    def __init__(
        self,
        model_config: ModelConfig,
        api_key: str,
        tool_runner: "StatuteRetrievalTool | None" = None,
    ) -> None:
        self.model_config = model_config
        self.api_key = api_key
        self.tool_runner = tool_runner
        self.last_stop_reason: str | None = None
        self.last_generation_warning: str | None = None
        self.last_tool_call_count = 0

    def generate_report(self, context: "ReviewContext") -> str:
        if self.tool_runner is not None:
            return self._generate_report_with_tools(context)

        url = f"{(self.model_config.base_url or 'https://api.anthropic.com').rstrip('/')}/v1/messages"
        body = {
            "model": self.model_config.model,
            "max_tokens": self.model_config.max_output_tokens,
            "temperature": self.model_config.temperature,
            "system": context.prompt,
            "messages": [
                {"role": "user", "content": _build_user_prompt(context)},
            ],
        }
        payload = _post_json(
            url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            body=body,
        )
        content = payload.get("content", [])
        text_parts = [
            item.get("text", "")
            for item in content
            if item.get("type") == "text" and item.get("text")
        ]
        text = "\n".join(text_parts).strip()
        self.last_stop_reason = payload.get("stop_reason")
        self.last_generation_warning = _generation_warning(
            provider="Anthropic",
            stop_reason=self.last_stop_reason,
            normal_reasons={"end_turn", "stop_sequence", None},
        )
        return _append_generation_warning(text, self.last_generation_warning)

    def _generate_report_with_tools(self, context: "ReviewContext") -> str:
        url = f"{(self.model_config.base_url or 'https://api.anthropic.com').rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": _build_user_prompt(context)},
        ]
        initial_tool_result = _required_statute_tool_search(self.tool_runner, context)
        self.last_tool_call_count += 1
        messages.append(
            {
                "role": "user",
                "content": _format_required_tool_result(initial_tool_result),
            }
        )
        final_text = ""
        for _ in range(2):
            payload = _post_json(
                url,
                headers=headers,
                body={
                    "model": self.model_config.model,
                    "max_tokens": self.model_config.max_output_tokens,
                    "temperature": self.model_config.temperature,
                    "system": context.prompt,
                    "tools": _anthropic_tool_definitions(),
                    "messages": messages,
                },
            )
            self.last_stop_reason = payload.get("stop_reason")
            content = payload.get("content", [])
            tool_uses = [item for item in content if item.get("type") == "tool_use"]
            if not tool_uses:
                final_text = "\n".join(
                    item.get("text", "")
                    for item in content
                    if item.get("type") == "text" and item.get("text")
                ).strip()
                break

            messages.append({"role": "assistant", "content": content})
            tool_results = []
            for tool_use in tool_uses:
                result = self.tool_runner.call_tool(
                    tool_use.get("name", ""),
                    tool_use.get("input", {}) or {},
                )
                self.last_tool_call_count += 1
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.get("id"),
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        if not final_text:
            raise RuntimeError("Model did not return a final report after tool calls.")

        self.last_generation_warning = _generation_warning(
            provider="Anthropic",
            stop_reason=self.last_stop_reason,
            normal_reasons={"end_turn", "stop_sequence", None},
        )
        return _append_generation_warning(final_text, self.last_generation_warning)


class GeminiLLMProvider:
    """Calls Google Gemini's generateContent API."""

    def __init__(
        self,
        model_config: ModelConfig,
        api_key: str,
        tool_runner: "StatuteRetrievalTool | None" = None,
    ) -> None:
        self.model_config = model_config
        self.api_key = api_key
        self.tool_runner = tool_runner
        self.last_stop_reason: str | None = None
        self.last_generation_warning: str | None = None
        self.last_tool_call_count = 0

    def generate_report(self, context: "ReviewContext") -> str:
        if self.tool_runner is not None:
            return self._generate_report_with_tools(context)

        base_url = (
            self.model_config.base_url
            or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        model = quote(self.model_config.model, safe="")
        url = f"{base_url}/models/{model}:generateContent?key={quote(self.api_key, safe='')}"
        body = {
            "systemInstruction": {
                "parts": [{"text": context.prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": _build_user_prompt(context)}],
                }
            ],
            "generationConfig": {
                "temperature": self.model_config.temperature,
                "maxOutputTokens": self.model_config.max_output_tokens,
            },
        }
        payload = _post_json(
            url,
            headers={"Content-Type": "application/json"},
            body=body,
        )
        candidates = payload.get("candidates", [])
        if not candidates:
            self.last_stop_reason = "no_candidates"
            self.last_generation_warning = _generation_warning(
                provider="Gemini",
                stop_reason=self.last_stop_reason,
                normal_reasons={"STOP", None},
            )
            return _append_generation_warning("", self.last_generation_warning)
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
        self.last_stop_reason = candidate.get("finishReason")
        self.last_generation_warning = _generation_warning(
            provider="Gemini",
            stop_reason=self.last_stop_reason,
            normal_reasons={"STOP", None},
        )
        return _append_generation_warning(text, self.last_generation_warning)

    def _generate_report_with_tools(self, context: "ReviewContext") -> str:
        base_url = (
            self.model_config.base_url
            or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        model = quote(self.model_config.model, safe="")
        url = f"{base_url}/models/{model}:generateContent?key={quote(self.api_key, safe='')}"
        headers = {"Content-Type": "application/json"}
        contents: list[dict[str, Any]] = [
            {
                "role": "user",
                "parts": [{"text": _build_user_prompt(context)}],
            }
        ]
        initial_tool_result = _required_statute_tool_search(self.tool_runner, context)
        self.last_tool_call_count += 1
        contents.append(
            {
                "role": "user",
                "parts": [{"text": _format_required_tool_result(initial_tool_result)}],
            }
        )
        final_text = ""
        for _ in range(2):
            payload = _post_json(
                url,
                headers=headers,
                body={
                    "systemInstruction": {"parts": [{"text": context.prompt}]},
                    "contents": contents,
                    "tools": [{"functionDeclarations": _gemini_tool_declarations()}],
                    "generationConfig": {
                        "temperature": self.model_config.temperature,
                        "maxOutputTokens": self.model_config.max_output_tokens,
                    },
                },
            )
            candidates = payload.get("candidates", [])
            if not candidates:
                self.last_stop_reason = "no_candidates"
                break
            candidate = candidates[0]
            self.last_stop_reason = candidate.get("finishReason")
            parts = candidate.get("content", {}).get("parts", [])
            function_calls = [part["functionCall"] for part in parts if "functionCall" in part]
            if not function_calls:
                final_text = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
                break

            contents.append({"role": "model", "parts": parts})
            response_parts = []
            for function_call in function_calls:
                result = self.tool_runner.call_tool(
                    function_call.get("name", ""),
                    function_call.get("args", {}) or {},
                )
                self.last_tool_call_count += 1
                response_parts.append(
                    {
                        "functionResponse": {
                            "name": function_call.get("name", ""),
                            "response": result,
                        }
                    }
                )
            contents.append({"role": "user", "parts": response_parts})

        if not final_text:
            raise RuntimeError("Model did not return a final report after tool calls.")

        self.last_generation_warning = _generation_warning(
            provider="Gemini",
            stop_reason=self.last_stop_reason,
            normal_reasons={"STOP", None},
        )
        return _append_generation_warning(final_text, self.last_generation_warning)


def _build_user_prompt(context: "ReviewContext") -> str:
    laws = "\n".join(
        f"- {article.citation}: {article.text}\n  Source: {article.source_url}"
        for article in context.related_articles
    )
    candidate_articles = "\n".join(
        f"- {item.get('citation')}: {item.get('match_reason')} | {item.get('source_url')}"
        for item in getattr(context, "candidate_articles", ())
    )
    keywords = ", ".join(getattr(context, "extracted_keywords", ()))
    review_perspective = getattr(context, "review_perspective", "neutral")
    review_perspective_label = getattr(
        context,
        "review_perspective_label",
        review_perspective,
    )
    missing_items = "\n".join(f"- {item}" for item in context.missing_items)
    focus_topics = "\n".join(f"- {topic}" for topic in context.focus_topics)
    risk_reasons = "\n".join(f"- {reason}" for reason in context.risk_reasons)
    risk_themes = "\n".join(f"- {theme}" for theme in context.risk_themes)

    return f"""請根據以下結構化資料產生 Markdown 合約審查報告。

強制規則：
- 不得推翻結構化資料中已抽出的事實；例如結構化資料或合約文字已列出期限時，不得改稱未定期限。
- 每個風險都要標示狀態：「合約已明確約定」、「合約未約定」或「需人工確認」。
- 法條只能使用下方 related_articles、candidate_articles 或工具查詢結果；不得自由補充未提供的法條、判決或函釋。
- 若工具查詢仍未命中精確法條，只能寫「本地快取與工具查詢未命中精確法條，需人工補查」，不得宣稱沒有相關法條。

合約類型：{context.contract_type_label}
審查立場：{review_perspective_label} ({review_perspective})
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
candidate_articles:
{candidate_articles or "- none"}

extracted_keywords:
{keywords or "none"}

{context.contract_text}

請固定包含：
1. 合約簡介：說明合約模式、可能目的、主要義務、付款/期間/終止等可從文字看出的重點；無法判斷時寫「合約未明確約定」。
2. 相關法條與來源 URL。
3. 可能缺漏項目。
4. 初步風險判斷：每個風險標示「合約已明確約定」、「合約未約定」或「需人工確認」。
5. 逐項修改建議：每項包含問題、合約狀態、相關法條、修改方向。
6. 甲方明確修改範例或乙方維護權益建議：若審查立場為 party_a，提供可貼入合約的甲方條款草稿；若為 party_b，提供談判重點、補充條款、證據保存與應拒絕條款；若為 neutral，提供雙方平衡建議。
7. 需人工確認事項。
8. 免責聲明。
"""


def _tool_parameter_schema() -> dict[str, dict[str, Any]]:
    return {
        "lookup_article": {
            "type": "object",
            "properties": {
                "law_name": {"type": "string"},
                "article_no": {"type": "string"},
            },
            "required": ["law_name", "article_no"],
            "additionalProperties": False,
        },
        "search_statutes": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "contract_mode": {
                    "type": "string",
                    "enum": ["sale", "labor", "lease", "unknown"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "retrieve_candidate_articles": {
            "type": "object",
            "properties": {
                "contract_text": {"type": "string"},
                "contract_mode": {
                    "type": "string",
                    "enum": ["sale", "labor", "lease", "unknown"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            },
            "required": ["contract_text"],
            "additionalProperties": False,
        },
    }


def _tool_descriptions() -> dict[str, str]:
    return {
        "lookup_article": "Look up one cached Taiwan statute article by law name and article number.",
        "search_statutes": "Search cached Taiwan statute articles by query text and optional contract mode.",
        "retrieve_candidate_articles": "Extract keywords from a contract and retrieve candidate statute articles.",
    }


def _openai_tool_definitions() -> list[dict[str, Any]]:
    schemas = _tool_parameter_schema()
    descriptions = _tool_descriptions()
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": descriptions[name],
                "parameters": schema,
            },
        }
        for name, schema in schemas.items()
    ]


def _anthropic_tool_definitions() -> list[dict[str, Any]]:
    schemas = _tool_parameter_schema()
    descriptions = _tool_descriptions()
    return [
        {
            "name": name,
            "description": descriptions[name],
            "input_schema": schema,
        }
        for name, schema in schemas.items()
    ]


def _gemini_tool_declarations() -> list[dict[str, Any]]:
    schemas = _tool_parameter_schema()
    descriptions = _tool_descriptions()
    declarations = []
    for name, schema in schemas.items():
        gemini_schema = {
            key: value
            for key, value in schema.items()
            if key != "additionalProperties"
        }
        declarations.append(
            {
                "name": name,
                "description": descriptions[name],
                "parameters": gemini_schema,
            }
        )
    return declarations


def _required_statute_tool_search(
    tool_runner: "StatuteRetrievalTool",
    context: "ReviewContext",
) -> dict[str, Any]:
    query_parts = [
        *getattr(context, "extracted_keywords", ()),
        *getattr(context, "risk_themes", ()),
        *getattr(context, "focus_topics", ()),
    ]
    query = " ".join(str(part) for part in query_parts if str(part).strip())
    if not query:
        query = context.contract_text[:500]
    contract_mode = getattr(context, "contract_mode", None)
    arguments = {
        "query": query,
        "contract_mode": contract_mode if contract_mode != "unknown" else None,
        "limit": 12,
    }
    return {
        "required": True,
        "tool": "search_statutes",
        "arguments": arguments,
        "result": tool_runner.call_tool("search_statutes", arguments),
        "instruction": (
            "If this result does not contain an exact statute for a risk, write "
            "'本地快取與工具查詢未命中精確法條，需人工補查' instead of '無直接相關法條'."
        ),
    }


def _format_required_tool_result(result: dict[str, Any]) -> str:
    return (
        "Required statute tool query result. Use these statutes before claiming a "
        "citation is unavailable:\n"
        f"{json.dumps(result, ensure_ascii=False)}"
    )


def _loads_json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _post_json(url: str, headers: dict[str, str], body: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Model API is unavailable at {url}.") from exc


def _generation_warning(
    *,
    provider: str,
    stop_reason: str | None,
    normal_reasons: set[str | None],
) -> str | None:
    if stop_reason in normal_reasons:
        return None

    return (
        f"生成狀態：{provider} 回傳 `{stop_reason}`。"
        "報告可能未完整生成；請提高最大輸出 tokens，或縮短合約文字後重試。"
    )


def _append_generation_warning(text: str, warning: str | None) -> str:
    if not warning:
        return text
    return f"{text}\n\n> {warning}" if text else f"> {warning}"
    return f"{text}{warning}" if text else warning.strip()
