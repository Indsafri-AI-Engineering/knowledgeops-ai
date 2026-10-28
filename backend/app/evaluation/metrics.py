from collections.abc import Sequence
from dataclasses import asdict, dataclass


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
