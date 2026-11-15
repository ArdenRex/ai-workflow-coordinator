import pytest
from pydantic import BaseModel, ConfigDict

from app.kernel.builtin_tools import build_default_registry
from app.kernel.errors import (DuplicateToolError, InvalidToolDefinitionError,
                               ToolInputError, ToolNotFoundError, ToolOutputError)
from app.kernel.registry import ToolDefinition, ToolRegistry
from app.models.enums import RiskLevel


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int


class Out(BaseModel):
    name: str


def make(**kw):
    base = dict(id="aceden.customer.read", description="Read a customer", input_schema=In,
                output_schema=Out, required_permission="customer:read", risk_level=RiskLevel.LOW)
    base.update(kw)
    return ToolDefinition(**base)


def test_register_get_list_sorted():
    r = ToolRegistry()
    r.register(make(id="b.thing.read"))
    r.register(make(id="a.thing.read"))
    assert [t.id for t in r.list()] == ["a.thing.read", "b.thing.read"]
    assert r.get("a.thing.read").risk_level == RiskLevel.LOW


def test_duplicate_and_unknown():
    r = ToolRegistry()
    r.register(make())
    with pytest.raises(DuplicateToolError):
        r.register(make())
    with pytest.raises(ToolNotFoundError):
        r.get("nope.tool")


@pytest.mark.parametrize("bad", ["Aceden.read", "single", "a..b", "a.b-c", "1a.b", "a.b.c.d.e"])
def test_invalid_tool_ids_rejected(bad):
    with pytest.raises(InvalidToolDefinitionError):
        make(id=bad)


def test_invalid_permission_and_limits():
    for kw in ({"required_permission": "Read"}, {"timeout_seconds": 0},
               {"timeout_seconds": 9999}, {"description": " "}, {"max_retries": 9}):
        with pytest.raises(InvalidToolDefinitionError):
            make(**kw)


def test_approval_defaults_by_risk():
    assert make(risk_level=RiskLevel.LOW).approval_required is False
    assert make(risk_level=RiskLevel.MEDIUM).approval_required is False
    assert make(risk_level=RiskLevel.MEDIUM, requires_approval=True).approval_required is True
    assert make(risk_level=RiskLevel.HIGH).approval_required is True


def test_high_risk_cannot_opt_out_of_approval():
    with pytest.raises(InvalidToolDefinitionError):
        make(risk_level=RiskLevel.HIGH, requires_approval=False)


def test_only_low_risk_tools_may_retry():
    assert make(max_retries=2).max_retries == 2
    with pytest.raises(InvalidToolDefinitionError):
        make(risk_level=RiskLevel.MEDIUM, max_retries=1)


def test_input_validation_ok_and_errors_do_not_echo_values():
    r = ToolRegistry()
    r.register(make())
    assert r.validate_input("aceden.customer.read", {"customer_id": 5}).customer_id == 5
    with pytest.raises(ToolInputError) as e:
        r.validate_input("aceden.customer.read", {"customer_id": "SECRET-TOKEN-xyz"})
    assert "SECRET-TOKEN-xyz" not in str(e.value)
    with pytest.raises(ToolInputError):
        r.validate_input("aceden.customer.read", {"customer_id": 1, "extra": 1})  # extra=forbid


def test_output_validation():
    r = ToolRegistry()
    r.register(make())
    assert r.validate_output("aceden.customer.read", {"name": "A"}).name == "A"
    with pytest.raises(ToolOutputError):
        r.validate_output("aceden.customer.read", {"wrong": 1})


def test_describe_exposes_no_handler():
    d = make(handler=lambda *a: 1).describe()
    assert "handler" not in d and d["input_schema"]["properties"]["customer_id"]


def test_default_registry_has_ping():
    r = build_default_registry()
    assert r.has("system.ping")
    assert r.validate_input("system.ping", {}).message == "ping"
