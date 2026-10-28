import re
from dataclasses import dataclass
from pathlib import Path

DATA_ROOT = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "fictional_demo"
)
CHUNK_SIZE = 700


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    title: str
    source: str
    access_scope: str
    source_path: str
    section: str
    text: str
    owner: str | None = None
    version: str | None = None
    effective_date: str | None = None
    next_review: str | None = None
    environment: str | None = None


def _read_front_matter(content: str) -> tuple[dict[str, str], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, content

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip().strip("'\"")
    return metadata, "\n".join(lines[end + 1 :])


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "Overview"
    current_lines: list[str] = []

    for line in markdown.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading:
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = heading.group(1)
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines))

    return [
        (title, "\n".join(lines).strip())
        for title, lines in sections
        if "\n".join(lines).strip()
    ]


def _chunk_text(text: str) -> list[str]:
    paragraphs = [
        " ".join(line.strip() for line in part.splitlines()).strip()
        for part in re.split(r"\n\s*\n", text)
        if part.strip()
    ]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > CHUNK_SIZE:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                paragraph[index : index + CHUNK_SIZE].strip()
                for index in range(0, len(paragraph), CHUNK_SIZE)
            )
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


def load_knowledge_chunks(root: Path = DATA_ROOT) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        content = path.read_text(encoding="utf-8")
        metadata, markdown = _read_front_matter(content)
        required_fields = ("document_id", "title", "source", "access_scope")
        missing = [field for field in required_fields if not metadata.get(field)]
        if missing:
            raise ValueError(f"{path}: missing front matter fields: {', '.join(missing)}")

        relative_path = path.relative_to(root).as_posix()
        chunk_number = 0
        for section, section_text in _split_sections(markdown):
            for text in _chunk_text(section_text):
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=f"{metadata['document_id']}:{chunk_number}",
                        document_id=metadata["document_id"],
                        title=metadata["title"],
                        source=metadata["source"],
                        access_scope=metadata["access_scope"],
                        source_path=relative_path,
                        section=section,
                        text=text,
                        owner=metadata.get("owner"),
                        version=metadata.get("version"),
                        effective_date=metadata.get("effective_date"),
                        next_review=metadata.get("next_review"),
                        environment=metadata.get("environment"),
                    )
                )
                chunk_number += 1
    return chunks
