import os

import pytest

from backend.app.evaluation.metrics import binary_classification_metrics
from backend.app.evaluation.metrics import evaluate_rag_answer, latency_summary
from backend.app.evaluation.run_demo_evaluation import (
    evaluate_answers,
    evaluate_moderation_cases,
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


def test_rag_metrics_identify_unsupported_answer_claims() -> None:
    metrics = evaluate_rag_answer(
        answer=(
            "Full-time employees receive 20 working days of annual leave. "
            "Employees may carry over 100 days."
        ),
        reference_answer="Full-time employees receive 20 working days of annual leave.",
        retrieved_document_ids=["leave-guide", "unrelated-guide"],
        expected_document_ids=["leave-guide"],
        retrieved_contexts=[
            "Full-time employees receive 20 working days of annual leave."
        ],
        supporting_facts=[
            "Full-time employees receive 20 working days of annual leave."
        ],
    )

    assert metrics["faithfulness"] < 1
    assert metrics["answer_relevancy"] > 0
    assert metrics["contextual_precision"] == 0.5
    assert metrics["contextual_recall"] == 1
    assert metrics["unsupported_sentences"] == [
        "Employees may carry over 100 days."
    ]


def test_latency_summary_reports_samples_and_percentiles() -> None:
    assert latency_summary([10, 20, 30, 40]) == {
        "samples": 4,
        "mean_ms": 25,
        "p50_ms": 20,
        "p95_ms": 40,
    }


def test_answer_evaluation_compares_modes_and_tracks_failures(monkeypatch) -> None:
    from backend.app.evaluation import run_demo_evaluation

    monkeypatch.delenv("RAG_GENERATION_BACKEND", raising=False)

    def fail_generation(*args: object, **kwargs: object) -> str:
        _ = (args, kwargs)
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        run_demo_evaluation,
        "generate_grounded_answer",
        fail_generation,
    )

    report = evaluate_answers(["synthetic-test-backend"])

    assert set(report["synthetic-test-backend"]) == {"vector", "keyword", "hybrid"}
    for mode_results in report["synthetic-test-backend"].values():
        assert mode_results["cases"] == 4
        assert mode_results["successful_cases"] == 0
        assert mode_results["error_count"] == 4
        assert mode_results["error_rate"] == 1
        assert mode_results["latency"]["samples"] == 4
        assert all(
            result["error_type"] == "RuntimeError"
            for result in mode_results["results"]
        )
    assert "RAG_GENERATION_BACKEND" not in os.environ


def test_extractive_answers_are_evaluated_for_every_retrieval_mode(monkeypatch) -> None:
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "extractive")

    report = evaluate_answers()

    assert set(report["extractive"]) == {"vector", "keyword", "hybrid"}
    for mode_results in report["extractive"].values():
        assert mode_results["cases"] == 4
        assert mode_results["error_count"] == 0
        assert mode_results["latency"]["samples"] == 4
        assert mode_results["mean_metrics"]["contextual_recall"] > 0


def test_synthetic_guardrail_evaluation_meets_defined_fixture_expectations() -> None:
    report = evaluate_moderation_cases()

    assert report["total_cases"] == 19
    assert report["passed"] == report["total_cases"]
    assert report["failed"] == 0
    assert report["authorization"] == {
        "checks": 1,
        "denials": 1,
        "denial_rate": 1.0,
    }
    assert report["side_effect_prevention"] == {
        "checks": 1,
        "prevented": 1,
        "prevention_rate": 1.0,
    }
    for stage in ("input", "retrieval", "output"):
        assert report["by_stage"][stage]["metrics"]["false_negatives"] == 0
