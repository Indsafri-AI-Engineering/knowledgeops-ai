"""VirusTotal URL reputation lookups with privacy filtering and safe telemetry."""

import base64
import hashlib
import ipaddress
import re
import threading
import time
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import BaseModel, Field

from backend.app.core.config import VirusTotalSettings, get_virustotal_settings
from backend.app.threat_detection.urls import URL_PATTERN, validate_url

VIRUSTOTAL_URL_REPORTS = "https://www.virustotal.com/api/v3/urls"
_SENSITIVE_PATH = re.compile(
    r"(?:token|auth|password|passwd|secret|session|credential|"
    r"verify|verification|login|account|reset|invite|private)",
    re.IGNORECASE,
)
_EMAIL_COMPONENT = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_UUID_COMPONENT = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_OPAQUE_COMPONENT = re.compile(r"^[A-Za-z0-9_-]{24,}$")
_PUBLIC_HOST = re.compile(
    r"(?=.{1,253}\Z)"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}\Z"
)
_PRIVATE_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".intranet",
    ".home",
    ".test",
    ".invalid",
)

ReputationStatus = Literal[
    "malicious",
    "suspicious",
    "clean",
    "unknown",
    "provider_unavailable",
    "rate_limited",
    "authentication_failure",
    "not_configured",
    "disabled",
    "privacy_filtered",
]


class VirusTotalURLResult(BaseModel):
    status: ReputationStatus
    redacted_url: str
    malicious: int | None = None
    suspicious: int | None = None
    harmless: int | None = None
    undetected: int | None = None
    detection_ratio: str | None = None
    analysis_status: str = "unknown"
    last_analysis_at: datetime | None = None
    checked_at: datetime
    reason: str | None = None


class VirusTotalDocumentSummary(BaseModel):
    enabled: bool
    provider_status: str
    urls_detected: int
    malicious_count: int
    suspicious_count: int
    clean_count: int
    unknown_count: int
    provider_unavailable_count: int
    rate_limited_count: int
    authentication_failure_count: int
    ingestion_blocked: bool = False
    results: list[VirusTotalURLResult] = Field(default_factory=list)


class VirusTotalProviderStatus(BaseModel):
    enabled: bool
    api_key_configured: bool
    connection_status: str
    last_successful_check: datetime | None = None
    last_check: datetime | None = None
    last_error: str | None = None
    privacy_policy: str
    failure_policy: str


_STATE_LOCK = threading.RLock()
_CACHE: dict[str, tuple[float, VirusTotalURLResult]] = {}
_LAST_CHECK: datetime | None = None
_LAST_SUCCESSFUL_CHECK: datetime | None = None
_LAST_ERROR: str | None = None
_RATE_LIMITED_UNTIL = 0.0
_CONNECTION_STATUS = "not_checked"


def _now() -> datetime:
    return datetime.now(UTC)


def _redacted_url(value: str) -> str:
    try:
        _, hostname = validate_url(value)
    except ValueError:
        return "[invalid URL]"
    return f"{hostname} (URL path and query redacted)"


def _is_public_host(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(_PRIVATE_SUFFIXES):
        return False
    if not _PUBLIC_HOST.fullmatch(hostname) or _EMAIL_COMPONENT.search(hostname):
        return False
    labels = hostname.split(".")
    if any(
        _UUID_COMPONENT.fullmatch(label) or _OPAQUE_COMPONENT.fullmatch(label)
        for label in labels
    ):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return not any(character.isspace() for character in hostname)
    return address.is_global


def _privacy_reason(
    url: str,
    policy: str,
    allowed_domains: tuple[str, ...],
) -> str | None:
    if policy == "disabled":
        return "privacy_policy_disabled"
    try:
        normalized, hostname = validate_url(url)
    except ValueError:
        return "invalid_url"
    parsed = urlsplit(normalized)
    if not _is_public_host(hostname):
        return "non_public_host"
    if allowed_domains and not any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in allowed_domains
    ):
        return "domain_not_allowlisted"
    if parsed.query:
        return "query_parameters_not_shared"
    path = unquote(parsed.path).strip("/")
    if policy == "public_root_urls" and path:
        return "non_root_url_not_shared"
    if path:
        components = path.split("/")
        if (
            _SENSITIVE_PATH.search(path)
            or _EMAIL_COMPONENT.search(path)
            or _UUID_COMPONENT.search(path)
            or any(_OPAQUE_COMPONENT.fullmatch(part) for part in components)
        ):
            return "sensitive_path_not_shared"
    return None


def _result(
    status: ReputationStatus,
    url: str,
    *,
    reason: str | None = None,
    **values: object,
) -> VirusTotalURLResult:
    return VirusTotalURLResult(
        status=status,
        redacted_url=_redacted_url(url),
        checked_at=_now(),
        reason=reason,
        **values,
    )


