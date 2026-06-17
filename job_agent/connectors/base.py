# job_agent/connectors/base.py
from typing import Protocol, runtime_checkable
from job_agent.models import RawResult


@runtime_checkable
class SourceConnector(Protocol):
    connector_type: str

    def search(self, query: str) -> list[RawResult]: ...
