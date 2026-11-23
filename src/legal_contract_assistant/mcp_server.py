"""MCP server exposing Taiwan statute retrieval tools."""

from __future__ import annotations

from typing import Literal

from .statute_tools import StatuteRetrievalTool


def create_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised when dependency is absent.
        raise RuntimeError(
            "MCP support requires the optional dependency: mcp>=1.27,<2"
        ) from exc

    mcp = FastMCP("taiwan-contract-statutes", json_response=True)
    tools = StatuteRetrievalTool()
    tools.initialize()

    @mcp.tool()
    def lookup_article(law_name: str, article_no: str) -> dict:
        """Look up one Taiwan statute article by law name and article number, e.g. 勞動基準法 9-1.

        Covers every article of the laws listed by statute_source_info, imported from
        the National Regulation Database open data. Returns the text and official URL.
        """
        return tools.lookup_article(law_name=law_name, article_no=article_no)

    @mcp.tool()
    def search_statutes(
        query: str,
        contract_mode: str | None = None,
        limit: int = 8,
        scope: Literal["all", "curated"] = "all",
    ) -> dict:
        """Search Taiwan statute articles by query text and optional contract mode.

        scope "all" searches every imported article; "curated" only the articles
        annotated for contract review (sale, labor, lease).
        """
        return {
            "articles": tools.search_statutes(
                query=query,
                contract_mode=contract_mode,
                limit=limit,
                scope=scope,
            )
        }

    @mcp.tool()
    def retrieve_candidate_articles(
        contract_text: str,
        contract_mode: str | None = None,
        limit: int = 12,
    ) -> dict:
        """Extract legal terms from a contract and retrieve candidate curated articles."""
        return tools.retrieve_candidate_articles(
            contract_text=contract_text,
            contract_mode=contract_mode,
            limit=limit,
        )

    @mcp.tool()
    def statute_source_info() -> dict:
        """Data source, license, data date and article counts of the statute store."""
        return tools.source_info()

    return mcp


def main() -> None:
    create_mcp_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
