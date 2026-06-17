# tests/conftest.py
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_resume_path() -> str:
    return str(FIXTURES_DIR / "sample_resume.txt")

@pytest.fixture
def bigset_csv_path() -> str:
    return str(FIXTURES_DIR / "bigset_export.csv")
