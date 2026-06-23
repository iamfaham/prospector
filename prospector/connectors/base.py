# prospector/connectors/base.py
from typing import Protocol, runtime_checkable
from prospector.models import RawResult


@runtime_checkable
class SourceConnector(Protocol):
    connector_type: str

    def search(self, query: str) -> list[RawResult]: ...
