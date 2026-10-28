import re
from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile

from backend.app.threat_detection.rules import Severity, ThreatIndicator

_SECRET_ASSIGNMENT = re.compile(
    r"\b(?:api[_-]?key|client[_-]?secret|password|passwd|secret|"
    r"access[_-]?token|refresh[_-]?token|private[_-]?key)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}",
    re.IGNORECASE,
)
_PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_SSN = re.compile(r"\b(?!000|666|9\d{2})\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b")
_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_BEARER_TOKEN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE)
_EMAIL_ADDRESS = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_CONFIDENTIAL_LABEL = re.compile(
    r"\b(?:strictly confidential|highly confidential|restricted data)\b",
    re.IGNORECASE,
)
_MACRO_PARTS = (
    "word/vbaproject.bin",
    "xl/vbaproject.bin",
    "ppt/vbaproject.bin",
)


def _indicator(
    rule_id: str,
    severity: Severity,
    description: str,
    line: int | None = None,
) -> ThreatIndicator:
    evidence = f"line {line}" if line is not None else "artifact structure"
    return ThreatIndicator(
        rule_id=rule_id,
        severity=severity,
        description=description,
        evidence=evidence,
    )


def inspect_document_content(text: str) -> list[ThreatIndicator]:
    indicators: list[ThreatIndicator] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        checks = (
            (
                "document-secret-assignment",
                "high",
                "A line resembles an embedded credential or secret assignment.",
                _SECRET_ASSIGNMENT,
            ),
            (
                "document-private-key",
                "high",
                "A private-key PEM marker is present.",
                _PRIVATE_KEY_HEADER,
            ),
            (
                "document-cloud-access-key",
                "high",
                "A cloud access-key identifier pattern is present.",
                _AWS_ACCESS_KEY,
            ),
            (
                "document-bearer-token",
                "high",
                "A bearer-token-like value is present.",
                _BEARER_TOKEN,
            ),
            (
                "document-national-id",
                "high",
                "A US Social Security number pattern is present.",
                _SSN,
            ),
            (
                "document-personal-email",
                "medium",
                "An email address is present and may contain personal information.",
                _EMAIL_ADDRESS,
            ),
            (
                "document-confidential-label",
                "medium",
                "The document contains a restricted or confidential classification label.",
                _CONFIDENTIAL_LABEL,
            ),
        )
        for rule_id, severity, description, pattern in checks:
            if rule_id in seen or not pattern.search(line):
                continue
            seen.add(rule_id)
            indicators.append(
                _indicator(rule_id, severity, description, line_number)
            )
        if "document-payment-card" not in seen:
            for match in _PAYMENT_CARD.finditer(line):
                digits = "".join(character for character in match.group(0) if character.isdigit())
                if _luhn_valid(digits):
                    seen.add("document-payment-card")
                    indicators.append(
                        _indicator(
                            "document-payment-card",
                            "high",
                            "A payment-card-number pattern passed a checksum check.",
                            line_number,
                        )
                    )
                    break
    return indicators


def _luhn_valid(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def inspect_document_preflight(
    filename: str,
    file_bytes: bytes,
) -> list[ThreatIndicator]:
    extension = PurePath(filename).suffix.lower()
    indicators = (
        inspect_document_content(file_bytes.decode("utf-8", errors="ignore"))
        if extension in {".txt", ".md", ".html"}
        else []
    )
    if extension not in {".docx", ".xlsx", ".pptx"} or not file_bytes.startswith(b"PK"):
        return indicators

    try:
        with ZipFile(BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
    except BadZipFile:
        return indicators

    names = {entry.filename.lower() for entry in entries}
    if any(part in names for part in _MACRO_PARTS):
        indicators.append(
            _indicator(
                "document-office-macro",
                "high",
                "The Office package contains a VBA macro project.",
            )
        )
    return indicators
