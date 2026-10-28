from collections.abc import Iterator
from html import escape
from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.knowledge.index import get_knowledge_index
from backend.app.storage.knowledge import (
    CorruptKnowledgeStoreError,
    KnowledgeDocumentStore,
)


def _text_pdf(text: str) -> bytes:
    escaped_text = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    stream = (
        f"BT /F1 12 Tf 20 100 Td ({escaped_text}) Tj ET".encode("ascii")
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        ),
    ]
    parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for object_number, content in enumerate(objects, start=1):
        offsets.append(sum(map(len, parts)))
        parts.append(
            f"{object_number} 0 obj\n".encode()
            + content
            + b"\nendobj\n"
        )
    xref_offset = sum(map(len, parts))
    parts.append(f"xref\n0 {len(offsets)}\n".encode())
    parts.append(b"0000000000 65535 f \n")
    parts.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    parts.append(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return b"".join(parts)


def _text_docx(*paragraphs: str) -> bytes:
    paragraph_xml = "".join(
        f"<w:p><w:r><w:t>{escape(paragraph)}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>'
        f"{paragraph_xml}"
        "<w:sectPr/></w:body></w:document>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _office_archive(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return buffer.getvalue()


def _text_xlsx(text: str) -> bytes:
    return _office_archive(
        {
            "xl/worksheets/sheet1.xml": (
                '<worksheet xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main"><sheetData><row r="1">'
                f'<c r="A1" t="inlineStr"><is><t>{escape(text)}</t></is></c>'
                "</row></sheetData></worksheet>"
            )
        }
    )


def _text_pptx(text: str) -> bytes:
    return _office_archive(
        {
            "ppt/slides/slide1.xml": (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/'
                'presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/'
                'drawingml/2006/main"><p:cSld><a:p><a:r><a:t>'
                f"{escape(text)}"
                "</a:t></a:r></a:p></p:cSld></p:sld>"
            )
        }
    )


@pytest.fixture
def admin_client(monkeypatch, tmp_path) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("KNOWLEDGE_STORE_PATH", str(tmp_path / "knowledge.json"))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_knowledge_index.cache_clear()
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/demo-login",
            json={"user_id": "demo-admin"},
        )
        yield client
    get_knowledge_index.cache_clear()


def _upload(
    client: TestClient,
    content: bytes,
    filename: str = "synthetic_policy.pdf",
):
    content_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    suffix = filename.rsplit(".", 1)[-1].lower()
    return client.post(
        "/api/v1/knowledge/documents",
        files={"file": (filename, content, content_types.get(f".{suffix}", "application/octet-stream"))},
        data={
            "title": "Synthetic Widget Calibration",
            "access_scope": "it",
            "owner": "Fictional IT",
            "version": "synthetic-v1",
        },
    )


def test_pdf_ingestion_persists_chunks_and_makes_them_retrievable(
    admin_client: TestClient,
    tmp_path,
) -> None:
    pdf = _text_pdf(
        "The fictional quantum widget calibration sequence requires a "
        "blue alignment key and a safe local test cycle."
    )

    response = _upload(admin_client, pdf)

    assert response.status_code == 201, response.text
    stored_document = response.json()["document"]
    assert stored_document["access_scope"] == "it"
    assert stored_document["chunk_count"] == 1
    assert stored_document["filename"] == "synthetic_policy.pdf"
    assert stored_document["document_type"] == "application/pdf"
    assert len(stored_document["sha256"]) == 64

    index = get_knowledge_index()
    allowed_results = index.search(
        "quantum widget calibration blue alignment key",
        {"it"},
    )
    denied_results = index.search(
        "quantum widget calibration blue alignment key",
        {"general", "recruitment"},
    )
    assert allowed_results[0].chunk.document_id == stored_document["document_id"]
    assert allowed_results[0].chunk.section == "Page 1"
    assert denied_results == []

    reopened_store = KnowledgeDocumentStore(tmp_path / "knowledge.json")
    assert reopened_store.list_documents()[0].document_id == stored_document["document_id"]
    assert "blue alignment key" in reopened_store.list_chunks()[0].text

    get_knowledge_index.cache_clear()
    with TestClient(app) as it_client:
        it_client.post(
            "/api/v1/auth/demo-login",
            json={"user_id": "demo-it"},
        )
        chat_response = it_client.post(
            "/api/v1/chat",
            json={"question": "What is the quantum widget blue alignment key?"},
        )
    assert chat_response.status_code == 200
    assert chat_response.json()["sources"][0]["document_id"] == stored_document["document_id"]

    with TestClient(app) as recruiter_client:
        recruiter_client.post(
            "/api/v1/auth/demo-login",
            json={"user_id": "demo-recruiter"},
        )
        restricted_chat = recruiter_client.post(
            "/api/v1/chat",
            json={"question": "What is the quantum widget blue alignment key?"},
        )
    assert restricted_chat.status_code == 200
    assert stored_document["document_id"] not in {
        source["document_id"] for source in restricted_chat.json()["sources"]
    }


def test_hr_scoped_document_is_cited_for_hr_and_withheld_from_employee(
    admin_client: TestClient,
) -> None:
    policy_text = (
        "The fictional Marigold parental leave process requires submitting "
        "Form P-17 to the HR review desk."
    )
    response = admin_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("marigold-leave.txt", policy_text.encode(), "text/plain")},
        data={
            "title": "Synthetic Marigold Leave Procedure",
            "access_scope": "hr",
            "owner": "Fictional HR",
            "version": "synthetic-v1",
        },
    )

    assert response.status_code == 201, response.text
    document_id = response.json()["document"]["document_id"]
    question = (
        "According to the Marigold parental leave process, where is Form P-17 "
        "submitted?"
    )

    with TestClient(app) as hr_client:
        hr_client.post("/api/v1/auth/demo-login", json={"user_id": "demo-hr"})
        hr_response = hr_client.post("/api/v1/chat", json={"question": question})

    assert hr_response.status_code == 200
    assert document_id in {
        source["document_id"] for source in hr_response.json()["sources"]
    }

    with TestClient(app) as employee_client:
        employee_client.post(
            "/api/v1/auth/demo-login",
            json={"user_id": "demo-employee"},
        )
        employee_response = employee_client.post(
            "/api/v1/chat",
            json={"question": question},
        )

    assert employee_response.status_code == 200
    assert document_id not in {
        source["document_id"] for source in employee_response.json()["sources"]
    }
    assert "HR review desk" not in employee_response.json()["answer"]


def test_docx_ingestion_extracts_and_indexes_paragraphs(
    admin_client: TestClient,
) -> None:
    text = "DOCX calibration requires a green safety interlock."

    response = _upload(
        admin_client,
        _text_docx("Equipment procedure", text),
        "equipment-procedure.docx",
    )

    assert response.status_code == 201
    document = response.json()["document"]
    assert document["document_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert document["chunk_count"] == 1
    results = get_knowledge_index().search(
        "green safety interlock",
        {"it"},
        mode="vector",
    )
    assert any(document["document_id"] == result.chunk.document_id for result in results)
    assert text in next(
        result.chunk.text
        for result in results
        if result.chunk.document_id == document["document_id"]
    )


def test_knowledge_document_listing_is_audited_without_document_content(
    admin_client: TestClient,
    tmp_path,
) -> None:
    response = admin_client.get("/api/v1/knowledge/documents")

    assert response.status_code == 200
    audit_events = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    list_event = next(
        event
        for event in audit_events
        if event["action"] == "knowledge.document.list"
    )
    assert list_event["resource_type"] == "local_knowledge_document"
    assert list_event["outcome"] == "success"
    assert list_event["metadata"] == {"result_count": 0}


@pytest.mark.parametrize(
    ("filename", "content", "mime_type", "expected_text"),
    [
        (
            "operations.txt",
            b"Text files can be searched using the violet turbine checklist.",
            "text/plain",
            "violet turbine checklist",
        ),
        (
            "operations.md",
            b"# Operations\n\nMarkdown indexing preserves the silver valve guide.",
            "text/markdown",
            "silver valve guide",
        ),
        (
            "operations.html",
            (
                b"<h1>Visible HTML procedure</h1><script>"
                b"secret injected script payload"
                b"</script><style>.x{color:red}</style><p>"
                b"HTML exposes the orange pressure control."
                b"</p>"
            ),
            "text/html",
            "orange pressure control",
        ),
        (
            "operations.xlsx",
            _text_xlsx("Spreadsheet records the copper sensor sequence."),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "copper sensor sequence",
        ),
        (
            "operations.pptx",
            _text_pptx("Presentation explains the white relay procedure."),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "white relay procedure",
        ),
    ],
)
def test_supported_text_and_office_formats_are_ingested(
    admin_client: TestClient,
    filename: str,
    content: bytes,
    mime_type: str,
    expected_text: str,
) -> None:
    response = _upload(admin_client, content, filename)

    assert response.status_code == 201, response.text
    document = response.json()["document"]
    assert document["document_type"] == mime_type
    assert document["chunk_count"] >= 1
    stored_chunk = next(
        chunk
        for chunk in get_knowledge_index().chunks
        if chunk.document_id == document["document_id"]
    )
    assert expected_text in stored_chunk.text
    if filename.endswith(".html"):
        assert "secret injected script payload" not in stored_chunk.text
        assert ".x{color:red}" not in stored_chunk.text


def test_pdf_document_management_requires_admin_capability(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("KNOWLEDGE_STORE_PATH", str(tmp_path / "knowledge.json"))
    client = TestClient(app)
    client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-employee"},
    )

    assert client.get("/api/v1/knowledge/documents").status_code == 403
    denied_upload = _upload(
        client,
        _text_pdf("Synthetic restricted content."),
    )
    assert denied_upload.status_code == 403


def test_duplicate_pdf_is_rejected_and_delete_removes_searchable_chunks(
    admin_client: TestClient,
) -> None:
    pdf = _text_pdf("Synthetic document about the amber calibration dial.")
    first_response = _upload(admin_client, pdf)
    document_id = first_response.json()["document"]["document_id"]

    assert _upload(admin_client, pdf).status_code == 409
    assert admin_client.delete(
        f"/api/v1/knowledge/documents/{document_id}"
    ).status_code == 204
    assert admin_client.get("/api/v1/knowledge/documents").json() == []
    assert get_knowledge_index().search("amber calibration dial", {"it"}) == []


def test_pdf_upload_rejects_invalid_content(admin_client: TestClient) -> None:
    response = _upload(admin_client, b"%PDF-not-a-readable-pdf")

    assert response.status_code == 422


def test_preingestion_security_blocks_secret_and_redacts_alert(
    admin_client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "security_alerts.json"))
    secret_value = "fictionalSecretValue983721"
    existing_chunks = list(get_knowledge_index().chunks)
    response = _upload(
        admin_client,
        f"api_key = {secret_value}\n".encode(),
        "configuration.txt",
    )

    assert response.status_code == 422
    assert "blocked before extraction or indexing" in response.json()["detail"]
    alerts_path = tmp_path / "security_alerts.json"
    alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
    alert = next(iter(alerts.values()))
    assert alert["alert_type"] == "document_security"
    assert alert["severity"] == "high"
    assert all(item["evidence_redacted"] for item in alert["indicators"])
    assert secret_value not in alerts_path.read_text(encoding="utf-8")
    assert "configuration.txt" not in alerts_path.read_text(encoding="utf-8")
    assert get_knowledge_index().chunks == existing_chunks


