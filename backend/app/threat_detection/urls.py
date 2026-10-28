import ipaddress
import re
from urllib.parse import urlsplit

from backend.app.threat_detection.rules import ThreatIndicator

URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
SUSPICIOUS_PATH_TERMS = re.compile(
    r"\b(login|verify|secure|account|password|wallet|invoice)\b",
    re.IGNORECASE,
)


def validate_url(value: str) -> tuple[str, str]:
    candidate = value.strip()
    if not candidate or len(candidate) > 2048:
        raise ValueError("URL must contain between 1 and 2048 characters.")
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http and https URL schemes can be inspected.")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not accepted.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("URL port is invalid.")
    normalized = parsed._replace(fragment="").geturl()
    return normalized, parsed.hostname.rstrip(".").lower()


def inspect_url(value: str) -> tuple[str, list[ThreatIndicator]]:
    normalized, hostname = validate_url(value)
    parsed = urlsplit(normalized)
    indicators: list[ThreatIndicator] = []

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        indicators.append(
            ThreatIndicator(
                rule_id="url-ip-address-host",
                severity="medium",
                description="URL uses a numeric IP address instead of a domain name.",
                evidence=hostname,
            )
        )

    if hostname.startswith("xn--") or ".xn--" in hostname:
        indicators.append(
            ThreatIndicator(
                rule_id="url-punycode-host",
                severity="medium",
                description="URL hostname contains an internationalized punycode label.",
                evidence=hostname,
            )
        )

    if parsed.scheme.lower() != "https":
        indicators.append(
            ThreatIndicator(
                rule_id="url-no-https",
                severity="low",
                description="URL does not use HTTPS; this alone does not prove maliciousness.",
                evidence=f"scheme={parsed.scheme.lower()}",
            )
        )

    suspicious_term = SUSPICIOUS_PATH_TERMS.search(
        f"{parsed.path} {parsed.query}"
    )
    if suspicious_term:
        indicators.append(
            ThreatIndicator(
                rule_id="url-sensitive-path",
                severity="low",
                description="URL path or query references a sensitive account-related term.",
                evidence=suspicious_term.group(0),
            )
        )
    return normalized, indicators
