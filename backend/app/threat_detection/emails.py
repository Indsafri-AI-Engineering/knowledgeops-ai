from email import policy
from email.parser import Parser
from email.utils import parseaddr

from backend.app.threat_detection.rules import ThreatIndicator
from backend.app.threat_detection.urls import URL_PATTERN, inspect_url

MAX_EMAIL_CHARS = 50_000


def inspect_email(text: str) -> tuple[list[ThreatIndicator], list[str]]:
    if not text.strip() or len(text) > MAX_EMAIL_CHARS:
        raise ValueError(
            f"Email text must contain between 1 and {MAX_EMAIL_CHARS} characters."
        )
    message = Parser(policy=policy.default).parsestr(text, headersonly=False)
    indicators: list[ThreatIndicator] = []

    from_header = message.get("From", "")
    display_name, address = parseaddr(from_header)
    reply_to = parseaddr(message.get("Reply-To", ""))[1]
    if reply_to and address and reply_to.casefold() != address.casefold():
        indicators.append(
            ThreatIndicator(
                rule_id="email-reply-to-mismatch",
                severity="medium",
                description="Reply-To address differs from the From address.",
                evidence=f"From={address}; Reply-To={reply_to}",
            )
        )
    if display_name and address and display_name.casefold() in address.casefold():
        indicators.append(
            ThreatIndicator(
                rule_id="email-display-name-address-overlap",
                severity="low",
                description="Display name text is repeated in the sender address.",
                evidence=f"From display name={display_name}",
            )
        )

    body_parts: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() == "attachment":
            filename = part.get_filename() or "unnamed attachment"
            indicators.append(
                ThreatIndicator(
                    rule_id="email-attachment-present",
                    severity="info",
                    description="Email contains an attachment; its contents were not opened.",
                    evidence=filename[:120],
                )
            )
            continue
        if part.get_content_type() == "text/plain":
            content = part.get_content()
            if isinstance(content, str):
                body_parts.append(content)

    body = "\n".join(body_parts)
    indicators.extend(inspect_text_indicators(body))

    urls: list[str] = []
    for match in URL_PATTERN.finditer(body):
        candidate = match.group(0).rstrip(".,);]")
        try:
            normalized, url_indicators = inspect_url(candidate)
        except ValueError:
            indicators.append(
                ThreatIndicator(
                    rule_id="email-invalid-url",
                    severity="low",
                    description="Email contains a URL that failed safe syntax validation.",
                    evidence="URL not retained",
                )
            )
            continue
        if normalized not in urls:
            urls.append(normalized)
        indicators.extend(url_indicators)
    return indicators, urls


def inspect_text_indicators(text: str) -> list[ThreatIndicator]:
    from backend.app.threat_detection.rules import detect_text_indicators

    return detect_text_indicators(text)
