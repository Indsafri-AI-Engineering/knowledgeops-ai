import re
from html.parser import HTMLParser

from backend.app.knowledge.ingestion import CHUNK_SIZE, KnowledgeChunk
from backend.app.knowledge.document_models import (
    DocumentIngestionError,
    KnowledgeDocumentMetadata,
    MAX_EXTRACTED_CHARACTERS,
)


class TextIngestionError(DocumentIngestionError):
    pass


def split_paragraphs(paragraphs: list[str]) -> list[str]:
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        while len(paragraph) > CHUNK_SIZE:
            if current:
                chunks.append(current)
                current = ""
            split_at = paragraph.rfind(" ", 0, CHUNK_SIZE + 1)
            if split_at <= 0:
                split_at = CHUNK_SIZE
            chunks.append(paragraph[:split_at].strip())
            paragraph = paragraph[split_at:].strip()
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) > CHUNK_SIZE:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunks_from_sections(
    sections: list[tuple[str, list[str]]],
    metadata: KnowledgeDocumentMetadata,
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    extracted_characters = 0
    for section, paragraphs in sections:
        normalized = [
            re.sub(r"\s+", " ", paragraph).strip()
            for paragraph in paragraphs
        ]
        normalized = [paragraph for paragraph in normalized if paragraph]
        extracted_characters += sum(map(len, normalized))
        if extracted_characters > MAX_EXTRACTED_CHARACTERS:
            raise TextIngestionError(
                "Extracted document text is limited to "
                f"{MAX_EXTRACTED_CHARACTERS} characters."
            )
        chunks.extend(
            KnowledgeChunk(
                chunk_id=f"{metadata.document_id}:{len(chunks)}",
                document_id=metadata.document_id,
                title=metadata.title,
                source=metadata.source,
                access_scope=metadata.access_scope,
                source_path=f"uploaded/{metadata.document_id}/{metadata.filename}",
                section=section,
                text=text,
                owner=metadata.owner,
                version=metadata.version,
                effective_date=metadata.effective_date,
                next_review=metadata.next_review,
                environment=metadata.environment,
            )
            for text in split_paragraphs(normalized)
        )
    if not chunks:
        raise TextIngestionError("No searchable text was found in the document.")
    return chunks


def extract_text_chunks(
    file_bytes: bytes,
    metadata: KnowledgeDocumentMetadata,
    *,
    html: bool = False,
) -> list[KnowledgeChunk]:
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TextIngestionError("Text documents must use UTF-8 encoding.") from error

    if html:
        parser = _VisibleHtmlText()
        parser.feed(text)
        parser.close()
        text = "".join(parser.paragraphs)

    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", text)
    ]
    return chunks_from_sections(
        [("Content", [paragraph for paragraph in paragraphs if paragraph])],
        metadata,
    )


class _VisibleHtmlText(HTMLParser):
    _IGNORED_TAGS = {"script", "style", "noscript", "template"}
    _BLOCK_TAGS = {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.ignored: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        _attrs: list[tuple[str, str | None]],
    ) -> None:
        del _attrs
        normalized_tag = tag.lower()
        if normalized_tag in self._IGNORED_TAGS:
            self.ignored.append(normalized_tag)
        elif normalized_tag in self._BLOCK_TAGS and not self.ignored:
            self.paragraphs.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in self.ignored:
            self.ignored.remove(normalized_tag)
        elif normalized_tag in self._BLOCK_TAGS and not self.ignored:
            self.paragraphs.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored and data.strip():
            self.paragraphs.append(data.strip())
