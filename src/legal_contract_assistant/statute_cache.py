"""SQLite cache for contract-related Taiwan statute articles."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from functools import lru_cache
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Iterable

from .review_rules import ReviewRule, load_seed_review_rules
from .statutes import StatuteArticle

SCHEMA_VERSION = 4
OFFICIAL_VERSION_KEY = "official_statutes_version"


def default_cache_path() -> Path:
    return Path(".cache") / "contract_statutes.db"


def normalize_article_no(article_no: str) -> str:
    return article_no.strip().replace("－", "-").replace("–", "-")


class ContractStatuteCache:
    """Local statute store.

    Two kinds of rows share one table:
    - curated: the candidate scope of the report's statute retrieval. Built from
      the article ranges per contract type (contract_scope_seed.json), the
      statutes cited by review rules, and the hand-annotated articles with topics
      (contract_statutes_seed.json).
    - official: every article of the laws in official_statutes.json, imported
      from the National Regulation Database open data; used for exact lookups,
      rule citations, MCP and model tool searches.
    Curated rows take their text from the official data when it has the article.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_cache_path()

    def initialize(self, seed: bool = True) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS statute_articles (
                        law_name TEXT NOT NULL,
                        pcode TEXT NOT NULL,
                        article_no TEXT NOT NULL,
                        text TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        contract_types_json TEXT NOT NULL DEFAULT '[]',
                        topics_json TEXT NOT NULL DEFAULT '[]',
                        cached_at TEXT NOT NULL,
                        PRIMARY KEY (law_name, article_no)
                    );

                    CREATE INDEX IF NOT EXISTS idx_statute_articles_pcode_article
                    ON statute_articles (pcode, article_no);

                    CREATE TABLE IF NOT EXISTS review_rules (
                        rule_id TEXT PRIMARY KEY,
                        risk_theme TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        pattern TEXT NOT NULL,
                        legal_basis_json TEXT NOT NULL DEFAULT '[]',
                        suggestion TEXT NOT NULL DEFAULT '',
                        source_note TEXT NOT NULL DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS idx_review_rules_risk_level
                    ON review_rules (risk_level);
                    """
                )
                _ensure_column(conn, "statute_articles", "contract_types_json", "TEXT NOT NULL DEFAULT '[]'")
                _ensure_column(conn, "statute_articles", "curated", "INTEGER NOT NULL DEFAULT 1")
                _ensure_column(conn, "review_rules", "basis_note", "TEXT NOT NULL DEFAULT ''")
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
        if seed:
            source, official = load_official_articles()
            # imported_at changes with every rebuilt data file, including scope changes.
            if self.metadata(OFFICIAL_VERSION_KEY) != source["imported_at"]:
                self.upsert_many(official)
                self.set_metadata(OFFICIAL_VERSION_KEY, source["imported_at"])
            rules = load_seed_review_rules()
            # Curated rows go last so their annotations and flag win.
            self.replace_curated(load_curated_articles(rules))
            self.upsert_review_rules(rules)

    def metadata(self, key: str) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value)
                )

    def source_info(self) -> dict:
        """Where the statute text comes from, and how much of it is stored."""
        source, _ = load_official_articles()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT law_name, pcode, COUNT(*) AS articles, SUM(curated) AS curated
                FROM statute_articles
                GROUP BY law_name, pcode
                ORDER BY law_name
                """
            ).fetchall()
        laws = {law["law_name"]: law for law in official_statutes_data()["laws"]}
        return {
            **source,
            "loaded_version": self.metadata(OFFICIAL_VERSION_KEY),
            "laws": [
                {
                    "law_name": row["law_name"],
                    "pcode": row["pcode"],
                    "articles": row["articles"],
                    "curated_articles": row["curated"],
                    "level": laws.get(row["law_name"], {}).get("level"),
                    "last_amended": laws.get(row["law_name"], {}).get("last_amended"),
                }
                for row in rows
            ],
        }

    def get(self, law_name: str, article_no: str) -> StatuteArticle | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT law_name, pcode, article_no, text, source_url,
                       contract_types_json, topics_json, cached_at, curated
                FROM statute_articles
                WHERE law_name = ? AND article_no = ?
                """,
                (law_name.strip(), normalize_article_no(article_no)),
            ).fetchone()
        return _row_to_article(row)

    def search_by_topic(self, topic: str) -> list[StatuteArticle]:
        pattern = f"%{topic.strip()}%"
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT law_name, pcode, article_no, text, source_url,
                       contract_types_json, topics_json, cached_at, curated
                FROM statute_articles
                WHERE curated = 1 AND (topics_json LIKE ? OR text LIKE ?)
                ORDER BY law_name, article_no
                """,
                (pattern, pattern),
            ).fetchall()
        return [_row_to_article(row) for row in rows if row is not None]

    def search_by_contract_type(self, contract_type: str) -> list[StatuteArticle]:
        pattern = f'%"{contract_type.strip()}"%'
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT law_name, pcode, article_no, text, source_url,
                       contract_types_json, topics_json, cached_at, curated
                FROM statute_articles
                WHERE contract_types_json LIKE ?
                ORDER BY law_name, article_no
                """,
                (pattern,),
            ).fetchall()
        return [_row_to_article(row) for row in rows if row is not None]

    def search_by_contract_and_topic(
        self, contract_type: str, topic: str
    ) -> list[StatuteArticle]:
        contract_pattern = f'%"{contract_type.strip()}"%'
        topic_pattern = f'%"{topic.strip()}"%'
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT law_name, pcode, article_no, text, source_url,
                       contract_types_json, topics_json, cached_at, curated
                FROM statute_articles
                WHERE contract_types_json LIKE ? AND topics_json LIKE ?
                ORDER BY law_name, article_no
                """,
                (contract_pattern, topic_pattern),
            ).fetchall()
        return [_row_to_article(row) for row in rows if row is not None]

    def list_articles(self, *, curated_only: bool = False) -> list[StatuteArticle]:
        where = "WHERE curated = 1" if curated_only else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT law_name, pcode, article_no, text, source_url,
                       contract_types_json, topics_json, cached_at, curated
                FROM statute_articles
                {where}
                ORDER BY law_name, article_no
                """
            ).fetchall()
        return [_row_to_article(row) for row in rows if row is not None]

    def upsert(self, article: StatuteArticle) -> None:
        self.upsert_many([article])

    def list_review_rules(self) -> list[ReviewRule]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT rule_id, risk_theme, risk_level, pattern,
                       legal_basis_json, suggestion, source_note, basis_note
                FROM review_rules
                ORDER BY rule_id
                """
            ).fetchall()
        return [
            ReviewRule(
                rule_id=row["rule_id"],
                risk_theme=row["risk_theme"],
                risk_level=row["risk_level"],
                pattern=row["pattern"],
                legal_basis=tuple(
                    (basis["law_name"], basis["article_no"])
                    for basis in json.loads(row["legal_basis_json"])
                ),
                suggestion=row["suggestion"],
                source_note=row["source_note"],
                basis_note=row["basis_note"],
            )
            for row in rows
        ]

    def upsert_review_rules(self, rules: Iterable[ReviewRule]) -> None:
        rows = [
            (
                rule.rule_id,
                rule.risk_theme,
                rule.risk_level,
                rule.pattern,
                json.dumps(
                    [
                        {"law_name": law_name, "article_no": article_no}
                        for law_name, article_no in rule.legal_basis
                    ],
                    ensure_ascii=False,
                ),
                rule.suggestion,
                rule.source_note,
                rule.basis_note,
            )
            for rule in rules
        ]
        if not rows:
            return

        with closing(self._connect()) as conn:
            with conn:
                conn.executemany(
                    """
                    INSERT INTO review_rules (
                        rule_id, risk_theme, risk_level, pattern,
                        legal_basis_json, suggestion, source_note, basis_note
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(rule_id) DO UPDATE SET
                        risk_theme = excluded.risk_theme,
                        risk_level = excluded.risk_level,
                        pattern = excluded.pattern,
                        legal_basis_json = excluded.legal_basis_json,
                        suggestion = excluded.suggestion,
                        source_note = excluded.source_note,
                        basis_note = excluded.basis_note
                    """,
                    rows,
                )

    def replace_curated(self, articles: Iterable[StatuteArticle]) -> None:
        """Make exactly these articles curated; rows dropped from the scope lose the flag."""
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE statute_articles
                    SET curated = 0, contract_types_json = '[]', topics_json = '[]'
                    WHERE curated = 1
                    """
                )
                _upsert_articles(conn, articles)

    def upsert_many(self, articles: Iterable[StatuteArticle]) -> None:
        with closing(self._connect()) as conn:
            with conn:
                _upsert_articles(conn, articles)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _upsert_articles(conn: sqlite3.Connection, articles: Iterable[StatuteArticle]) -> None:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    rows = [
        (
            article.law_name.strip(),
            article.pcode.strip(),
            normalize_article_no(article.article_no),
            article.text.strip(),
            article.source_url.strip(),
            json.dumps(list(article.contract_types), ensure_ascii=False),
            json.dumps(list(article.topics), ensure_ascii=False),
            article.cached_at or now,
            int(article.curated),
        )
        for article in articles
    ]
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO statute_articles (
            law_name, pcode, article_no, text, source_url,
            contract_types_json, topics_json, cached_at, curated
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(law_name, article_no) DO UPDATE SET
            pcode = excluded.pcode,
            text = excluded.text,
            source_url = excluded.source_url,
            contract_types_json = excluded.contract_types_json,
            topics_json = excluded.topics_json,
            cached_at = excluded.cached_at,
            curated = excluded.curated
        """,
        rows,
    )


