"""Minimal live lookup client for Taiwan's National Regulation Database."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .statute_cache import normalize_article_no
from .statutes import StatuteArticle

LAW_PCODES = {
    "民法": "B0000001",
    "消費者保護法": "J0170001",
    "勞動基準法": "N0030001",
}


class MojLookupError(RuntimeError):
    """Raised when the official source cannot be parsed into an article."""


class MojLawClient:
    """Fetch single statute articles from law.moj.gov.tw."""

    base_url = "https://law.moj.gov.tw/LawClass/LawSingle.aspx"

    def lookup_article(self, law_name: str, article_no: str) -> StatuteArticle:
        pcode = LAW_PCODES.get(law_name.strip())
        if not pcode:
            raise MojLookupError(f"Unsupported law name for live lookup: {law_name}")

        article_no = normalize_article_no(article_no)
        query = urlencode({"pcode": pcode, "flno": article_no})
        url = f"{self.base_url}?{query}"
        request = Request(url, headers={"User-Agent": "legal-contract-assistant/0.1"})

        with urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="replace")

        text = _parse_article_text(html, article_no)
        return StatuteArticle(
            law_name=law_name.strip(),
            pcode=pcode,
            article_no=article_no,
            text=text,
            source_url=url,
            topics=(),
        )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if text:
            self.parts.append(text)


def _parse_article_text(html: str, article_no: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parts = parser.parts

    article_pattern = re.compile(rf"^第\s*{re.escape(article_no)}\s*條$")
    start = next((index for index, part in enumerate(parts) if article_pattern.match(part)), None)
    if start is None:
        raise MojLookupError(f"Article {article_no} was not found in the official page.")

    stop_markers = {
        ":::",
        "最新訊息",
        "中央法規",
        "司法解釋",
        "判例",
        "相關法條",
        "大法官解釋（舊制）",
    }
    body: list[str] = []
    for part in parts[start + 1 :]:
        if part in stop_markers or part.startswith("*"):
            break
        body.append(part)

    if not body:
        raise MojLookupError(f"Article {article_no} was found, but no body text was parsed.")
    return "\n".join(body)
