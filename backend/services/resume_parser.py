"""Parse resume files (PDF, Word, HTML) into profile fields."""

import re
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _read_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _read_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _read_html(data: bytes) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(data.decode("utf-8", errors="ignore"))
    return parser.get_text()


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _read_pdf(data)
    if ext in (".docx", ".doc"):
        if ext == ".doc":
            raise ValueError("Legacy .doc files are not supported. Please upload .docx, .pdf, or .html")
        return _read_docx(data)
    if ext in (".html", ".htm"):
        return _read_html(data)
    raise ValueError("Unsupported file type. Upload PDF, Word (.docx), or HTML.")


def _section(text: str, header: str) -> str:
    pattern = rf"(?im)^{re.escape(header)}\s*[:\-]?\s*\n(.*?)(?=\n[A-Z][A-Za-z /&]+\s*[:\-]?\s*\n|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _first_match(pattern: str, text: str, group: int = 1) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(group).strip() if match else None


def _extract_name(lines: list[str]) -> str | None:
    for line in lines[:8]:
        cleaned = line.strip()
        if not cleaned or "@" in cleaned or re.search(r"\d{3}[-.\s]?\d{3}", cleaned):
            continue
        if len(cleaned.split()) >= 2 and len(cleaned) < 60:
            return cleaned
    return None


def _extract_job_title(text: str) -> str | None:
    labeled = _first_match(r"(?im)(?:current\s+)?(?:role|position|title)\s*[:\-]\s*(.+)", text)
    if labeled:
        return labeled

    for line in text.splitlines()[:30]:
        lower = line.lower()
        if any(kw in lower for kw in ("analyst", "scientist", "engineer", "manager", "director", "consultant", "developer")):
            if 4 < len(line.strip()) < 80:
                return line.strip()
    return None


def _extract_skills(text: str) -> str | None:
    skills_block = _section(text, "Skills") or _section(text, "Technical Skills") or _section(text, "Core Competencies")
    if skills_block:
        items = re.split(r"[\n,;•·]", skills_block)
        cleaned = [i.strip() for i in items if i.strip()]
        if cleaned:
            return ", ".join(cleaned[:15])

    skill_keywords = re.findall(
        r"\b(SQL|Python|R\b|Tableau|Power BI|Excel|Spark|Snowflake|Looker|dbt|A/B testing|machine learning|statistics)\b",
        text,
        re.IGNORECASE,
    )
    if skill_keywords:
        return ", ".join(dict.fromkeys(s.title() if s.isupper() else s for s in skill_keywords))
    return None


def _extract_years(text: str) -> int | None:
    match = _first_match(r"(\d{1,2})\+?\s*years?(?:\s+of)?\s+(?:experience|exp)", text)
    if match:
        return int(match)
    dates = re.findall(r"(20\d{2})\s*[-–]\s*(20\d{2}|present|current)", text, re.IGNORECASE)
    if dates:
        from datetime import datetime

        current_year = datetime.now().year
        spans = []
        for start, end in dates:
            end_year = current_year if end.lower() in ("present", "current") else int(end)
            spans.append(end_year - int(start))
        if spans:
            return max(1, max(spans))
    return None


def _extract_field(job_title: str | None, text: str) -> str | None:
    if not job_title:
        return None
    lower = job_title.lower()
    mapping = {
        "data analyst": "Data Analytics",
        "data scientist": "Data Science",
        "product analyst": "Product Analytics",
        "marketing": "Marketing",
        "financial analyst": "Finance",
        "software engineer": "Software Engineering",
    }
    for key, field in mapping.items():
        if key in lower:
            return field
    if "analyst" in lower:
        return "Data Analytics"
    return None


def _extract_industry(text: str) -> str | None:
    industries = ["e-commerce", "saas", "retail", "fintech", "healthcare", "media", "consulting"]
    lower = text.lower()
    for ind in industries:
        if ind in lower:
            return ind.title() if ind != "saas" else "SaaS"
    return None


def parse_resume(filename: str, data: bytes) -> dict:
    text = extract_text(filename, data)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    job_title = _extract_job_title(text)
    return {
        "full_name": _extract_name(lines),
        "current_job": job_title,
        "skillset": _extract_skills(text),
        "years_experience": _extract_years(text),
        "field": _extract_field(job_title, text),
        "industry": _extract_industry(text),
        "raw_text_preview": text[:2000],
    }
