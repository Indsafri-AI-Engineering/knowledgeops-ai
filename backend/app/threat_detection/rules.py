import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

DETECTOR_VERSION = "fictional-rules-v1"
Severity = Literal["info", "low", "medium", "high"]


class ThreatIndicator(BaseModel):
    rule_id: str
    severity: Severity
    description: str
    evidence: str


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: Severity
    description: str
    pattern: re.Pattern[str]


RULES = (
    Rule(
        rule_id="credential-request",
        severity="high",
        description="Requests a password, authentication code, or account credential.",
        pattern=re.compile(
            r"\b(password|passcode|one[- ]time code|verification code|"
            r"authenticate|login credentials)\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        rule_id="urgent-payment",
        severity="medium",
        description="Uses urgent payment or transfer language.",
        pattern=re.compile(
            r"\b(urgent(?:ly)?|immediately|wire transfer|gift card|"
            r"payment today|transfer funds)\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        rule_id="impersonation-language",
        severity="medium",
        description="Claims authority or asks to bypass normal verification.",
        pattern=re.compile(
            r"\b(keep this confidential|bypass (?:the )?(?:usual )?process|"
            r"do not verify|pretend to be|on behalf of the ceo)\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        rule_id="suspicious-file-reference",
        severity="medium",
        description="References an executable or script attachment.",
        pattern=re.compile(
            r"\b[\w.-]+\.(?:exe|scr|bat|cmd|js|vbs|ps1)\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        rule_id="prompt-injection-text",
        severity="low",
        description="Contains text that resembles an instruction to override system rules.",
        pattern=re.compile(
            r"\b(ignore (?:all )?(?:previous|prior) instructions|"
            r"reveal (?:the )?(?:system prompt|secret)|disable (?:security|safety) rules)\b",
            re.IGNORECASE,
        ),
    ),
)


def detect_text_indicators(text: str) -> list[ThreatIndicator]:
    indicators: list[ThreatIndicator] = []
    for rule in RULES:
        match = rule.pattern.search(text)
        if match:
            indicators.append(
                ThreatIndicator(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    description=rule.description,
                    evidence=match.group(0),
                )
            )
    return indicators
