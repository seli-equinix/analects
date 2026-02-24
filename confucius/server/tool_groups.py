# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""Tool group definitions and route-based extension builder.

Maps ExpertType routes to ToolGroup sets, then builds the correct
extension list for each route.  Adding a new tool group is:
  1. Add the ToolGroup enum value
  2. Register the extension factory in TOOL_GROUP_FACTORIES
  3. Add it to the appropriate routes in ROUTE_TOOL_GROUPS
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ..orchestrator.extensions import Extension
from ..orchestrator.extensions.caching.anthropic import AnthropicPromptCaching
from ..orchestrator.extensions.command_line.base import CommandLineExtension
from ..orchestrator.extensions.file.edit import FileEditExtension
from ..orchestrator.extensions.function import FunctionExtension
from ..orchestrator.extensions.memory.hierarchical import HierarchicalMemoryExtension
from ..orchestrator.extensions.plain_text import PlainTextExtension
from ..orchestrator.extensions.plan.llm import LLMCodingArchitectExtension

from ..analects.code.commands import get_allowed_commands
from ..analects.infrastructure.commands import get_infra_commands
from .expert_router import ExpertType, RouteDecision
from ..orchestrator.extensions.expert.reviewer import CodeReviewerExtension
from ..orchestrator.extensions.expert.test_gen import TestGeneratorExtension
from .user.memory_extension import UserMemoryExtension
from .utility_tools import UtilityToolsExtension

logger = logging.getLogger(__name__)


# ========================= Tool Groups =========================


class ToolGroup(str, Enum):
    """Logical groupings of tools.  Each maps to one extension class."""
    USER = "user"           # UserToolsExtension (6 tools)
    USER_MEMORY = "user_memory"  # UserMemoryExtension (3 tools: get_context, remember_fact, update_pref)
    WEB = "web"             # UtilityToolsExtension (2 tools)
    FILE = "file"           # FileEditExtension (1 tool: TextEditor)
    SHELL = "shell"         # CommandLineExtension (1 tool: BashTool)
    MEMORY = "memory"       # HierarchicalMemoryExtension (6 tools)
    PLANNER = "planner"     # LLMCodingArchitectExtension (0 tools, prompt-based)
    # Future groups — uncomment as extensions are ported:
    # GRAPH = "graph"       # GraphToolsExtension (3 tools)
    # SEARCH = "search"     # SearchToolsExtension (3 tools)
    # DOCUMENT = "document" # DocumentToolsExtension (4 tools)
    # VISION = "vision"     # VisionToolsExtension (1 tool)
    # RULES = "rules"       # RulesToolsExtension (4 tools)
    # GIT = "git"           # GitToolsExtension (1 tool)


# ========================= Route → Tool Groups =========================

# Which tool groups each route needs.
# Order matters: extensions are presented to the LLM in this order.

ROUTE_TOOL_GROUPS: Dict[ExpertType, List[ToolGroup]] = {
    ExpertType.USER: [
        ToolGroup.USER,
    ],
    ExpertType.CODER: [
        ToolGroup.PLANNER,
        ToolGroup.FILE,
        ToolGroup.SHELL,
        ToolGroup.MEMORY,
        ToolGroup.WEB,
        ToolGroup.USER_MEMORY,
    ],
    ExpertType.INFRASTRUCTURE: [
        ToolGroup.PLANNER,
        ToolGroup.FILE,
        ToolGroup.SHELL,
        ToolGroup.MEMORY,
        ToolGroup.WEB,
        ToolGroup.USER_MEMORY,
    ],
    ExpertType.SEARCH: [
        ToolGroup.WEB,
        ToolGroup.FILE,
        ToolGroup.MEMORY,
        ToolGroup.USER_MEMORY,
    ],
    ExpertType.PLANNER: [
        ToolGroup.PLANNER,
        ToolGroup.MEMORY,
    ],
}


# ========================= Route Settings =========================


_BASE_MAX_ITERATIONS: Dict[ExpertType, int] = {
    ExpertType.USER: 10,
    ExpertType.CODER: 20,
    ExpertType.INFRASTRUCTURE: 30,
    ExpertType.SEARCH: 15,
    ExpertType.PLANNER: 10,
}


def get_max_iterations(route: RouteDecision) -> int:
    """Compute max iterations from route's estimated steps.

    Formula: max(base, min(estimated_steps * 2, 200)).
    The base per-route value acts as a floor for that route type.
    """
    base = _BASE_MAX_ITERATIONS.get(route.expert, 20)
    from_steps = route.estimated_steps * 2
    return max(base, min(from_steps, 200))


