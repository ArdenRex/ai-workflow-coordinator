"""CRM domain interface, tool schemas and kernel tools (read-only in 10.2).

Tools are vendor-neutral (`crm.lead.list`, `crm.lead.get`, permission `crm:read`, low risk). Whichever CRM the workspace
has connected serves them (WorkspaceConnectors.for_domain). A connector for the domain implements `CrmConnector`; if the
connected provider does not, the tool fails with a configuration error rather than guessing.

Outputs are an explicit allow-list: unknown remote fields (phone numbers, addresses, notes, owners) are dropped, and
every free-text field is cleaned and length-capped because it came from an external system (see kit.ExternalText).
"""
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.connectors.base import BaseConnector
from app.connectors.domains import business_tool
from app.connectors.errors import ConnectorConfigError
from app.connectors.kit import ExternalText
from app.connectors.writes import check_email, check_line
from app.kernel.registry import ToolDefinition

CURSOR_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"
LEAD_ID_PATTERN = r"^[0-9]{1,20}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListLeadsInput(_Strict):
    limit: int = Field(default=25, ge=1, le=100)
    cursor: Optional[str] = Field(default=None, pattern=CURSOR_PATTERN)


class GetLeadInput(_Strict):
    lead_id: str = Field(pattern=LEAD_ID_PATTERN)


class Lead(BaseModel):
    id: str = Field(pattern=LEAD_ID_PATTERN)
    first_name: Optional[ExternalText(100)] = None
    last_name: Optional[ExternalText(100)] = None
    email: Optional[ExternalText(254)] = None
    company: Optional[ExternalText(200)] = None
    stage: Optional[ExternalText(64)] = None
    created_at: Optional[ExternalText(40)] = None
    updated_at: Optional[ExternalText(40)] = None


class ListLeadsOutput(BaseModel):
    leads: List[Lead]
    next_cursor: Optional[str] = None


class GetLeadOutput(BaseModel):
    lead: Lead


class CrmConnector(ABC):
    """What a connector must provide to serve the `crm` domain."""

    @abstractmethod
    def list_leads(self, data: ListLeadsInput) -> ListLeadsOutput: ...

    @abstractmethod
    def get_lead(self, data: GetLeadInput) -> GetLeadOutput: ...


def _crm(provider: Callable[[str], BaseConnector], workspace_id: str) -> CrmConnector:
    connector = provider(workspace_id)
    if not isinstance(connector, CrmConnector):
        raise ConnectorConfigError("The connected system does not support CRM tools")
    return connector


def crm_tool_definitions(provider: Callable[[str], BaseConnector]) -> List[ToolDefinition]:
    """Kernel tools. `provider(workspace_id)` returns that workspace's single connected CRM connector."""

    def _list(ctx, data: ListLeadsInput):
        return _crm(provider, ctx.workspace_id).list_leads(data).model_dump()

    def _get(ctx, data: GetLeadInput):
        return _crm(provider, ctx.workspace_id).get_lead(data).model_dump()

    return [
        business_tool("crm", "read", resource="lead", action="list", handler=_list, timeout_seconds=30,
                      description="List leads (contacts) from the connected CRM, newest first by the CRM's own order. "
                                  "Returns a cursor for the next page.",
                      input_schema=ListLeadsInput, output_schema=ListLeadsOutput),
        business_tool("crm", "read", resource="lead", action="get", handler=_get, timeout_seconds=30,
                      description="Get one lead (contact) from the connected CRM by its id.",
                      input_schema=GetLeadInput, output_schema=GetLeadOutput),
    ]


# ------------------------------------------------------------------ write side (10.5)
class CreateLeadInput(_Strict):
    email: str
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    company: Optional[str] = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def _addr(cls, v):
        return check_email(v)

    @field_validator("first_name", "last_name", "company")
    @classmethod
    def _line(cls, v):
        return None if v is None else check_line(v)


class CreateLeadOutput(BaseModel):
    lead: Lead


class CrmWriter(ABC):
    @abstractmethod
    def create_lead(self, data: CreateLeadInput) -> CreateLeadOutput: ...


def crm_write_tool_definitions(provider: Callable[[str], BaseConnector]) -> List[ToolDefinition]:
    def _create(ctx, data: CreateLeadInput):
        connector = provider(ctx.workspace_id)
        if not isinstance(connector, CrmWriter):
            raise ConnectorConfigError("The connected system does not support CRM writes")
        return connector.create_lead(data).model_dump()

    return [business_tool("crm", "write", resource="lead", action="create", handler=_create, timeout_seconds=30,
                          description="Create a lead (contact) in the connected CRM. Always needs human approval.",
                          input_schema=CreateLeadInput, output_schema=CreateLeadOutput)]
