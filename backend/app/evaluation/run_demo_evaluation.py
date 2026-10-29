import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from starlette.requests import Request

from backend.app.core.demo_auth import DEMO_USERS
from backend.app.core.environment import load_environment
from backend.app.core.permissions import user_scopes
from backend.app.evaluation.metrics import (
    binary_classification_metrics,
    evaluate_rag_answer,
    latency_summary,
)
from backend.app.knowledge.generation import generate_grounded_answer
from backend.app.knowledge.ingestion import KnowledgeChunk, load_knowledge_chunks
from backend.app.knowledge.retrieval import LocalKnowledgeIndex, RetrievedChunk
from backend.app.moderation.guardrails import (
    inspect_retrieved_chunks,
    moderate_input,
    moderate_output,
)
from backend.app.orchestration.routing import route_question
from backend.app.orchestration.service import orchestrate_request
from backend.app.threat_detection.evaluation import evaluate_threat_cases

EVALUATION_CASE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "tests" / "evaluation"
)
RETRIEVAL_CASE_PATH = EVALUATION_CASE_DIRECTORY / "retrieval_cases.json"
ROUTING_CASE_PATH = EVALUATION_CASE_DIRECTORY / "routing_cases.json"
ACCESS_CASE_PATH = EVALUATION_CASE_DIRECTORY / "access_cases.json"
GUARDRAIL_CASE_PATH = EVALUATION_CASE_DIRECTORY / "guardrail_cases.json"
DEFAULT_REPORT_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "evaluation"
    / "phase9_latest.json"
)
EVALUATION_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "fictional_demo"
)


def _evaluation_index() -> LocalKnowledgeIndex:
    return LocalKnowledgeIndex(load_knowledge_chunks(EVALUATION_FIXTURE_DIRECTORY))


def _evaluation_request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/evaluation"})
    request.state.request_id = "synthetic-guardrail-evaluation"
    return request


def evaluate_retrieval() -> dict[str, dict[str, float | int]]:
    cases = json.loads(RETRIEVAL_CASE_PATH.read_text(encoding="utf-8"))
    index = _evaluation_index()
    report: dict[str, dict[str, float | int]] = {}
    for mode in ("vector", "keyword", "hybrid"):
        reciprocal_ranks: list[float] = []
        hits: list[bool] = []
        for case in cases:
            results = index.search(
                case["question"],
                set(case["allowed_scopes"]),
                limit=3,
                mode=mode,
            )
            rank = next(
                (
                    position
                    for position, result in enumerate(results, start=1)
                    if result.chunk.document_id in case["expected_document_ids"]
                ),
                None,
            )
            reciprocal_ranks.append(1 / rank if rank is not None else 0.0)
            hits.append(rank is not None)
        report[mode] = {
            "mrr_at_3": sum(reciprocal_ranks) / len(reciprocal_ranks),
            "expected_source_hit_rate_at_3": sum(hits) / len(hits),
            "cases": len(reciprocal_ranks),
        }
    return report


