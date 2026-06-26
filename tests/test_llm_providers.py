from src.legal_contract_assistant.contract_review import ContractReviewService
from src.legal_contract_assistant.llm import AnthropicLLMProvider
from src.legal_contract_assistant.llm import GeminiLLMProvider
from src.legal_contract_assistant.llm import ModelConfig
from src.legal_contract_assistant.llm import OpenAICompatibleLLMProvider


class FakeToolRunner:
    def __init__(self) -> None:
        self.calls = []

    def call_tool_json(self, name, arguments):  # noqa: ANN001
        self.calls.append((name, arguments))
        return '{"articles":[{"citation":"民法 第421條","source_url":"https://law.moj.gov.tw/"}]}'

    def call_tool(self, name, arguments):  # noqa: ANN001
        self.calls.append((name, arguments))
        return {"articles": [{"citation": "民法 第421條", "source_url": "https://law.moj.gov.tw/"}]}


def _context():
    service = ContractReviewService()
    service.initialize()
    return service.build_context(
        "甲方為出租人，乙方為承租人。乙方每月支付租金，房屋修繕由雙方約定。",
        contract_type="lease",
    )


def test_anthropic_provider_posts_messages_payload(monkeypatch) -> None:
    captured = {}

    def fake_post_json(url, headers, body):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return {"content": [{"type": "text", "text": "anthropic report"}]}

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)

    provider = AnthropicLLMProvider(
        ModelConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-latest",
            base_url="https://api.anthropic.com",
        ),
        api_key="test-key",
    )

    report = provider.generate_report(_context())

    assert report == "anthropic report"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["model"] == "claude-3-5-sonnet-latest"
    assert captured["body"]["max_tokens"] == 8192
    assert captured["body"]["messages"][0]["role"] == "user"


def test_gemini_provider_posts_generate_content_payload(monkeypatch) -> None:
    captured = {}

    def fake_post_json(url, headers, body):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return {
            "candidates": [
                {"content": {"parts": [{"text": "gemini report"}]}}
            ]
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)

    provider = GeminiLLMProvider(
        ModelConfig(
            provider="gemini",
            model="gemini-2.5-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        ),
        api_key="test-key",
    )

    report = provider.generate_report(_context())

    assert report == "gemini report"
    assert captured["url"].startswith(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert "key=test-key" in captured["url"]
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 8192
    assert captured["body"]["contents"][0]["role"] == "user"
    assert captured["body"]["systemInstruction"]["parts"][0]["text"]


def test_openai_compatible_provider_warns_when_output_is_truncated(monkeypatch) -> None:
    def fake_post_json(url, headers, body):  # noqa: ANN001
        return {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "partial openai-compatible report"},
                }
            ]
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)

    provider = OpenAICompatibleLLMProvider(
        ModelConfig(
            provider="openrouter",
            model="openai/gpt-test",
            base_url="https://openrouter.ai/api/v1",
        ),
        api_key="test-key",
    )

    report = provider.generate_report(_context())

    assert "partial openai-compatible report" in report
    assert "length" in report
    assert "報告可能未完整生成" in report


def test_anthropic_provider_warns_when_output_is_truncated(monkeypatch) -> None:
    def fake_post_json(url, headers, body):  # noqa: ANN001
        return {
            "content": [{"type": "text", "text": "partial anthropic report"}],
            "stop_reason": "max_tokens",
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)

    provider = AnthropicLLMProvider(
        ModelConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-latest",
            base_url="https://api.anthropic.com",
        ),
        api_key="test-key",
    )

    report = provider.generate_report(_context())

    assert "partial anthropic report" in report
    assert "max_tokens" in report
    assert "報告可能未完整生成" in report


def test_gemini_provider_warns_when_output_is_truncated(monkeypatch) -> None:
    def fake_post_json(url, headers, body):  # noqa: ANN001
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": "partial gemini report"}]},
                    "finishReason": "MAX_TOKENS",
                }
            ]
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)

    provider = GeminiLLMProvider(
        ModelConfig(
            provider="gemini",
            model="gemini-2.5-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        ),
        api_key="test-key",
    )

    report = provider.generate_report(_context())

    assert "partial gemini report" in report
    assert "MAX_TOKENS" in report
    assert "報告可能未完整生成" in report


def test_openai_compatible_provider_handles_native_tool_calling(monkeypatch) -> None:
    calls = []

    def fake_post_json(url, headers, body):  # noqa: ANN001
        calls.append(body)
        if len(calls) == 1:
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_statutes",
                                        "arguments": '{"query":"repair","contract_mode":"lease"}',
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "final report with tools"},
                }
            ]
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)
    tool_runner = FakeToolRunner()
    provider = OpenAICompatibleLLMProvider(
        ModelConfig(provider="openai", model="gpt-test", base_url="https://api.openai.com/v1"),
        api_key="test-key",
        tool_runner=tool_runner,
    )

    report = provider.generate_report(_context())

    assert report == "final report with tools"
    assert calls[0]["tools"]
    assert calls[1]["messages"][-1]["role"] == "tool"
    assert tool_runner.calls[-1] == ("search_statutes", {"query": "repair", "contract_mode": "lease"})
    assert provider.last_tool_call_count == 2


def test_anthropic_provider_handles_native_tool_calling(monkeypatch) -> None:
    calls = []

    def fake_post_json(url, headers, body):  # noqa: ANN001
        calls.append(body)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "search_statutes",
                        "input": {"query": "repair", "contract_mode": "lease"},
                    }
                ],
            }
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "anthropic final report"}],
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)
    tool_runner = FakeToolRunner()
    provider = AnthropicLLMProvider(
        ModelConfig(provider="anthropic", model="claude-test", base_url="https://api.anthropic.com"),
        api_key="test-key",
        tool_runner=tool_runner,
    )

    report = provider.generate_report(_context())

    assert report == "anthropic final report"
    assert calls[0]["tools"]
    assert calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert tool_runner.calls[-1] == ("search_statutes", {"query": "repair", "contract_mode": "lease"})
    assert provider.last_tool_call_count == 2


def test_gemini_provider_handles_native_tool_calling(monkeypatch) -> None:
    calls = []

    def fake_post_json(url, headers, body):  # noqa: ANN001
        calls.append(body)
        if len(calls) == 1:
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "search_statutes",
                                        "args": {"query": "repair", "contract_mode": "lease"},
                                    }
                                }
                            ]
                        },
                    }
                ]
            }
        return {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": "gemini final report"}]},
                }
            ]
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)
    tool_runner = FakeToolRunner()
    provider = GeminiLLMProvider(
        ModelConfig(provider="gemini", model="gemini-test", base_url="https://example.test/v1beta"),
        api_key="test-key",
        tool_runner=tool_runner,
    )

    report = provider.generate_report(_context())

    assert report == "gemini final report"
    assert calls[0]["tools"][0]["functionDeclarations"]
    assert "functionResponse" in calls[1]["contents"][-1]["parts"][0]
    assert tool_runner.calls[-1] == ("search_statutes", {"query": "repair", "contract_mode": "lease"})
    assert provider.last_tool_call_count == 2


def test_gemini_provider_runs_required_statute_search_even_without_model_tool_call(monkeypatch) -> None:
    def fake_post_json(url, headers, body):  # noqa: ANN001
        return {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": "gemini final report without function call"}]},
                }
            ]
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)
    tool_runner = FakeToolRunner()
    provider = GeminiLLMProvider(
        ModelConfig(provider="gemini", model="gemini-test", base_url="https://example.test/v1beta"),
        api_key="test-key",
        tool_runner=tool_runner,
    )

    report = provider.generate_report(_context())

    assert report == "gemini final report without function call"
    assert tool_runner.calls[0][0] == "search_statutes"
    assert provider.last_tool_call_count == 1
