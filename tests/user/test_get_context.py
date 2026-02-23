"""Tests for session context and user identification state.

Validates that user identification persists across messages in the
same session, and that anonymous sessions stay anonymous.
"""

import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.user, pytest.mark.timeout(300)]


class TestGetContext:
    """Session context — identification state across messages."""

    def test_context_identified_user(self, cca, trace_test, judge_model):
        """After identification, the session should remain identified."""
        name = f"CtxUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-ctx-{uuid.uuid4().hex[:8]}"
        message = (
            f"Hi I'm {name}. I work at ContextCorp. "
            f"Write a Python one-liner to get the current timestamp."
        )

        r1 = cca.chat(message, session_id=session_id)

        evaluate_response(r1, message, trace_test, judge_model, "user")

        trace_test.set_attribute("cca.test.r1_response", r1.content[:300])

        # User should be auto-created
        user = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_created", user is not None)
        assert user is not None, f"User '{name}' not created after first message"

        # Second message: same session — should still be identified
        msg2 = "Now write a Python function to calculate fibonacci numbers."
        r2 = cca.chat(msg2, session_id=session_id)

        evaluate_response(r2, msg2, trace_test, judge_model, "user")

        trace_test.set_attribute("cca.test.r2_response", r2.content[:300])
        assert r2.content, "Second message returned empty response"

        # Session should show user as identified in metadata
        trace_test.set_attribute("cca.test.user_identified", r2.user_identified)
        assert r2.user_identified, \
            "Session should remain identified across messages"

        cca.cleanup_test_user(name)

    def test_context_anonymous(self, cca, trace_test, judge_model):
        """Anonymous session should not show identification."""
        session_id = f"test-anon-{uuid.uuid4().hex[:8]}"
        message = "What is the capital of France?"

        result = cca.chat(message, session_id=session_id)

        evaluate_response(result, message, trace_test, judge_model, "user")

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # Should not be identified
        trace_test.set_attribute("cca.test.user_identified", result.user_identified)
        assert not result.user_identified, \
            "Anonymous session should not be identified"
