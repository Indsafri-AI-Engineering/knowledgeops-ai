import re
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from defusedxml.ElementTree import ParseError, fromstring
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import Element

from backend.app.knowledge.document_models import KnowledgeDocumentMetadata
from backend.app.knowledge.ingestion import KnowledgeChunk
from backend.app.knowledge.text_ingestion import (
    TextIngestionError,
    chunks_from_sections,
)

MAX_OFFICE_ENTRIES = 2_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SHEET_NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
PRESENTATION_NAMESPACE = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


class OfficeIngestionError(TextIngestionError):
    pass


def _validate_archive(archive: ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_OFFICE_ENTRIES:
        raise OfficeIngestionError("The Office archive contains too many files.")
    if any(entry.flag_bits & 0x1 for entry in entries):
        raise OfficeIngestionError("Encrypted Office documents are not supported.")
    if sum(entry.file_size for entry in entries) > MAX_OFFICE_UNCOMPRESSED_BYTES:
        raise OfficeIngestionError("Expanded Office content is limited to 20 MiB.")


def _parse_xml(content: bytes) -> Element:
    try:
        return fromstring(content)
    except (ParseError, DefusedXmlException, ValueError) as error:
        raise OfficeIngestionError("The Office document contains invalid XML.") from error


def extract_docx_sections(docx_bytes: bytes) -> list[tuple[str, list[str]]]:
    try:
        with ZipFile(BytesIO(docx_bytes)) as archive:
            _validate_archive(archive)
            try:
                root = _parse_xml(archive.read("word/document.xml"))
            except KeyError as error:
                raise OfficeIngestionError(
                    "The DOCX file has no document content."
                ) from error
    except BadZipFile as error:
        raise OfficeIngestionError("The uploaded file is not a valid DOCX document.") from error

    paragraphs = [
        " ".join(
            text_node.text or ""
            for text_node in paragraph.iter(f"{WORD_NAMESPACE}t")
        )
        for paragraph in root.iter(f"{WORD_NAMESPACE}p")
    ]
    return [("Document", paragraphs)]


def extract_docx_chunks(
    docx_bytes: bytes,
    metadata: KnowledgeDocumentMetadata,
) -> list[KnowledgeChunk]:
    return chunks_from_sections(extract_docx_sections(docx_bytes), metadata)


def extract_xlsx_sections(xlsx_bytes: bytes) -> list[tuple[str, list[str]]]:
    try:
        with ZipFile(BytesIO(xlsx_bytes)) as archive:
            _validate_archive(archive)
            names = set(archive.namelist())
            worksheets = sorted(
                (
                    name
                    for name in names
                    if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
                ),
                key=lambda name: int(
                    PurePosixPath(name).stem.removeprefix("sheet")
                ),
            )
            if not worksheets:
                raise OfficeIngestionError(
                    "The XLSX file contains no readable worksheets."
                )

            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = _parse_xml(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(text.text or "" for text in item.iter(f"{SHEET_NAMESPACE}t"))
                    for item in shared_root.iter(f"{SHEET_NAMESPACE}si")
                ]

            sections: list[tuple[str, list[str]]] = []
            for sheet_number, worksheet_name in enumerate(worksheets, start=1):
                root = _parse_xml(archive.read(worksheet_name))
                rows: list[str] = []
                for row in root.iter(f"{SHEET_NAMESPACE}row"):
                    cells: list[str] = []
                    for cell in row.iter(f"{SHEET_NAMESPACE}c"):
                        cell_type = cell.attrib.get("t")
                        if cell_type == "s":
                            value_node = cell.find(f"{SHEET_NAMESPACE}v")
                            if value_node is None or value_node.text is None:
                                continue
                            try:
                                value = shared_strings[int(value_node.text)]
                            except (ValueError, IndexError) as error:
                                raise OfficeIngestionError(
                                    "The XLSX file contains an invalid shared string reference."
                                ) from error
                        elif cell_type == "inlineStr":
                            value = "".join(
                                text.text or ""
                                for text in cell.iter(f"{SHEET_NAMESPACE}t")
                            )
                        else:
                            value_node = cell.find(f"{SHEET_NAMESPACE}v")
                            value = value_node.text if value_node is not None else ""
                        if value:
                            cells.append(f"{cell.attrib.get('r', '')}: {value}")
                    if cells:
                        rows.append(" | ".join(cells))
                sections.append((f"Worksheet {sheet_number}", rows))
    except BadZipFile as error:
        raise OfficeIngestionError("The uploaded file is not a valid XLSX workbook.") from error

    return sections


def extract_xlsx_chunks(
    xlsx_bytes: bytes,
    metadata: KnowledgeDocumentMetadata,
) -> list[KnowledgeChunk]:
    return chunks_from_sections(extract_xlsx_sections(xlsx_bytes), metadata)


def extract_pptx_sections(pptx_bytes: bytes) -> list[tuple[str, list[str]]]:
    try:
        with ZipFile(BytesIO(pptx_bytes)) as archive:
            _validate_archive(archive)
            slides = sorted(
                (
                    name
                    for name in archive.namelist()
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
                ),
                key=lambda name: int(
                    PurePosixPath(name).stem.removeprefix("slide")
                ),
            )
            if not slides:
                raise OfficeIngestionError(
                    "The PPTX file contains no readable slides."
                )
            sections = []
            for slide_number, slide_name in enumerate(slides, start=1):
                root = _parse_xml(archive.read(slide_name))
                paragraphs = [
                    " ".join(
                        text.text or ""
                        for text in paragraph.iter(
                            f"{PRESENTATION_NAMESPACE}t"
                        )
                    )
                    for paragraph in root.iter(
                        f"{PRESENTATION_NAMESPACE}p"
                    )
                ]
                sections.append((f"Slide {slide_number}", paragraphs))
    except BadZipFile as error:
        raise OfficeIngestionError("The uploaded file is not a valid PPTX presentation.") from error

    return sections


def extract_pptx_chunks(
    pptx_bytes: bytes,
    metadata: KnowledgeDocumentMetadata,
) -> list[KnowledgeChunk]:
    return chunks_from_sections(extract_pptx_sections(pptx_bytes), metadata)


def extract_office_link_targets(file_bytes: bytes) -> list[str]:
    try:
        with ZipFile(BytesIO(file_bytes)) as archive:
            _validate_archive(archive)
            targets: list[str] = []
            for name in archive.namelist():
                if not name.lower().endswith(".rels"):
                    continue
                root = _parse_xml(archive.read(name))
                for relationship in root.iter():
                    target = relationship.attrib.get("Target")
                    mode = relationship.attrib.get("TargetMode", "")
                    if target and mode.lower() == "external":
                        targets.append(target)
            return targets
    except BadZipFile as error:
        raise OfficeIngestionError(
            "The uploaded file is not a valid Office document."
        ) from error