@lru_cache
def official_statutes_data() -> dict:
    path = resources.files(f"{__package__}.data").joinpath("official_statutes.json")
    return json.loads(path.read_text(encoding="utf-8"))


def article_url(pcode: str, article_no: str) -> str:
    return f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={article_no}"


def load_official_articles() -> tuple[dict, list[StatuteArticle]]:
    """Every article in official_statutes.json (scripts/import_official_statutes.py)."""
    data = official_statutes_data()
    articles = []
    for law in data["laws"]:
        for item in law["articles"]:
            article_no = normalize_article_no(item["article_no"])
            articles.append(
                StatuteArticle(
                    law_name=law["law_name"],
                    pcode=law["pcode"],
                    article_no=article_no,
                    text=item["text"],
                    source_url=article_url(law["pcode"], article_no),
                    cached_at=data["source"]["imported_at"],
                    curated=False,
                )
            )
    return data["source"], articles


def load_seed_articles() -> list[StatuteArticle]:
    """Curated articles; their text comes from the official data when it has the article."""
    seed_path = resources.files(f"{__package__}.data").joinpath("contract_statutes_seed.json")
    raw_articles = json.loads(seed_path.read_text(encoding="utf-8"))
    official = {
        (article.law_name, article.article_no): article.text
        for article in load_official_articles()[1]
    }
    return [
        StatuteArticle(
            law_name=item["law_name"],
            pcode=item["pcode"],
            article_no=normalize_article_no(item["article_no"]),
            text=official.get(
                (item["law_name"], normalize_article_no(item["article_no"])), item["text"]
            ),
            source_url=item["source_url"],
            contract_types=tuple(item.get("contract_types", [])),
            topics=tuple(item.get("topics", [])),
            cached_at=item.get("cached_at"),
        )
        for item in raw_articles
    ]


