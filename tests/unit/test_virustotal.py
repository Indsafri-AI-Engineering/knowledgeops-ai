import base64
from datetime import UTC, datetime

import httpx
import pytest

from backend.app.core.config import VirusTotalSettings
from backend.app.threat_detection.virustotal import (
    VirusTotalService,
    reset_virustotal_state,
)

SAMPLE_URL = "https://reputation.example/"


@pytest.fixture(autouse=True)
def reset_provider_state():
    reset_virustotal_state()
    yield
    reset_virustotal_state()


def _settings(
    *,
    enabled: bool = True,
    api_key: str = "fictional-test-key",
    privacy_policy: str = "public_root_urls",
    allowed_domains: tuple[str, ...] = (),
    failure_policy: str = "fail_open",
) -> VirusTotalSettings:
    return VirusTotalSettings(
        enabled=enabled,
        api_key=api_key,
        privacy_policy=privacy_policy,
        allowed_domains=allowed_domains,
        failure_policy=failure_policy,
        timeout_seconds=1,
        cache_ttl_seconds=60,
        max_urls_per_document=10,
    )


def _report(
    *,
    malicious: int = 0,
    suspicious: int = 0,
    harmless: int = 80,
    undetected: int = 10,
) -> dict[str, object]:
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": malicious,
                    "suspicious": suspicious,
                    "harmless": harmless,
                    "undetected": undetected,
                },
                "last_analysis_date": 1_761_800_000,
            }
        }
    }


def _transport(handler):
    return httpx.MockTransport(handler)


def test_clean_url_report_parses_counts_timestamp_and_unpadded_urlsafe_id() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        assert request.headers["x-apikey"] == "fictional-test-key"
        return httpx.Response(200, json=_report())

    result = VirusTotalService(
        _settings(),
        transport=_transport(handler),
    ).lookup_url(SAMPLE_URL)

    expected_id = base64.urlsafe_b64encode(
        SAMPLE_URL.encode("utf-8")
    ).decode("ascii").rstrip("=")
    assert observed_paths == [f"/api/v3/urls/{expected_id}"]
    assert "=" not in observed_paths[0].rsplit("/", 1)[-1]
    assert result.status == "clean"
    assert result.malicious == 0
    assert result.suspicious == 0
    assert result.harmless == 80
    assert result.undetected == 10
    assert result.detection_ratio == "0/90"
    assert result.analysis_status == "completed"
    assert result.last_analysis_at == datetime.fromtimestamp(1_761_800_000, UTC)
    assert result.redacted_url == "reputation.example (URL path and query redacted)"


@pytest.mark.parametrize(
    ("stats", "expected_status", "expected_ratio"),
    [
        ({"malicious": 3, "suspicious": 0, "harmless": 70, "undetected": 20}, "malicious", "3/93"),
        ({"malicious": 0, "suspicious": 2, "harmless": 70, "undetected": 20}, "suspicious", "2/92"),
    ],
)
def test_malicious_and_suspicious_reports_are_not_clean(
    stats: dict[str, int],
    expected_status: str,
    expected_ratio: str,
) -> None:
    result = VirusTotalService(
        _settings(),
        transport=_transport(lambda _request: httpx.Response(
            200,
            json={"data": {"attributes": {
                "last_analysis_stats": stats,
                "last_analysis_date": 1_761_800_000,
            }}},
        )),
    ).lookup_url(SAMPLE_URL)

    assert result.status == expected_status
    assert result.detection_ratio == expected_ratio


def test_missing_report_is_unknown_and_does_not_cache_as_clean() -> None:
    result = VirusTotalService(
        _settings(),
        transport=_transport(lambda _request: httpx.Response(404)),
    ).lookup_url(SAMPLE_URL)

    assert result.status == "unknown"
    assert result.reason == "no_existing_report"
    assert result.detection_ratio is None


@pytest.mark.parametrize("http_status", [401, 403])
def test_authentication_failures_are_reported_without_exposing_credentials(
    http_status: int,
) -> None:
    result = VirusTotalService(
        _settings(),
        transport=_transport(lambda _request: httpx.Response(http_status)),
    ).lookup_url(SAMPLE_URL)

    assert result.status == "authentication_failure"
    assert "fictional-test-key" not in result.model_dump_json()


