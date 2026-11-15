"""Agent registry. When bound to a tool registry it validates every agent at registration time, so a
typo or an over-narrow scope fails loudly at startup instead of silently producing a useless agent."""
from typing import Dict, List, Optional

from app.agents.definition import AgentDefinition, effective_tools
from app.agents.errors import (AgentNotFoundError, DuplicateAgentError, InvalidAgentDefinitionError,
                               UnknownToolPatternError)
from app.kernel.registry import ToolRegistry


class AgentRegistry:
    def __init__(self, tools: Optional[ToolRegistry] = None) -> None:
        self._agents: Dict[str, AgentDefinition] = {}
        self._tools = tools

    def register(self, agent: AgentDefinition) -> AgentDefinition:
        if agent.id in self._agents:
            raise DuplicateAgentError(f"Agent already registered: {agent.id}")
        if self._tools is not None:
            self._check_against_tools(agent)
        self._agents[agent.id] = agent
        return agent

    def _check_against_tools(self, agent: AgentDefinition) -> None:
        known = [t.id for t in self._tools.list()]
        for pattern in agent.tool_patterns:
            if not any(_single(pattern, t) for t in known):
                raise UnknownToolPatternError(f"Tool pattern matches no registered tool: {pattern!r}")
        if agent.tool_patterns and not effective_tools(agent, self._tools):
            raise InvalidAgentDefinitionError("Agent has no usable tools (check its permission scope and risk ceiling)")

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise AgentNotFoundError(f"Unknown agent: {agent_id}") from None

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def list(self) -> List[AgentDefinition]:
        return sorted(self._agents.values(), key=lambda a: a.id)

    def find_by_capability(self, capability: str) -> List[AgentDefinition]:
        return [a for a in self.list() if capability in a.capabilities]


def _single(pattern: str, tool_id: str) -> bool:
    """Does this ONE pattern match this tool id (used to catch dead patterns)."""
    return tool_id.startswith(pattern[:-1]) if pattern.endswith(".*") else tool_id == pattern
