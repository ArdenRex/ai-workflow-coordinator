"""HubSpot CRM connector (read-only): contacts as leads, via a private-app bearer token.

Only GET requests are ever made here. The token is held by KitConnector and never leaves the config.
API shape assumed (HubSpot CRM v3 objects): GET /crm/v3/objects/contacts[?limit&after&properties&archived],
GET /crm/v3/objects/contacts/{id}; results carry `id`, `properties`, `createdAt`, `updatedAt`, `archived`, and
`paging.next.after` for the next page. Verify against a real HubSpot account before relying on it in production.
"""
import re
from typing import Any, List

from pydantic import ValidationError

from app.connectors.base import Capability, ConnectionStatus
from app.connectors.crm.base import (CURSOR_PATTERN, CreateLeadInput, CreateLeadOutput, CrmConnector, CrmWriter, GetLeadInput, GetLeadOutput, Lead, ListLeadsInput,
                                     ListLeadsOutput, crm_tool_definitions)
from app.connectors.errors import ConnectorBadResponseError
from app.connectors.kit import KitConnector
from app.connectors.writes import WriteGate
from app.kernel.registry import ToolDefinition

CONTACTS = "/crm/v3/objects/contacts"
PROPERTIES = "firstname,lastname,email,company,lifecyclestage"
_CURSOR = re.compile(CURSOR_PATTERN)


class HubSpotConnector(KitConnector, CrmConnector, CrmWriter, WriteGate):
    name = "hubspot"
    auth_kind = "bearer"
    probe_path = CONTACTS
    probe_params = {"limit": 1}

    def __init__(self, config, *, allow_write: bool = False, **kw):
        self.allow_write = allow_write
        super().__init__(config, **kw)

    def capabilities(self) -> List[Capability]:
        caps = [Capability("lead.list", "List contacts as leads"), Capability("lead.get", "Get one contact as a lead")]
        if self.allow_write:
            caps.append(Capability("lead.create", "Create a contact as a lead", write=True))
        return caps

    def tools(self) -> List[ToolDefinition]:
        return crm_tool_definitions(lambda workspace_id: self)

    # -- reads -----------------------------------------------------------------
    def list_leads(self, data: ListLeadsInput) -> ListLeadsOutput:
        params = {"limit": data.limit, "properties": PROPERTIES, "archived": "false"}
        if data.cursor:
            params["after"] = data.cursor
        raw = self._request("GET", CONTACTS, params=params)
        if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
            raise ConnectorBadResponseError("External system returned an unexpected shape")
        leads = [self._lead(r) for r in raw["results"] if not (isinstance(r, dict) and r.get("archived") is True)]
        return ListLeadsOutput(leads=leads[:data.limit], next_cursor=self._next(raw))

    def get_lead(self, data: GetLeadInput) -> GetLeadOutput:
        raw = self._request("GET", f"{CONTACTS}/{data.lead_id}", params={"properties": PROPERTIES})
        lead = self._lead(raw)
        if lead.id != data.lead_id:                                   # the remote must answer for the lead we asked for
            raise ConnectorBadResponseError("External system returned an unexpected shape")
        return GetLeadOutput(lead=lead)

    # -- parsing (allow-list; everything else is dropped) ------------------------
    @staticmethod
    def _lead(raw: Any) -> Lead:
        p = raw.get("properties") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or not (p is None or isinstance(p, dict)):
            raise ConnectorBadResponseError("External system returned an unexpected shape")
        p = p or {}
        try:
            return Lead(id=raw.get("id"), first_name=p.get("firstname"), last_name=p.get("lastname"),
                        email=p.get("email"), company=p.get("company"), stage=p.get("lifecyclestage"),
                        created_at=raw.get("createdAt"), updated_at=raw.get("updatedAt"))
        except ValidationError:
            raise ConnectorBadResponseError("External system returned an unexpected shape") from None

    @staticmethod
    def _next(raw: dict):
        paging = raw.get("paging")
        if paging is None:
            return None
        after = paging.get("next", {}).get("after") if isinstance(paging, dict) and isinstance(paging.get("next", {}), dict) else False
        if after is None:
            return None
        if not isinstance(after, str) or not _CURSOR.match(after):
            raise ConnectorBadResponseError("External system returned an unexpected shape")
        return after


    # -- writes (10.5): only when the connection has allow_write; never retried -------------------------------------
    def create_lead(self, data: CreateLeadInput) -> CreateLeadOutput:
        self._require_write()
        props = {"email": data.email}
        for key, value in (("firstname", data.first_name), ("lastname", data.last_name), ("company", data.company)):
            if value:
                props[key] = value
        lead = self._lead(self._request("POST", CONTACTS, json_body={"properties": props}))
        if (lead.email or "").lower() != data.email.lower():      # the remote must have created what was approved
            raise ConnectorBadResponseError("External system returned an unexpected shape")
        return CreateLeadOutput(lead=lead)
