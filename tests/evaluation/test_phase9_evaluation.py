import pytest

from backend.app.evaluation.metrics import binary_classification_metrics
from backend.app.evaluation.run_demo_evaluation import (
    evaluate_restricted_access,
    evaluate_retrieval,
    evaluate_routing,
)
from backend.app.threat_detection.evaluation import evaluate_threat_cases


def test_threat_metrics_match_hand_calculated_confusion_matrix() -> None:
    metrics = binary_classification_metrics(
        [True, True, False, False],
        [True, False, True, False],
    )

    assert metrics.true_positives == 1
    assert metrics.false_positives == 1
    assert metrics.true_negatives == 1
    assert metrics.false_negatives == 1
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.f1 == 0.5
    assert metrics.false_positive_rate == 0.5


def test_evaluation_rejects_empty_or_mismatched_labels() -> None:
    with pytest.raises(ValueError):
        binary_classification_metrics([], [])
    with pytest.raises(ValueError):
        binary_classification_metrics([True], [True, False])


def test_fictional_threat_and_retrieval_smoke_evaluation() -> None:
    threat_metrics = evaluate_threat_cases()
    retrieval_metrics = evaluate_retrieval()

    assert threat_metrics.true_positives == 4
    assert threat_metrics.true_negatives == 4
    assert threat_metrics.false_positives == 0
    assert threat_metrics.false_negatives == 0
    assert retrieval_metrics["vector"]["cases"] == 4
    assert retrieval_metrics["hybrid"]["cases"] == 4
    assert retrieval_metrics["hybrid"]["expected_source_hit_rate_at_3"] >= 0


def test_fictional_routing_evaluation_reports_measured_accuracy() -> None:
    metrics = evaluate_routing()

    assert metrics["cases"] == 8
    assert metrics["correct"] == metrics["cases"]
    assert metrics["accuracy"] == 1.0


def test_employee_restricted_access_evaluation_has_no_leaks() -> None:
    metrics = evaluate_restricted_access()

    assert metrics == {"checks": 3, "denials": 3, "leaks": 0}
