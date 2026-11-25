"""Optional local cosine index with one embedding per statute article."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Protocol
from zipfile import BadZipFile

from .statutes import StatuteArticle

if TYPE_CHECKING:
    import numpy as np

DEFAULT_EMBED_MODEL = "BAAI/bge-m3"


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray:
        """Return a matrix with one L2-normalised row per input."""


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = DEFAULT_EMBED_MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, normalize_embeddings=True)


class VectorIndex:
    def __init__(self, cache_dir: Path, embedder: Embedder, model_name: str) -> None:
        self.cache_dir = cache_dir
        self.embedder = embedder
        self.model_name = model_name
        self._fingerprint = ""
        self.keys: list[tuple[str, str]] = []

    def prepare(self, articles: list[StatuteArticle], version: str | None) -> None:
        import numpy as np

        keys = [(article.law_name, article.article_no) for article in articles]
        texts = [
            " ".join((article.law_name, article.article_no, *article.topics, article.text))
            for article in articles
        ]
        fingerprint = hashlib.sha256(
            json.dumps([self.model_name, version, keys, texts], ensure_ascii=False).encode()
        ).hexdigest()
        if self._fingerprint == fingerprint:
            return

        path = self.cache_dir / f"vectors-{fingerprint}.npz"
        try:
            with np.load(path, allow_pickle=False) as saved:
                stored_keys = saved["keys"].tolist()
                matrix = saved["matrix"]
                if stored_keys != [list(key) for key in keys] or not self._valid(matrix, len(keys)):
                    raise ValueError("Invalid vector index")
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            matrix = np.asarray(self.embedder.encode(texts), dtype=np.float32) if keys else np.empty((0, 0))
            if not self._valid(matrix, len(keys)):
                raise ValueError("Invalid article embeddings")
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as temp:
                temp_path = Path(temp.name)
            try:
                np.savez(temp_path, keys=np.asarray(keys, dtype=str), matrix=matrix)
                temp_path.replace(path)
            finally:
                temp_path.unlink(missing_ok=True)
        self.keys, self.matrix, self._fingerprint = keys, matrix, fingerprint

    @staticmethod
    def _valid(matrix: np.ndarray, rows: int) -> bool:
        import numpy as np

        return matrix.ndim == 2 and matrix.shape[0] == rows and (
            not rows or (matrix.shape[1] > 0 and np.isfinite(matrix).all())
        )

    def scores(self, queries: list[str]) -> list[dict[tuple[str, str], float]]:
        import numpy as np

        if not self.keys:
            return [{} for _ in queries]
        vectors = np.asarray(self.embedder.encode(queries), dtype=np.float32)
        if not self._valid(vectors, len(queries)):
            raise ValueError("Invalid query embeddings")
        return [dict(zip(self.keys, row.tolist())) for row in vectors @ self.matrix.T]
