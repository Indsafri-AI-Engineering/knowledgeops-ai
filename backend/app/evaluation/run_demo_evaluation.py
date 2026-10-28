import json
from pathlib import Path

from backend.app.knowledge.index import get_knowledge_index
from backend.app.threat_detection.evaluation import evaluate_threat_cases

RETRIEVAL_CASE_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "evaluation"
    / "retrieval_cases.json"
)


def evaluate_retrieval() -> dict[str, dict[str, float]]:
    cases = json.loads(RETRIEVAL_CASE_PATH.read_text(encoding="utf-8"))
    index = get_knowledge_index()
    report: dict[str, dict[str, float]] = {}
    for mode in ("vector", "keyword", "hybrid"):
        reciprocal_ranks: list[float] = []
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
        report[mode] = {
            "mrr_at_3": sum(reciprocal_ranks) / len(reciprocal_ranks),
            "cases": len(reciprocal_ranks),
        }
    return report


def main() -> None:
    report = {
        "scope": "fictional deterministic smoke evaluation; not a production quality claim",
        "retrieval": evaluate_retrieval(),
        "threat_detection": evaluate_threat_cases().as_dict(),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
