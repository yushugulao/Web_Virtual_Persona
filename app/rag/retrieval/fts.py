from __future__ import annotations

import sqlite3

from app.rag.chunking.markdown import Chunk
from app.rag.retrieval.lexical import tokenize


class SqliteFtsRetriever:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            "CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, tokens)"
        )
        self.connection.executemany(
            "INSERT INTO chunk_fts (chunk_id, tokens) VALUES (?, ?)",
            [
                (
                    chunk.chunk_id,
                    " ".join(
                        tokenize(
                            f"{chunk.title} {chunk.section_path} {chunk.source_type} {chunk.text}"
                        )
                    ),
                )
                for chunk in chunks
            ],
        )

    def search(self, query: str, top_k: int, include_private: bool = False) -> list[tuple[Chunk, float]]:
        query_terms = unique_terms(tokenize(query))
        if not query_terms:
            return []
        match_query = " OR ".join(quote_fts_term(term) for term in query_terms)
        rows = self.connection.execute(
            """
            SELECT chunk_id, bm25(chunk_fts) AS rank
            FROM chunk_fts
            WHERE chunk_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match_query, max(top_k * 3, top_k)),
        ).fetchall()

        results: list[tuple[Chunk, float]] = []
        for chunk_id, rank in rows:
            chunk = self.chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            if not include_private and chunk.privacy_level != "public":
                continue
            results.append((chunk, max(0.0, -float(rank))))
            if len(results) >= top_k:
                break
        return results


def unique_terms(tokens: list[str], limit: int = 32) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= limit:
            break
    return terms


def quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'
