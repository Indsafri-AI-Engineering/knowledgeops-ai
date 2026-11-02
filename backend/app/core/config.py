"""Application configuration."""

import os
from dataclasses import dataclass
from typing import Literal, cast


VirusTotalPrivacyPolicy = Literal[
    "disabled",
    "public_root_urls",
    "public_urls",
]
VirusTotalFailurePolicy = Literal["fail_open", "fail_closed"]


@dataclass(frozen=True)
class VirusTotalSettings:
    enabled: bool
    api_key: str
    privacy_policy: VirusTotalPrivacyPolicy
    allowed_domains: tuple[str, ...]
    failure_policy: VirusTotalFailurePolicy
    timeout_seconds: float
    cache_ttl_seconds: int
    max_urls_per_document: int

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key)


def get_virustotal_settings() -> VirusTotalSettings:
    privacy_policy = os.getenv(
        "VIRUSTOTAL_PRIVACY_POLICY",
        "public_root_urls",
    ).strip().lower()
    if privacy_policy not in {"disabled", "public_root_urls", "public_urls"}:
        raise ValueError(
            "VIRUSTOTAL_PRIVACY_POLICY must be disabled, public_root_urls, or public_urls."
        )

    failure_policy = os.getenv(
        "VIRUSTOTAL_FAILURE_POLICY",
        "fail_open",
    ).strip().lower()
    if failure_policy not in {"fail_open", "fail_closed"}:
        raise ValueError(
            "VIRUSTOTAL_FAILURE_POLICY must be fail_open or fail_closed."
        )

    timeout_seconds = float(os.getenv("VIRUSTOTAL_TIMEOUT_SECONDS", "5"))
    cache_ttl_seconds = int(os.getenv("VIRUSTOTAL_CACHE_TTL_SECONDS", "3600"))
    max_urls_per_document = int(
        os.getenv("VIRUSTOTAL_MAX_URLS_PER_DOCUMENT", "10")
    )
    allowed_domains = tuple(
        domain.strip().lower().rstrip(".")
        for domain in os.getenv("VIRUSTOTAL_ALLOWED_DOMAINS", "").split(",")
        if domain.strip()
    )
    if not 0.1 <= timeout_seconds <= 30:
        raise ValueError("VIRUSTOTAL_TIMEOUT_SECONDS must be between 0.1 and 30.")
    if not 0 <= cache_ttl_seconds <= 86_400:
        raise ValueError(
            "VIRUSTOTAL_CACHE_TTL_SECONDS must be between 0 and 86400."
        )
    if not 1 <= max_urls_per_document <= 100:
        raise ValueError(
            "VIRUSTOTAL_MAX_URLS_PER_DOCUMENT must be between 1 and 100."
        )

    return VirusTotalSettings(
        enabled=os.getenv("VIRUSTOTAL_ENABLED", "false").strip().lower()
        in {"true", "1", "yes", "on"},
        api_key=os.getenv("VIRUSTOTAL_API_KEY", "").strip(),
        privacy_policy=cast(VirusTotalPrivacyPolicy, privacy_policy),
        allowed_domains=allowed_domains,
        failure_policy=cast(VirusTotalFailurePolicy, failure_policy),
        timeout_seconds=timeout_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
        max_urls_per_document=max_urls_per_document,
    )
