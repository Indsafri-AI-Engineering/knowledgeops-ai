import os
from pathlib import Path
import tempfile

import pytest

os.environ["APP_ENV"] = "test"
os.environ["ENABLE_TEST_FIXTURES"] = "true"
os.environ["AUTH_MODE"] = "demo"
os.environ["KNOWLEDGE_SEED_DIRECTORY"] = str(
    Path(__file__).resolve().parent / "fixtures" / "fictional_demo"
)
_TEST_RUNTIME_DIRECTORY = tempfile.TemporaryDirectory(
    prefix="knowledgeops-test-runtime-"
)
_TEST_RUNTIME_PATH = Path(_TEST_RUNTIME_DIRECTORY.name)
os.environ["KNOWLEDGE_STORE_PATH"] = str(_TEST_RUNTIME_PATH / "knowledge.json")
os.environ["AUDIT_LOG_PATH"] = str(_TEST_RUNTIME_PATH / "audit.jsonl")
os.environ["SECURITY_ALERTS_PATH"] = str(
    _TEST_RUNTIME_PATH / "security_alerts.json"
)
os.environ.pop("N8N_ALERT_WEBHOOK_URL", None)
os.environ.pop("N8N_ALERT_WEBHOOK_TOKEN", None)
os.environ.pop("N8N_JIRA_WEBHOOK_URL", None)
os.environ.pop("N8N_JIRA_WEBHOOK_TOKEN", None)
for key in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
    os.environ.pop(key, None)
os.environ["SECURITY_DENIAL_THRESHOLD"] = "5"
os.environ["SECURITY_DENIAL_WINDOW_SECONDS"] = "300"
os.environ["SECURITY_DENIAL_ALERT_COOLDOWN_SECONDS"] = "600"
os.environ["JIRA_ACTIONS_PATH"] = str(_TEST_RUNTIME_PATH / "jira_actions.json")
os.environ["JIRA_CREATED_ISSUES_PATH"] = str(
    _TEST_RUNTIME_PATH / "jira_created_issues.json"
)
for key in (
    "RAG_EMBEDDING_PROVIDER",
    "RAG_GENERATION_BACKEND",
    "AI_DATA_CLASS",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "QDRANT_LOCAL_PATH",
):
    os.environ.pop(key, None)
os.environ["RAG_BACKEND"] = "local"


@pytest.fixture(autouse=True)
def reset_security_event_monitor():
    from backend.app.threat_detection.monitor import reset_monitor_state

    reset_monitor_state()
    yield
    reset_monitor_state()
