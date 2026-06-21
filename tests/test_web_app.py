from fastapi.testclient import TestClient

from src.legal_contract_assistant.web_app import create_app


def test_health_endpoint(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
    assert "# 合約審查報告" in body["markdown"]
    assert body["related_articles"]
    assert any(article["source_url"].startswith("https://law.moj.gov.tw/") for article in body["related_articles"])


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
