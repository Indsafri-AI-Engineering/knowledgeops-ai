import os

from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.audit import router as audit_router
from backend.app.api.v1.chat import router as chat_router
from backend.app.api.v1.connectors import router as connectors_router
from backend.app.api.v1.observability import router as observability_router
from backend.app.api.v1.jira import router as jira_router
from backend.app.api.v1.knowledge_documents import router as knowledge_documents_router
from backend.app.api.v1.system_status import router as system_status_router
from backend.app.api.v1.security_alerts import router as security_alerts_router
from backend.app.api.v1.threat_scans import router as threat_scans_router
from fastapi import APIRouter, Depends
from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(chat_router)
router.include_router(audit_router)
if os.getenv("ENABLE_TEST_FIXTURES", "").lower() == "true":
    router.include_router(connectors_router)
router.include_router(threat_scans_router)
router.include_router(security_alerts_router)
router.include_router(observability_router)
router.include_router(system_status_router)
router.include_router(jira_router)
router.include_router(knowledge_documents_router)


@router.get("/health", tags=["health"])
def api_health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/me", response_model=DemoUser, tags=["authentication"])
def read_current_user(user: DemoUser = Depends(get_current_user)) -> DemoUser:
    return user
