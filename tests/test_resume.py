import pytest
from pathlib import Path
from prospector.resume import parse_resume, make_resume_summary


def test_parse_txt_resume(sample_resume_path):
    text = parse_resume(sample_resume_path)
    assert "python" in text.lower()
    assert "backend" in text.lower()


def test_parse_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_resume("nonexistent.pdf")


def test_make_resume_summary(sample_resume_path):
    text = parse_resume(sample_resume_path)
    summary = make_resume_summary(text, max_chars=100)
    assert len(summary) <= 100
    assert len(summary) > 0


def test_make_resume_summary_default_length(sample_resume_path):
    text = parse_resume(sample_resume_path)
    summary = make_resume_summary(text)
    assert len(summary) <= 500