@lru_cache
def contract_scope_data() -> dict:
    path = resources.files(f"{__package__}.data").joinpath("contract_scope_seed.json")
    return json.loads(path.read_text(encoding="utf-8"))


def contract_type_labels() -> dict[str, str]:
    """Contract type keys and their Chinese names, from contract_scope_seed.json."""
    return dict(contract_scope_data()["_types"])


def article_sort_key(article_no: str) -> tuple[int, int]:
    """\"463-1\" -> (463, 1); \"9\" -> (9, 0)."""
    main, _, sub = normalize_article_no(article_no).partition("-")
    return int(main), int(sub or 0)


def article_in_range(article_no: str, start: str, end: str) -> bool:
    """Inclusive; an end without a suffix also covers its -1, -2 ... articles."""
    key = article_sort_key(article_no)
    end_key = article_sort_key(end)
    if "-" not in normalize_article_no(end):
        end_key = (end_key[0], 10**6)
    return article_sort_key(start) <= key <= end_key


def scope_contract_types(rules: Iterable[ReviewRule] = ()) -> dict[tuple[str, str], set[str]]:
    """(law_name, article_no) -> contract types whose candidate scope includes it.

    Sources: the ranges in contract_scope_seed.json ("common" applies to every
    type) and the statutes cited by review rules, typed by the rule_id prefix
    (a prefix that is not a contract type, such as "shared", means every type).
    """
    data = contract_scope_data()
    all_types = set(data["_types"])
    official = {law["law_name"]: law for law in official_statutes_data()["laws"]}
    scope: dict[tuple[str, str], set[str]] = {}

    for group, entries in data.items():
        if group.startswith("_"):
            continue
        types = all_types if group == "common" else {group}
        for entry in entries:
            law = official.get(entry["law_name"])
            if law is None:
                raise ValueError(f"scope law not imported: {entry['law_name']}")
            for item in law["articles"]:
                article_no = normalize_article_no(item["article_no"])
                if entry.get("all") or any(
                    article_in_range(article_no, start, end) for start, end in entry["ranges"]
                ):
                    scope.setdefault((law["law_name"], article_no), set()).update(types)

    for rule in rules:
        prefix = rule.rule_id.split("_", 1)[0]
        types = {prefix} if prefix in all_types else all_types
        for law_name, article_no in rule.legal_basis:
            scope.setdefault((law_name, normalize_article_no(article_no)), set()).update(types)
    return scope


