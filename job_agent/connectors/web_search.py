# job_agent/connectors/web_search.py
import logging
import httpx
from job_agent.models import RawResult

logger = logging.getLogger(__name__)


class WebSearchConnector:
    def __init__(self, api_key: str, connector_type: str = "generic"):
        self._api_key = api_key
        self.connector_type = connector_type

    def search(self, query: str, num: int = 10) -> list[RawResult]:
        try:
            resp = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self._api_key, "Content-Type": "application/json"},
                json={"q": query, "num": num},
                timeout=15.0,
            )
            resp.raise_for_status()
            return [
                RawResult(
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                )
                for item in resp.json().get("organic", [])
            ]
        except Exception as exc:
            logger.error(f"[web_search] search failed for '{query}': {exc}")
            return []
