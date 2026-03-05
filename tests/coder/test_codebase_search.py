"""Flow test: Codebase search via the CODER route.

Journey: ask about code in the indexed workspace → verify agent uses
search_codebase or search_knowledge tools → verify relevant results.

Exercises: search_codebase, search_knowledge (CODE_SEARCH group), CODER route.
"""

import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.coder]


class TestCodebaseSearch:
    """CODER route: search indexed codebase for functions and patterns."""

    def test_codebase_search(self, cca, trace_test, judge_model):
        """Search the indexed codebase and verify relevant results."""
        sid = f"test-codesearch-{uuid.uuid4().hex[:8]}"

        # ── Turn 1: Search for a known pattern ──
        # The MCP server codebase is indexed — search for something
        # that definitely exists in the indexed files.
        msg1 = (
            "Search the codebase for functions related to 'health check' "
            "or 'health endpoint'. What files implement health checks?"
        )
        r1 = cca.chat(msg1, session_id=sid)
        evaluate_response(r1, msg1, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.t1_response", r1.content[:500])
        assert r1.content, "Turn 1 returned empty"

        # Should have used search tools
        iters = r1.metadata.get("tool_iterations", 0)
        trace_test.set_attribute("cca.test.t1_iters", iters)
        assert iters >= 1, (
            f"Agent didn't use search tools (iters={iters}). "
            f"Response: {r1.content[:200]}"
        )

        # Response should mention file paths or function names
        content_lower = r1.content.lower()
        has_code_refs = any(w in content_lower for w in [
            ".py", "def ", "health", "endpoint", "function",
        ])
        trace_test.set_attribute("cca.test.has_code_refs", has_code_refs)
        assert has_code_refs, (
            f"Response doesn't reference code: {r1.content[:300]}"
        )

        # ── Turn 2: Ask about a specific technology ──
        msg2 = (
            "Search the codebase for anything related to Qdrant — "
            "which files use Qdrant and what collections do they reference?"
        )
        r2 = cca.chat(msg2, session_id=sid)
        evaluate_response(r2, msg2, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.t2_response", r2.content[:500])
        assert r2.content, "Turn 2 returned empty"

        iters2 = r2.metadata.get("tool_iterations", 0)
        trace_test.set_attribute("cca.test.t2_iters", iters2)
        assert iters2 >= 1, (
            f"Agent didn't use search tools for Qdrant query (iters={iters2})"
        )

        # Should mention Qdrant-related content
        content_lower = r2.content.lower()
        has_qdrant = "qdrant" in content_lower
        trace_test.set_attribute("cca.test.has_qdrant", has_qdrant)
        assert has_qdrant, (
            f"Response doesn't mention Qdrant: {r2.content[:300]}"
        )
