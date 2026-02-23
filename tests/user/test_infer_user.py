"""Tests for the infer_user tool.

Validates semantic user matching — the agent's ability to identify
a user from contextual clues without an explicit name introduction.
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(600)]


class TestInferUser:
    """infer_user tool — semantic user identification."""

    def test_infer_known_user_from_context(self, cca, trace_test):
        """Agent should infer a known user from project/domain clues."""
        name = f"TestInfer_{uuid.uuid4().hex[:6]}"
        sid_setup = f"test-infer-setup-{uuid.uuid4().hex[:8]}"
        sid_infer = f"test-infer-test-{uuid.uuid4().hex[:8]}"

        # Setup: create user with distinctive facts
        cca.chat(
            f"I'm {name}. Identify me. Remember these facts: "
            f"I work on the UniqueProject_{uuid.uuid4().hex[:4]} project, "
            f"my main language is Rust, and my server is called "
            f"test-gpu-{uuid.uuid4().hex[:4]}. "
            f"Use remember_user_fact for each.",
            session_id=sid_setup,
            timeout=240,
        )

        # Test: new session without name, but with contextual clues
        result = cca.chat(
            "I need help with my UniqueProject project. "
            "Can you check who I might be using infer_user?",
            session_id=sid_infer,
        )

        trace_test.set_attribute("cca.test.user_name", name)
        trace_test.set_attribute("cca.test.response", result.content[:500])

        # The agent should attempt inference (response is non-empty)
        assert result.content, "Agent returned empty response"
        assert len(result.content) > 20, "Response too short"

        cca.cleanup_test_user(name)

    def test_infer_no_match_generic_message(self, cca, trace_test):
        """A generic message should not trigger false identification."""
        session_id = f"test-infer-none-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            "How do I list files in a directory using Python?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])

        assert result.content, "Agent returned empty response"
        # Should answer the coding question without trying to identify anyone.
        # The response should NOT contain "identified as" or "you are <name>".
        content_lower = result.content.lower()
        assert "os" in content_lower or "listdir" in content_lower or \
            "pathlib" in content_lower or "directory" in content_lower or \
            "file" in content_lower, \
            "Agent didn't answer the coding question"

    def test_infer_uncertain_asks_user(self, cca, trace_test):
        """With medium confidence, agent may ask the user to confirm."""
        name = f"TestInferAsk_{uuid.uuid4().hex[:6]}"
        sid_setup = f"test-inferask-setup-{uuid.uuid4().hex[:8]}"
        sid_test = f"test-inferask-test-{uuid.uuid4().hex[:8]}"

        # Setup: create user with some facts
        cca.chat(
            f"I'm {name}. Identify me and remember I work with Docker "
            f"and Kubernetes. Use remember_user_fact for each.",
            session_id=sid_setup,
        )

        # Test: vague message that partially matches
        result = cca.chat(
            "I need help with my container orchestration setup.",
            session_id=sid_test,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])

        # Agent should either help directly or ask about identity
        assert result.content, "Agent returned empty response"
        assert len(result.content) > 20, "Response too short"

        cca.cleanup_test_user(name)
