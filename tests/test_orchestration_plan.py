"""Substep 7.1: execution plan model, graph logic and validation (pure: no DB, no LLM)."""
import pytest

from app.agents.starter import build_agent_registry
from app.config import Settings
from app.kernel.builtin_tools import build_default_registry
from app.orchestration.errors import InvalidPlanError
from app.models.enums import StepState as S
from app.orchestration.plan import (HARD_MAX_STEPS, MAX_DEPENDENCIES, MAX_INSTRUCTION_CHARS, ExecutionPlan, PlanStep,
                                    descendants, is_finished, levels, outcome, ready_steps,
                                    steps_to_skip, topological_order, validate_for_workspace)
from app.runtime import build_runtime


def st(id, deps=(), agent="ops_agent", text="do the thing"):
    return PlanStep(id, agent, text, tuple(deps))


def code(fn, *a, **k):
    with pytest.raises(InvalidPlanError) as e:
        fn(*a, **k)
    return e.value.code


# diamond:  a -> b, c -> d ;  plus an independent e
@pytest.fixture
def plan():
    return ExecutionPlan((st("a"), st("b", "a"), st("c", "a"), st("d", ("b", "c")), st("e")))


# ------------------------------------------------------------------ steps
@pytest.mark.parametrize("bad", ["", "A", "1a", "a-b", "a b", "x" * 33, "../x", None, 5])
def test_step_ids_are_strict_slugs(bad):
    assert code(PlanStep, bad, "ops_agent", "x") == "invalid_step_id"


@pytest.mark.parametrize("bad", ["", "Ops", "ops-agent", "x" * 40, None])
def test_agent_ids_are_strict(bad):
    assert code(PlanStep, "a", bad, "x") == "invalid_agent_id"


@pytest.mark.parametrize("text", ["", "   ", None, "x" * (MAX_INSTRUCTION_CHARS + 1), "bad\x00char", "esc\x1b[0m"])
def test_instructions_are_bounded_plain_text(text):
    assert code(PlanStep, "a", "ops_agent", text) == "invalid_instruction"


def test_instruction_whitespace_is_trimmed_and_newlines_are_allowed():
    s = PlanStep("a", "ops_agent", "  line one\nline two  ")
    assert s.instruction == "line one\nline two"


def test_dependencies_are_deduplicated_and_bounded():
    assert st("z", ["a", "a", "b"]).depends_on == ("a", "b")
    assert code(st, "z", [f"d{i}" for i in range(MAX_DEPENDENCIES + 1)]) == "too_many_dependencies"
    assert code(st, "z", ["Bad Id"]) == "invalid_step_id"
    assert code(st, "z", ["z"]) == "self_dependency"


def test_steps_are_immutable():
    with pytest.raises(Exception):
        st("a").id = "b"


# ------------------------------------------------------------------ plan validation
def test_plan_size_bounds():
    assert code(ExecutionPlan, ()) == "invalid_plan_size"
    assert code(ExecutionPlan, tuple(st(f"s{i}") for i in range(HARD_MAX_STEPS + 1))) == "invalid_plan_size"
    assert len(ExecutionPlan(tuple(st(f"s{i}") for i in range(HARD_MAX_STEPS))).steps) == HARD_MAX_STEPS


def test_plan_rejects_junk_duplicates_unknown_deps_and_cycles():
    assert code(ExecutionPlan, ("not a step",)) == "invalid_plan"
    assert code(ExecutionPlan, (st("a"), st("a"))) == "duplicate_step_id"
    assert code(ExecutionPlan, (st("a", "ghost"),)) == "unknown_dependency"
    assert code(ExecutionPlan, (st("a", "b"), st("b", "a"))) == "dependency_cycle"
    assert code(ExecutionPlan, (st("a", "c"), st("b", "a"), st("c", "b"))) == "dependency_cycle"
    assert code(ExecutionPlan, (st("ok"), st("a", "b"), st("b", "a"))) == "dependency_cycle"


def test_a_plan_may_be_given_as_a_list():
    assert ExecutionPlan([st("a")]).ids == ("a",)


# ------------------------------------------------------------------ graph logic
def test_topological_order_respects_dependencies_and_is_deterministic(plan):
    order = [s.id for s in topological_order(plan)]
    assert order.index("a") < order.index("b") < order.index("d") and order.index("c") < order.index("d")
    assert order == [s.id for s in topological_order(plan)]
    assert len(order) == 5


def test_levels_group_independent_steps(plan):
    assert levels(plan) == [["a", "e"], ["b", "c"], ["d"]]
    assert levels(ExecutionPlan((st("x"),))) == [["x"]]


def test_descendants_are_transitive_and_exclude_independent_branches(plan):
    assert descendants(plan, "a") == {"b", "c", "d"}
    assert descendants(plan, "b") == {"d"} and descendants(plan, "d") == set() and descendants(plan, "e") == set()


