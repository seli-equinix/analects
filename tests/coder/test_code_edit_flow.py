"""Flow test: File creation and editing via the CODER route.

Journey: ask agent to create a Python file → verify file exists →
ask to modify it (add a function) → verify the edit applied →
ask to view the file → verify content in response.

Exercises: str_replace_editor (create, str_replace, view), CODER route.
"""

import re
import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.coder, pytest.mark.slow]


class TestCodeEditFlow:
    """CODER route: create, edit, and view files in /workspace."""

    def test_code_edit_flow(self, cca, trace_test, judge_model):
        """Full file lifecycle: create → edit → view."""
        filename = f"test_edit_{uuid.uuid4().hex[:6]}.py"
        sid = f"test-edit-{uuid.uuid4().hex[:8]}"

        try:
            # ── Turn 1: Create a file ──
            msg1 = (
                f"Create a Python file called {filename} in /workspace "
                f"with a function called greet(name) that returns "
                f"'Hello, {{name}}!'. Just the function, no main block."
            )
            r1 = cca.chat(msg1, session_id=sid)
            evaluate_response(r1, msg1, trace_test, judge_model, "integration")

            trace_test.set_attribute("cca.test.t1_response", r1.content[:300])
            assert r1.content, "Turn 1 returned empty"

            # Should have used tools
            iters = r1.metadata.get("tool_iterations", 0)
            trace_test.set_attribute("cca.test.t1_iters", iters)
            assert iters >= 1, (
                f"Agent didn't use tools to create file (iters={iters})"
            )

            # Verify file exists via REST
            files = cca.list_workspace_files()
            file_list = files.get("files", [])
            file_names = [f.get("name", "") if isinstance(f, dict) else str(f) for f in file_list]
            has_file = any(filename in name for name in file_names)
            trace_test.set_attribute("cca.test.file_created", has_file)
            assert has_file, (
                f"File '{filename}' not found in workspace. "
                f"Files: {file_names[:10]}"
            )

            # ── Turn 2: Edit the file — add a second function ──
            msg2 = (
                f"Add a function called farewell(name) to {filename} "
                f"that returns 'Goodbye, {{name}}!'. Put it after greet."
            )
            r2 = cca.chat(msg2, session_id=sid)
            evaluate_response(r2, msg2, trace_test, judge_model, "integration")

            trace_test.set_attribute("cca.test.t2_response", r2.content[:300])
            assert r2.content, "Turn 2 returned empty"

            iters2 = r2.metadata.get("tool_iterations", 0)
            trace_test.set_attribute("cca.test.t2_iters", iters2)
            assert iters2 >= 1, (
                f"Agent didn't use tools to edit file (iters={iters2})"
            )

            # ── Turn 3: View the file and verify both functions ──
            msg3 = f"Show me the contents of /workspace/{filename}"
            r3 = cca.chat(msg3, session_id=sid)
            evaluate_response(r3, msg3, trace_test, judge_model, "integration")

            trace_test.set_attribute("cca.test.t3_response", r3.content[:500])
            assert r3.content, "Turn 3 returned empty"

            content_lower = r3.content.lower()
            has_greet = "def greet" in content_lower or "greet" in content_lower
            has_farewell = "def farewell" in content_lower or "farewell" in content_lower
            trace_test.set_attribute("cca.test.has_greet", has_greet)
            trace_test.set_attribute("cca.test.has_farewell", has_farewell)
            assert has_greet, (
                f"Response doesn't show greet function: {r3.content[:300]}"
            )
            assert has_farewell, (
                f"Response doesn't show farewell function: {r3.content[:300]}"
            )

        finally:
            cca.clean_workspace_files(prefix=filename.replace(".py", ""))
