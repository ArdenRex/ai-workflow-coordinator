"""Substep 9.1: workflow definition model, retry/trigger rules and strict parsing (pure: no DB, no LLM)."""
import pathlib

import pytest

from app.agents.starter import build_agent_registry
from app.config import Settings
from app.orchestration.plan import ExecutionPlan, levels
from app.runtime import build_runtime
from app.workflows.definition import (HARD_MAX_ATTEMPTS, MAX_DELAY_SECONDS, MAX_INTERVAL_SECONDS, MAX_TRIGGERS,
                                      EventTrigger, ManualTrigger, RetryPolicy, ScheduleTrigger, WorkflowDefinition,
                                      WorkflowStep, from_dict, validate_for_workspace)
from app.workflows.errors import InvalidWorkflowError


def code(fn, *a, **k):
    with pytest.raises(InvalidWorkflowError) as e:
        fn(*a, **k)
    return e.value.code


def st(id, deps=(), **kw):
    return WorkflowStep(id, kw.pop("agent", "ops_agent"), kw.pop("text", "do the thing"), tuple(deps), **kw)


def wf(steps=None, **kw):
    return WorkflowDefinition(kw.pop("id", "daily_review"), kw.pop("name", "Daily review"),
                              tuple([st("a"), st("b", "a")] if steps is None else steps), **kw)


# ------------------------------------------------------------------ retry
@pytest.mark.parametrize("kw", [dict(max_attempts=0), dict(max_attempts=HARD_MAX_ATTEMPTS + 1), dict(max_attempts=True),
                                dict(max_attempts="3"), dict(backoff="random"), dict(delay_seconds=-1),
                                dict(delay_seconds=MAX_DELAY_SECONDS + 1), dict(delay_seconds=10, max_delay_seconds=5),
                                dict(max_delay_seconds=MAX_DELAY_SECONDS + 1), dict(delay_seconds=1.5)])
def test_retry_policy_is_bounded_and_typed(kw):
    assert code(RetryPolicy, **kw) == "invalid_retry"


def test_default_policy_never_retries():
    p = RetryPolicy()
    assert not p.should_retry(1) and p.delay_after(1) == 0


def test_retry_decision_and_delays_are_deterministic():
    p = RetryPolicy(max_attempts=4, backoff="exponential", delay_seconds=10, max_delay_seconds=50)
    assert [p.should_retry(n) for n in (0, 1, 2, 3, 4, 5)] == [False, True, True, True, False, False]
    assert [p.delay_after(n) for n in (0, 1, 2, 3, 4)] == [0, 10, 20, 40, 50]
    f = RetryPolicy(max_attempts=3, delay_seconds=7)
    assert [f.delay_after(n) for n in (1, 2, 3)] == [7, 7, 7]


def test_exponential_delay_never_exceeds_the_cap_even_for_huge_attempt_numbers():
    p = RetryPolicy(max_attempts=5, backoff="exponential", delay_seconds=3600)
    assert p.delay_after(5) == MAX_DELAY_SECONDS == p.delay_after(60)


# ------------------------------------------------------------------ steps
def test_step_reuses_plan_rules_with_the_same_codes():
    assert code(st, "Bad") == "invalid_step_id"
    assert code(WorkflowStep, "a", "Bad-Agent", "x") == "invalid_agent_id"
    assert code(WorkflowStep, "a", "ops_agent", "  ") == "invalid_instruction"
    assert code(WorkflowStep, "a", "ops_agent", "x\x00y") == "invalid_instruction"
    assert code(st, "z", ["z"]) == "self_dependency"
    assert code(st, "z", [f"d{i}" for i in range(6)]) == "too_many_dependencies"


@pytest.mark.parametrize("t", [0, -1, 3601, True, "5", 2.5])
def test_timeout_is_bounded_and_typed(t):
    assert code(st, "a", timeout_seconds=t) == "invalid_timeout"


def test_step_trims_and_dedupes_and_rejects_bad_retry_object():
    s = WorkflowStep("a", "ops_agent", "  hi  ", ("x", "x"))
    assert s.instruction == "hi" and s.depends_on == ("x",)
    assert code(st, "a", retry={"max_attempts": 2}) == "invalid_retry"


def test_steps_and_definitions_are_immutable():
    for obj, attr in ((st("a"), "instruction"), (wf(), "name"), (RetryPolicy(), "max_attempts")):
        with pytest.raises(Exception):
            setattr(obj, attr, "x")


def test_credential_looking_instructions_are_rejected_without_echo():
    secret = "AKIA" + "ABCDEFGHIJKLMNOP"
    with pytest.raises(InvalidWorkflowError) as e:
        st("a", text=f"use key {secret} now")
    assert e.value.code == "secret_detected" and secret not in str(e.value)


