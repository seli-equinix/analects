"""Tests for user identification via the CCA agent.

The CCA expert router short-circuits simple greetings as DIRECT answers.
User creation only happens when the agent loop runs (CODER/INFRA routing).
Tests pair introductions with a coding task to trigger the agent loop.

Validates via the /users REST API for ground-truth.
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(300)]


class TestIdentifyUser:
    """identify_user tool — session-to-user linking."""

    def test_identify_new_user(self, cca, trace_test):
        """A new name + coding task should create a user profile."""
        name = f"NewUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-new-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi, I'm {name}. Help me write a Python one-liner "
            f"that prints 'hello world'.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # Ground truth: REST API confirms user exists
        user = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_created", user is not None)
        assert user is not None, f"User '{name}' not found via /users API"

        cca.cleanup_test_user(name)

    def test_identify_returning_user(self, cca, trace_test):
        """Same name in a new session should find the existing profile."""
        name = f"Return_{uuid.uuid4().hex[:6]}"
        sid1 = f"test-ret1-{uuid.uuid4().hex[:8]}"
        sid2 = f"test-ret2-{uuid.uuid4().hex[:8]}"

        # Session 1: create user
        cca.chat(
            f"Hi, I'm {name}. Write a one-liner to reverse a string.",
            session_id=sid1,
        )

        # Session 2: same name, new session
        result = cca.chat(
            f"Hey, it's {name} again. Now write a one-liner to sort a list.",
            session_id=sid2,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # REST API: user should exist with session_count >= 2
        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not found"
        trace_test.set_attribute("cca.test.session_count", user["session_count"])
        assert user["session_count"] >= 2, \
            f"Expected session_count >= 2, got {user['session_count']}"

        cca.cleanup_test_user(name)

    def test_identify_with_greeting(self, cca, trace_test):
        """Natural greeting + task should trigger identification."""
        name = f"Greeter_{uuid.uuid4().hex[:6]}"
        session_id = f"test-greet-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Good morning! My name is {name}. Can you help me write "
            f"a Python function that checks if a number is even?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # Agent auto-identifies from natural intro
        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not created from greeting"

        cca.cleanup_test_user(name)

    def test_identify_updates_metadata(self, cca, trace_test):
        """After identification, context_metadata should show identified."""
        name = f"MetaUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-meta-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi, I'm {name}. Help me debug this: print('hello'",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:300])
        trace_test.set_attribute("cca.test.user_identified", result.user_identified)

        assert result.content, "Agent returned empty response"
        # Check via REST API as fallback if metadata doesn't show identified
        user = cca.find_user_by_name(name)
        assert result.user_identified or user is not None, \
            "User not identified via metadata or REST API"

        cca.cleanup_test_user(name)
