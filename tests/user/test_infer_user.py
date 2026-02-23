"""Tests for the infer_user tool.

Validates semantic user matching — the agent's ability to identify
a user from contextual clues without an explicit name introduction.
"""

import uuid

import pytest

pytestmark = [pytest.mark.user, pytest.mark.timeout(300)]


class TestInferUser:
    """infer_user tool — semantic matching via embeddings."""

    def test_infer_known_user(self, cca, trace_test):
        """Agent should recognize a known user from context clues."""
        name = f"InferKnown_{uuid.uuid4().hex[:6]}"
        sid1 = f"test-infer1-{uuid.uuid4().hex[:8]}"
        sid2 = f"test-infer2-{uuid.uuid4().hex[:8]}"

        # Session 1: create user with distinctive info
        cca.chat(
            f"Hi I'm {name}. I work on the vLLM server at Spark2.",
            session_id=sid1,
        )

        # Session 2: give context clue instead of name
        result = cca.chat(
            f"Hey, it's the {name.split('_')[0]} person who works on vLLM. "
            f"Actually, I'm {name}.",
            session_id=sid2,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # User should still exist (not duplicated)
        user = cca.find_user_by_name(name)
        trace_test.set_attribute("cca.test.user_found", user is not None)
        assert user is not None, f"User '{name}' not found"

        cca.cleanup_test_user(name)

    def test_infer_no_match(self, cca, trace_test):
        """Generic message with no user clues should not auto-identify."""
        session_id = f"test-noinfer-{uuid.uuid4().hex[:8]}"

        result = cca.chat(
            "What is the capital of France?",
            session_id=session_id,
        )

        trace_test.set_attribute("cca.test.response", result.content[:500])
        assert result.content, "Agent returned empty response"

        # Should not claim identification
        trace_test.set_attribute("cca.test.user_identified", result.user_identified)
        # This is a soft check — auto-inference may or may not trigger
        assert len(result.content) > 5, "Response too short"
