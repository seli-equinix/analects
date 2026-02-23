"""End-to-end integration tests for user lifecycle flows.

Tests multi-step user flows: fact persistence across sessions
and full user lifecycle (create → facts → view → delete).
These route to the cca-user-tests Phoenix project.
"""

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.user, pytest.mark.timeout(300)]


class TestRememberAndRecall:
    """Store facts in session 1, recall them in session 2."""

    def test_facts_persist_across_sessions(self, cca, trace_test):
        """Facts stored in one session should be recalled in another."""
        name = f"Recall_{uuid.uuid4().hex[:6]}"
        company = f"RecallCorp_{uuid.uuid4().hex[:4]}"
        sid1 = f"test-recall1-{uuid.uuid4().hex[:8]}"
        sid2 = f"test-recall2-{uuid.uuid4().hex[:8]}"

        # Session 1: Identify and store fact
        cca.chat(
            f"Hello I'm {name}. I work at {company}. Remember that.",
            session_id=sid1,
        )

        # Session 2: New session, ask to recall
        result = cca.chat(
            f"Hi, I'm {name}. Where do I work?",
            session_id=sid2,
        )

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
    """Full CRUD lifecycle: create → facts → view → delete."""

    @pytest.mark.timeout(360)
    def test_full_lifecycle(self, cca, trace_test):
        """Complete user profile lifecycle using natural conversation."""
        name = f"Lifecycle_{uuid.uuid4().hex[:6]}"
        session_id = f"test-life-{uuid.uuid4().hex[:8]}"

        # Step 1: Create user with facts and skills
        r1 = cca.chat(
            f"Hi I'm {name}. I work at LifecycleCorp and know Rust. "
            f"Remember all of that about me.",
            session_id=session_id,
            timeout=240,
        )
        trace_test.set_attribute("cca.test.step1", r1.content[:300])
        assert r1.content, "Setup step returned empty"

        # Verify user exists via REST API
        user = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_created", user is not None)
        assert user is not None, f"User '{name}' not created"

        # Step 2: View profile
        r2 = cca.chat(
            "What do you know about me? Show my profile.",
            session_id=session_id,
        )
        trace_test.set_attribute("cca.test.step2", r2.content[:500])
        assert r2.content, "View step returned empty"

        view_lower = r2.content.lower()
        assert any(w in view_lower for w in [
            "lifecyclecorp", "rust", "profile", name.lower(),
            "employer", "skill",
        ]), f"View missing data: {r2.content[:200]}"

        # Step 3: Delete profile
        r3 = cca.chat(
            "Please delete my profile completely. I confirm deletion.",
            session_id=session_id,
        )
        trace_test.set_attribute("cca.test.step3", r3.content[:200])
        assert r3.content, "Delete step returned empty"

        # Verify deletion via REST API
        user_after = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_deleted", user_after is None)

        # Cleanup if agent refused to delete
        if user_after:
            cca.cleanup_test_user(name)
