import os
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Literal

from fastapi import Request

from backend.app.knowledge.retrieval import RetrievedChunk
from backend.app.storage.audit import AuditLog, AuditOutcome

ModerationStage = Literal["input", "retrieval", "output", "action"]
ModerationOutcome = Literal["allowed", "blocked", "flagged", "clarification_required"]
ModerationSeverity = Literal["low", "medium", "high", "critical"]
POLICY_VERSION = "local-rules-v1"

BLOCKED_INPUT_MESSAGE = (
    "I can’t help disclose protected secrets, bypass access controls, or follow "
    "instructions that override the workspace’s safety rules. Ask a permitted "
    "knowledge question instead."
)
OUT_OF_SCOPE_MESSAGE = (
    "I can help answer questions using knowledge sources available to your "
    "workspace. Please ask about a policy, process, or team resource."
)
AMBIGUOUS_MESSAGE = (
    "Could you clarify what policy, process, or resource you mean?"
)
UNSAFE_ANSWER_MESSAGE = (
    "I couldn’t provide that answer safely from the permitted sources. Please "
    "ask a more specific question or check the source material."
)


@dataclass(frozen=True)
class ModerationDecision:
    stage: ModerationStage
    outcome: ModerationOutcome
    category: str
    severity: ModerationSeverity
    rule_id: str
    reason_code: str


_SECRET_REQUEST = re.compile(
    r"\b(?:show|reveal|print|dump|expose|extract|share|send)\b.{0,35}\b"
    r"(?:passwords?|api[\s_-]?keys?|access[\s_-]?tokens?|bearer[\s_-]?tokens?|"
    r"credentials?|client secrets?)\b"
    r"|\b(?:give|provide|return|tell)\s+(?:me\s+)?"
    r"(?:(?:the|all|any|actual|real|your|their)\s+)?"
    r"(?:passwords?|api[\s_-]?keys?|access[\s_-]?tokens?|bearer[\s_-]?tokens?|"
    r"credentials?|client secrets?)\b",
    re.IGNORECASE,
)
_ACCESS_BYPASS = re.compile(
    r"\b(?:bypass|circumvent|override|ignore)\b.{0,80}\b"
    r"(?:permissions?|authorization|access controls?|role restrictions?|"
    r"security rules?)\b",
    re.IGNORECASE,
)
_INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|override|forget)\b.{0,80}\b"
    r"(?:previous|prior|system|developer|safety|workspace)\s+"
    r"(?:instructions?|rules?|policies?)\b"
    r"|\b(?:reveal|print|show|dump)\b.{0,50}\b(?:system prompt|hidden prompt)\b",
    re.IGNORECASE,
)
_HARMFUL_REQUEST = re.compile(
    r"\b(?:write|create|build|deploy)\b.{0,100}\b"
    r"(?:ransomware|malware|credential stealer|keylogger)\b"
    r"|\b(?:steal|exfiltrate)\b.{0,60}\b(?:passwords?|credentials?|tokens?)\b"
    r"|\bphishing email\b.{0,60}\b(?:steal|capture|harvest)\b",
    re.IGNORECASE,
)
_TARGETED_ABUSE = re.compile(
    r"\b(?:you are|you’re|youre)\s+(?:a\s+)?(?:stupid|useless|idiot|moron)\b"
    r"|\bshut up,?\s+(?:you|idiot|moron)\b",
    re.IGNORECASE,
)
_OUT_OF_SCOPE = re.compile(
    r"^\s*(?:write|compose)\s+(?:me\s+)?(?:a\s+)?(?:poem|song|fictional story)\b"
    r"|^\s*tell\s+me\s+(?:a\s+)?joke\b",
    re.IGNORECASE,
)
_AMBIGUOUS = re.compile(
    r"^\s*(?:what about (?:it|that|them)|tell me more|explain this|"
    r"can you clarify that)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
_SUSPICIOUS_DOCUMENT_SENTENCE = re.compile(
    r"\b(?:ignore|disregard|override)\b.{0,80}\b"
    r"(?:system|developer|previous|prior)\s+instructions?\b"
    r"|\b(?:reveal|print|dump|expose)\b.{0,60}\b"
    r"(?:secrets?|credentials?|system prompt|api[\s_-]?keys?)\b"
    r"|\b(?:use|call|invoke)\b.{0,50}\b(?:jira|n8n|external tool)\b"
    r".{0,60}\b(?:without approval|bypass|secret|token)\b",
    re.IGNORECASE,
)
_EXPLANATORY_CONTEXT = re.compile(
    r"\b(?:example|attacker|awareness|training|explain|describes|demonstrates|"
    r"illustrates|quote|quoted|fictional)\b",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"\b(?:api[\s_-]?key|access[\s_-]?token|client[\s_-]?secret|"
    r"password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/-]{8,}"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]{16,}"
    r"|\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b",
    re.IGNORECASE,
)
_CITATION_LABEL = re.compile(r"\[S(\d+)\]")
_NON_CLAIM_SENTENCE = re.compile(
    r"^\s*(?:based on the available source material|"
    r"please check the cited source for context and any applicable exceptions|"
    r"evidence[- ]bounded analysis)\s*[.!:]?\s*$",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "can",
        "could", "do", "does", "for", "from", "how", "i", "if", "in",
        "is", "it", "of", "on", "or", "the", "this", "to", "was", "what",
        "when", "where", "which", "who", "why", "with", "you",
    }
)


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _max_input_chars() -> int:
    max_length = int(os.getenv("MODERATION_MAX_INPUT_CHARS", "2000"))
    if not 1 <= max_length <= 2000:
        raise ValueError("MODERATION_MAX_INPUT_CHARS must be between 1 and 2000.")
    return max_length


