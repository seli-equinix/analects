"""Tests for the remember_user_fact tool.

Validates that CCA's agent stores facts about users that persist
across sessions and can be retrieved.
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(600)]


class TestRememberFact:
    """remember_user_fact tool — store persistent facts about users."""

    def test_remember_single_fact(self, cca, trace_test):
        """Agent should store a fact about the user."""
        name = f"TestFact_{uuid.uuid4().hex[:6]}"
        session_id = f"test-fact-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi I'm {name}. Identify me, then remember that I work at "
            f"AcmeCorp. Use remember_user_fact with key 'employer' and "
            f"value 'AcmeCorp'.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.user_name", name)
        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        # Response should acknowledge storing the fact
        content_lower = result.content.lower()
        assert "acmecorp" in content_lower or "remembered" in content_lower or \
            "noted" in content_lower or "saved" in content_lower or \
            "employer" in content_lower, \
            "Response doesn't acknowledge the stored fact"

        cca.cleanup_test_user(name)

    def test_remember_multiple_facts(self, cca, trace_test):
        """Agent should store multiple facts in one conversation."""
        name = f"TestMultiFact_{uuid.uuid4().hex[:6]}"
        session_id = f"test-mfact-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"I'm {name}. Identify me first. Then remember these facts "
            f"about me: I use Python as my main language, my server is "
            f"called gpu-box, and I work on machine learning projects. "
            f"Use remember_user_fact for each one.",
            session_id=session_id,
            timeout=240,
        )

        trace_test.set_attribute("cca.test.user_name", name)
        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        assert len(result.content) > 50, \
            "Response too short for acknowledging multiple facts"

        cca.cleanup_test_user(name)

    def test_remember_overwrites_fact(self, cca, trace_test):
        """Storing a fact with the same key should overwrite the old value."""
        name = f"TestOverwrite_{uuid.uuid4().hex[:6]}"
        session_id = f"test-overwrite-{uuid.uuid4().hex[:8]}"

        # Set initial fact
        cca.chat(
            f"I'm {name}. Identify me and remember my employer is OldCorp. "
            f"Use remember_user_fact with key='employer' value='OldCorp'.",
            session_id=session_id,
        )

        # Overwrite fact in same session
        result = cca.chat(
            "Actually, I changed jobs. My employer is now NewCorp. "
            "Update my employer fact to NewCorp using remember_user_fact.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        content_lower = result.content.lower()
        assert "newcorp" in content_lower or "updated" in content_lower or \
            "changed" in content_lower, \
            "Response doesn't acknowledge the updated fact"

        cca.cleanup_test_user(name)

    def test_fact_persists_across_sessions(self, cca, trace_test):
        """Facts stored in one session should be available in the next."""
        name = f"TestPersist_{uuid.uuid4().hex[:6]}"
        sid1 = f"test-persist-1-{uuid.uuid4().hex[:8]}"
        sid2 = f"test-persist-2-{uuid.uuid4().hex[:8]}"

        # Session 1: identify and store fact
        cca.chat(
            f"I'm {name}. Identify me and remember that I work at "
            f"PersistCorp using remember_user_fact.",
            session_id=sid1,
        )

        # Session 2: new session, identify again and ask what they know
        result = cca.chat(
            f"Hey it's {name} again. What do you know about me? "
            f"What's my employer?",
            session_id=sid2,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        # Agent should mention PersistCorp from the stored fact
        content_lower = result.content.lower()
        assert "persistcorp" in content_lower or "employer" in content_lower, \
            "Response doesn't recall the stored fact from previous session"

        cca.cleanup_test_user(name)