def load_curated_articles(rules: Iterable[ReviewRule] = ()) -> list[StatuteArticle]:
    """Every curated article: scope ranges, rule citations and annotated seed articles.

    Seed articles keep their topics; contract types are the union of the seed
    annotation and the scope. Articles missing from the official data are skipped,
    except seed articles, which carry their own text.
    """
    scope = scope_contract_types(rules)
    official = {(a.law_name, a.article_no): a for a in load_official_articles()[1]}
    seeds = {(a.law_name, a.article_no): a for a in load_seed_articles()}

    curated: list[StatuteArticle] = []
    for key in sorted(set(scope) | set(seeds), key=lambda k: (k[0], article_sort_key(k[1]))):
        base = seeds.get(key) or official.get(key)
        if base is None:
            continue
        seed = seeds.get(key)
        types = set(scope.get(key, ())) | set(seed.contract_types if seed else ())
        curated.append(
            StatuteArticle(
                law_name=base.law_name,
                pcode=base.pcode,
                article_no=base.article_no,
                text=base.text,
                source_url=base.source_url,
                contract_types=tuple(sorted(types)),
                topics=seed.topics if seed else (),
                cached_at=base.cached_at,
                curated=True,
            )
        )
    return curated


def _row_to_article(row: sqlite3.Row | None) -> StatuteArticle | None:
    if row is None:
        return None
    return StatuteArticle(
        law_name=row["law_name"],
        pcode=row["pcode"],
        article_no=row["article_no"],
        text=row["text"],
        source_url=row["source_url"],
        contract_types=tuple(json.loads(row["contract_types_json"])),
        topics=tuple(json.loads(row["topics_json"])),
        cached_at=row["cached_at"],
        curated=bool(row["curated"]),
    )


def _ensure_column(
    conn: sqlite3.Connection, table_name: str, column_name: str, column_definition: str
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