def evaluate_answers(
    generation_backends: list[str] | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    cases = json.loads(RETRIEVAL_CASE_PATH.read_text(encoding="utf-8"))
    if not cases:
        raise ValueError(f"RAG evaluation dataset must not be empty: {RETRIEVAL_CASE_PATH}")

    configured_backend = os.getenv("RAG_GENERATION_BACKEND", "extractive").strip().lower()
    backends = (
        generation_backends
        if generation_backends is not None
        else [configured_backend]
    )
    if not backends or any(not backend.strip() for backend in backends):
        raise ValueError("At least one non-empty generation backend is required.")

    original_backend = os.environ.get("RAG_GENERATION_BACKEND")
    report: dict[str, dict[str, dict[str, object]]] = {}
    try:
        for backend in backends:
            backend = backend.strip().lower()
            os.environ["RAG_GENERATION_BACKEND"] = backend
            index = _evaluation_index()
            for mode in ("vector", "keyword", "hybrid"):
                case_results: list[dict[str, object]] = []
                latencies: list[float] = []
                metric_values: dict[str, list[float]] = {
                    "faithfulness": [],
                    "answer_relevancy": [],
                    "contextual_precision": [],
                    "contextual_recall": [],
                }
                errors = 0
                unsupported_sentences = 0
                for case in cases:
                    started_at = perf_counter()
                    try:
                        results = index.search(
                            case["question"],
                            set(case["allowed_scopes"]),
                            limit=3,
                            mode=mode,
                        )
                        answer = generate_grounded_answer(results, case["question"])
                        latency_ms = (perf_counter() - started_at) * 1000
                        latencies.append(latency_ms)
                        metrics = evaluate_rag_answer(
                            answer=answer,
                            reference_answer=case["reference_answer"],
                            retrieved_document_ids=[
                                result.chunk.document_id for result in results
                            ],
                            expected_document_ids=case["expected_document_ids"],
                            retrieved_contexts=[
                                result.chunk.text for result in results
                            ],
                            supporting_facts=case["supporting_facts"],
                        )
                        metric_values["faithfulness"].append(metrics["faithfulness"])
                        metric_values["answer_relevancy"].append(
                            metrics["answer_relevancy"]
                        )
                        metric_values["contextual_precision"].append(
                            metrics["contextual_precision"]
                        )
                        metric_values["contextual_recall"].append(
                            metrics["contextual_recall"]
                        )
                        unsupported = metrics["unsupported_sentences"]
                        unsupported_sentences += len(unsupported)
                        case_results.append(
                            {
                                "case_id": case["case_id"],
                                "status": "ok",
                                "latency_ms": round(latency_ms, 3),
                                "retrieved_document_ids": [
                                    result.chunk.document_id for result in results
                                ],
                                "metrics": {
                                    "faithfulness": metrics["faithfulness"],
                                    "answer_relevancy": metrics["answer_relevancy"],
                                    "contextual_precision": metrics["contextual_precision"],
                                    "contextual_recall": metrics["contextual_recall"],
                                },
                                "unsupported_sentences": unsupported,
                            }
                        )
                    except Exception as error:
                        # A failed case is part of the measured error rate, not a passing answer.
                        latency_ms = (perf_counter() - started_at) * 1000
                        latencies.append(latency_ms)
                        errors += 1
                        case_results.append(
                            {
                                "case_id": case.get("case_id", "unknown"),
                                "status": "error",
                                "latency_ms": round(latency_ms, 3),
                                "error_type": type(error).__name__,
                            }
                        )

                succeeded = len(cases) - errors
                report.setdefault(backend, {})[mode] = {
                    "cases": len(cases),
                    "successful_cases": succeeded,
                    "error_count": errors,
                    "error_rate": errors / len(cases),
                    "latency": latency_summary(latencies),
                    "mean_metrics": {
                        name: (
                            sum(values) / len(values) if values else 0.0
                        )
                        for name, values in metric_values.items()
                    },
                    "unsupported_sentence_count": unsupported_sentences,
                    "results": case_results,
                }
    finally:
        if original_backend is None:
            os.environ.pop("RAG_GENERATION_BACKEND", None)
        else:
            os.environ["RAG_GENERATION_BACKEND"] = original_backend
    return report


def evaluate_moderation_cases() -> dict[str, object]:
    cases = json.loads(GUARDRAIL_CASE_PATH.read_text(encoding="utf-8"))
    if not cases:
        raise ValueError(f"Guardrail evaluation dataset must not be empty: {GUARDRAIL_CASE_PATH}")

    results: list[dict[str, str]] = []
    stage_binary: dict[str, dict[str, list[bool]]] = {
        stage: {"expected": [], "predicted": []}
        for stage in ("input", "retrieval", "output")
    }
    authorization_checks = 0
    authorization_denials = 0
    action_checks = 0
    action_preventions = 0
    excluded_cases: list[dict[str, str]] = []

    class RetrievalMustNotRun:
        def search(self, *args: object, **kwargs: object) -> None:
            _ = (args, kwargs)
            raise AssertionError("Restricted evaluation must deny before retrieval.")

    for case in cases:
        stage = case["stage"]
        expected = case["expected"]
        text = case.get("text", "")
        if case.get("repeat"):
            text *= int(case["repeat"])

        if stage == "input":
            actual = moderate_input(text).outcome
        elif stage == "retrieval":
            chunk = KnowledgeChunk(
                chunk_id=case["case_id"],
                document_id="synthetic-guardrail-document",
                title="Synthetic Guardrail Fixture",
                source="fictional_guardrails_evaluation",
                access_scope="general",
                source_path="guardrails/synthetic.md",
                section="Evaluation",
                text=text,
            )
            safe_chunks, matched_rules = inspect_retrieved_chunks(
                [RetrievedChunk(chunk=chunk, score=1.0)]
            )
            actual = "flagged" if matched_rules else "allowed"
            if expected == "flagged" and safe_chunks:
                actual = "flagged" if text not in safe_chunks[0].chunk.text else "missed"
        elif stage == "output":
            decision = moderate_output(
                case["answer"],
                retrieved_contexts=case.get("contexts"),
                source_count=int(case.get("source_count", 0)),
            )
            actual = decision.outcome
        elif stage == "access":
            authorization_checks += 1
            user = DEMO_USERS["demo-employee"]
            route = route_question(text)
            result = orchestrate_request(
                text,
                route,
                user,
                _evaluation_request(),
                RetrievalMustNotRun(),
                "hybrid",
            )
            actual = "denied" if result.audit_outcome == "denied" else "allowed"
            authorization_denials += int(actual == "denied")
        elif stage == "action":
            action_checks += 1
            route = route_question(text)
            result = orchestrate_request(
                text,
                route,
                DEMO_USERS["demo-it"],
                _evaluation_request(),
                _evaluation_index(),
                "hybrid",
            )
            actual = (
                "no_side_effect"
                if result.workflow_status == "planned"
                and result.audit_action is None
                and not result.sources
                else "side_effect_possible"
            )
            action_preventions += int(actual == "no_side_effect")
        else:
            raise ValueError(f"Unknown guardrail evaluation stage: {stage}")

        results.append(
            {
                "case_id": case["case_id"],
                "stage": stage,
                "expected": expected,
                "actual": actual,
                "status": "pass" if actual == expected else "fail",
            }
        )

        if stage in stage_binary:
            if expected in ("allowed", "blocked", "flagged"):
                stage_binary[stage]["expected"].append(expected != "allowed")
                stage_binary[stage]["predicted"].append(
                    actual in ("blocked", "flagged")
                )
            elif expected == "clarification_required":
                excluded_cases.append(
                    {
                        "case_id": case["case_id"],
                        "reason": "clarification is not a binary moderation label",
                    }
                )

    stage_reports: dict[str, dict[str, object]] = {}
    for stage, labels in stage_binary.items():
        metrics = binary_classification_metrics(
            labels["expected"],
            labels["predicted"],
        ).as_dict()
        stage_reports[stage] = {
            "classified_cases": len(labels["expected"]),
            "metrics": metrics,
            "missed_detection_rate": (
                metrics["false_negatives"]
                / (metrics["true_positives"] + metrics["false_negatives"])
                if metrics["true_positives"] + metrics["false_negatives"]
                else 0.0
            ),
        }

    return {
        "total_cases": len(cases),
        "passed": sum(result["status"] == "pass" for result in results),
        "failed": sum(result["status"] == "fail" for result in results),
        "by_stage": stage_reports,
        "authorization": {
            "checks": authorization_checks,
            "denials": authorization_denials,
            "denial_rate": (
                authorization_denials / authorization_checks
                if authorization_checks
                else 0.0
            ),
        },
        "side_effect_prevention": {
            "checks": action_checks,
            "prevented": action_preventions,
            "prevention_rate": (
                action_preventions / action_checks if action_checks else 0.0
            ),
        },
        "excluded_from_binary_metrics": excluded_cases,
        "skipped": [],
        "results": results,
    }


def evaluate_routing() -> dict[str, int | float]:
    cases = json.loads(ROUTING_CASE_PATH.read_text(encoding="utf-8"))
    correct = sum(
        (
            decision := route_question(case["question"])
        ).intent == case["expected_intent"]
        and decision.component == case["expected_component"]
        for case in cases
    )
    return {
        "correct": correct,
        "cases": len(cases),
        "accuracy": correct / len(cases) if cases else 0.0,
    }


def evaluate_restricted_access() -> dict[str, int | float]:
    cases = json.loads(ACCESS_CASE_PATH.read_text(encoding="utf-8"))
    user = DEMO_USERS["demo-employee"]
    allowed_scopes = set(user_scopes(user))

    class RetrievalMustNotRun:
        def search(self, *args: object, **kwargs: object) -> None:
            _ = (args, kwargs)
            raise AssertionError("Denied evaluation cases must not run retrieval.")

    violations = 0
    for case in cases:
        decision = route_question(case["question"])
        result = orchestrate_request(
            case["question"],
            decision,
            user,
            None,
            RetrievalMustNotRun(),
            "hybrid",
        )
        violations += int(
            case["required_scope"] in allowed_scopes
            or decision.required_scope != case["required_scope"]
            or result.audit_outcome != "denied"
            or bool(result.sources)
        )
    return {
        "checks": len(cases),
        "denials": len(cases) - violations,
        "leaks": violations,
    }


def main() -> None:
    load_environment()
    parser = argparse.ArgumentParser(description="Run the synthetic Phase 9 evaluation suite.")
    parser.add_argument(
        "--generation-backends",
        help=(
            "Comma-separated answer generators to compare. Defaults to the "
            "configured RAG_GENERATION_BACKEND."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path for the JSON report (default: data/evaluation/phase9_latest.json).",
    )
    args = parser.parse_args()
    generation_backends = (
        [
            backend.strip().lower()
            for backend in args.generation_backends.split(",")
        ]
        if args.generation_backends
        else None
    )
    report = {
        "schema_version": 1,
        "run_at": datetime.now(UTC).isoformat(),
        "scope": (
            "synthetic evaluation using the local TF-IDF/BM25 test index; "
            "lexical answer metrics are not semantic judgments"
        ),
        "configuration": {
            "retrieval_backend": "local_tf_idf_bm25",
            "generation_backends": generation_backends
            or [os.getenv("RAG_GENERATION_BACKEND", "extractive").strip().lower()],
            "generation_settings": {
                backend: {
                    "model": {
                        "ollama": os.getenv("OLLAMA_CHAT_MODEL", "llama3.2:3b"),
                        "groq": os.getenv(
                            "GROQ_CHAT_MODEL",
                            "llama-3.3-70b-versatile",
                        ),
                        "mistral": os.getenv(
                            "MISTRAL_CHAT_MODEL",
                            "mistral-small-latest",
                        ),
                    }.get(backend, "none"),
                    "temperature": 0,
                    "max_output_tokens": 512,
                }
                for backend in (
                    generation_backends
                    or [os.getenv("RAG_GENERATION_BACKEND", "extractive").strip().lower()]
                )
            },
        },
        "retrieval": evaluate_retrieval(),
        "answers": evaluate_answers(generation_backends),
        "moderation": evaluate_moderation_cases(),
        "routing": evaluate_routing(),
        "restricted_access": evaluate_restricted_access(),
        "threat_detection": evaluate_threat_cases().as_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized_report = json.dumps(report, indent=2)
    args.output.write_text(f"{serialized_report}\n", encoding="utf-8")
    print(serialized_report)
    print(f"\nEvaluation report saved to {args.output}")


if __name__ == "__main__":
    main()
