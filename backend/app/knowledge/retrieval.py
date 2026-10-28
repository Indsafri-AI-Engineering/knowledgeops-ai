import math
import re
import threading
from collections import OrderedDict
from collections import Counter
from dataclasses import dataclass
from typing import Hashable, Literal, Protocol, TypeVar, runtime_checkable

from backend.app.knowledge.ingestion import KnowledgeChunk

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MIN_VECTOR_SCORE = 0.08
RRF_K = 60
BM25_K1 = 1.5
BM25_B = 0.75
STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "do", "does",
        "for", "from", "how", "i", "in", "is", "it", "of", "on", "or",
        "the", "this", "to", "under", "what", "when", "where", "which",
        "who", "why", "with",
    }
)
RetrievalMode = Literal["vector", "keyword", "hybrid"]
RankedItem = TypeVar("RankedItem", bound=Hashable)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: KnowledgeChunk
    score: float


@runtime_checkable
class KnowledgeIndex(Protocol):
    @property
    def chunks(self) -> list[KnowledgeChunk]: ...

    def cache_info(self) -> dict[str, int]: ...

    def search(
        self,
        question: str,
        allowed_scopes: set[str],
        limit: int = 4,
        mode: RetrievalMode = "hybrid",
    ) -> list[RetrievedChunk]: ...

    def delete_document(self, document_id: str) -> None: ...

    def add_chunks(self, chunks: list[KnowledgeChunk]) -> None: ...


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if token not in STOP_WORDS
    ]


def _tfidf_vector(
    text: str,
    document_frequencies: Counter[str],
    count: int,
) -> dict[str, float]:
    frequencies = Counter(_tokens(text))
    vector = {
        token: (1 + math.log(term_count))
        * (math.log((count + 1) / (document_frequencies[token] + 1)) + 1)
        for token, term_count in frequencies.items()
    }
    norm = math.sqrt(sum(weight * weight for weight in vector.values()))
    return {token: weight / norm for token, weight in vector.items()} if norm else {}


def reciprocal_rank_fusion(
    rankings: list[list[RankedItem]],
) -> dict[RankedItem, float]:
    fused_scores: dict[RankedItem, float] = {}
    for ranking in rankings:
        seen: set[RankedItem] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            fused_scores[item] = fused_scores.get(item, 0.0) + 1 / (RRF_K + rank)
    return fused_scores


class LocalKnowledgeIndex:
    """In-process TF-IDF vector and BM25 keyword retrieval."""

    def __init__(self, chunks: list[KnowledgeChunk], cache_size: int = 128) -> None:
        self._chunks = tuple(chunks)
        self._cache_size = max(0, cache_size)
        self._search_cache: OrderedDict[
            tuple[tuple[str, ...], frozenset[str], int, RetrievalMode],
            list[RetrievedChunk],
        ] = OrderedDict()
        self._cache_lock = threading.RLock()
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def chunks(self) -> list[KnowledgeChunk]:
        return list(self._chunks)

    def cache_info(self) -> dict[str, int]:
        with self._cache_lock:
            return {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "entries": len(self._search_cache),
                "max_entries": self._cache_size,
            }

    def delete_document(self, document_id: str) -> None:
        self._chunks = tuple(
            chunk for chunk in self._chunks if chunk.document_id != document_id
        )
        self._search_cache.clear()

    def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = (*self._chunks, *chunks)
        self._search_cache.clear()

    def search(
        self,
        question: str,
        allowed_scopes: set[str],
        limit: int = 4,
        mode: RetrievalMode = "hybrid",
    ) -> list[RetrievedChunk]:
        if limit <= 0 or mode not in ("vector", "keyword", "hybrid"):
            return []

        cache_key = (tuple(_tokens(question)), frozenset(allowed_scopes), limit, mode)
        if self._cache_size:
            with self._cache_lock:
                cached_results = self._search_cache.get(cache_key)
                if cached_results is not None:
                    self._cache_hits += 1
                    self._search_cache.move_to_end(cache_key)
                    return list(cached_results)
                self._cache_misses += 1

        results = self._search_uncached(
            question,
            allowed_scopes,
            limit,
            mode,
        )
        if self._cache_size:
            with self._cache_lock:
                self._search_cache[cache_key] = list(results)
                self._search_cache.move_to_end(cache_key)
                while len(self._search_cache) > self._cache_size:
                    self._search_cache.popitem(last=False)
        return results

    def _search_uncached(
        self,
        question: str,
        allowed_scopes: set[str],
        limit: int,
        mode: RetrievalMode,
    ) -> list[RetrievedChunk]:
        # Restrict the corpus before computing statistics or ranking candidates.
        eligible = [
            chunk for chunk in self._chunks if chunk.access_scope in allowed_scopes
        ]
        query_tokens = _tokens(question)
        if not eligible or not query_tokens:
            return []

        document_tokens = [_tokens(chunk.text) for chunk in eligible]
        document_frequencies: Counter[str] = Counter()
        for tokens in document_tokens:
            document_frequencies.update(set(tokens))
        query_vector = _tfidf_vector(
            question, document_frequencies, len(eligible)
        )
        document_vectors = [
            _tfidf_vector(chunk.text, document_frequencies, len(eligible))
            for chunk in eligible
        ]
        vector_scores = [
            sum(
                weight * vector.get(token, 0.0)
                for token, weight in query_vector.items()
            )
            for vector in document_vectors
        ]
        vector_ranking = sorted(
            (
                (index, score)
                for index, score in enumerate(vector_scores)
                if score >= MIN_VECTOR_SCORE
            ),
            key=lambda result: (-result[1], eligible[result[0]].chunk_id),
        )
        if mode == "vector":
            return [
                RetrievedChunk(eligible[index], score)
                for index, score in vector_ranking[:limit]
            ]

        average_length = (
            sum(len(tokens) for tokens in document_tokens) / len(document_tokens)
        )
        keyword_scores: list[float] = []
        for tokens in document_tokens:
            frequencies = Counter(tokens)
            score = 0.0
            for term in set(query_tokens):
                term_frequency = frequencies[term]
                if not term_frequency:
                    continue
                document_frequency = document_frequencies[term]
                inverse_frequency = math.log(
                    1
                    + (len(eligible) - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                length_normalizer = (
                    BM25_K1
                    * (
                        1
                        - BM25_B
                        + BM25_B * len(tokens) / max(average_length, 1)
                    )
                )
                score += inverse_frequency * (
                    term_frequency
                    * (BM25_K1 + 1)
                    / (term_frequency + length_normalizer)
                )
            keyword_scores.append(score)

        keyword_ranking = sorted(
            (
                (index, score)
                for index, score in enumerate(keyword_scores)
                if score > 0
            ),
            key=lambda result: (-result[1], eligible[result[0]].chunk_id),
        )
        if mode == "keyword":
            return [
                RetrievedChunk(eligible[index], score)
                for index, score in keyword_ranking[:limit]
            ]

        rrf_scores = reciprocal_rank_fusion(
            [
                [index for index, _ in vector_ranking],
                [index for index, _ in keyword_ranking],
            ]
        )
        hybrid_ranking = sorted(
            rrf_scores.items(),
            key=lambda result: (-result[1], eligible[result[0]].chunk_id),
        )
        return [
            RetrievedChunk(eligible[index], score)
            for index, score in hybrid_ranking[:limit]
        ]
