import math
import re
from collections import Counter

from app.rag.chunking.markdown import Chunk


TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    output: list[str] = []
    for token in TOKEN_RE.findall(text):
        normalized = token.lower()
        output.append(normalized)
        cjk_chars = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
        output.extend(cjk_chars)
    return output


class LexicalRetriever:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.chunk_terms = [Counter(tokenize(chunk.text)) for chunk in chunks]
        self.doc_freq: Counter[str] = Counter()
        for terms in self.chunk_terms:
            for token in terms:
                self.doc_freq[token] += 1

    def search(self, query: str, top_k: int, include_private: bool = False) -> list[tuple[Chunk, float]]:
        query_terms = tokenize(query)
        if not query_terms:
            return []

        query_counter = Counter(query_terms)
        scored: list[tuple[Chunk, float]] = []
        total_docs = max(1, len(self.chunks))
        for chunk, terms in zip(self.chunks, self.chunk_terms, strict=True):
            if not include_private and chunk.privacy_level != "public":
                continue
            score = 0.0
            length_norm = 1.0 + math.log(1 + sum(terms.values()))
            for term, query_count in query_counter.items():
                tf = terms.get(term, 0)
                if tf == 0:
                    continue
                idf = math.log((1 + total_docs) / (1 + self.doc_freq[term])) + 1.0
                score += query_count * (1 + math.log(tf)) * idf / length_norm
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]
