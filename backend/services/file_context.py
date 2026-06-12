"""Extract text context from uploaded file bytes."""

from __future__ import annotations

import csv
import io
from pathlib import Path


def read_file_context_from_bytes(data: bytes, original_name: str) -> str:
    ext = Path(original_name).suffix.lower()
    try:
        if ext == ".csv":
            text = data.decode("utf-8", errors="replace")
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)[:50]
            preview = "\n".join(", ".join(row) for row in rows)
            return f"CSV file {original_name} (first {len(rows)} rows):\n{preview[:6000]}"
        if ext in (".txt", ".md"):
            return data.decode("utf-8", errors="replace")[:8000]
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = []
            for page in reader.pages[:5]:
                pages.append(page.extract_text() or "")
            return f"PDF {original_name}:\n" + "\n".join(pages)[:8000]
        if ext == ".docx":
            from docx import Document

            doc = Document(io.BytesIO(data))
            paras = [p.text for p in doc.paragraphs if p.text.strip()][:40]
            return f"Document {original_name}:\n" + "\n".join(paras)[:8000]
    except Exception as exc:
        return f"File {original_name} uploaded (could not parse: {exc})"
    return f"File {original_name} attached."
