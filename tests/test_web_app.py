from fastapi.testclient import TestClient

from src.legal_contract_assistant import __version__
from src.legal_contract_assistant.web_app import create_app


def test_health_endpoint(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_provider_settings_mask_and_clear_api_key(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.post(
        "/api/settings/provider",
        json={
            "provider": "openai",
            "api_key": "sk-test-123456",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-test",
        },
    )

    assert response.status_code == 200
    provider = response.json()["provider"]
    assert provider["configured"] is True
    assert provider["api_key_mask"] == "***3456"
    assert "sk-test" not in response.text

    response = client.delete("/api/settings/provider/openai")

    assert response.status_code == 200
    provider = response.json()["provider"]
    assert provider["configured"] is False
    assert provider["api_key_mask"] is None


def test_settings_include_native_model_providers(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.get("/api/settings")

    assert response.status_code == 200
    providers = {item["provider"]: item for item in response.json()["providers"]}
    assert "anthropic" in providers
    assert "gemini" in providers
    assert "ollama" in providers
    assert "claude-3-5-sonnet-latest" in providers["anthropic"]["models"]
    assert "gemini-2.5-flash" in providers["gemini"]["models"]
    assert providers["ollama"]["base_url"] == "http://localhost:11434/v1"
    assert "qwen3:8b" in providers["ollama"]["models"]
    assert providers["gemini"]["default_max_output_tokens"] == 8192
    assert providers["gemini"]["long_contract_max_output_tokens"] == 32768


def test_review_endpoint_generates_dry_run_report(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.post(
        "/api/review",
        data={
            "text": "甲方為出租人，乙方為承租人。乙方每月支付租金，房屋修繕由雙方約定。",
            "contract_type": "lease",
            "provider": "openai",
            "model": "gpt-test",
            "use_llm": "false",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract_type"] == "lease"
    assert body["review_perspective"] == "neutral"
    assert "# 合約審查報告" in body["markdown"]
    assert "合約簡介" in body["markdown"]
    assert "逐項修改建議" in body["markdown"]
    assert body["related_articles"]
    assert body["keywords"]
    assert body["candidate_articles"]
    assert any(article["source_url"].startswith("https://law.moj.gov.tw/") for article in body["related_articles"])


def test_review_endpoint_auto_does_not_classify_contract_type(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.post(
        "/api/review",
        data={
            "text": "tenant rent repair maintenance",
            "contract_type": "auto",
            "provider": "noop",
            "use_llm": "false",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract_type"] == "unknown"
    assert body["generation"]["tool_call_count"] == 0


def test_review_endpoint_generates_party_a_clause_examples(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.post(
        "/api/review",
        data={
            "text": "甲方為出租人，乙方為承租人。乙方每月支付租金。",
            "contract_type": "lease",
            "review_perspective": "party_a",
            "provider": "noop",
            "use_llm": "false",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_perspective"] == "party_a"
    assert "甲方明確修改範例" in body["markdown"]
    assert "建議條款範例" in body["markdown"]


def test_review_endpoint_generates_party_b_rights_advice(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.post(
        "/api/review",
        data={
            "text": "甲方為出租人，乙方為承租人。乙方每月支付租金。",
            "contract_type": "lease",
            "review_perspective": "party_b",
            "provider": "noop",
            "use_llm": "false",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_perspective"] == "party_b"
    assert "乙方維護權益建議" in body["markdown"]
    assert "談判重點" in body["markdown"]


def test_review_endpoint_rejects_unsupported_review_perspective(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.post(
        "/api/review",
        data={
            "text": "甲乙雙方約定測試文字。",
            "contract_type": "lease",
            "review_perspective": "party_c",
            "provider": "noop",
            "use_llm": "false",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported review perspective"


def test_review_endpoint_reports_generation_warning_for_long_contract_mode(
    tmp_path,
    monkeypatch,
) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    client.post(
        "/api/settings/provider",
        json={
            "provider": "gemini",
            "api_key": "test-key",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "gemini-2.5-flash",
        },
    )

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

    response = client.post(
        "/api/review",
        data={
            "text": "租賃契約測試文字",
            "contract_type": "lease",
            "provider": "gemini",
            "long_contract": "true",
            "use_llm": "true",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generation"]["used_llm"] is True
    assert body["generation"]["long_contract"] is True
    assert body["generation"]["max_output_tokens"] == 32768
    assert body["generation"]["stop_reason"] == "MAX_TOKENS"
    assert "報告可能未完整生成" in body["generation"]["warning"]


def test_review_endpoint_supports_ollama_without_api_key(tmp_path, monkeypatch) -> None:
    captured = {}

    def fake_post_json(url, headers, body):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "ollama report"},
                }
            ]
        }

    monkeypatch.setattr("src.legal_contract_assistant.llm._post_json", fake_post_json)
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.post(
        "/api/review",
        data={
            "text": "租賃契約測試文字",
            "contract_type": "lease",
            "provider": "ollama",
            "model": "qwen3:8b",
            "use_llm": "true",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["markdown"] == "ollama report"
    assert body["generation"]["used_llm"] is True
    assert body["generation"]["provider"] == "ollama"
    assert body["generation"]["warning"] is None
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer ollama"
    assert captured["body"]["model"] == "qwen3:8b"


def test_review_endpoint_accepts_txt_upload(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.post(
        "/api/review",
        data={"contract_type": "sale", "provider": "noop", "use_llm": "false"},
        files={
            "file": (
                "contract.txt",
                "買方與賣方約定價金，標的物交付後驗收，瑕疵由雙方另議。".encode("utf-8"),
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract_type"] == "sale"
    assert "合約審查報告" in body["markdown"]
