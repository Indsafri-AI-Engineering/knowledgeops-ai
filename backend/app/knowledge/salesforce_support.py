from typing import Literal

from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.retrieval import KnowledgeIndex

SalesforceLoginSymptom = Literal[
    "sign_in_page",
    "password_rejected",
    "mfa_problem",
    "account_locked",
    "browser_error",
]

_SYMPTOM_GUIDANCE: dict[
    SalesforceLoginSymptom,
    tuple[str, list[str], str],
] = {
    "sign_in_page": (
        "Salesforce company sign-in page",
        [
            "Open Salesforce from the company-approved bookmark or portal.",
            "Do not use an unexpected sign-in link from a message.",
            "If the approved page is unavailable, contact the fictional IT Service Desk.",
        ],
        "Tell the Service Desk which approved portal you used and the time of the issue.",
    ),
    "password_rejected": (
        "Salesforce password rejected account password reset",
        [
            "Check that the correct fictional Northstar Works account is selected.",
            "Use only the company-approved password reset process.",
            "Never send a password or verification code to support staff.",
        ],
        "If the approved reset does not resolve the issue, contact the fictional IT Service Desk.",
    ),
    "mfa_problem": (
        "Salesforce multi-factor authentication MFA authenticator verification code",
        [
            "Use the configured company authenticator for the sign-in request.",
            "Check that the request is for the expected company sign-in.",
            "Never share a verification code with support staff.",
        ],
        "If the expected prompt does not appear, contact the fictional IT Service Desk; do not bypass MFA.",
    ),
    "account_locked": (
        "Salesforce account locked account sign-in error",
        [
            "Stop repeated sign-in attempts if the account is reported as locked.",
            "Record the exact displayed error without including a password or code.",
            "Contact the fictional IT Service Desk to review the account lock.",
        ],
        "Account unlocks require the fictional Service Desk; this demo cannot access or change an account.",
    ),
    "browser_error": (
        "Salesforce login browser sign-in error exact error text",
        [
            "Confirm that the browser is using the company-approved sign-in page.",
            "Check that the account name is entered correctly.",
            "Record the exact displayed error text without including secrets.",
        ],
        "If sign-in still fails, contact the fictional IT Service Desk and provide the displayed error text.",
    ),
}


class SalesforceLoginGuide(BaseModel):
    symptom: SalesforceLoginSymptom
    steps: list[str]
    escalation: str
    source_document_ids: list[str]


def _prepare_retrieval(
    request: dict[str, object],
) -> dict[str, object]:
    symptom = request["symptom"]
    if symptom not in _SYMPTOM_GUIDANCE:
        raise ValueError("Unsupported Salesforce login symptom.")
    query, _, _ = _SYMPTOM_GUIDANCE[symptom]
    return {
        "symptom": symptom,
        "query": query,
        "index": request["index"],
        "allowed_scopes": request["allowed_scopes"],
    }


def _retrieve_evidence(request: dict[str, object]) -> dict[str, object]:
    index = request["index"]
    if not isinstance(index, KnowledgeIndex):
        raise TypeError("Login guidance requires a supported knowledge index.")
    allowed_scopes = request["allowed_scopes"]
    if not isinstance(allowed_scopes, set):
        raise TypeError("Allowed knowledge scopes must be a set.")
    results = index.search(
        str(request["query"]),
        allowed_scopes,
        limit=3,
        mode="hybrid",
    )
    document_ids = list(dict.fromkeys(result.chunk.document_id for result in results))
    return {**request, "source_document_ids": document_ids}


def _format_guide(request: dict[str, object]) -> SalesforceLoginGuide:
    symptom = request["symptom"]
    if symptom not in _SYMPTOM_GUIDANCE:
        raise ValueError("Unsupported Salesforce login symptom.")
    _, steps, escalation = _SYMPTOM_GUIDANCE[symptom]
    source_document_ids = request["source_document_ids"]
    if not isinstance(source_document_ids, list):
        raise TypeError("Retrieved source identifiers must be a list.")
    if not source_document_ids:
        return SalesforceLoginGuide(
            symptom=symptom,
            steps=[],
            escalation="No supporting fictional guide was found. Contact the IT Service Desk.",
            source_document_ids=[],
        )
    return SalesforceLoginGuide(
        symptom=symptom,
        steps=steps,
        escalation=escalation,
        source_document_ids=source_document_ids,
    )


salesforce_login_chain = (
    RunnableLambda(_prepare_retrieval)
    | RunnableLambda(_retrieve_evidence)
    | RunnableLambda(_format_guide)
)


def troubleshoot_salesforce_login(
    symptom: SalesforceLoginSymptom,
    allowed_scopes: set[str],
    index: KnowledgeIndex | None = None,
) -> SalesforceLoginGuide:
    return salesforce_login_chain.invoke(
        {
            "symptom": symptom,
            "allowed_scopes": allowed_scopes,
            "index": index or get_knowledge_index(),
        }
    )