def test_extracted_office_text_is_scanned_before_indexing(
    admin_client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "security_alerts.json"))
    secret_value = "fictionalOfficeSecret928374"
    office_bytes = _text_docx("api_key = " + secret_value)
    assert secret_value.encode() not in office_bytes
    existing_chunks = list(get_knowledge_index().chunks)

    response = _upload(
        admin_client,
        office_bytes,
        "configuration.docx",
    )

    assert response.status_code == 422
    assert "blocked before indexing" in response.json()["detail"]
    assert get_knowledge_index().chunks == existing_chunks
    alerts_path = tmp_path / "security_alerts.json"
    assert secret_value not in alerts_path.read_text(encoding="utf-8")


def test_lower_severity_document_indicator_alerts_without_blocking(
    admin_client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "security_alerts.json"))
    content = b"STRICTLY CONFIDENTIAL - fictional internal procedure."

    response = _upload(admin_client, content, "internal-procedure.txt")

    assert response.status_code == 201
    assert response.json()["security_status"] == "alert_created"
    assert response.json()["security_alert_id"]
    assert response.json()["document"]["chunk_count"] == 1


def test_upload_rejects_unsupported_and_malformed_docx(
    admin_client: TestClient,
) -> None:
    existing_chunks = list(get_knowledge_index().chunks)
    unsupported = admin_client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("instructions.exe", b"text", "application/octet-stream")},
        data={"title": "Instructions", "access_scope": "general"},
    )
    unsupported_xyz = admin_client.post(
        "/api/v1/knowledge/documents",
        files={
            "file": (
                "invalid-demo.xyz",
                b"fictional unsupported document content",
                "application/octet-stream",
            )
        },
        data={"title": "Invalid Demo", "access_scope": "general"},
    )
    malformed_docx = _upload(
        admin_client,
        b"not a word document",
        "instructions.docx",
    )

    assert unsupported.status_code == 415
    assert unsupported_xyz.status_code == 415
    assert unsupported_xyz.json()["detail"] == (
        "Upload a PDF, DOCX, TXT, MD, HTML, XLSX, or PPTX document."
    )
    assert malformed_docx.status_code == 422
    assert admin_client.get("/api/v1/knowledge/documents").json() == []
    assert get_knowledge_index().chunks == existing_chunks


