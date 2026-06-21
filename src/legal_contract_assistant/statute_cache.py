"""SQLite cache for contract-related Taiwan statute articles."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Iterable

from .review_rules import ReviewRule, load_seed_review_rules
from .statutes import StatuteArticle

SCHEMA_VERSION = 3


def default_cache_path() -> Path:
    return Path(".cache") / "contract_statutes.db"


def normalize_article_no(article_no: str) -> str:
    return article_no.strip().replace("－", "-").replace("–", "-")


class ContractStatuteCache:
    """Small local cache for statutes that are often used in contract review."""

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
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
        if seed:
            self.upsert_many(load_seed_articles())
            self.upsert_review_rules(load_seed_review_rules())

    def get(self, law_name: str, article_no: str) -> StatuteArticle | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT law_name, pcode, article_no, text, source_url,
                       contract_types_json, topics_json, cached_at
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
                       contract_types_json, topics_json, cached_at
                FROM statute_articles
                WHERE topics_json LIKE ? OR text LIKE ?
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
                       contract_types_json, topics_json, cached_at
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
                       contract_types_json, topics_json, cached_at
                FROM statute_articles
                WHERE contract_types_json LIKE ? AND topics_json LIKE ?
                ORDER BY law_name, article_no
                """,
                (contract_pattern, topic_pattern),
            ).fetchall()
        return [_row_to_article(row) for row in rows if row is not None]

    def upsert(self, article: StatuteArticle) -> None:
        self.upsert_many([article])

    def list_review_rules(self) -> list[ReviewRule]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT rule_id, risk_theme, risk_level, pattern,
                       legal_basis_json, suggestion, source_note
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
                        legal_basis_json, suggestion, source_note
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(rule_id) DO UPDATE SET
                        risk_theme = excluded.risk_theme,
                        risk_level = excluded.risk_level,
                        pattern = excluded.pattern,
                        legal_basis_json = excluded.legal_basis_json,
                        suggestion = excluded.suggestion,
                        source_note = excluded.source_note
                    """,
                    rows,
                )

    def upsert_many(self, articles: Iterable[StatuteArticle]) -> None:
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
            )
            for article in articles
        ]
        if not rows:
            return

        with closing(self._connect()) as conn:
            with conn:
                conn.executemany(
                    """
                    INSERT INTO statute_articles (
                        law_name, pcode, article_no, text, source_url,
                        contract_types_json, topics_json, cached_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(law_name, article_no) DO UPDATE SET
                        pcode = excluded.pcode,
                        text = excluded.text,
                        source_url = excluded.source_url,
                        contract_types_json = excluded.contract_types_json,
                        topics_json = excluded.topics_json,
                        cached_at = excluded.cached_at
                    """,
                    rows,
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def load_seed_articles() -> list[StatuteArticle]:
    seed_path = resources.files(f"{__package__}.data").joinpath("contract_statutes_seed.json")
    raw_articles = json.loads(seed_path.read_text(encoding="utf-8"))
    return [
        StatuteArticle(
            law_name=item["law_name"],
            pcode=item["pcode"],
            article_no=normalize_article_no(item["article_no"]),
            text=item["text"],
            source_url=item["source_url"],
            contract_types=tuple(item.get("contract_types", [])),
            topics=tuple(item.get("topics", [])),
            cached_at=item.get("cached_at"),
        )
        for item in raw_articles
    ]


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
    )


def _ensure_column(
    conn: sqlite3.Connection, table_name: str, column_name: str, column_definition: str
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
