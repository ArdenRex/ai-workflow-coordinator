"""Business domains and the rules every business tool must follow (Step 10).

Tools are domain-level (`crm.lead.create`, `email.send`, `calendar.availability.read`), so agents and workflows never
name a vendor; whichever connector the workspace has connected for the domain serves them (see
WorkspaceConnectors.for_domain). `business_tool` is the only way these tools are built, and it enforces:

    verb kind   read   -> LOW risk, may declare retries (reads only)
                write  -> MEDIUM or HIGH risk, approval required, never retried
                send   -> HIGH risk, approval required, never retried (leaves the company's boundary)
    permission  always `<domain>:<verb>`; held only by ADMIN and OWNER until Step 11/12 assign it deliberately
"""
from typing import Any, Callable, Dict, Optional, Type

from pydantic import BaseModel

from app.kernel.errors import InvalidToolDefinitionError
from app.kernel.registry import ToolDefinition
from app.models.enums import RiskLevel

# domain -> verb -> kind
DOMAINS: Dict[str, Dict[str, str]] = {
    "email": {"read": "read", "draft": "write", "send": "send"},
    "calendar": {"read": "read", "write": "write"},
    "crm": {"read": "read", "write": "write"},
    "chat": {"read": "read", "post": "send"},
    "project": {"read": "read", "write": "write"},
}


def domain_permissions() -> frozenset:
    return frozenset(f"{d}:{v}" for d, verbs in DOMAINS.items() for v in verbs)


def verb_kind(domain: str, verb: str) -> str:
    try:
        return DOMAINS[domain][verb]
    except KeyError:
        raise InvalidToolDefinitionError("Unknown business domain or verb") from None


def business_tool(domain: str, verb: str, *, action: str, resource: Optional[str] = None, description: str,
                  input_schema: Type[BaseModel], output_schema: Type[BaseModel], handler: Callable[..., Any],
                  risk: Optional[RiskLevel] = None, timeout_seconds: int = 30, max_retries: int = 0) -> ToolDefinition:
    """Build a business tool. Id is `domain[.resource].action`; the permission is `domain:verb`."""
    kind = verb_kind(domain, verb)
    if kind == "read":
        if risk not in (None, RiskLevel.LOW):
            raise InvalidToolDefinitionError("Read tools are low risk")
        risk, approval, retries = RiskLevel.LOW, None, max_retries
    else:
        if kind == "send":
            if risk not in (None, RiskLevel.HIGH):
                raise InvalidToolDefinitionError("Send tools are high risk")
            risk = RiskLevel.HIGH
        elif risk not in (None, RiskLevel.MEDIUM, RiskLevel.HIGH):
            raise InvalidToolDefinitionError("Write tools are at least medium risk")
        risk = risk or RiskLevel.MEDIUM
        approval, retries = True, 0                                   # writes always need a human until Step 12
    tool_id = ".".join(p for p in (domain, resource, action) if p)
    return ToolDefinition(id=tool_id, description=description, input_schema=input_schema, output_schema=output_schema,
                          required_permission=f"{domain}:{verb}", risk_level=risk, requires_approval=approval,
                          timeout_seconds=timeout_seconds, max_retries=retries, handler=handler)