def test_upload_rejects_invalid_utf8_and_files_over_size_limit(
    admin_client: TestClient,
) -> None:
    invalid_text = _upload(admin_client, b"\xff\xfe", "invalid.txt")
    oversized = _upload(
        admin_client,
        b"x" * (10 * 1024 * 1024 + 1),
        "oversized.txt",
    )

    assert invalid_text.status_code == 422
    assert oversized.status_code == 413


def test_malformed_office_xml_is_rejected(admin_client: TestClient) -> None:
    malformed = _office_archive({"word/document.xml": "<w:document>"})

    response = _upload(admin_client, malformed, "malformed.docx")

    assert response.status_code == 422


def test_corrupt_knowledge_store_fails_without_overwriting_existing_bytes(
    tmp_path,
) -> None:
    path = tmp_path / "knowledge.json"
    original = b'{"documents": ['
    path.write_bytes(original)
    store = KnowledgeDocumentStore(path)

    with pytest.raises(CorruptKnowledgeStoreError):
        store.list_documents()

    assert path.read_bytes() == original


def test_runtime_index_is_empty_without_configured_seed_documents(
    monkeypatch,
    tmp_path,
) -> None:
    empty_seed_directory = tmp_path / "empty-seed"
    empty_seed_directory.mkdir()
    monkeypatch.setenv("KNOWLEDGE_SEED_DIRECTORY", str(empty_seed_directory))
    monkeypatch.setenv("KNOWLEDGE_STORE_PATH", str(tmp_path / "empty.json"))
    monkeypatch.setenv("RAG_BACKEND", "local")
    get_knowledge_index.cache_clear()

    try:
        assert get_knowledge_index().chunks == []
    finally:
        get_knowledge_index.cache_clear()
