"""CLI for the legal contract assistant."""

from __future__ import annotations

import argparse
import sys

from .contract_review import ContractReviewService
from .llm import ModelConfig, OpenAICompatibleLLMProvider
from .statute_tools import StatuteRetrievalTool


def analyze_contract(text: str) -> dict[str, list[str] | str]:
    """Return a minimal placeholder analysis for future expansion."""
    normalized = text.strip()
    if not normalized:
        return {
            "summary": "No contract text provided.",
            "risks": ["Missing input text."],
        }

    return {
        "summary": "Placeholder analysis completed.",
        "risks": [
            "Review payment terms.",
            "Review termination conditions.",
            "Review liability limitations.",
        ],
    }


def generate_review_report(
    text: str,
    contract_type: str | None = None,
    model_config: ModelConfig | None = None,
    use_local_llama: bool = False,
) -> str:
    service = ContractReviewService()
    service.initialize()
    llm_provider = (
        OpenAICompatibleLLMProvider(
            model_config,
            tool_runner=StatuteRetrievalTool(service.statute_lookup),
        )
        if use_local_llama and model_config is not None
        else None
    )
    return service.generate_markdown_report(
        text,
        contract_type=contract_type,
        llm_provider=llm_provider,
        model_config=model_config,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Taiwan contract review report.")
    parser.add_argument(
        "--contract-type",
        choices=("sale", "labor", "lease"),
        help="Optional user-selected contract mode. If omitted, no auto classification is used.",
    )
    parser.add_argument("--text", help="Contract text. If omitted, stdin or a sample is used.")
    parser.add_argument(
        "--model-provider",
        default="noop",
        help="Model provider label to record in the report. No API call is made.",
    )
    parser.add_argument(
        "--model",
        default="rule-based-report-writer",
        help="Model name to record in the report. No API call is made.",
    )
    parser.add_argument(
        "--model-base-url",
        default="http://127.0.0.1:18080/v1",
        help="OpenAI-compatible API base URL for local llama.cpp.",
    )
    parser.add_argument(
        "--use-local-llama",
        action="store_true",
        help="Call the local OpenAI-compatible llama.cpp server.",
    )
    args = parser.parse_args()

    text = args.text
    if text is None and not sys.stdin.isatty():
        text = sys.stdin.read()
    if not text:
        text = """
        甲方為出租人，乙方為承租人。乙方每月支付租金新臺幣二萬元。
        租期一年，乙方提前終止契約時應支付違約金。房屋修繕責任另由雙方協議。
        """

    model_config = ModelConfig(
        provider=args.model_provider,
        model=args.model,
        base_url=args.model_base_url,
    )
    print(
        generate_review_report(
            text,
            contract_type=args.contract_type,
            model_config=model_config,
            use_local_llama=args.use_local_llama,
        )
    )


if __name__ == "__main__":
    main()
