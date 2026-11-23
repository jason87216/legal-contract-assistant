"""Official statute data from the National Regulation Database open data."""

import asyncio

import pytest

from scripts.import_official_statutes import parse_laws, read_bundle
from src.legal_contract_assistant.statute_cache import ContractStatuteCache
from src.legal_contract_assistant.statute_lookup import StatuteLookupService
from src.legal_contract_assistant.statute_tools import StatuteRetrievalTool

SAMPLE_BUNDLE = {
    "UpdateDate": "2026/11/13 上午 12:00:00",
    "Laws": [
        {
            "LawName": "測試法",
            "LawURL": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=Z0000001",
            "LawModifiedDate": "20260101",
            "LawAbandonNote": "",
            "LawArticles": [
                {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "   第 一 章 總則"},
                {"ArticleType": "A", "ArticleNo": "第 1 條", "ArticleContent": "第一項。\r\n第二項。"},
                {"ArticleType": "A", "ArticleNo": "第 9-1 條", "ArticleContent": "增訂條文。"},
            ],
        },
        {
            "LawName": "已廢止法",
            "LawURL": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=Z0000002",
            "LawAbandonNote": "廢",
            "LawArticles": [],
        },
    ],
}


def _tool(tmp_path) -> StatuteRetrievalTool:  # noqa: ANN001
    tool = StatuteRetrievalTool(StatuteLookupService(ContractStatuteCache(tmp_path / "s.db")))
    tool.initialize()
    return tool


def test_importer_keeps_articles_paragraphs_and_source() -> None:
    data = parse_laws(SAMPLE_BUNDLE, ("測試法",))

    law = data["laws"][0]
    assert law["pcode"] == "Z0000001"
    assert law["articles"] == [
        {"article_no": "1", "text": "第一項。\n第二項。"},
        {"article_no": "9-1", "text": "增訂條文。"},
    ]
    assert data["source"]["data_updated"] == "2026/11/13 上午 12:00:00"
    assert "政府資料開放授權條款" in data["source"]["license"]


def test_importer_rejects_missing_or_repealed_laws() -> None:
    with pytest.raises(ValueError, match="已廢止法"):
        parse_laws(SAMPLE_BUNDLE, ("測試法", "已廢止法"))


def test_importer_reads_the_api_zip() -> None:
    import io
    import json
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("ChLaw.json", "\ufeff" + json.dumps(SAMPLE_BUNDLE, ensure_ascii=False))
        bundle.writestr("manifest.csv", "name,schema,description\n")

    assert read_bundle(buffer.getvalue())["Laws"][0]["LawName"] == "測試法"


def test_lookup_finds_articles_outside_the_curated_set(tmp_path) -> None:
    result = _tool(tmp_path).lookup_article("勞動基準法", "9-1")

    assert result["found"] is True
    article = result["article"]
    assert article["text"].startswith("未符合下列規定者，雇主不得與勞工為離職後競業禁止之約定")
    assert article["curated"] is False
    assert article["source_url"].endswith("pcode=N0030001&flno=9-1")


def test_regulations_and_added_laws_are_imported(tmp_path) -> None:
    tool = _tool(tmp_path)

    for law_name, article_no in [
        ("勞動基準法施行細則", "7-3"),
        ("就業保險法", "5"),
        ("勞工職業災害保險及保護法", "6"),
        ("營業秘密法", "2"),
        ("著作權法", "21"),
        ("專利法", "9"),
    ]:
        assert tool.lookup_article(law_name, article_no)["found"], (law_name, article_no)


def test_curated_articles_use_current_official_text(tmp_path) -> None:
    article = _tool(tmp_path).lookup_article("民法", "435")["article"]

    assert article["curated"] is True
    assert article["topics"]
    assert article["text"].startswith("租賃關係存續中，因不可歸責於承租人之事由")


def test_curated_scope_never_returns_uncurated_articles(tmp_path) -> None:
    tool = _tool(tmp_path)

    curated = tool.search_statutes("競業禁止 離職 補償", contract_mode="labor", limit=30)
    everything = tool.search_statutes(
        "競業禁止 離職 補償", contract_mode="labor", limit=30, scope="all"
    )

    assert all(article["curated"] for article in curated)
    assert "勞動基準法 第 9-1 條" in [article["citation"] for article in everything]
    with pytest.raises(ValueError):
        tool.search_statutes("押金", scope="everything")


def test_tool_calls_search_all_articles_by_default(tmp_path) -> None:
    result = _tool(tmp_path).call_tool("search_statutes", {"query": "競業禁止", "limit": 5})

    assert "勞動基準法 第 9-1 條" in [article["citation"] for article in result["articles"]]


def test_source_info_reports_license_date_and_counts(tmp_path) -> None:
    tool = _tool(tmp_path)
    tool.initialize()  # a second run must not reset curated rows

    info = tool.source_info()

    assert info["download_url"] == "https://law.moj.gov.tw/api/Ch/Law/JSON"
    assert info["loaded_version"] == info["imported_at"]
    laws = {law["law_name"]: law for law in info["laws"]}
    assert laws["民法"]["articles"] >= 1400
    assert laws["民法"]["curated_articles"] > 0
    assert laws["土地法"]["articles"] > 0
    assert laws["勞動基準法施行細則"]["level"] == "命令"


def test_mcp_server_exposes_source_info_tool(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mcp")
    from src.legal_contract_assistant.mcp_server import create_mcp_server

    monkeypatch.chdir(tmp_path)
    server = create_mcp_server()

    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {"lookup_article", "search_statutes", "statute_source_info"} <= names
