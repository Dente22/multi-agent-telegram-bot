"""Document loaders for PDF, TXT, DOCX."""

from __future__ import annotations

from pathlib import Path


class DocumentLoadError(ValueError):
    """Raised when a document cannot be parsed."""


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md"}


async def load_document_text(path: str | Path) -> str:
    """Extract plain text from an uploaded corporate file."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise DocumentLoadError(f"Unsupported file type: {suffix}")

    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        parts = [(page.extract_text() or "") for page in reader.pages]
        text = "\n".join(parts).strip()
        if not text:
            raise DocumentLoadError("PDF contains no extractable text")
        return text

    # .docx
    from docx import Document as DocxDocument

    doc = DocxDocument(str(file_path))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
    if not text:
        raise DocumentLoadError("DOCX contains no extractable text")
    return text
