"""Tests for the manage_user_profile tool.

Pairs profile operations with coding tasks to ensure the agent loop runs.
Uses REST API for ground truth validation.
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(300)]


class TestManageProfileView:
    """manage_user_profile action=view — full profile display."""

    def test_view_profile(self, cca, trace_test):
        """Agent should show profile data when asked."""
        name = f"ViewUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-view-{uuid.uuid4().hex[:8]}"

        # Create user with a coding task
        cca.chat(
            f"Hi I'm {name}. I work at ViewCorp. "
            f"Write a Python one-liner to generate a random number.",
            session_id=session_id,
        )

        # Ask for profile view (same session, user already identified)
        result = cca.chat(
            "What do you know about me? Show my profile. "
            "Also, how do I generate a random string in Python?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        content_lower = result.content.lower()
        assert any(w in content_lower for w in [
            name.lower(), "viewcorp", "profile", "python",
        ]), f"Profile view missing data: {result.content[:200]}"

        cca.cleanup_test_user(name)


class TestManageProfileSkills:
    """manage_user_profile action=add_skill."""

    def test_add_skill(self, cca, trace_test):
        """Agent should add a skill to the user's profile."""
        name = f"SkillUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-skill-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi I'm {name}. I know Python and Docker. "
            f"Write a Dockerfile for a simple Python Flask app.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # User should exist
        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not found via /users API"

        cca.cleanup_test_user(name)


class TestManageProfileAlias:
    """manage_user_profile action=add_alias."""

    def test_add_alias(self, cca, trace_test):
        """Agent should handle alias introduction alongside a task."""
        name = f"AliasUser_{uuid.uuid4().hex[:6]}"
        alias = f"al_{uuid.uuid4().hex[:4]}"
        session_id = f"test-alias-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi I'm {name}, also known as {alias}. "
            f"Write a Python function to merge two dictionaries.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        cca.cleanup_test_user(name)


class TestManageProfileListAll:
    """REST API /users endpoint."""

    def test_list_all_users(self, cca, trace_test):
        """REST API should list user profiles."""
        users_data = cca.list_users()
        trace_test.set_attribute("cca.test.user_count", users_data.get("count", 0))
        assert users_data.get("count", 0) > 0, "No users found via /users API"


class TestManageProfileDelete:
    """manage_user_profile action=delete_profile."""

    def test_delete_profile(self, cca, trace_test):
        """Agent should delete a user profile when confirmed."""
        name = f"DelUser_{uuid.uuid4().hex[:6]}"
        sid_create = f"test-delc-{uuid.uuid4().hex[:8]}"
        sid_delete = f"test-deld-{uuid.uuid4().hex[:8]}"

        # Create user via coding task
        cca.chat(
            f"Hi I'm {name}. Write a Python one-liner to flatten a list.",
            session_id=sid_create,
        )

        # Verify user exists
        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not created"

        # Request deletion in a new session (agent needs to enter loop)
        result = cca.chat(
            f"Hi I'm {name}. Please delete my profile completely. "
            f"I confirm permanent deletion. Also show me how to "
            f"delete a file in Python.",
            session_id=sid_delete,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        content_lower = result.content.lower()
        assert any(w in content_lower for w in [
            "deleted", "removed", "confirm", "delete", "profile",
            "python", "file", "os.",
        ]), f"Response doesn't address deletion or coding: {result.content[:200]}"

        # Check if actually deleted
        user_after = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_deleted", user_after is None)

        # Cleanup if agent refused
        if user_after:
            cca.cleanup_test_user(name)
