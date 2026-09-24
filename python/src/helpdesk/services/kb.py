"""The knowledge base: an exact filter for people, and ranked passages for the assistant."""

from __future__ import annotations

import sqlite3
from typing import Any

from helpdesk.data import repository
from helpdesk.services.errors import Invalid
from helpdesk.services.retrieval import MAX_WORDS, METHODS, SPLITS, Hit, Index, Method, Split

MAX_LIMIT = 20


def search(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """The articles whose title, body or tags contain the query exactly, for people browsing."""
    if not query.strip():
        raise Invalid("query must not be empty")
    if not 1 <= limit <= MAX_LIMIT:
        raise Invalid(f"limit must be between 1 and {MAX_LIMIT}; got {limit}")
    return repository.search_kb(conn, query.strip(), limit)


def articles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return repository.list_kb_articles(conn)


def build_index(conn: sqlite3.Connection, *, split: Split = "section", max_words: int = MAX_WORDS) -> Index:
    """An index over every article as it is now. At this size, building one takes milliseconds, so
    it's built for each search and never goes stale; a large knowledge base builds it once and
    updates it when an article changes."""
    if split not in SPLITS:
        raise Invalid(f"split must be one of {', '.join(SPLITS)}; got {split!r}")
    return Index.build(articles(conn), split=split, max_words=max_words)


def retrieve(conn: sqlite3.Connection, question: str, k: int = 3, method: Method = "hybrid") -> list[Hit]:
    """The k passages that best match a question (chapter 9), or fewer when fewer are relevant."""
    if not question.strip():
        raise Invalid("question must not be empty")
    if not 1 <= k <= MAX_LIMIT:
        raise Invalid(f"k must be between 1 and {MAX_LIMIT}; got {k}")
    if method not in METHODS:
        raise Invalid(f"method must be one of {', '.join(METHODS)}; got {method!r}")
    return build_index(conn).search(question, k, method)