def _url_identifier(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def _count(stats: object, key: str) -> int | None:
    if not isinstance(stats, dict):
        return None
    value = stats.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class VirusTotalService:
    def __init__(
        self,
        settings: VirusTotalSettings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_virustotal_settings()
        self._transport = transport

    def lookup_url(self, url: str) -> VirusTotalURLResult:
        global _CONNECTION_STATUS, _LAST_CHECK, _LAST_ERROR
        global _LAST_SUCCESSFUL_CHECK, _RATE_LIMITED_UNTIL

        try:
            normalized, _ = validate_url(url)
        except ValueError:
            return _result("privacy_filtered", url, reason="invalid_url")
        redacted = _redacted_url(normalized)

        if not self.settings.enabled:
            return _result("disabled", normalized, reason="provider_disabled")
        privacy_reason = _privacy_reason(
            normalized,
            self.settings.privacy_policy,
            self.settings.allowed_domains,
        )
        if privacy_reason:
            return _result("privacy_filtered", normalized, reason=privacy_reason)
        if not self.settings.api_key_configured:
            self._record_status("missing_api_key", "missing_api_key")
            return _result("not_configured", normalized, reason="missing_api_key")

        cache_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        now = time.monotonic()
        with _STATE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and cached[0] > now:
                return cached[1].model_copy(update={"redacted_url": redacted})
            if now < _RATE_LIMITED_UNTIL:
                return _result(
                    "rate_limited",
                    normalized,
                    reason="provider_rate_limit_cooldown",
                )

        try:
            with httpx.Client(
                timeout=self.settings.timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = client.get(
                    f"{VIRUSTOTAL_URL_REPORTS}/{_url_identifier(normalized)}",
                    headers={"x-apikey": self.settings.api_key},
                )
        except httpx.TimeoutException:
            self._record_status("unavailable", "timeout")
            return _result("provider_unavailable", normalized, reason="timeout")
        except httpx.RequestError:
            self._record_status("unavailable", "network_error")
            return _result("provider_unavailable", normalized, reason="network_error")

        with _STATE_LOCK:
            _LAST_CHECK = _now()

        if response.status_code in {401, 403}:
            self._record_status("authentication_failure", "authentication_failure")
            return _result(
                "authentication_failure",
                normalized,
                reason="provider_authentication_failure",
            )
        if response.status_code == 404:
            self._record_status("connected", None, successful=True)
            return self._cache_result(
                cache_key,
                _result("unknown", normalized, reason="no_existing_report"),
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            try:
                cooldown = min(max(int(retry_after), 1), 3600)
            except ValueError:
                cooldown = 60
            with _STATE_LOCK:
                _RATE_LIMITED_UNTIL = time.monotonic() + cooldown
            self._record_status("rate_limited", "rate_limited")
            return _result("rate_limited", normalized, reason="provider_rate_limit")
        if response.status_code >= 500:
            self._record_status("unavailable", "provider_error")
            return _result("provider_unavailable", normalized, reason="provider_error")
        if response.status_code != 200:
            self._record_status("unavailable", "unexpected_status")
            return _result(
                "provider_unavailable",
                normalized,
                reason="unexpected_provider_status",
            )

        try:
            payload = response.json()
        except ValueError:
            self._record_status("unavailable", "invalid_response")
            return _result(
                "provider_unavailable",
                normalized,
                reason="invalid_provider_response",
            )

        result = self._parse_report(normalized, payload)
        if result.status == "provider_unavailable":
            self._record_status("unavailable", "invalid_response")
            return result
        self._record_status("connected", None, successful=True)
        return self._cache_result(cache_key, result)

    def scan_document_urls(
        self,
        urls: list[str],
        *,
        suppress_external_lookup: bool = False,
    ) -> VirusTotalDocumentSummary:
        unique_urls: list[str] = []
        seen: set[str] = set()
        for value in urls:
            try:
                normalized, _ = validate_url(value)
            except ValueError:
                continue
            if normalized not in seen:
                seen.add(normalized)
                unique_urls.append(normalized)

        results: list[VirusTotalURLResult] = []
        paused_status: ReputationStatus | None = None
        for index, url in enumerate(unique_urls):
            if suppress_external_lookup:
                result = _result(
                    "privacy_filtered",
                    url,
                    reason="document_contains_sensitive_information",
                )
            elif index >= self.settings.max_urls_per_document:
                result = _result(
                    "unknown",
                    url,
                    reason="per_document_url_limit",
                )
            elif paused_status is not None:
                result = _result(
                    paused_status,
                    url,
                    reason="provider_request_skipped_after_error",
                )
            else:
                result = self.lookup_url(url)
            results.append(result)
            if result.status in {
                "provider_unavailable",
                "rate_limited",
                "authentication_failure",
                "not_configured",
            }:
                paused_status = result.status

        status = self.provider_status().connection_status
        counts = [item.status for item in results]
        return VirusTotalDocumentSummary(
            enabled=self.settings.enabled,
            provider_status=status,
            urls_detected=len(unique_urls),
            malicious_count=counts.count("malicious"),
            suspicious_count=counts.count("suspicious"),
            clean_count=counts.count("clean"),
            unknown_count=sum(
                status in {
                    "unknown",
                    "disabled",
                    "not_configured",
                    "privacy_filtered",
                }
                for status in counts
            ),
            provider_unavailable_count=counts.count("provider_unavailable"),
            rate_limited_count=counts.count("rate_limited"),
            authentication_failure_count=counts.count("authentication_failure"),
            results=results,
        )

    def provider_status(self) -> VirusTotalProviderStatus:
        with _STATE_LOCK:
            connection_status = _CONNECTION_STATUS
            if not self.settings.enabled:
                connection_status = "disabled"
            elif not self.settings.api_key_configured:
                connection_status = "missing_api_key"
            elif time.monotonic() < _RATE_LIMITED_UNTIL:
                connection_status = "rate_limited"
            return VirusTotalProviderStatus(
                enabled=self.settings.enabled,
                api_key_configured=self.settings.api_key_configured,
                connection_status=connection_status,
                last_successful_check=_LAST_SUCCESSFUL_CHECK,
                last_check=_LAST_CHECK,
                last_error=_LAST_ERROR,
                privacy_policy=self.settings.privacy_policy,
                failure_policy=self.settings.failure_policy,
            )

    def _parse_report(self, url: str, payload: object) -> VirusTotalURLResult:
        if not isinstance(payload, dict):
            return _result(
                "provider_unavailable",
                url,
                reason="invalid_provider_response",
            )
        data = payload.get("data")
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            return _result(
                "provider_unavailable",
                url,
                reason="invalid_provider_response",
            )
        stats = attributes.get("last_analysis_stats")
        malicious = _count(stats, "malicious")
        suspicious = _count(stats, "suspicious")
        harmless = _count(stats, "harmless")
        undetected = _count(stats, "undetected")
        values = (malicious, suspicious, harmless, undetected)
        total = sum(value for value in values if value is not None)
        analysis_status = "completed" if any(value is not None for value in values) else "unknown"
        timestamp = attributes.get("last_analysis_date")
        try:
            analyzed_at = (
                datetime.fromtimestamp(timestamp, UTC)
                if isinstance(timestamp, int) and not isinstance(timestamp, bool)
                else None
            )
        except (OverflowError, OSError, ValueError):
            analyzed_at = None
        ratio = (
            f"{(malicious or 0) + (suspicious or 0)}/{total}"
            if total > 0
            else None
        )
        if analysis_status != "completed" or any(value is None for value in values):
            status: ReputationStatus = "unknown"
        elif (malicious or 0) > 0:
            status = "malicious"
        elif (suspicious or 0) > 0:
            status = "suspicious"
        elif total > 0:
            status = "clean"
        else:
            status = "unknown"
        return _result(
            status,
            url,
            malicious=malicious,
            suspicious=suspicious,
            harmless=harmless,
            undetected=undetected,
            detection_ratio=ratio,
            analysis_status=analysis_status,
            last_analysis_at=analyzed_at,
            reason="analysis_incomplete" if status == "unknown" else None,
        )

    def _cache_result(
        self,
        cache_key: str,
        result: VirusTotalURLResult,
    ) -> VirusTotalURLResult:
        if self.settings.cache_ttl_seconds > 0:
            with _STATE_LOCK:
                now = time.monotonic()
                expired = [
                    key for key, (expires_at, _) in _CACHE.items()
                    if expires_at <= now
                ]
                for key in expired:
                    _CACHE.pop(key, None)
                while len(_CACHE) >= 4096:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[cache_key] = (
                    now + self.settings.cache_ttl_seconds,
                    result,
                )
        return result

    @staticmethod
    def _record_status(
        connection_status: str,
        error: str | None,
        *,
        successful: bool = False,
    ) -> None:
        global _CONNECTION_STATUS, _LAST_CHECK, _LAST_ERROR
        global _LAST_SUCCESSFUL_CHECK
        with _STATE_LOCK:
            _CONNECTION_STATUS = connection_status
            _LAST_CHECK = _now()
            _LAST_ERROR = error
            if successful:
                _LAST_SUCCESSFUL_CHECK = _LAST_CHECK


def extract_document_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_PATTERN.finditer(text):
        candidate = match.group(0).rstrip(".,);]")
        try:
            normalized, _ = validate_url(candidate)
        except ValueError:
            continue
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls


def reset_virustotal_state() -> None:
    """Reset process-local cache and provider telemetry for isolated tests."""
    global _LAST_CHECK, _LAST_SUCCESSFUL_CHECK, _LAST_ERROR
    global _RATE_LIMITED_UNTIL, _CONNECTION_STATUS
    with _STATE_LOCK:
        _CACHE.clear()
        _LAST_CHECK = None
        _LAST_SUCCESSFUL_CHECK = None
        _LAST_ERROR = None
        _RATE_LIMITED_UNTIL = 0.0
        _CONNECTION_STATUS = "not_checked"
