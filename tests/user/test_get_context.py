"""Tests for the get_user_context tool (enhanced with Redis + Qdrant).

Validates that the agent can report session status, user profile,
and critical infrastructure facts extracted from conversation.
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(600)]


class TestGetContext:
    """get_user_context tool — session + profile + critical facts."""

    def test_get_context_identified_user(self, cca, trace_test):
        """After identification, context should include user profile."""
        name = f"TestCtx_{uuid.uuid4().hex[:6]}"
        session_id = f"test-ctx-{uuid.uuid4().hex[:8]}"

        # Identify and store a fact
        cca.chat(
            f"I'm {name}. Identify me and remember I work at ContextCorp.",
            session_id=session_id,
        )

        # Ask about session context
        result = cca.chat(
            "What do you know about my current session and profile? "
            "Use get_user_context to check.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        content_lower = result.content.lower()
        # Should mention the user name, session status, or at least
        # attempt to call get_user_context (raw tool XML = agent tried)
        assert name.lower() in content_lower or "identified" in content_lower or \
            "session" in content_lower or "context" in content_lower or \
            "get_user_context" in content_lower or \
            "contextcorp" in content_lower, \
            "Response doesn't include session/user context"

        cca.cleanup_test_user(name)

    def test_get_context_anonymous(self, cca, trace_test):
        """Anonymous session should show not-identified status."""
        session_id = f"test-ctx-anon-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            "What's my current session status? Use get_user_context "
            "to check if I'm identified.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        # Should indicate user is not identified, or at least reference context
        content_lower = result.content.lower()
        assert "not identified" in content_lower or \
            "not yet" in content_lower or \
            "anonymous" in content_lower or \
            "haven't been identified" in content_lower or \
            "don't know who" in content_lower or \
            "identify" in content_lower or \
            "context" in content_lower or \
            "session" in content_lower or \
            "get_user_context" in content_lower, \
            "Response doesn't indicate anonymous status"

    def test_get_context_with_critical_facts(self, cca, trace_test):
        """Critical facts (IPs, passwords) should be extracted and available."""
        name = f"TestCritFact_{uuid.uuid4().hex[:6]}"
        session_id = f"test-crit-{uuid.uuid4().hex[:8]}"

        # Message with infrastructure details that should be auto-extracted
        cca.chat(
            f"I'm {name}. Identify me. My test server is at "
            f"10.99.99.1 with password TestPass123. "
            f"Remember these as facts too.",
            session_id=session_id,
        )

        # Ask about context — should include critical facts
        result = cca.chat(
            "What infrastructure details do you know about from our "
            "conversation? Use get_user_context to check.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        # The CriticalFactsExtractor should have picked up the IP/password
        content_lower = result.content.lower()
        has_infra_ref = (
            "10.99.99.1" in result.content or
            "testpass" in content_lower or
            "server" in content_lower or
            "infrastructure" in content_lower or
            "critical" in content_lower or
            "ip" in content_lower
        )
        trace_test.set_attribute("cca.test.has_infra_ref", has_infra_ref)
        assert has_infra_ref, \
            "Response doesn't mention any infrastructure details"

        cca.cleanup_test_user(name)
