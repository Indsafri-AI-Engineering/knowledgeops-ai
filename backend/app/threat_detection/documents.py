from pathlib import PurePath

from backend.app.threat_detection.rules import ThreatIndicator, detect_text_indicators
from backend.app.threat_detection.urls import URL_PATTERN, inspect_url

MAX_DOCUMENT_CHARS = 100_000
ALLOWED_EXTENSIONS = {".txt", ".md", ".eml"}


def inspect_document(
    filename: str,
    text: str,
) -> tuple[list[ThreatIndicator], list[str]]:
    extension = PurePath(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Only plain-text .txt, .md, and .eml documents are supported.")
    if not text.strip() or len(text) > MAX_DOCUMENT_CHARS:
        raise ValueError(
            f"Document text must contain between 1 and {MAX_DOCUMENT_CHARS} characters."
        )

    indicators = detect_text_indicators(text)
    urls: list[str] = []
    for match in URL_PATTERN.finditer(text):
        candidate = match.group(0).rstrip(".,);]")
        try:
            normalized, url_indicators = inspect_url(candidate)
        except ValueError:
            continue
        if normalized not in urls:
            urls.append(normalized)
        indicators.extend(url_indicators)
    return indicators, urls
