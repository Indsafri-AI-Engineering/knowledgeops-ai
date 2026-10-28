import json
from pathlib import Path

from backend.app.core.demo_auth import DEMO_USERS
from backend.app.core.permissions import user_scopes
from backend.app.knowledge.ingestion import load_knowledge_chunks
from backend.app.knowledge.retrieval import LocalKnowledgeIndex
from backend.app.orchestration.routing import route_question
from backend.app.orchestration.service import orchestrate_request
from backend.app.threat_detection.evaluation import evaluate_threat_cases

EVALUATION_CASE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "tests" / "evaluation"
)
RETRIEVAL_CASE_PATH = EVALUATION_CASE_DIRECTORY / "retrieval_cases.json"
ROUTING_CASE_PATH = EVALUATION_CASE_DIRECTORY / "routing_cases.json"
ACCESS_CASE_PATH = EVALUATION_CASE_DIRECTORY / "access_cases.json"
EVALUATION_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "fictional_demo"
)


def _evaluation_index() -> LocalKnowledgeIndex:
    return LocalKnowledgeIndex(load_knowledge_chunks(EVALUATION_FIXTURE_DIRECTORY))


def evaluate_retrieval() -> dict[str, dict[str, float]]:
    cases = json.loads(RETRIEVAL_CASE_PATH.read_text(encoding="utf-8"))
    index = _evaluation_index()
    report: dict[str, dict[str, float]] = {}
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
                    if result.chunk.document_id == case["expected_document_id"]
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
        def search(self, *args, **kwargs):
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
    report = {
        "scope": "fictional deterministic smoke evaluation; not a production quality claim",
        "retrieval": evaluate_retrieval(),
        "routing": evaluate_routing(),
        "restricted_access": evaluate_restricted_access(),
        "threat_detection": evaluate_threat_cases().as_dict(),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
