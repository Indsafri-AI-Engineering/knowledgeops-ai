import json
from pathlib import Path

from pydantic import BaseModel

from backend.app.knowledge.retrieval import TOKEN_PATTERN

FAQ_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "fictional_demo"
    / "faqs.json"
)


class FAQItem(BaseModel):
    faq_id: str
    question: str
    access_scope: str
    keywords: list[str]


def _faq_items() -> list[FAQItem]:
    payload = json.loads(FAQ_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"FAQ catalogue must contain a JSON array: {FAQ_PATH}")
    return [FAQItem.model_validate(item) for item in payload]


def suggest_faqs(query: str, allowed_scopes: set[str], limit: int = 5) -> list[FAQItem]:
    eligible = [item for item in _faq_items() if item.access_scope in allowed_scopes]
    if not query.strip():
        return eligible[:limit]

    query_terms = set(TOKEN_PATTERN.findall(query.lower()))
    scored: list[tuple[int, int, FAQItem]] = []
    for order, item in enumerate(eligible):
        searchable = " ".join([item.question, *item.keywords]).lower()
        item_terms = set(TOKEN_PATTERN.findall(searchable))
        overlap = len(query_terms & item_terms)
        if overlap:
            scored.append((overlap, -order, item))
    scored.sort(key=lambda result: (-result[0], -result[1]))
    return [item for _, _, item in scored[:limit]]
