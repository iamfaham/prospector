# job_agent/connectors/bigset.py
import csv
import logging
from pathlib import Path
from job_agent.models import RawResult

logger = logging.getLogger(__name__)


class BigSetConnector:
    connector_type = "bigset"

    def __init__(self, csv_path: str):
        self._csv_path = Path(csv_path)

    def search(self, query: str) -> list[RawResult]:
        """Read all rows from BigSet CSV export. The query arg is unused — returns all rows."""
        if not self._csv_path.exists():
            logger.warning(f"[bigset] CSV not found: {self._csv_path}")
            return []
        results: list[RawResult] = []
        with open(self._csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                url = row.get("url") or row.get("website") or row.get("link") or ""
                title = row.get("name") or row.get("company") or row.get("title") or ""
                snippet = row.get("description") or row.get("snippet") or row.get("summary") or ""
                if title or url:
                    results.append(RawResult(url=url, title=title, snippet=snippet))
        return results