def _minimum_answer_support() -> float:
    threshold = float(os.getenv("MODERATION_MIN_ANSWER_SUPPORT", "0.35"))
    if not 0 <= threshold <= 1:
        raise ValueError("MODERATION_MIN_ANSWER_SUPPORT must be between 0 and 1.")
    return threshold


def _decision(
    stage: ModerationStage,
    outcome: ModerationOutcome,
    category: str,
    severity: ModerationSeverity,
    rule_id: str,
    reason_code: str,
) -> ModerationDecision:
    return ModerationDecision(
        stage=stage,
        outcome=outcome,
        category=category,
        severity=severity,
        rule_id=rule_id,
        reason_code=reason_code,
    )


def moderate_input(text: str) -> ModerationDecision:
    normalized = _normalized(text)
    if not normalized:
        return _decision(
            "input", "blocked", "invalid_input", "medium", "input-empty",
            "empty_input",
        )
    max_length = _max_input_chars()
    if len(normalized) > max_length:
        return _decision(
            "input", "blocked", "invalid_input", "medium", "input-too-long",
            "input_length_exceeded",
        )
    rules = (
        (_SECRET_REQUEST, "secret_disclosure", "critical", "input-secret-request"),
        (_ACCESS_BYPASS, "access_bypass", "critical", "input-access-bypass"),
        (
            _INSTRUCTION_OVERRIDE,
            "prompt_injection",
            "high",
            "input-instruction-override",
        ),
        (_HARMFUL_REQUEST, "harmful_assistance", "high", "input-harmful-request"),
        (_TARGETED_ABUSE, "targeted_abuse", "medium", "input-targeted-abuse"),
    )
    for pattern, category, severity, rule_id in rules:
        if pattern.search(normalized):
            return _decision(
                "input", "blocked", category, severity, rule_id, category
            )
    if _OUT_OF_SCOPE.search(normalized):
        return _decision(
            "input", "clarification_required", "out_of_scope", "low",
            "input-out-of-scope", "unsupported_task",
        )
    if _AMBIGUOUS.fullmatch(normalized):
        return _decision(
            "input", "clarification_required", "ambiguous", "low",
            "input-ambiguous", "needs_context",
        )
    return _decision(
        "input", "allowed", "benign", "low", "input-allowed", "no_rule_matched"
    )