# ------------------------------------------------------------------ triggers
@pytest.mark.parametrize("bad", ["", "Lead.Created", "lead..created", "1lead", "a.b.c.d.e", "lead created", None, 5])
def test_event_types_are_strict_dotted_slugs(bad):
    assert code(EventTrigger, bad) == "invalid_trigger"


def test_valid_event_types():
    assert EventTrigger("lead.created").event_type == "lead.created"
    assert EventTrigger("payment").event_type == "payment"


@pytest.mark.parametrize("n", [0, 59, MAX_INTERVAL_SECONDS + 1, True, "3600", 90.5])
def test_schedule_interval_is_bounded_and_typed(n):
    assert code(ScheduleTrigger, n) == "invalid_trigger"
    assert ScheduleTrigger(60).interval_seconds == 60


def test_trigger_set_rules():
    assert wf().triggers == (ManualTrigger(),)
    assert code(wf, triggers=()) == "invalid_trigger"
    assert code(wf, triggers=(ManualTrigger(), ManualTrigger())) == "duplicate_trigger"
    many = tuple(EventTrigger(f"e{i}") for i in range(MAX_TRIGGERS + 1))
    assert code(wf, triggers=many) == "invalid_trigger"
    assert code(wf, triggers=("manual",)) == "invalid_trigger"
    ok = wf(triggers=(EventTrigger("lead.created"), ScheduleTrigger(3600)))
    assert len(ok.triggers) == 2


# ------------------------------------------------------------------ definition
@pytest.mark.parametrize("bad", ["", "A", "1a", "a-b", "x" * 41, None, 5])
def test_workflow_ids_are_slugs(bad):
    assert code(wf, id=bad) == "invalid_workflow_id"


@pytest.mark.parametrize("bad", ["", "  ", "x" * 101, "two\nlines", "tab\there", None])
def test_names_are_one_bounded_line(bad):
    assert code(wf, name=bad) == "invalid_name"


def test_description_bounds_and_multiline_allowed():
    assert wf(description="line one\nline two").description == "line one\nline two"
    assert code(wf, description="x" * 301) == "invalid_description"
    assert code(wf, description=None) == "invalid_description"
    assert code(wf, description="bad\x00") == "invalid_description"


@pytest.mark.parametrize("v", [0, -1, True, "1", 1_000_001])
def test_version_is_bounded_and_typed(v):
    assert code(wf, version=v) == "invalid_version"


def test_secret_in_name_or_description_is_rejected():
    assert code(wf, name="password: hunter22222") == "secret_detected"
    assert code(wf, description="token=abcdefghij") == "secret_detected"


def test_graph_rules_surface_as_workflow_errors():
    assert code(wf, steps=[]) == "invalid_workflow"
    assert code(wf, steps=["not a step"]) == "invalid_workflow"
    assert code(wf, steps=[st("a"), st("a")]) == "duplicate_step_id"
    assert code(wf, steps=[st("a", "ghost")]) == "unknown_dependency"
    assert code(wf, steps=[st("a", "b"), st("b", "a")]) == "dependency_cycle"
    assert code(wf, steps=[st(f"s{i}") for i in range(21)]) == "invalid_plan_size"


def test_to_plan_matches_the_plan_model():
    d = wf(steps=[st("a"), st("b", "a"), st("c", "a"), st("d", ("b", "c"))])
    plan = d.to_plan()
    assert isinstance(plan, ExecutionPlan) and levels(plan) == [["a"], ["b", "c"], ["d"]]
    assert d.step("c").agent_id == "ops_agent"
    with pytest.raises(KeyError):
        d.step("zzz")


def test_digest_covers_behaviour_but_not_labels_and_ignores_dependency_order():
    base = wf(steps=[st("a"), st("b"), st("c", ("a", "b"))])
    same = wf(steps=[st("a"), st("b"), st("c", ("b", "a"))], name="Another name", description="other")
    assert base.digest() == same.digest() and len(base.digest()) == 64
    assert wf(version=2).digest() != wf().digest()
    assert wf(steps=[st("a", text="x"), st("b", "a")]).digest() != wf().digest()
    assert wf(steps=[st("a", retry=RetryPolicy(max_attempts=2)), st("b", "a")]).digest() != wf().digest()
    assert wf(steps=[st("a", timeout_seconds=5), st("b", "a")]).digest() != wf().digest()
    assert wf(triggers=(ScheduleTrigger(60),)).digest() != wf().digest()
    assert wf(triggers=(EventTrigger("a"), ManualTrigger())).digest() == wf(triggers=(ManualTrigger(), EventTrigger("a"))).digest()


