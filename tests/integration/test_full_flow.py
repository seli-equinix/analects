"""End-to-end integration tests for user lifecycle flows.

Tests multi-step user flows: fact persistence across sessions
and full user lifecycle (create → verify → delete).

The server auto-creates users when it detects a name introduction.
Tests validate state via the /users REST API for ground-truth.
"""

import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.integration, pytest.mark.user]


class TestRememberAndRecall:
    """Store facts in session 1, recall them in session 2."""

    def test_facts_persist_across_sessions(self, cca, trace_test, judge_model):
        """Facts stored in one session should be recalled in another."""
        name = f"Recall_{uuid.uuid4().hex[:6]}"
        company = f"RecallCorp_{uuid.uuid4().hex[:4]}"
        sid1 = f"test-rec1-{uuid.uuid4().hex[:8]}"
        sid2 = f"test-rec2-{uuid.uuid4().hex[:8]}"

        # Session 1: Identify + store fact via coding task
        cca.chat(
            f"Hello I'm {name}. I work at {company}. "
            f"Write a Python function to reverse a string.",
            session_id=sid1,
        )

        # Session 2: New session, ask to recall
        message = (
            f"Hi, I'm {name}. Where do I work? "
            f"Also write a one-liner to check if a string is empty."
        )
        result = cca.chat(message, session_id=sid2)

        evaluate_response(result, message, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Session 2 returned empty"

        content_lower = result.content.lower()
        recalled = any(w in content_lower for w in [
            company.lower(), "employer", "work", "company",
            "profile", "fact",
        ])
        trace_test.set_attribute("cca.test.fact_recalled", recalled)
        assert recalled, \
            f"Agent didn't recall '{company}': {result.content[:200]}"

        cca.cleanup_test_user(name)


class TestFullUserLifecycle:
    """Full CRUD lifecycle: create → verify via API → delete via API."""

    def test_full_lifecycle(self, cca, trace_test, judge_model):
        """Complete user profile lifecycle."""
        name = f"Lifecycle_{uuid.uuid4().hex[:6]}"
        session_id = f"test-life-{uuid.uuid4().hex[:8]}"
        message = (
            f"Hi I'm {name}. I work at LifecycleCorp and know Rust. "
            f"Write a Python function to find the maximum in a list."
        )

        # Step 1: Create user with facts via coding task
        r1 = cca.chat(message, session_id=session_id, timeout=240)

        evaluate_response(r1, message, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.step1", r1.content[:300])
        assert r1.content, "Setup step returned empty"

        # Step 2: Verify user exists via REST API
        user = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_created", user is not None)
        assert user is not None, f"User '{name}' not created"

        # Step 3: Verify session is identified
        assert r1.user_identified, \
            "Session should be identified after auto-creation"

        # Step 4: Delete via REST API
        cca.cleanup_test_user(name)

        # Step 5: Verify deletion
        user_after = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_deleted", user_after is None)
        assert user_after is None, f"User '{name}' still exists after delete"
