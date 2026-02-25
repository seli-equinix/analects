# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""Dual-model orchestrator — dynamic model selection per iteration.

Presents as a single agent-as-a-model. The 8B handles research tool
orchestration silently, the 80B handles reasoning and creation visibly.
A quality gate escalates to 80B if the 8B struggles.

Architecture:
    _process_messages() is recursive. Each call invokes:
        get_root_tag() → get_llm_params() → fresh _get_chat(params) → LLM call

    get_llm_params() is called ONCE per iteration (llm.py:179). A fresh chat
    object is created each time, so switching models between iterations is
    seamless. We override get_llm_params() to decide which model to use.

    _num_iterations is incremented in base.py:221 AFTER get_root_tag() returns,
    so during get_llm_params(), _num_iterations == 0 on the first iteration.

    super().get_llm_params() (anthropic.py:42-78) calls parent .copy(), adds
    tools to additional_kwargs["tools"], and adds Claude-specific beta tags.
    We MUST call super() first so the 8B also gets tool definitions.

Text suppression:
    LLM response → _process_response() separates text (returned as str) from
    tool_use blocks (queued in _tool_use_queue). Text flows through
    on_llm_output() → on_plain_text() → PlainTextExtension → io.ai() → user.
    Suppressing in on_llm_output() prevents text from reaching the user.
    Tool execution is unaffected (tools are queued before on_llm_output).
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import PrivateAttr

from ..core.analect import AnalectRunContext
from ..core.chat_models.bedrock.api.invoke_model import anthropic as ant
from ..core.llm_manager import LLMParams
from ..core.tracing import get_tracer, OPENINFERENCE_SPAN_KIND, OUTPUT_VALUE
from ..orchestrator.anthropic import AnthropicLLMOrchestrator

logger = logging.getLogger(__name__)

# Max consecutive 8B iterations with tool errors before escalating to 80B
MAX_FAST_CONSECUTIVE_FAILURES = 3

# Tools that only READ data — safe for the 8B to orchestrate.
# Any tool NOT in this set triggers 80B on the next iteration.
RESEARCH_TOOLS = frozenset({
    # Web tools
    "web_search",
    "fetch_url_content",
    # Knowledge search tools
    "search_codebase",
    "search_knowledge",
    "search_documents",
    "list_session_docs",
    # Graph tools (read-only queries)
    "query_call_graph",
    "find_orphan_functions",
    "analyze_dependencies",
    # Note-taker tools (read-only)
    "search_notes",
    "get_trajectory",
    "list_recent_sessions",
})


