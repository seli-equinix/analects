"""Tests for the update_user_preference tool.

Pairs preference setting with a coding task to ensure the agent loop runs.
"""

import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.user, pytest.mark.timeout(300)]


class TestUserPreference:
    """update_user_preference tool — adjust response style per user."""

    def test_set_preference(self, cca, trace_test, judge_model):
        """Agent should store a user preference during a coding task."""
        name = f"PrefUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-pref-{uuid.uuid4().hex[:8]}"
        message = (
            f"Hi I'm {name}. I prefer concise responses. "
            f"Write a Python function to check if a number is prime."
        )

        result = cca.chat(message, session_id=session_id)

        evaluate_response(result, message, trace_test, judge_model, "user")

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not found via /users API"

        cca.cleanup_test_user(name)

    def test_preference_acknowledged(self, cca, trace_test, judge_model):
        """Agent should respond with code when given a coding preference."""
        name = f"PrefAck_{uuid.uuid4().hex[:6]}"
        session_id = f"test-ack-{uuid.uuid4().hex[:8]}"
        message = (
            f"Hi, I'm {name}. I prefer Python code with type hints. "
            f"Write a function to calculate factorial."
        )

        result = cca.chat(message, session_id=session_id)

        evaluate_response(result, message, trace_test, judge_model, "user")

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"
        assert len(result.content) > 50, "Response too short for a code task"

        cca.cleanup_test_user(name)
