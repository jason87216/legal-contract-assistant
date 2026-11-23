"""Build data/official_statutes.json from the National Regulation Database open data API.

Source: 法務部全國法規資料庫開放資料 API, Chinese laws in JSON
(https://law.moj.gov.tw/api/Ch/Law/JSON, documented at
https://law.moj.gov.tw/api/swagger/docs/v1). The site updates its content weekly.
The same data is listed on data.gov.tw (https://data.gov.tw/dataset/18289) under
the Open Government Data License, version 1.0.

    python -m scripts.import_official_statutes                       # download and rebuild
    python -m scripts.import_official_statutes --zip ChLaw.json.zip  # use a downloaded file

Only the laws listed in LAWS are kept. Repealed laws are skipped. Article
numbers are stored as in the database ("245-1"); text keeps one line per
paragraph.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

DOWNLOAD_URL = "https://law.moj.gov.tw/api/Ch/Law/JSON"
API_DOCS_URL = "https://law.moj.gov.tw/api/swagger/docs/v1"
DATASET_URL = "https://data.gov.tw/dataset/18289"
LICENSE = "政府資料開放授權條款－第1版"
ATTRIBUTION = "資料來源：法務部全國法規資料庫開放資料（中文法律）"
OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "legal_contract_assistant"
    / "data"
    / "official_statutes.json"
)

# Laws commonly needed to review sale, labour and lease contracts.
LAWS = (
    "民法",
    "消費者保護法",
    "民事訴訟法",
    "勞動基準法",
    "勞工保險條例",
    "勞工退休金條例",
    "就業服務法",
    "性別平等工作法",
    "勞資爭議處理法",
    "土地法",
    "租賃住宅市場發展及管理條例",
)

_ARTICLE_NO = re.compile(r"^第(.+)條$")
_PCODE = re.compile(r"pcode=([A-Z0-9]+)", re.IGNORECASE)


def download(url: str = DOWNLOAD_URL) -> bytes:
    request = Request(url, headers={"User-Agent": "legal-contract-assistant statute import"})
    with urlopen(request, timeout=300) as response:
        return response.read()


def read_bundle(archive: bytes) -> dict:
    """Return the parsed ChLaw.json inside the API's zip archive."""
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [name for name in bundle.namelist() if name.lower().endswith(".json")]
        if len(names) != 1:
            raise ValueError(f"Expected one JSON file in the archive, found {names}")
        return json.loads(bundle.read(names[0]).decode("utf-8-sig"))


def _clean(text: str | None) -> str:
    return "\n".join(line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")).strip()


def parse_laws(bundle: dict, wanted: tuple[str, ...] = LAWS) -> dict:
    found: dict[str, dict] = {}
    for law in bundle.get("Laws", []):
        name = (law.get("LawName") or "").strip()
        if name not in wanted or (law.get("LawAbandonNote") or "").strip():
            continue
        url = (law.get("LawURL") or "").strip()
        pcode = _PCODE.search(url)
        if pcode is None:
            raise ValueError(f"No pcode in the URL of {name}: {url}")
        articles = []
        for article in law.get("LawArticles", []):
            if article.get("ArticleType") != "A":
                continue  # "C" rows are chapter headings
            number = _ARTICLE_NO.match(re.sub(r"\s", "", article.get("ArticleNo") or ""))
            if number is None:
                continue
            articles.append(
                {"article_no": number.group(1), "text": _clean(article.get("ArticleContent"))}
            )
        found[name] = {
            "law_name": name,
            "pcode": pcode.group(1),
            "url": url,
            "last_amended": (law.get("LawModifiedDate") or "").strip(),
            "articles": articles,
        }
    missing = [name for name in wanted if name not in found]
    if missing:
        raise ValueError(f"Laws not found in the source file: {missing}")
    return {
        "source": {
            "name": ATTRIBUTION,
            "download_url": DOWNLOAD_URL,
            "api_docs_url": API_DOCS_URL,
            "dataset_url": DATASET_URL,
            "license": LICENSE,
            "data_updated": (bundle.get("UpdateDate") or "").strip(),
            "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "laws": [found[name] for name in wanted],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, help="use a downloaded ChLaw.json.zip")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    archive = args.zip.read_bytes() if args.zip else download()
    data = parse_laws(read_bundle(archive))
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    counts = ", ".join(f"{law['law_name']} {len(law['articles'])}" for law in data["laws"])
    print(f"{args.out.name}: data updated {data['source']['data_updated']}; {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
