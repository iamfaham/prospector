# prospector/connectors/web_search.py
#
# Uses Tavily Search API — 1,000 queries/month FREE, no credit card.
# Sign up at https://app.tavily.com → copy your API key.
import logging
import httpx
from prospector.models import RawResult

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"


class WebSearchConnector:
    def __init__(self, api_key: str, connector_type: str = "generic"):
        self._api_key = api_key
        self.connector_type = connector_type

    def search(self, query: str, num: int = 10) -> list[RawResult]:
        try:
            resp = httpx.post(
                _TAVILY_URL,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": min(num, 20),
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            return [
                RawResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("content", ""),
                )
                for item in resp.json().get("results", [])
            ]
        except Exception as exc:
            logger.error("[web_search] search failed for '%s': %s", query, exc)
            return []
