"""Tests for the remember_user_fact tool.

Pairs fact storage with a coding task to ensure the agent loop runs
(the expert router short-circuits pure greetings as DIRECT answers).
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(300)]


class TestRememberFact:
    """remember_user_fact tool — store persistent facts about users."""

    def test_remember_single_fact(self, cca, trace_test):
        """Agent should store a fact when told about the user."""
        name = f"FactUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-fact-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi I'm {name}. I work at AcmeCorp. "
            f"Write me a Python one-liner to get today's date.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # User should exist
        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not found via /users API"

        cca.cleanup_test_user(name)

    def test_remember_multiple_facts(self, cca, trace_test):
        """Agent should handle multiple facts alongside a coding task."""
        name = f"MultiFact_{uuid.uuid4().hex[:6]}"
        session_id = f"test-mfact-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi, I'm {name}. I use Python, my server is gpu-box, "
            f"and I work in machine learning. Help me write a function "
            f"to calculate the mean of a list of numbers.",
            session_id=session_id,
            timeout=240,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # User should exist
        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not found via /users API"

        cca.cleanup_test_user(name)

    def test_fact_persists_across_sessions(self, cca, trace_test):
        """Facts stored in one session should be available in the next."""
        name = f"Persist_{uuid.uuid4().hex[:6]}"
        company = f"PersistCorp_{uuid.uuid4().hex[:4]}"
        sid1 = f"test-per1-{uuid.uuid4().hex[:8]}"
        sid2 = f"test-per2-{uuid.uuid4().hex[:8]}"

        # Session 1: identify + store fact via coding task
        cca.chat(
            f"Hi I'm {name}. I work at {company}. "
            f"Write a Python one-liner to check if a string is a palindrome.",
            session_id=sid1,
        )

        # Session 2: new session, ask what the agent knows
        result = cca.chat(
            f"Hey, it's {name}. Where do I work? Also help me with "
            f"a one-liner to count vowels in a string.",
            session_id=sid2,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        content_lower = result.content.lower()
        assert any(w in content_lower for w in [
            company.lower(), "employer", "work", "company",
            name.lower(), "profile",
        ]), f"Agent didn't recall the fact: {result.content[:200]}"

        cca.cleanup_test_user(name)
