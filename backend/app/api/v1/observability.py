from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.observability import request_metrics
from backend.app.core.permissions import require_capability
from backend.app.knowledge.index import get_knowledge_index

router = APIRouter(prefix="/observability", tags=["observability"])


class RetrievalCacheMetrics(BaseModel):
    hits: int
    misses: int
    entries: int
    max_entries: int


class RequestMetric(BaseModel):
    method: str
    route: str
    status_code: int
    count: int
    duration_seconds_total: float
    duration_seconds_max: float


class ObservabilitySnapshot(BaseModel):
    requests: list[RequestMetric]
    retrieval_cache: RetrievalCacheMetrics


@router.get("/metrics", response_model=ObservabilitySnapshot)
def read_metrics(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> ObservabilitySnapshot:
    require_capability(user, "system:admin", request)
    index = get_knowledge_index()
    return ObservabilitySnapshot(
        requests=[
            RequestMetric.model_validate(item)
            for item in request_metrics.snapshot()
        ],
        retrieval_cache=RetrievalCacheMetrics.model_validate(index.cache_info()),
    )
