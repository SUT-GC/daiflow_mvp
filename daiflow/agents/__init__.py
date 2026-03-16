"""Agent configuration registry.

Each agent type (plan, todo_split, todo_exec, init, review) registers an AgentConfig
that declares how to build prompts, detect artifacts, and prepare chat context.

The registry replaces scattered if-elif branches in task_service and chat_service
with a lookup-based dispatch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from daiflow.models import Task, Todo

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Runtime context built by AgentExecutor and passed to AgentConfig methods."""

    db: AsyncSession
    session_id: str
    entity_id: str  # task_id for most agents, todo_id for todo_exec
    task: Task | None = None
    todo: Todo | None = None
    project_id: str = ""
    task_dir: str = ""
    allowed_roots: list[str] = field(default_factory=list)


class AgentConfig:
    """Base class for agent type declarations.

    Subclasses override methods to provide agent-specific behaviour.
    Instances are stateless singletons — all runtime state lives in AgentContext.
    """

    agent_type: str = ""
    chattable: bool = False

    # --- Prompt & execution ---

    async def build_prompt(self, ctx: AgentContext) -> "str | Any":
        """Build the prompt to send to Cody. Returns str or MultimodalPrompt."""
        raise NotImplementedError

    async def resolve_cody_session_id(self, ctx: AgentContext) -> str | None:
        """Return a cody_session_id to reuse, or None for a fresh session."""
        return None

    def build_artifact_detector(self, ctx: AgentContext) -> Callable | None:
        """Return an on_tool_result callback for file-write detection, or None."""
        return None

    async def on_complete(self, ctx: AgentContext) -> None:
        """Post-execution hook: sync artifacts to DB, transition state, etc."""

    # --- Chat (only relevant when chattable=True) ---

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        """System prefix prepended to user chat messages."""
        return None


# ── Global registry ──

_AGENT_REGISTRY: dict[str, AgentConfig] = {}


def register_agent(config: AgentConfig) -> None:
    """Register an agent config singleton."""
    _AGENT_REGISTRY[config.agent_type] = config


def get_agent_config(agent_type: str) -> AgentConfig:
    """Look up a registered agent config by type. Raises KeyError if not found."""
    try:
        return _AGENT_REGISTRY[agent_type]
    except KeyError:
        raise KeyError(f"Unknown agent type: {agent_type!r}. Registered: {list(_AGENT_REGISTRY)}")


def _auto_register() -> None:
    """Import all agent modules to trigger their register_agent() calls."""
    from daiflow.agents import (  # noqa: F401
        init_agent,
        plan_agent,
        review_agent,
        todo_exec_agent,
        todo_split_agent,
    )


_auto_register()
