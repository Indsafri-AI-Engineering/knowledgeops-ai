import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from math import ceil
from typing import TypedDict

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "being", "but",
        "by", "can", "could", "do", "does", "for", "from", "had", "has",
        "have", "he", "her", "here", "hers", "him", "his", "how", "i", "if",
        "in", "into", "is", "it", "its", "may", "might", "more", "most",
        "must", "my", "no", "not", "of", "on", "or", "our", "ours", "please",
        "should", "so", "than", "that", "the", "their", "them", "there",
        "these", "they", "this", "those", "to", "under", "up", "us", "was",
        "we", "were", "what", "when", "where", "which", "who", "why", "will",
        "with", "would", "you", "your",
    }
)


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(text.lower())
        if token not in _STOP_WORDS and len(token) > 1
    }


class RagAnswerMetrics(TypedDict):
    faithfulness: float
    answer_relevancy: float
    contextual_precision: float
    contextual_recall: float
    unsupported_sentences: list[str]


@dataclass(frozen=True)
class BinaryClassificationMetrics:
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    false_positive_rate: float

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


def evaluate_rag_answer(
    answer: str,
    reference_answer: str,
    retrieved_document_ids: Sequence[str],
    expected_document_ids: Sequence[str],
    retrieved_contexts: Sequence[str],
    supporting_facts: Sequence[str],
) -> RagAnswerMetrics:
    """Return deterministic lexical RAG metrics and unsupported sentences.

    These are transparent lexical proxies, not semantic entailment judgments.
    """
    answer_tokens = _content_tokens(answer)
    reference_tokens = _content_tokens(reference_answer)
    reference_overlap = answer_tokens & reference_tokens
    answer_precision = (
        len(reference_overlap) / len(answer_tokens) if answer_tokens else 0.0
    )
    answer_recall = (
        len(reference_overlap) / len(reference_tokens) if reference_tokens else 0.0
    )
    answer_relevancy = (
        2 * answer_precision * answer_recall / (answer_precision + answer_recall)
        if answer_precision + answer_recall
        else 0.0
    )

    context_tokens = _content_tokens(" ".join(retrieved_contexts))
    answer_sentences = [
        sentence.strip()
        for sentence in _SENTENCE_PATTERN.split(answer.strip())
        if _content_tokens(sentence)
    ]
    sentence_support: list[float] = []
    unsupported_sentences: list[str] = []
    for sentence in answer_sentences:
        sentence_tokens = _content_tokens(sentence)
        support = len(sentence_tokens & context_tokens) / len(sentence_tokens)
        sentence_support.append(support)
        if support < 0.5:
            unsupported_sentences.append(sentence)
    faithfulness = (
        sum(sentence_support) / len(sentence_support) if sentence_support else 0.0
    )

    expected_ids = set(expected_document_ids)
    relevant_retrieved = sum(
        document_id in expected_ids for document_id in retrieved_document_ids
    )
    contextual_precision = (
        relevant_retrieved / len(retrieved_document_ids)
        if retrieved_document_ids
        else 0.0
    )
    fact_recalls = []
    for fact in supporting_facts:
        fact_tokens = _content_tokens(fact)
        fact_recalls.append(
            len(fact_tokens & context_tokens) / len(fact_tokens)
            if fact_tokens
            else 0.0
        )
    contextual_recall = (
        sum(fact_recalls) / len(fact_recalls) if fact_recalls else 0.0
    )
    return {
        "faithfulness": faithfulness,
        "answer_relevancy": answer_relevancy,
        "contextual_precision": contextual_precision,
        "contextual_recall": contextual_recall,
        "unsupported_sentences": unsupported_sentences,
    }


def latency_summary(latencies_ms: Sequence[float]) -> dict[str, float | int]:
    """Summarize measured request latency in milliseconds."""
    if not latencies_ms:
        return {
            "samples": 0,
            "mean_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
        }

    ordered = sorted(latencies_ms)

    def percentile(value: float) -> float:
        rank = max(0, min(len(ordered) - 1, ceil(len(ordered) * value) - 1))
        return ordered[rank]

    return {
        "samples": len(ordered),
        "mean_ms": sum(ordered) / len(ordered),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
    }


def binary_classification_metrics(
    expected: Sequence[bool],
    predicted: Sequence[bool],
) -> BinaryClassificationMetrics:
    if not expected or len(expected) != len(predicted):
        raise ValueError("Expected and predicted labels must be non-empty and equal in length.")

    true_positives = sum(
        actual and guess for actual, guess in zip(expected, predicted)
    )
    false_positives = sum(
        not actual and guess for actual, guess in zip(expected, predicted)
    )
    true_negatives = sum(
        not actual and not guess for actual, guess in zip(expected, predicted)
    )
    false_negatives = sum(
        actual and not guess for actual, guess in zip(expected, predicted)
    )

    precision_denominator = true_positives + false_positives
    recall_denominator = true_positives + false_negatives
    false_positive_denominator = false_positives + true_negatives
    precision = (
        true_positives / precision_denominator if precision_denominator else 0.0
    )
    recall = true_positives / recall_denominator if recall_denominator else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    false_positive_rate = (
        false_positives / false_positive_denominator
        if false_positive_denominator
        else 0.0
    )
    return BinaryClassificationMetrics(
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_rate=false_positive_rate,
    )
