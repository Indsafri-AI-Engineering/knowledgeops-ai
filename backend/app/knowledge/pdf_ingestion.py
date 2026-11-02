from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from backend.app.knowledge.ingestion import CHUNK_SIZE, KnowledgeChunk
from backend.app.knowledge.document_models import (
    DocumentIngestionError,
    KnowledgeDocumentMetadata,
    MAX_EXTRACTED_CHARACTERS,
)

MAX_PDF_PAGES = 100


class PDFIngestionError(DocumentIngestionError):
    pass


def _split_page_text(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current_words: list[str] = []
    current_length = 0
    for word in words:
        candidate_length = current_length + len(word) + bool(current_words)
        if current_words and candidate_length > CHUNK_SIZE:
            chunks.append(" ".join(current_words))
            current_words = []
            current_length = 0
        current_words.append(word)
        current_length += len(word) + (1 if len(current_words) > 1 else 0)
    if current_words:
        chunks.append(" ".join(current_words))
    return chunks


def extract_pdf_sections(pdf_bytes: bytes) -> list[tuple[str, list[str]]]:
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=True)
    except (PdfReadError, ValueError) as error:
        raise PDFIngestionError("The uploaded file is not a valid readable PDF.") from error

    if reader.is_encrypted:
        raise PDFIngestionError("Encrypted PDFs are not supported.")
    if not reader.pages:
        raise PDFIngestionError("The PDF contains no pages.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise PDFIngestionError(
            f"PDFs are limited to {MAX_PDF_PAGES} pages."
        )

    sections: list[tuple[str, list[str]]] = []
    character_count = 0
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        character_count += len(text)
        if character_count > MAX_EXTRACTED_CHARACTERS:
            raise PDFIngestionError(
                f"Extracted PDF text is limited to {MAX_EXTRACTED_CHARACTERS} characters."
            )
        if text.strip():
            sections.append((f"Page {page_number}", [text]))

    if not sections:
        raise PDFIngestionError(
            "No searchable text was found. Scanned/image-only PDFs are not supported."
        )
    return sections


def chunks_from_pdf_sections(
    sections: list[tuple[str, list[str]]],
    metadata: KnowledgeDocumentMetadata,
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for section, paragraphs in sections:
        for paragraph in paragraphs:
            for chunk_text in _split_page_text(paragraph):
                chunk_id = f"{metadata.document_id}:{len(chunks)}"
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=chunk_id,
                        document_id=metadata.document_id,
                        title=metadata.title,
                        source=metadata.source,
                        access_scope=metadata.access_scope,
                        source_path=(
                            f"uploaded/{metadata.document_id}/{metadata.filename}"
                        ),
                        section=section,
                        text=chunk_text,
                        owner=metadata.owner,
                        version=metadata.version,
                        effective_date=metadata.effective_date,
                        next_review=metadata.next_review,
                        environment=metadata.environment,
                    )
                )
    if not chunks:
        raise PDFIngestionError(
            "No searchable text was found. Scanned/image-only PDFs are not supported."
        )
    return chunks


def extract_pdf_chunks(
    pdf_bytes: bytes,
    metadata: KnowledgeDocumentMetadata,
) -> list[KnowledgeChunk]:
    return chunks_from_pdf_sections(extract_pdf_sections(pdf_bytes), metadata)


def extract_pdf_link_targets(pdf_bytes: bytes) -> list[str]:
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=True)
    except (PdfReadError, ValueError) as error:
        raise PDFIngestionError("The uploaded file is not a valid readable PDF.") from error
    if reader.is_encrypted:
        raise PDFIngestionError("Encrypted PDFs are not supported.")

    targets: list[str] = []
    for page in reader.pages:
        annotations = page.get("/Annots") or []
        for annotation_reference in annotations:
            annotation = annotation_reference.get_object()
            action = annotation.get("/A")
            target = action.get("/URI") if action else None
            if isinstance(target, str):
                targets.append(target)
    return targets
