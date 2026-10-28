import json
from pathlib import Path

import pytest

from backend.app.knowledge.index import get_knowledge_index

CASES_PATH = Path(__file__).parents[1] / "evaluation" / "retrieval_cases.json"


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_retrieval_benchmark_mrr_at_three(mode: str) -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    index = get_knowledge_index()
    reciprocal_ranks = []

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
        reciprocal_ranks.append(1 / rank if rank is not None else 0)

    mrr_at_three = sum(reciprocal_ranks) / len(reciprocal_ranks)
    assert mrr_at_three >= 0.75
