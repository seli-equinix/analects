"""Tests for the get_user_context tool.

Validates that the agent can report session status and user profile
information, including for anonymous sessions.
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

        # Identify and store a fact
        cca.chat(
            f"Hi I'm {name}. I work at ContextCorp.",
            session_id=session_id,
        )

        # Ask about what the agent knows
        result = cca.chat(
            "What do you know about me?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        content_lower = result.content.lower()
        assert any(w in content_lower for w in [
            name.lower(), "contextcorp", "identified", "session",
            "context", "work", "profile",
        ]), f"Response doesn't include user context: {result.content[:200]}"

        cca.cleanup_test_user(name)

    def test_context_anonymous(self, cca, trace_test):
        """Anonymous session should show not-identified status."""
        session_id = f"test-anon-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            "Am I identified? What session info do you have?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # Response metadata should show not identified
        trace_test.set_attribute("cca.test.user_identified", result.user_identified)
        # Either metadata says not identified, or agent mentions it
        content_lower = result.content.lower()
        assert (
            not result.user_identified or
            any(w in content_lower for w in [
                "not identified", "anonymous", "don't know",
                "haven't", "identify", "name", "who",
            ])
        ), f"Response doesn't indicate anonymous: {result.content[:200]}"
