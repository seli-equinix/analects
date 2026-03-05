"""Flow test: Bash command execution via the CODER route.

Journey: ask agent to run a simple command → verify output in response →
ask to run a pipeline command → verify structured output.

Exercises: bash_tool, CODER route.
"""

import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.coder]


class TestBashExecution:
    """CODER route: execute bash commands and report results."""

    def test_bash_execution(self, cca, trace_test, judge_model):
        """Run commands and verify output is reported back."""
        sid = f"test-bash-{uuid.uuid4().hex[:8]}"

        # ── Turn 1: Simple command ──
        msg1 = "Run `uname -a` and tell me what OS this system is running."
        r1 = cca.chat(msg1, session_id=sid)
        evaluate_response(r1, msg1, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.t1_response", r1.content[:300])
        assert r1.content, "Turn 1 returned empty"

        # Should have used tools (bash_tool)
        iters = r1.metadata.get("tool_iterations", 0)
        trace_test.set_attribute("cca.test.t1_iters", iters)
        assert iters >= 1, (
            f"Agent didn't use tools to run command (iters={iters}). "
            f"Response: {r1.content[:200]}"
        )

        # Response should contain OS info from uname
        content_lower = r1.content.lower()
        has_os_info = any(w in content_lower for w in [
            "linux", "aarch64", "arm", "gnu", "ubuntu", "kernel",
        ])
        trace_test.set_attribute("cca.test.has_os_info", has_os_info)
        assert has_os_info, (
            f"Response doesn't contain OS info from uname: {r1.content[:300]}"
        )

        # ── Turn 2: Pipeline command ──
        msg2 = (
            "How much disk space is used on the root filesystem? "
            "Run df -h / and tell me the usage percentage."
        )
        r2 = cca.chat(msg2, session_id=sid)
        evaluate_response(r2, msg2, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.t2_response", r2.content[:300])
        assert r2.content, "Turn 2 returned empty"

        iters2 = r2.metadata.get("tool_iterations", 0)
        trace_test.set_attribute("cca.test.t2_iters", iters2)
        assert iters2 >= 1, (
            f"Agent didn't use tools for disk check (iters={iters2})"
        )

        # Should mention percentage or size
        has_disk_info = any(w in content_lower for w in [
            "%", "gb", "tb", "used", "available", "filesystem",
        ]) or any(c.isdigit() for c in r2.content)
        trace_test.set_attribute("cca.test.has_disk_info", has_disk_info)
