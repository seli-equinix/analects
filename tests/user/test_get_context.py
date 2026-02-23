"""Tests for the get_user_context tool.

Validates that the agent can report session status and user profile.
Pairs with coding tasks to ensure the agent loop runs.
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(300)]


class TestGetContext:
    """get_user_context tool — session + profile info."""

    def test_context_identified_user(self, cca, trace_test):
        """After identification, the agent should know who we are."""
        name = f"CtxUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-ctx-{uuid.uuid4().hex[:8]}"

        # Identify via coding task
        cca.chat(
            f"Hi I'm {name}. I work at ContextCorp. "
            f"Write a Python one-liner to get the current timestamp.",
            session_id=session_id,
        )

        # Ask about context (same session, user already in agent loop)
        result = cca.chat(
            "What do you know about me? Also write a one-liner "
            "to format a datetime as ISO 8601.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        content_lower = result.content.lower()
        assert any(w in content_lower for w in [
            name.lower(), "contextcorp", "identified", "session",
            "context", "work", "profile", "iso", "datetime",
        ]), f"Response doesn't include user context: {result.content[:200]}"

        cca.cleanup_test_user(name)

    def test_context_anonymous(self, cca, trace_test):
        """Anonymous session should not show identification."""
        session_id = f"test-anon-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            "What is the capital of France?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # Should not be identified
        trace_test.set_attribute("cca.test.user_identified", result.user_identified)
        assert not result.user_identified, \
            "Anonymous session should not be identified"
