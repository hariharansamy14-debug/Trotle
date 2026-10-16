from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd
from docx import Document as DocxDocument
from pypdf import PdfReader

SUPPORTED_TYPES = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "markdown",
    ".csv": "csv",
    ".xlsx": "xlsx",
}


def file_hash(path: str) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def extract_text_from_file(path: str, filename: str) -> str:
    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n\n".join(pages)
    if lower_name.endswith(".docx"):
        document = DocxDocument(path)
        return "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
    if lower_name.endswith((".txt", ".md")):
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    if lower_name.endswith(".csv"):
        df = pd.read_csv(path)
        return "\n".join(df.astype(str).to_dict(orient="records")[i].__str__() for i in range(len(df)))
    if lower_name.endswith(".xlsx"):
        df = pd.read_excel(path)
        return "\n".join(df.astype(str).to_dict(orient="records")[i].__str__() for i in range(len(df)))
    raise ValueError(f"Unsupported file type for {filename}")


def extract_pages_from_file(path: str, filename: str) -> list[tuple[str, int | None]]:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(path)
        return [(page.extract_text() or "", index) for index, page in enumerate(reader.pages, start=1)]
    return [(extract_text_from_file(path, filename), None)]


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]
    chunks = []
    current = []
    for paragraph in cleaned.split("\n\n"):
        if len("\n\n".join(current + [paragraph])) <= chunk_size:
            current.append(paragraph)
        else:
            if current:
                chunks.append("\n\n".join(current))
            current = [paragraph]
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def ensure_upload_directory(base_dir: str) -> Path:
    upload_dir = Path(base_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir
