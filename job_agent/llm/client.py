import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, api_key: str, model: str, max_total_calls: int = 200):
        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = model
        self.max_total_calls = max_total_calls
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def is_over_budget(self) -> bool:
        return self._call_count >= self.max_total_calls

    def call(self, system: str, user: str, *, expect_json: bool = False) -> str:
        """Single LLM call with one automatic retry. Raises LLMError on failure."""
        if self.is_over_budget():
            raise LLMError(f"LLM call budget exhausted ({self.max_total_calls} calls)")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict = {"model": self.model, "messages": messages}
        if expect_json:
            kwargs["response_format"] = {"type": "json_object"}

        self._call_count += 1
        try:
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as exc:
            logger.warning(f"LLM call failed, retrying once: {exc}")
            if self.is_over_budget():
                raise LLMError("LLM budget exhausted during retry") from exc
            self._call_count += 1
            try:
                resp = self._client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
            except Exception as exc2:
                raise LLMError(f"LLM call failed after retry: {exc2}") from exc2

    def call_json(self, system: str, user: str) -> dict:
        """Call LLM, parse JSON. Raises LLMError if response is not valid JSON."""
        raw = self.call(system, user, expect_json=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned invalid JSON: {raw[:200]}") from exc