def test_rate_limit_is_reported_and_throttles_following_requests() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "30"})

    service = VirusTotalService(_settings(), transport=_transport(handler))
    first = service.lookup_url(SAMPLE_URL)
    second = service.lookup_url("https://another.example/")

    assert first.status == "rate_limited"
    assert second.status == "rate_limited"
    assert calls == 1
    assert VirusTotalService(_settings()).provider_status().connection_status == "rate_limited"


def test_server_error_is_reported_as_provider_unavailable() -> None:
    result = VirusTotalService(
        _settings(),
        transport=_transport(lambda _request: httpx.Response(503)),
    ).lookup_url(SAMPLE_URL)

    assert result.status == "provider_unavailable"
    assert result.reason == "provider_error"


def test_provider_timeout_is_unknown_not_clean() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    result = VirusTotalService(
        _settings(),
        transport=_transport(handler),
    ).lookup_url(SAMPLE_URL)

    assert result.status == "provider_unavailable"
    assert result.reason == "timeout"


def test_disabled_and_missing_key_do_not_make_http_requests() -> None:
    def unexpected_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("A disabled or unconfigured scanner must not call HTTP.")

    disabled = VirusTotalService(
        _settings(enabled=False),
        transport=_transport(unexpected_request),
    ).lookup_url(SAMPLE_URL)
    missing_key = VirusTotalService(
        _settings(api_key=""),
        transport=_transport(unexpected_request),
    ).lookup_url(SAMPLE_URL)

    assert disabled.status == "disabled"
    assert missing_key.status == "not_configured"


def test_multiple_urls_are_scanned_once_and_fragments_are_deduplicated() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_report())

    summary = VirusTotalService(
        _settings(),
        transport=_transport(handler),
    ).scan_document_urls(
        [
            SAMPLE_URL,
            "https://reputation.example/#section",
            "https://another.example/",
        ]
    )

    assert summary.urls_detected == 2
    assert summary.clean_count == 2
    assert calls == 2


def test_repeated_lookup_uses_the_process_cache() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_report())

    service = VirusTotalService(_settings(), transport=_transport(handler))
    assert service.lookup_url(SAMPLE_URL).status == "clean"
    assert service.lookup_url(SAMPLE_URL).status == "clean"
    assert calls == 1


def test_sensitive_urls_and_private_hosts_are_filtered_before_http() -> None:
    def unexpected_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Privacy-filtered URLs must not reach VirusTotal.")

    summary = VirusTotalService(
        _settings(privacy_policy="public_urls"),
        transport=_transport(unexpected_request),
    ).scan_document_urls(
        [
            "https://reputation.example/?email=person@example.org",
            "https://reputation.example/login/fictional-secret",
            "https://service.internal/",
            "http://127.0.0.1/",
        ]
    )

    assert summary.urls_detected == 4
    assert summary.unknown_count == 4
    assert all(result.status == "privacy_filtered" for result in summary.results)
    assert all("person@example.org" not in result.redacted_url for result in summary.results)
    assert all("fictional-secret" not in result.redacted_url for result in summary.results)


def test_configured_domain_allowlist_is_applied_before_http() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_report())

    summary = VirusTotalService(
        _settings(allowed_domains=("approved.example",)),
        transport=_transport(handler),
    ).scan_document_urls(
        [
            "https://not-approved.example/",
            "https://subdomain.approved.example/",
        ]
    )

    assert [result.status for result in summary.results] == [
        "privacy_filtered",
        "clean",
    ]
    assert len(requests) == 1


def test_missing_or_malformed_report_statistics_remain_unknown() -> None:
    result = VirusTotalService(
        _settings(),
        transport=_transport(lambda _request: httpx.Response(
            200,
            json={"data": {"attributes": {
                "last_analysis_stats": {"harmless": 9},
            }}},
        )),
    ).lookup_url(SAMPLE_URL)

    assert result.status == "unknown"
    assert result.analysis_status == "completed"
    assert result.detection_ratio == "0/9"


def test_provider_auth_failure_stops_repeated_requests_for_document() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    summary = VirusTotalService(
        _settings(),
        transport=_transport(handler),
    ).scan_document_urls(
        [SAMPLE_URL, "https://another.example/"],
    )

    assert calls == 1
    assert summary.authentication_failure_count == 2
    assert all(
        result.status == "authentication_failure"
        for result in summary.results
    )
