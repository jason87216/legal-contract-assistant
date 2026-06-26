"""FastAPI web app for the packaged local GUI agent."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .contract_review import CONTRACT_TYPE_LABELS, REVIEW_PERSPECTIVE_LABELS, ContractReviewService
from .llm import (
    AnthropicLLMProvider,
    GeminiLLMProvider,
    ModelConfig,
    NoopLLMProvider,
    OpenAICompatibleLLMProvider,
)
from .statute_tools import StatuteRetrievalTool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_STATIC_DIR = PROJECT_ROOT / "frontend" / "dist"
DEFAULT_MAX_OUTPUT_TOKENS = 8192
LONG_CONTRACT_MAX_OUTPUT_TOKENS = 32768

PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "kind": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
        "max_output_tokens": LONG_CONTRACT_MAX_OUTPUT_TOKENS,
    },
    "openrouter": {
        "label": "OpenRouter",
        "kind": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4.1-mini",
        "models": [
            "openai/gpt-4.1-mini",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.5-flash",
        ],
        "max_output_tokens": LONG_CONTRACT_MAX_OUTPUT_TOKENS,
    },
    "llama_cpp": {
        "label": "llama.cpp",
        "kind": "openai_compatible",
        "base_url": "http://127.0.0.1:18080/v1",
        "model": "local-chat",
        "models": ["local-chat"],
        "max_output_tokens": LONG_CONTRACT_MAX_OUTPUT_TOKENS,
    },
    "ollama": {
        "label": "Ollama",
        "kind": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen3:8b",
        "models": ["qwen3:8b", "llama3.1:8b", "gpt-oss:20b"],
        "max_output_tokens": LONG_CONTRACT_MAX_OUTPUT_TOKENS,
    },
    "anthropic": {
        "label": "Anthropic",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-3-5-sonnet-latest",
        "models": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
        "max_output_tokens": LONG_CONTRACT_MAX_OUTPUT_TOKENS,
    },
    "gemini": {
        "label": "Gemini",
        "kind": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
        "max_output_tokens": LONG_CONTRACT_MAX_OUTPUT_TOKENS,
    },
}


class ProviderSettingsRequest(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


def create_app(
    env_path: Path | str | None = None,
    static_dir: Path | str | None = None,
) -> FastAPI:
    app = FastAPI(title="Taiwan Contract Review Agent")
    app.state.env_path = Path(env_path) if env_path is not None else DEFAULT_ENV_PATH
    app.state.static_dir = (
        Path(static_dir) if static_dir is not None else DEFAULT_STATIC_DIR
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        values = _read_env(app.state.env_path)
        return {"providers": _provider_states(values)}

    @app.post("/api/settings/provider")
    def save_provider_settings(request: ProviderSettingsRequest) -> dict[str, Any]:
        provider = _normalize_provider(request.provider)
        updates: dict[str, str] = {}
        if request.api_key is not None and request.api_key.strip():
            updates[_env_key(provider, "API_KEY")] = request.api_key.strip()
        if request.base_url is not None and request.base_url.strip():
            updates[_env_key(provider, "BASE_URL")] = request.base_url.strip()
        if request.model is not None and request.model.strip():
            updates[_env_key(provider, "MODEL")] = request.model.strip()

        values = _read_env(app.state.env_path)
        values.update(updates)
        _write_env(app.state.env_path, values)
        return {"provider": _provider_state(provider, values)}

    @app.delete("/api/settings/provider/{provider}")
    def clear_provider_settings(provider: str) -> dict[str, Any]:
        provider = _normalize_provider(provider)
        values = _read_env(app.state.env_path)
        for suffix in ("API_KEY", "BASE_URL", "MODEL"):
            values.pop(_env_key(provider, suffix), None)
        _write_env(app.state.env_path, values)
        return {"provider": _provider_state(provider, values)}

    @app.post("/api/review")
    async def review_contract(
        text: Annotated[str, Form()] = "",
        contract_type: Annotated[str, Form()] = "auto",
        provider: Annotated[str, Form()] = "noop",
        model: Annotated[str, Form()] = "",
        base_url: Annotated[str, Form()] = "",
        long_contract: Annotated[bool, Form()] = False,
        review_perspective: Annotated[str, Form()] = "neutral",
        use_llm: Annotated[bool, Form()] = False,
        file: UploadFile | None = File(default=None),
    ) -> dict[str, Any]:
        contract_text = text.strip()
        if file is not None and file.filename:
            if not file.filename.lower().endswith(".txt"):
                raise HTTPException(status_code=400, detail="Only .txt upload is supported")
            raw = await file.read()
            contract_text = raw.decode("utf-8-sig").strip()

        if not contract_text:
            raise HTTPException(status_code=400, detail="Contract text is required")

        selected_contract_type = None if contract_type == "auto" else contract_type
        if selected_contract_type is not None and selected_contract_type not in {
            "sale",
            "labor",
            "lease",
        }:
            raise HTTPException(status_code=400, detail="Unsupported contract type")
        if review_perspective not in REVIEW_PERSPECTIVE_LABELS:
            raise HTTPException(status_code=400, detail="Unsupported review perspective")

        service = ContractReviewService()
        service.initialize()
        context = service.build_context(
            contract_text,
            contract_type=selected_contract_type,
            review_perspective=review_perspective,
        )
        statute_tools = StatuteRetrievalTool(service.statute_lookup)

        model_config = _model_config_for_request(
            app.state.env_path,
            provider=provider,
            model=model,
            base_url=base_url,
            long_contract=long_contract,
            use_llm=use_llm,
        )
        context = replace(context, model_config=model_config)
        report_writer = _provider_for_request(
            app.state.env_path,
            model_config,
            use_llm,
            tool_runner=statute_tools,
        )

        try:
            markdown = report_writer.generate_report(context)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        generation_warning = getattr(report_writer, "last_generation_warning", None)
        stop_reason = getattr(report_writer, "last_stop_reason", None)
        tool_call_count = getattr(report_writer, "last_tool_call_count", 0)
        used_llm = use_llm and not isinstance(report_writer, NoopLLMProvider)

        return {
            "markdown": markdown,
            "contract_type": context.contract_type,
            "contract_type_label": context.contract_type_label,
            "review_perspective": context.review_perspective,
            "review_perspective_label": context.review_perspective_label,
            "risk_level": context.risk_level,
            "risk_themes": list(context.risk_themes),
            "generation": {
                "provider": model_config.provider,
                "model": model_config.model,
                "used_llm": used_llm,
                "long_contract": long_contract,
                "max_output_tokens": model_config.max_output_tokens,
                "stop_reason": stop_reason,
                "warning": generation_warning,
                "status": "warning" if generation_warning else "completed" if used_llm else "dry_run",
                "tool_call_count": tool_call_count,
            },
            "keywords": list(context.extracted_keywords),
            "candidate_articles": list(context.candidate_articles),
            "related_articles": [
                {
                    "law_name": article.law_name,
                    "article_no": article.article_no,
                    "citation": article.citation,
                    "source_url": article.source_url,
                    "contract_types": list(article.contract_types),
                    "topics": list(article.topics),
                }
                for article in context.related_articles
            ],
        }

    _mount_frontend(app, app.state.static_dir)
    return app


def _mount_frontend(app: FastAPI, static_dir: Path) -> None:
    assets_dir = static_dir / "assets"
    index_file = static_dir / "index.html"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse(
            "<h1>Taiwan Contract Review Agent</h1>"
            "<p>Frontend build not found. Run <code>npm run build</code> in frontend/.</p>"
        )


def _model_config_for_request(
    env_path: Path,
    *,
    provider: str,
    model: str,
    base_url: str,
    long_contract: bool,
    use_llm: bool,
) -> ModelConfig:
    max_output_tokens = _max_output_tokens_for_request(
        provider=provider,
        long_contract=long_contract,
        use_llm=use_llm,
    )
    if not use_llm or provider == "noop":
        return ModelConfig(
            provider="noop",
            model=model.strip() or "rule-based-report-writer",
            max_output_tokens=max_output_tokens,
            base_url=None,
        )

    provider = _normalize_provider(provider)
    values = _read_env(env_path)
    defaults = PROVIDER_DEFAULTS[provider]
    return ModelConfig(
        provider=provider,
        model=model.strip() or values.get(_env_key(provider, "MODEL")) or defaults["model"],
        max_output_tokens=max_output_tokens,
        base_url=base_url.strip()
        or values.get(_env_key(provider, "BASE_URL"))
        or defaults["base_url"],
    )


def _max_output_tokens_for_request(
    *,
    provider: str,
    long_contract: bool,
    use_llm: bool,
) -> int:
    if not long_contract:
        return DEFAULT_MAX_OUTPUT_TOKENS
    if not use_llm or provider == "noop":
        return DEFAULT_MAX_OUTPUT_TOKENS
    provider = _normalize_provider(provider)
    return int(PROVIDER_DEFAULTS[provider]["max_output_tokens"])


def _provider_for_request(
    env_path: Path,
    model_config: ModelConfig,
    use_llm: bool,
    tool_runner: StatuteRetrievalTool | None = None,
):
    if not use_llm or model_config.provider == "noop":
        return NoopLLMProvider(model_config=model_config)

    values = _read_env(env_path)
    api_key = values.get(_env_key(model_config.provider, "API_KEY"), "")
    if not api_key and model_config.provider in {"llama_cpp", "ollama"}:
        api_key = "ollama" if model_config.provider == "ollama" else "sk-no-key-required"
    if not api_key:
        return NoopLLMProvider(model_config=model_config)

    kind = PROVIDER_DEFAULTS[model_config.provider]["kind"]
    if kind == "anthropic":
        return AnthropicLLMProvider(model_config, api_key=api_key, tool_runner=tool_runner)
    if kind == "gemini":
        return GeminiLLMProvider(model_config, api_key=api_key, tool_runner=tool_runner)
    return OpenAICompatibleLLMProvider(model_config, api_key=api_key, tool_runner=tool_runner)


def _provider_states(values: dict[str, str]) -> list[dict[str, Any]]:
    return [_provider_state(provider, values) for provider in PROVIDER_DEFAULTS]


def _provider_state(provider: str, values: dict[str, str]) -> dict[str, Any]:
    provider = _normalize_provider(provider)
    defaults = PROVIDER_DEFAULTS[provider]
    api_key = values.get(_env_key(provider, "API_KEY"), "")
    return {
        "provider": provider,
        "label": defaults["label"],
        "configured": bool(api_key),
        "api_key_mask": _mask_secret(api_key),
        "base_url": values.get(_env_key(provider, "BASE_URL"), defaults["base_url"]),
        "model": values.get(_env_key(provider, "MODEL"), defaults["model"]),
        "models": defaults["models"],
        "default_max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
        "long_contract_max_output_tokens": defaults["max_output_tokens"],
    }


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower().replace("-", "_")
    if normalized not in PROVIDER_DEFAULTS:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    return normalized


def _env_key(provider: str, suffix: str) -> str:
    return f"LCA_{provider.upper()}_{suffix}"


def _mask_secret(secret: str) -> str | None:
    if not secret:
        return None
    return f"***{secret[-4:]}" if len(secret) > 4 else "***"


def _read_env(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = _unquote_env_value(value.strip())
    return values


def _write_env(env_path: Path, values: dict[str, str]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Local settings for Legal Contract Assistant. Do not commit this file.",
        *[
            f"{key}={_quote_env_value(value)}"
            for key, value in sorted(values.items())
            if value
        ],
    ]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


app = create_app()
