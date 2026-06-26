"""MCP server exposing Taiwan statute retrieval tools."""

from __future__ import annotations

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
        """Look up one cached Taiwan statute article by law name and article number."""
        return tools.lookup_article(law_name=law_name, article_no=article_no)

    @mcp.tool()
    def search_statutes(
        query: str,
        contract_mode: str | None = None,
        limit: int = 8,
    ) -> dict:
        """Search cached Taiwan statute articles by query text and optional contract mode."""
        return {
            "articles": tools.search_statutes(
                query=query,
                contract_mode=contract_mode,
                limit=limit,
            )
        }

    @mcp.tool()
    def retrieve_candidate_articles(
        contract_text: str,
        contract_mode: str | None = None,
        limit: int = 12,
    ) -> dict:
        """Extract keywords from a contract and retrieve candidate statute articles."""
        return tools.retrieve_candidate_articles(
            contract_text=contract_text,
            contract_mode=contract_mode,
            limit=limit,
        )

    return mcp


def main() -> None:
    create_mcp_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
