import pytest
from unittest.mock import MagicMock, patch
from prospector.llm.client import LLMClient, LLMError

@pytest.fixture
def client():
    return LLMClient(api_key="test-key", model="anthropic/claude-haiku-4-5", max_total_calls=5)

def test_call_returns_content(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = client.call("system", "user")
    assert result == "hello"

def test_call_increments_counter(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "x"
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        client.call("s", "u")
        client.call("s", "u")
    assert client.call_count == 2

def test_call_budget_exceeded_raises(client):
    client._call_count = 5
    with pytest.raises(LLMError, match="budget exhausted"):
        client.call("s", "u")

def test_call_json_parses(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"score": 8, "reasoning": "good"}'
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = client.call_json("s", "u")
    assert result == {"score": 8, "reasoning": "good"}

def test_call_json_invalid_raises(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "not json"
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        with pytest.raises(LLMError, match="invalid JSON"):
            client.call_json("s", "u")

def test_retry_on_first_failure(client):
    mock_ok = MagicMock()
    mock_ok.choices[0].message.content = "ok"
    call_count = {"n": 0}
    def side_effect(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("transient error")
        return mock_ok
    with patch.object(client._client.chat.completions, "create", side_effect=side_effect):
        result = client.call("s", "u")
    assert result == "ok"
    assert client.call_count == 2