# Command allowlists per route.  None = no shell access.
ROUTE_COMMANDS: Dict[ExpertType, Optional[Dict[str, str]]] = {
    ExpertType.USER: None,
    ExpertType.CODER: None,  # filled lazily
    ExpertType.INFRASTRUCTURE: None,  # filled lazily
    ExpertType.SEARCH: None,
    ExpertType.PLANNER: None,
}


def _get_commands_for_route(expert: ExpertType) -> Optional[Dict[str, str]]:
    """Return the command allowlist for a route (lazy evaluation)."""
    if expert == ExpertType.INFRASTRUCTURE:
        return get_infra_commands()
    elif expert in (ExpertType.CODER, ExpertType.SEARCH):
        return get_allowed_commands()
    return None


# ========================= Extension Builder =========================


def _get_functions() -> list[Callable[..., Any]]:
    """Placeholder for future function-call tools."""
    return []


def build_extensions_for_route(
    route: RouteDecision,
    user_extension: Optional[Extension] = None,
) -> List[Extension]:
    """Build the extension list for a given route.

    Only includes extensions whose tool group is in the route's
    ROUTE_TOOL_GROUPS mapping.  For complex tasks (estimated_steps >= 8),
    conditionally adds CodeReviewerExtension and TestGeneratorExtension.
    Always appends PlainTextExtension and AnthropicPromptCaching at the end.

    Args:
        route: The RouteDecision from the Functionary router.
        user_extension: Pre-built UserToolsExtension (session-bound).

    Returns:
        Ordered list of extensions for the orchestrator.
    """
    expert = route.expert
    groups = ROUTE_TOOL_GROUPS.get(expert, ROUTE_TOOL_GROUPS[ExpertType.CODER])
    commands = _get_commands_for_route(expert)
    extensions: List[Extension] = []

    for group in groups:
        if group == ToolGroup.PLANNER:
            extensions.append(LLMCodingArchitectExtension())

        elif group == ToolGroup.FILE:
            extensions.append(FileEditExtension(
                max_output_lines=500,
                enable_tool_use=True,
            ))

        elif group == ToolGroup.SHELL:
            if commands is not None:
                extensions.append(CommandLineExtension(
                    allowed_commands=commands,
                    max_output_lines=500 if expert == ExpertType.INFRASTRUCTURE else 300,
                    allow_bash_script=True,
                    enable_tool_use=True,
                ))

        elif group == ToolGroup.MEMORY:
            extensions.append(HierarchicalMemoryExtension())

        elif group == ToolGroup.USER:
            if user_extension is not None:
                extensions.append(user_extension)

        elif group == ToolGroup.WEB:
            extensions.append(UtilityToolsExtension())

        elif group == ToolGroup.USER_MEMORY:
            # Lightweight 3-tool user memory for non-USER routes.
            # Extract session_mgr/session/critical_facts from the
            # pre-built UserToolsExtension (same session context).
            if user_extension is not None:
                extensions.append(UserMemoryExtension(
                    session_mgr=user_extension._session_mgr,  # type: ignore[attr-defined]
                    session=user_extension._session,  # type: ignore[attr-defined]
                    critical_facts=user_extension._critical_facts,  # type: ignore[attr-defined]
                ))

        # Future groups will be handled here:
        # elif group == ToolGroup.GRAPH:
        #     extensions.append(GraphToolsExtension(...))

    # Conditionally add expert extensions for complex tasks
    if route.is_complex:  # estimated_steps >= 8
        if expert in (ExpertType.CODER, ExpertType.INFRASTRUCTURE):
            reviewer = CodeReviewerExtension(review_threshold=2)
            if reviewer.enabled:
                extensions.append(reviewer)
                logger.info("Added CodeReviewerExtension (threshold=2)")

            if expert == ExpertType.CODER:
                tester = TestGeneratorExtension()
                if tester.enabled:
                    extensions.append(tester)
                    logger.info("Added TestGeneratorExtension")

    # Always include these non-tool extensions
    extensions.append(PlainTextExtension())
    extensions.append(AnthropicPromptCaching())

    tool_count = sum(
        1 for ext in extensions
        if hasattr(ext, 'enable_tool_use') and ext.enable_tool_use
    )
    logger.info(
        f"Built {len(extensions)} extensions ({tool_count} tool-providing) "
        f"for route {expert.value} (estimated_steps={route.estimated_steps}): "
        f"groups={[g.value for g in groups]}"
    )

    return extensions
