from datetime import datetime
from io import BytesIO
from pathlib import Path
import re

from docx import Document
from pypdf import PdfReader


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    return "\n".join(
        page_text
        for page in reader.pages
        if (page_text := page.extract_text())
    )


def extract_text_from_docx(file_bytes: bytes) -> str:
    document = Document(BytesIO(file_bytes))
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"(?:\n\s*){2,}", normalized)
        if paragraph.strip()
    ] or re.split(r"(?<=[.!?])\s+", normalized)

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        sentences = [paragraph] if len(paragraph) <= chunk_size else re.split(r"(?<=[.!?])\s+", paragraph)
        for sentence in (item.strip() for item in sentences):
            if not sentence:
                continue
            if len(sentence) > chunk_size:
                step = max(1, chunk_size - overlap)
                chunks.extend(
                    sentence[start:start + chunk_size].strip()
                    for start in range(0, len(sentence), step)
                    if sentence[start:start + chunk_size].strip()
                )
                current = ""
                continue
            candidate = f"{current} {sentence}".strip()
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            if current:
                chunks.append(current)
            tail = current[-overlap:].strip() if overlap and current else ""
            current = f"{tail} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def derive_document_title(filename: str, text: str) -> str:
    for line in text.splitlines()[:80]:
        candidate = line.strip().lstrip("#").strip()
        if 4 <= len(candidate) <= 160:
            return candidate
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip()[:160]


def normalize_document_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{2}[./-]\d{2}[./-]\d{4})\b", value)
    if not match:
        return None
    raw_date = match.group(1).replace("/", ".").replace("-", ".")
    for date_format in ("%Y.%m.%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw_date, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def split_document_sections(text: str, fallback_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = fallback_title
    current_lines: list[str] = []

    def append_section() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_title, content))

    for line in text.splitlines():
        heading_match = re.match(r"^\s*(?:#{1,6}\s+|\d+(?:\.\d+)*[.)]?\s+)(.{3,160})$", line)
        if heading_match:
            append_section()
            current_title = heading_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    append_section()
    return sections or [(fallback_title, text)]


def chunk_document(text: str, fallback_title: str) -> tuple[list[str], list[str]]:
    chunks: list[str] = []
    sections: list[str] = []
    for section_title, section_text in split_document_sections(text, fallback_title):
        for chunk in chunk_text(section_text):
            chunks.append(chunk)
            sections.append(section_title)
    return chunks, sections
