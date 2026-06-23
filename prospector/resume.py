from pathlib import Path


def parse_resume(resume_path: str) -> str:
    """Extract text from a PDF or plaintext resume file."""
    path = Path(resume_path)
    if not path.exists():
        raise FileNotFoundError(f"Resume not found: {resume_path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    return path.read_text(encoding="utf-8")


def _parse_pdf(path: Path) -> str:
    import pdfplumber
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def make_resume_summary(resume_text: str, max_chars: int = 500) -> str:
    """Return the first max_chars of the resume as a brief outreach summary."""
    return resume_text[:max_chars].strip()
