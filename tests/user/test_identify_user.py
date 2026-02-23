"""Tests for the identify_user tool.

Validates that CCA's agent correctly identifies users by name,
creates new profiles, and recognizes returning users.

Note: The CCA server has server-side user inference that may
auto-identify users from message content before the agent calls
identify_user.  Tests account for both paths (server-side and
agent-side identification).
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(600)]


def _unique_name() -> str:
    """Generate a name unlikely to match any existing user via embeddings."""
    return f"Zxq_{uuid.uuid4().hex[:8]}"


class TestIdentifyUser:
    """identify_user tool — link sessions to user profiles."""

    def test_identify_new_user(self, cca, trace_test):
        """Agent should identify a user and confirm via response or metadata."""
        name = _unique_name()
        session_id = f"id-new-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi, my name is {name}. Please use the identify_user tool "
            f"to identify me as {name}.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.user_name", name)
        trace_test.set_attribute("cca.test.response", result.content[:500])
        trace_test.set_attribute(
            "cca.test.user_identified", result.user_identified
        )

        assert result.content, "Agent returned empty response"
        # Agent should either mention the name or confirm identification
        content_lower = result.content.lower()
        assert (
            name.lower() in content_lower
            or "identified" in content_lower
            or "recognized" in content_lower
            or "welcome" in content_lower
            or "profile" in content_lower
            or result.user_identified
        ), f"Response doesn't acknowledge identification: {result.content[:200]}"

        # Secondary: check /users (may match an existing profile
        # via server-side inference if embeddings are similar)
        user = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_found", user is not None)
        if user:
            assert user["session_count"] >= 1
            cca.cleanup_test_user(name)

    def test_identify_returning_user(self, cca, trace_test):
        """Agent should welcome back a user who has been seen before."""
        name = _unique_name()
        sid1 = f"id-ret-1-{uuid.uuid4().hex[:8]}"
        sid2 = f"id-ret-2-{uuid.uuid4().hex[:8]}"

        # First session — create user
        r1 = cca.chat(
            f"Hi I'm {name}. Use identify_user to identify me.",
            session_id=sid1,
        )
        trace_test.set_attribute("cca.test.r1_identified", r1.user_identified)

        # Second session — returning user
        result = cca.chat(
            f"Hey it's {name} again. Identify me please.",
            session_id=sid2,
        )

        trace_test.set_attribute("cca.test.user_name", name)
        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        # Should acknowledge the user in some way
        content_lower = result.content.lower()
        assert (
            name.lower() in content_lower
            or "welcome back" in content_lower
            or "recognized" in content_lower
            or "identified" in content_lower
            or result.user_identified
        ), f"Agent didn't acknowledge returning user: {result.content[:200]}"

        # Secondary: verify session count if user was created with exact name
        user = cca.find_user_by_name(name)
        if user:
            trace_test.set_attribute(
                "cca.test.session_count", user["session_count"]
            )
            cca.cleanup_test_user(name)

    def test_identify_with_natural_greeting(self, cca, trace_test):
        """Agent should detect name from a natural greeting."""
        name = _unique_name()
        session_id = f"id-greet-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hey there! I'm {name}, nice to meet you. "
            f"What can you help me with today?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.user_name", name)
        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        assert len(result.content) > 20, "Response too short"

        user = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_found", user is not None)
        if user:
            cca.cleanup_test_user(name)

    def test_identify_updates_session(self, cca, trace_test):
        """After identification, /sessions should show active sessions."""
        name = _unique_name()
        session_id = f"id-sess-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"I'm {name}. Use identify_user to identify me.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:300])

        sessions = cca.list_sessions()
        trace_test.set_attribute(
            "cca.test.session_count", sessions.get("count", 0)
        )

        # Session should exist in active sessions
        assert sessions.get("count", 0) > 0, "No active sessions found"

        cca.cleanup_test_user(name)

    def test_identify_case_insensitive(self, cca, trace_test):
        """Identification should work regardless of case."""
        name = _unique_name()
        sid1 = f"id-case-1-{uuid.uuid4().hex[:8]}"
        sid2 = f"id-case-2-{uuid.uuid4().hex[:8]}"

        # Create with original case
        cca.chat(
            f"Hi I'm {name}. Use identify_user to identify me.",
            session_id=sid1,
        )

        # Identify with lowercase
        result = cca.chat(
            f"I'm {name.lower()}. Identify me.",
            session_id=sid2,
        )

        trace_test.set_attribute("cca.test.original_name", name)
        trace_test.set_attribute("cca.test.lowercase_name", name.lower())
        trace_test.set_attribute("cca.test.response", result.content[:300])

        assert result.content, "Agent returned empty response"
        # Should acknowledge the user (case-insensitive match)
        content_lower = result.content.lower()
        assert (
            name.lower() in content_lower
            or "identified" in content_lower
            or "recognized" in content_lower
            or result.user_identified
        ), "Agent didn't handle case-insensitive identification"

        cca.cleanup_test_user(name)
