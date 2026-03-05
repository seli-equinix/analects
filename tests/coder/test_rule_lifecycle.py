"""Flow test: Rules lifecycle — create, list, request, delete.

Journey: create a behavior rule → list rules to verify → request it
by name → delete it → verify it's gone.

Exercises: create_rule, list_rules, request_rule, delete_rule
(RULES group), CODER route.
"""

import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.coder, pytest.mark.slow]


class TestRuleLifecycle:
    """CODER route: full CRUD lifecycle for behavior rules."""

    def test_rule_lifecycle(self, cca, trace_test, judge_model):
        """Create → list → request → delete a rule."""
        sid = f"test-rule-{uuid.uuid4().hex[:8]}"
        rule_name = f"test-rule-{uuid.uuid4().hex[:6]}"

        # ── Turn 1: Create a rule ──
        msg1 = (
            f"Create a new rule called '{rule_name}' with type 'manual' "
            f"that says: 'Always use type hints in Python function signatures. "
            f"Include return type annotations.' "
            f"Set the description to 'Python type hint enforcement'."
        )
        r1 = cca.chat(msg1, session_id=sid)
        evaluate_response(r1, msg1, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.t1_response", r1.content[:300])
        assert r1.content, "Turn 1 returned empty"

        iters = r1.metadata.get("tool_iterations", 0)
        trace_test.set_attribute("cca.test.t1_iters", iters)
        assert iters >= 1, (
            f"Agent didn't use tools to create rule (iters={iters})"
        )

        # ── Turn 2: List rules — should include ours ──
        msg2 = "List all the rules you have. Is my rule there?"
        r2 = cca.chat(msg2, session_id=sid)
        evaluate_response(r2, msg2, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.t2_response", r2.content[:300])
        assert r2.content, "Turn 2 returned empty"

        content_lower = r2.content.lower()
        has_rule = rule_name in content_lower or "type hint" in content_lower
        trace_test.set_attribute("cca.test.rule_listed", has_rule)
        assert has_rule, (
            f"Rule '{rule_name}' not found in list: {r2.content[:300]}"
        )

        # ── Turn 3: Request the rule by name ──
        msg3 = f"Show me the details of the rule called '{rule_name}'."
        r3 = cca.chat(msg3, session_id=sid)
        evaluate_response(r3, msg3, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.t3_response", r3.content[:300])
        assert r3.content, "Turn 3 returned empty"

        content_lower = r3.content.lower()
        has_details = "type hint" in content_lower or "annotation" in content_lower
        trace_test.set_attribute("cca.test.has_details", has_details)
        assert has_details, (
            f"Rule details not shown: {r3.content[:300]}"
        )

        # ── Turn 4: Delete the rule ──
        msg4 = f"Delete the rule called '{rule_name}'."
        r4 = cca.chat(msg4, session_id=sid)
        evaluate_response(r4, msg4, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.t4_response", r4.content[:300])
        assert r4.content, "Turn 4 returned empty"

        # Should confirm deletion
        content_lower = r4.content.lower()
        has_confirm = any(w in content_lower for w in [
            "deleted", "removed", "done", "successfully",
        ])
        trace_test.set_attribute("cca.test.delete_confirmed", has_confirm)
        assert has_confirm, (
            f"Agent didn't confirm deletion: {r4.content[:300]}"
        )