# ------------------------------------------------------------------ parsing
def full():
    return {"id": "daily_review", "name": "Daily review", "description": "d", "version": 3,
            "steps": [{"id": "a", "agent_id": "ops_agent", "instruction": "go",
                       "retry": {"max_attempts": 3, "backoff": "exponential", "delay_seconds": 5},
                       "timeout_seconds": 30},
                      {"id": "b", "agent_id": "ops_agent", "instruction": "then", "depends_on": ["a"]}],
            "triggers": [{"type": "manual"}, {"type": "event", "event_type": "lead.created"},
                         {"type": "schedule", "interval_seconds": 3600}]}


def test_round_trip():
    d = from_dict(full())
    assert from_dict(d.to_dict()) == d and d.to_dict()["version"] == 3
    assert d.step("a").retry.max_attempts == 3 and d.step("a").timeout_seconds == 30
    assert d.step("b").retry == RetryPolicy() and d.step("b").depends_on == ("a",)


def test_minimal_input_gets_safe_defaults():
    d = from_dict({"id": "w", "name": "W", "steps": [{"id": "a", "agent_id": "ops_agent", "instruction": "go"}]})
    assert d.version == 1 and d.triggers == (ManualTrigger(),) and d.steps[0].timeout_seconds == 120


def mut(path, value=None, drop=False):
    d = full()
    cur = d
    for k in path[:-1]:
        cur = cur[k]
    if drop:
        del cur[path[-1]]
    else:
        cur[path[-1]] = value
    return d


@pytest.mark.parametrize("data,expected", [
    (None, "invalid_workflow"), ([], "invalid_workflow"), ("x", "invalid_workflow"),
    (mut(["extra"], 1), "unknown_field"),
    (mut(["steps", 0, "extra"], 1), "unknown_field"),
    (mut(["steps", 0, "retry", "extra"], 1), "unknown_field"),
    (mut(["triggers", 1, "extra"], 1), "unknown_field"),
    (mut(["name"], drop=True), "missing_field"),
    (mut(["steps", 0, "agent_id"], drop=True), "missing_field"),
    (mut(["triggers", 1, "event_type"], drop=True), "missing_field"),
    (mut(["steps"], "nope"), "invalid_workflow"),
    (mut(["triggers"], "nope"), "invalid_workflow"),
    (mut(["steps", 0, "depends_on"], "a"), "invalid_workflow"),
    (mut(["steps", 0, "retry"], "x"), "invalid_workflow"),
    (mut(["triggers", 0], {"type": "cron"}), "invalid_trigger"),
    (mut(["triggers", 0], "manual"), "invalid_trigger"),
    (mut(["version"], True), "invalid_version"),
    (mut(["steps", 0, "timeout_seconds"], "30"), "invalid_timeout"),
    (mut(["steps", 0, "retry", "max_attempts"], 99), "invalid_retry"),
])
def test_parser_rejects_malformed_input(data, expected):
    assert code(from_dict, data) == expected


def test_parser_bounds_work_before_parsing_items():
    d = full()
    d["steps"] = [{"bogus": 1}] * 500          # would fail per item; the size check must come first
    assert code(from_dict, d) == "invalid_workflow"
    d = full()
    d["triggers"] = [{"type": "manual"}] * 50
    assert code(from_dict, d) == "invalid_workflow"


def test_errors_never_echo_input():
    d = full()
    d["steps"][0]["instruction"] = "password: supersecretvalue123"
    with pytest.raises(InvalidWorkflowError) as e:
        from_dict(d)
    assert "supersecretvalue123" not in str(e.value)
    d = full()
    d["zzz_unexpected_key"] = 1
    with pytest.raises(InvalidWorkflowError) as e:
        from_dict(d)
    assert "zzz_unexpected_key" not in str(e.value)


# ------------------------------------------------------------------ workspace checks
@pytest.fixture
def agents():
    reg, _ = build_runtime(Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None))
    return build_agent_registry(reg)


def test_workspace_validation_checks_agents_and_size(agents):
    validate_for_workspace(wf(), agents, max_steps=10)
    assert code(validate_for_workspace, wf(steps=[st("a", agent="ghost_agent")]), agents, max_steps=10) == "unknown_agent"
    assert code(validate_for_workspace, wf(steps=[st(f"s{i}") for i in range(4)]), agents, max_steps=3) == "plan_too_large"


def test_workflow_size_setting_is_bounded():
    assert Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None).workflow_max_steps == 10
    for bad in (0, 21):
        with pytest.raises(Exception):
            Settings(app_env="test", database_url="sqlite:///:memory:", workflow_max_steps=bad, _env_file=None)


def test_the_workflow_modules_are_pure():
    for f in ("definition.py", "errors.py"):
        src = pathlib.Path("app/workflows", f).read_text()
        for banned in ("sqlalchemy", "app.llm", "app.kernel.service", "requests", "httpx", "open(", "datetime", "random"):
            assert banned not in src
