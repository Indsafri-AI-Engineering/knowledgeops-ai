from typing import Literal, Protocol

from pydantic import BaseModel

ConnectorStatus = Literal["mock"]


class ConnectorMetadata(BaseModel):
    connector: str
    status: ConnectorStatus = "mock"


class KnowledgeConnector(Protocol):
    metadata: ConnectorMetadata