class DualModelOrchestrator(AnthropicLLMOrchestrator):
    """Orchestrator that switches between fast 8B and reasoning 80B per iteration.

    Acts as a single agent-as-a-model:
    - 8B text is suppressed (user never sees intermediate chatter)
    - 80B text is shown normally
    - Quality gate escalates to 80B after consecutive 8B failures
    """

    _tool_orch_params: LLMParams | None = PrivateAttr(default=None)
    _last_tool_names: list[str] = PrivateAttr(default_factory=list)
    _using_fast_model: bool = PrivateAttr(default=False)
    _model_reason: str = PrivateAttr(default="initial planning")
    _consecutive_fast_failures: int = PrivateAttr(default=0)
    _force_primary: bool = PrivateAttr(default=False)
    _last_queue_had_error: bool = PrivateAttr(default=False)

    # ── Model selection ──────────────────────────────────────────

    def _overlay_fast_params(self, params: LLMParams) -> LLMParams:
        """Replace model-level fields with fast model, keeping tools.

        super().get_llm_params() adds tools to additional_kwargs["tools"]
        and Claude beta tags. The fast model's additional_kwargs has
        base_url (pointing to Spark1:8400). Merging via update() preserves
        tools and swaps the endpoint.
        """
        fast = self._tool_orch_params
        assert fast is not None
        params.model = fast.model
        if fast.temperature is not None:
            params.temperature = fast.temperature
        if fast.max_tokens is not None:
            params.max_tokens = fast.max_tokens
        if fast.initial_max_tokens is not None:
            params.initial_max_tokens = fast.initial_max_tokens
        # Merge additional_kwargs: keeps "tools" from super, adds "base_url"
        if fast.additional_kwargs:
            if params.additional_kwargs is None:
                params.additional_kwargs = {}
            params.additional_kwargs.update(fast.additional_kwargs)
        return params

    def _should_use_fast_model(self) -> bool:
        """Decide whether this iteration should use the 8B model."""
        # No tool_orchestrator configured
        if self._tool_orch_params is None:
            return False
        # Quality gate triggered — force 80B for rest of request
        if self._force_primary:
            return False
        # First iteration — always 80B (needs to understand task)
        if self._num_iterations == 0:
            return False
        # After tool execution: use 8B only if ALL tools were research tools
        if self._last_tool_names:
            return all(t in RESEARCH_TOOLS for t in self._last_tool_names)
        # No tools in last iteration (final synthesis) — 80B
        return False

    async def get_llm_params(self) -> LLMParams:
        """Pick model based on iteration context.

        Always calls super() first to get tool-decorated params (with tools,
        beta tags, etc.), then overlays the fast model settings when needed.
        """
        params = await super().get_llm_params()

        if self._should_use_fast_model():
            self._using_fast_model = True
            self._model_reason = f"research: {self._last_tool_names}"
            logger.info(
                "Dual-model: iter %d → 8B (after research tools: %s)",
                self._num_iterations,
                self._last_tool_names,
            )
            return self._overlay_fast_params(params)

        self._using_fast_model = False
        self._model_reason = (
            "initial planning"
            if self._num_iterations == 0
            else "quality gate"
            if self._force_primary
            else f"creation: {self._last_tool_names}"
            if self._last_tool_names
            else "final synthesis"
        )
        logger.info(
            "Dual-model: iter %d → 80B (%s)",
            self._num_iterations,
            self._model_reason,
        )
        return params

    # ── Phoenix tracing enrichment ──────────────────────────────

    async def _invoke_claude_impl(
        self,
        chat: BaseChatModel,
        messages: list[BaseMessage],
        context: AnalectRunContext,
    ) -> str:
        """Override to enrich Phoenix spans with dual-model context."""
        tracer = get_tracer()
        iteration = getattr(self, '_iteration_count', 0) + 1
        object.__setattr__(self, '_iteration_count', iteration)

        model_name = getattr(chat, 'model', 'unknown')
        with tracer.start_as_current_span("cca.llm.invoke") as span:
            span.set_attribute(OPENINFERENCE_SPAN_KIND, "LLM")
            span.set_attribute("llm.model_name", str(model_name))
            span.set_attribute("cca.llm.iteration", iteration)
            span.set_attribute("cca.llm.message_count", len(messages))

            # Dual-model tracing attributes
            span.set_attribute("cca.dual_model.using_fast", self._using_fast_model)
            span.set_attribute("cca.dual_model.reason", self._model_reason)
            span.set_attribute("cca.dual_model.quality_gate_active", self._force_primary)
            span.set_attribute(
                "cca.dual_model.consecutive_failures",
                self._consecutive_fast_failures,
            )
            if self._last_tool_names:
                span.set_attribute(
                    "cca.dual_model.last_tools",
                    ",".join(self._last_tool_names),
                )

            response = await context.invoke(chat, messages)
            response = await self.on_llm_response(response, context)
            result = await self._process_response(response, context)

            span.set_attribute(OUTPUT_VALUE, str(result)[:500] if result else "")
            return result

    # ── Silent 8B output ─────────────────────────────────────────

    async def on_llm_output(
        self, text: str, context: AnalectRunContext
    ) -> str:
        """Suppress 8B text only when it also generated tool calls.

        Called in get_root_tag() (llm.py:186) AFTER _invoke_llm_impl().
        At this point, _process_response() has already populated
        _tool_use_queue with any tool calls from this iteration.

        If the 8B generated text WITH tools → suppress (intermediate chatter).
        If the 8B generated text WITHOUT tools → final synthesis → show it.
        The queue hasn't been cleared yet (that happens in _process_messages
        finally block), so checking it here is valid.
        """
        if self._using_fast_model and self._tool_use_queue:
            if text.strip():
                logger.debug(
                    "Dual-model: suppressing 8B text (%d chars): %.80s...",
                    len(text),
                    text,
                )
            return ""  # Suppress — PlainTextExtension won't call io.ai()
        if self._using_fast_model and not self._tool_use_queue:
            logger.info(
                "Dual-model: 8B final synthesis (%d chars) — showing to user",
                len(text),
            )
        return await super().on_llm_output(text, context)

    # ── Tool tracking + quality gate ─────────────────────────────

    async def _process_tool_use(
        self,
        tool_use: ant.MessageContentToolUse,
        all_tool_names: set[str],
        context: AnalectRunContext,
    ) -> ant.MessageContentToolResult | None:
        """Override to detect tool errors for the quality gate."""
        result = await super()._process_tool_use(tool_use, all_tool_names, context)
        if result is not None and getattr(result, "is_error", False):
            self._last_queue_had_error = True
        return result

    async def _process_tool_use_queue(
        self, context: AnalectRunContext
    ) -> None:
        """Override to track which tools were used and detect failures."""
        # Capture tool names BEFORE processing
        # (queue is cleared in _process_messages finally block)
        self._last_tool_names = [tu.name for tu in self._tool_use_queue]
        self._last_queue_had_error = False

        await super()._process_tool_use_queue(context)

        # Quality gate: check for errors after processing
        self._update_quality_gate()

    def _update_quality_gate(self) -> None:
        """Escalate to 80B if 8B has too many consecutive failures."""
        if not self._using_fast_model:
            self._consecutive_fast_failures = 0
            return

        if self._last_queue_had_error:
            self._consecutive_fast_failures += 1
            logger.warning(
                "Dual-model: 8B tool failure %d/%d (tools: %s)",
                self._consecutive_fast_failures,
                MAX_FAST_CONSECUTIVE_FAILURES,
                self._last_tool_names,
            )
            if self._consecutive_fast_failures >= MAX_FAST_CONSECUTIVE_FAILURES:
                self._force_primary = True
                logger.warning(
                    "Dual-model: quality gate triggered — escalating to 80B "
                    "after %d consecutive 8B failures",
                    self._consecutive_fast_failures,
                )
        else:
            self._consecutive_fast_failures = 0
