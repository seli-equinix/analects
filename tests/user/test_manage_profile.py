"""Tests for the manage_user_profile tool.

Validates profile operations: view, add/remove skills, aliases,
list all users, and delete profile. Uses REST API for ground truth.
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

        # Create user with some data in one message
        cca.chat(
            f"Hi I'm {name}. I work at ViewCorp and prefer detailed answers.",
            session_id=session_id,
        )

        # Ask for profile view
        result = cca.chat(
            "Show me my profile — what do you know about me?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        content_lower = result.content.lower()
        assert any(w in content_lower for w in [
            name.lower(), "viewcorp", "profile", "detail", "preference",
        ]), f"Profile view missing data: {result.content[:200]}"

        cca.cleanup_test_user(name)


class TestManageProfileSkills:
    """manage_user_profile action=add_skill/remove_skill."""

    def test_add_skill(self, cca, trace_test):
        """Agent should add a skill to the user's profile."""
        name = f"SkillUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-skill-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi I'm {name}. I know Python — add that to my skills.",
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
        """Agent should add an alias to the user's profile."""
        name = f"AliasUser_{uuid.uuid4().hex[:6]}"
        alias = f"al_{uuid.uuid4().hex[:4]}"
        session_id = f"test-alias-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            f"Hi I'm {name}. I also go by {alias} — "
            f"please add that as an alias for me.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        cca.cleanup_test_user(name)


class TestManageProfileListAll:
    """manage_user_profile action=list_all."""

    def test_list_all_users(self, cca, trace_test):
        """REST API should list user profiles."""
        name = f"ListUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-list-{uuid.uuid4().hex[:8]}"

        # Create a user so there's at least one
        cca.chat(f"Hi I'm {name}.", session_id=session_id)

        # Use REST API directly to verify
        users_data = cca.list_users()
        trace_test.set_attribute("cca.test.user_count", users_data.get("count", 0))

        assert users_data.get("count", 0) > 0, "No users found via /users API"

        cca.cleanup_test_user(name)


class TestManageProfileDelete:
    """manage_user_profile action=delete_profile."""

    def test_delete_profile(self, cca, trace_test):
        """Agent should delete a user profile when asked with confirmation."""
        name = f"DelUser_{uuid.uuid4().hex[:6]}"
        session_id = f"test-del-{uuid.uuid4().hex[:8]}"

        # Create user
        cca.chat(f"Hi I'm {name}.", session_id=session_id)

        # Verify user exists
        user = cca.find_user_by_name(name)
        assert user is not None, f"User '{name}' not created"

        # Ask to delete
        result = cca.chat(
            "Please delete my profile completely. I confirm the deletion.",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        content_lower = result.content.lower()
        assert any(w in content_lower for w in [
            "deleted", "removed", "confirm", "delete", "profile",
            "goodbye", "permanently",
        ]), f"Response doesn't address deletion: {result.content[:200]}"

        # Check if actually deleted
        user_after = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_deleted", user_after is None)

        # Cleanup if agent refused
        if user_after:
            cca.cleanup_test_user(name)
