"""Manually (re)build the FAQ vector index. Not required to run the server —
main.py seeds automatically on first startup — but handy after editing docs
in app/rag/docs/ if you want to reseed without restarting the server."""

from __future__ import annotations

from app.config import get_settings
from app.rag.store import DOCS_DIR, FaqStore

if __name__ == "__main__":
    settings = get_settings()
    store = FaqStore(settings.chroma_persist_dir)
    n = store.seed_from_docs(DOCS_DIR)
    print(f"Seeded {n} FAQ chunks into {settings.chroma_persist_dir}")
