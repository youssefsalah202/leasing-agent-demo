from __future__ import annotations

from pathlib import Path

import chromadb

DOCS_DIR = Path(__file__).parent / "docs"
COLLECTION_NAME = "faq"


class FaqStore:
    """Thin wrapper around a local Chroma collection for the housing FAQ.

    Uses Chroma's bundled default embedding model (downloads once on first
    use, no external embeddings API needed). Chunking is deliberately simple
    — split each doc on blank lines — since the seed docs are short and
    hand-written; a larger real FAQ corpus would want smarter chunking.
    """

    def __init__(self, persist_dir: str | Path):
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(COLLECTION_NAME)

    def is_seeded(self) -> bool:
        return self._collection.count() > 0

    def seed_from_docs(self, docs_dir: Path = DOCS_DIR) -> int:
        ids, texts, metadatas = [], [], []
        for path in sorted(docs_dir.glob("*.md")):
            chunks = [c.strip() for c in path.read_text(encoding="utf-8").split("\n\n") if c.strip()]
            for i, chunk in enumerate(chunks):
                ids.append(f"{path.stem}-{i}")
                texts.append(chunk)
                metadatas.append({"source": path.name})
        if not texts:
            return 0
        self._collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
        return len(texts)

    def retrieve(self, query: str, k: int = 3) -> list[dict]:
        if not self.is_seeded():
            return []
        result = self._collection.query(query_texts=[query], n_results=k)
        hits = []
        for doc, meta, dist in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            hits.append({"text": doc, "source": meta.get("source"), "distance": dist})
        return hits
