"""Tests for the update_user_preference tool.

Validates that the agent stores user preferences and acknowledges them.
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(300)]


class TestUserPreference:
    """update_user_preference tool — adjust response style per user."""

    def test_set_preference(self, cca, trace_test):
        """Agent should store a user preference."""
        name = f"PrefUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-pref-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi I'm {name}. I prefer concise responses — please remember that.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # User should exist
        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not found via /users API"

        cca.cleanup_test_user(name)

    def test_preference_acknowledged(self, cca, trace_test):
        """Agent should confirm when a preference is set."""
        name = f"PrefAck_{uuid.uuid4().hex[:6]}"
        session_id = f"test-ack-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi, I'm {name}. I prefer Python code examples when "
            f"explaining things. Remember that preference for me.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"
        assert len(result.content) >= 2, "Response too short"

        cca.cleanup_test_user(name)