def test_ready_steps_need_every_dependency_to_have_succeeded(plan):
    assert [s.id for s in ready_steps(plan, {})] == ["a", "e"]
    assert [s.id for s in ready_steps(plan, {"a": S.SUCCEEDED})] == ["b", "c", "e"]
    assert [s.id for s in ready_steps(plan, {"a": S.SUCCEEDED, "b": S.SUCCEEDED})] == ["c", "e"]
    done = {"a": S.SUCCEEDED, "b": S.SUCCEEDED, "c": S.SUCCEEDED}
    assert [s.id for s in ready_steps(plan, done)] == ["d", "e"]


@pytest.mark.parametrize("state", [S.RUNNING, S.WAITING_APPROVAL, S.FAILED, S.SKIPPED, S.CANCELLED, S.SUCCEEDED])
def test_a_step_that_is_not_pending_is_never_ready_again(plan, state):
    assert "a" not in [s.id for s in ready_steps(plan, {"a": state})]


@pytest.mark.parametrize("dead", [S.FAILED, S.SKIPPED, S.CANCELLED])
def test_a_dead_dependency_never_unblocks_its_dependents(plan, dead):
    states = {"a": S.SUCCEEDED, "b": dead, "c": S.SUCCEEDED}
    assert "d" not in [s.id for s in ready_steps(plan, states)]
    assert steps_to_skip(plan, states) == ["d"]


def test_failure_propagates_transitively_but_not_to_independent_branches(plan):
    skip = steps_to_skip(plan, {"a": S.FAILED})
    assert set(skip) == {"b", "c", "d"} and "e" not in skip
    assert [s.id for s in ready_steps(plan, {"a": S.FAILED})] == ["e"]


def test_running_or_waiting_dependencies_block_without_skipping(plan):
    states = {"a": S.WAITING_APPROVAL}
    assert steps_to_skip(plan, states) == [] and [s.id for s in ready_steps(plan, states)] == ["e"]


def test_finish_and_outcome(plan):
    ok = {i: S.SUCCEEDED for i in plan.ids}
    assert is_finished(plan, ok) and outcome(plan, ok) == "succeeded"
    part = {**ok, "b": S.FAILED, "d": S.SKIPPED}
    assert is_finished(plan, part) and outcome(plan, part) == "failed"
    assert not is_finished(plan, {**ok, "d": S.RUNNING}) and not is_finished(plan, {})
    assert outcome(plan, {**ok, "d": S.CANCELLED}) == "failed"


# ------------------------------------------------------------------ digest
def test_digest_is_stable_content_bound_and_order_insensitive_for_dependencies():
    a = ExecutionPlan((st("a"), st("b", "a")))
    same = ExecutionPlan((st("a"), st("b", "a")))
    assert a.digest() == same.digest() and len(a.digest()) == 64
    assert a.digest() != ExecutionPlan((st("a"), st("b", "a", text="other"))).digest()
    assert a.digest() != ExecutionPlan((st("a"), st("b"))).digest()
    assert a.digest() != ExecutionPlan((st("a"), st("b", "a", agent="insight_agent"))).digest()
    two = ExecutionPlan((st("a"), st("c"), st("b", ("a", "c"))))
    assert two.digest() == ExecutionPlan((st("a"), st("c"), st("b", ("c", "a")))).digest()


# ------------------------------------------------------------------ workspace validation
@pytest.fixture
def agents():
    return build_agent_registry(build_runtime(Settings(app_env="test", database_url="sqlite:///:memory:",
                                                       _env_file=None))[0])


def test_workspace_validation_checks_agents_and_size(agents):
    ok = ExecutionPlan((st("a"), st("b", "a", agent="insight_agent")))
    validate_for_workspace(ok, agents, max_steps=8)
    assert code(validate_for_workspace, ExecutionPlan((st("a", agent="ghost_agent"),)), agents, max_steps=8) == "unknown_agent"
    big = ExecutionPlan(tuple(st(f"s{i}") for i in range(9)))
    assert code(validate_for_workspace, big, agents, max_steps=8) == "plan_too_large"
    validate_for_workspace(big, agents, max_steps=9)


def test_plan_size_setting_is_bounded():
    assert Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None).plan_max_steps == 8
    for bad in (0, 21):
        with pytest.raises(Exception):
            Settings(app_env="test", database_url="sqlite:///:memory:", plan_max_steps=bad, _env_file=None)


def test_the_plan_module_is_pure():
    import pathlib
    src = pathlib.Path("app/orchestration/plan.py").read_text()
    for banned in ("sqlalchemy", "app.llm", "app.kernel.service", "requests", "httpx", "open("):
        assert banned not in src
