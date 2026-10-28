"""Evaluate deterministic threat rules against labeled fictional cases."""

import json
from pathlib import Path
from typing import Any

from backend.app.evaluation.metrics import (
    BinaryClassificationMetrics,
    binary_classification_metrics,
)
from backend.app.threat_detection.document_security import inspect_document_content
from backend.app.threat_detection.scanner import scan_document, scan_email, scan_url

CASE_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "fictional_demo"
    / "threat_test_fixtures"
    / "evaluation_cases.json"
)


def _scan_case(case: dict[str, Any]) -> bool:
    artifact_type = case["artifact_type"]
    payload = case["input"]
    if artifact_type == "url":
        result = scan_url(payload["url"])
    elif artifact_type == "email":
        result = scan_email(payload["email_text"])
    elif artifact_type == "document":
        result = scan_document(payload["filename"], payload["text"])
    elif artifact_type == "document_security":
        return bool(inspect_document_content(payload["text"]))
    else:
        raise ValueError(f"Unsupported threat evaluation artifact type: {artifact_type}")
    return bool(result.indicators)


def evaluate_threat_cases(
    cases_path: Path = CASE_PATH,
) -> BinaryClassificationMetrics:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError(
            f"Threat evaluation cases must contain a JSON array: {cases_path}"
        )
    expected: list[bool] = []
    predicted: list[bool] = []
    for case in cases:
        expected.append(bool(case["expected_indicator"]))
        predicted.append(_scan_case(case))
    return binary_classification_metrics(expected, predicted)