def inspect_retrieved_chunks(
    chunks: list[RetrievedChunk],
) -> tuple[list[RetrievedChunk], list[str]]:
    safe_chunks: list[RetrievedChunk] = []
    matched_rules: set[str] = set()
    for result in chunks:
        sentences = _SENTENCE_BOUNDARY.split(result.chunk.text)
        safe_sentences: list[str] = []
        for sentence in sentences:
            if (
                _SUSPICIOUS_DOCUMENT_SENTENCE.search(sentence)
                and not _EXPLANATORY_CONTEXT.search(sentence)
            ):
                matched_rules.add("retrieval-instruction-injection")
            else:
                safe_sentences.append(sentence)
        sanitized_text = " ".join(safe_sentences).strip()
        if sanitized_text:
            safe_chunks.append(
                replace(result, chunk=replace(result.chunk, text=sanitized_text))
            )
    return safe_chunks, sorted(matched_rules)


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(text.lower())
        if token not in _STOP_WORDS and len(token) > 1
    }


def moderate_output(
    answer: str,
    *,
    retrieved_contexts: list[str] | None = None,
    source_count: int = 0,
) -> ModerationDecision:
    threshold = _minimum_answer_support()
    if _SECRET_VALUE.search(answer):
        return _decision(
            "output", "blocked", "secret_disclosure", "critical",
            "output-secret-value", "synthetic_or_credential_pattern",
        )

    citation_numbers = [
        int(match.group(1)) for match in _CITATION_LABEL.finditer(answer)
    ]
    if any(number < 1 or number > source_count for number in citation_numbers):
        return _decision(
            "output", "blocked", "invalid_citation", "high",
            "output-invalid-citation", "citation_not_in_permitted_sources",
        )

    if retrieved_contexts and answer.strip():
        combined_context = " ".join(retrieved_contexts)
        evidence_tokens = _content_tokens(combined_context)
        normalized_answer = _CITATION_LABEL.sub("", answer)
        answer_numbers = set(_NUMBER.findall(normalized_answer))
        evidence_numbers = set(_NUMBER.findall(combined_context))
        if answer_numbers - evidence_numbers:
            return _decision(
                "output", "blocked", "unsupported_answer", "high",
                "output-unsupported-number", "numeric_claim_not_in_evidence",
            )
        sentences = []
        for sentence in _SENTENCE_BOUNDARY.split(answer):
            without_citations = _CITATION_LABEL.sub("", sentence).strip()
            if (
                _content_tokens(without_citations)
                and not _NON_CLAIM_SENTENCE.fullmatch(without_citations)
            ):
                sentences.append(without_citations)
        support = [
            len(tokens & evidence_tokens) / len(tokens)
            for sentence in sentences
            if (tokens := _content_tokens(sentence))
        ]
        average_support = sum(support) / len(support) if support else 0.0
        if support and average_support < threshold:
            return _decision(
                "output", "blocked", "unsupported_answer", "medium",
                "output-insufficient-evidence", "lexical_support_below_threshold",
            )
        if any(value < 0.25 for value in support):
            return _decision(
                "output", "flagged", "partially_unsupported", "low",
                "output-unsupported-sentence", "sentence_support_is_low",
            )

    return _decision(
        "output", "allowed", "safe_answer", "low", "output-allowed",
        "no_output_rule_matched",
    )


def record_moderation_event(
    decision: ModerationDecision,
    *,
    request: Request,
    actor_id: str,
    metadata: dict[str, str | int | bool] | None = None,
) -> None:
    outcome: AuditOutcome = (
        "denied" if decision.outcome == "blocked" else "success"
    )
    event_metadata: dict[str, str | int | bool] = {
        "stage": decision.stage,
        "moderation_outcome": decision.outcome,
        "category": decision.category,
        "severity": decision.severity,
        "rule_id": decision.rule_id,
        "reason_code": decision.reason_code,
        "policy_version": POLICY_VERSION,
    }
    if metadata:
        event_metadata.update(metadata)
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=actor_id,
        action=f"moderation.{decision.stage}",
        resource_type="moderation",
        outcome=outcome,
        metadata=event_metadata,
    )
