"""Flow test: EVA full trace — trace, assemble, write to migration, validate integrity.

Journey: identify as user → trace EVA PowerShell VM automation code for both
Windows and Linux build paths → assemble into a single standalone .ps1 file
written to the EVA-migration project → CCA self-validates that assembled
functions match their original source files exactly.

Exercises the FULL code intelligence pipeline end-to-end AND file writing:
  workspace-sync → tree-sitter AST → Qdrant vectors → Memgraph call graph →
  trace_execution → assemble_traced_code (file output) → str_replace_editor
  (VIEW for validation) → write to /workspace/EVA-migration/.

Exercises: search_codebase (CODE_SEARCH), trace_execution,
assemble_traced_code (TRACE), str_replace_editor (FILE), CODER route.

Requires: Indexed EVA project in Qdrant + Memgraph (PowerShell files
from /workspace/EVA/code/). EVA-migration project in /workspace/EVA-migration/.
"""

import uuid

import pytest

from tests.evaluators import assert_tools_called, evaluate_response

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.eva,
    pytest.mark.trace,
]

# Output file CCA will write to
OUTPUT_FILE = "EVA-standalone-orchestration.ps1"
OUTPUT_PATH = f"/workspace/EVA-migration/{OUTPUT_FILE}"


class TestEvaFullTrace:
    """Real-world EVA scenario: trace, assemble, write, and validate code integrity."""

    def test_eva_trace_assemble_and_validate(self, cca, trace_test, judge_model):
        """3-turn flow: full trace request → code integrity validation → summary.

        Turn 1: Single-message request — trace both Windows and Linux VM build
                 paths from JobStart.ps1, assemble into standalone .ps1 in
                 /workspace/EVA-migration/
        Turn 2: Ask CCA to open the assembled file AND original sources,
                 compare function bodies, confirm they match exactly
        Turn 3: Final summary — function counts, source files, output path
        """
        tracker = cca.tracker()
        sid = f"test-eva-full-{uuid.uuid4().hex[:8]}"
        tracker.track_session(sid)
        tracker.track_user("Sean")
        tracker.track_workspace_prefix("EVA-standalone")

        try:
            # ── Turn 1: Full trace + assemble request ──
            # This is the real user request — one message, complete context.
            msg1 = (
                "Hello this is Sean. In your knowledge on the EVA Project "
                "there are two files: equinix.automation.vcenter.psm1 and "
                "jobstart.ps1.\n\n"
                "jobstart.ps1 takes JSON input and uses it to build both "
                "Windows and Linux servers. The JSON contains sections for "
                "SearchVM, AddVMFromTemplate, InvokeIPAddressUpdate, "
                "LDAPConfig (Linux only), and BuildOptions.\n\n"
                "I need you to trace the code execution for BOTH Windows "
                "and Linux VM build paths starting from JobStart.ps1. Then "
                "give me back a single standalone .ps1 file that contains "
                "ALL the needed functions to run both build types.\n\n"
                "CRITICAL: Do NOT change or refactor any code. This is "
                "production code — I need the original functions exactly "
                "as they are.\n\n"
                f"Write the output file to: {OUTPUT_PATH}"
            )
            r1 = cca.chat(msg1, session_id=sid, idle_timeout=300)
            evaluate_response(r1, msg1, trace_test, judge_model, "coder")

            trace_test.set_attribute("cca.test.t1_response", r1.content[:500])
            assert r1.content, "Turn 1 returned empty"

            # Should have been identified as Sean
            trace_test.set_attribute(
                "cca.test.t1_user_identified", r1.user_identified,
            )
            assert r1.user_identified, (
                "Sean should be identified as a known user"
            )

            # Agent must use tools (trace, search, assemble, etc.)
            iters1 = r1.metadata.get("tool_iterations", 0)
            trace_test.set_attribute("cca.test.t1_iters", iters1)
            assert iters1 >= 1, (
                f"Agent didn't use tools (iters={iters1}). "
                f"Response: {r1.content[:200]}"
            )

            # Should have used trace or search tools
            tool_names_1 = r1.tool_names
            trace_test.set_attribute("cca.test.t1_tools", str(tool_names_1))
            used_code_tools = any(
                t in name for name in tool_names_1
                for t in [
                    "trace_execution", "search_codebase",
                    "assemble_traced_code", "query_call_graph",
                ]
            )
            assert used_code_tools, (
                f"Agent didn't use code intelligence tools. "
                f"Called: {tool_names_1}"
            )

            # Response should mention EVA-related content (not a refusal)
            content1 = r1.content.lower()
            has_eva_content = any(w in content1 for w in [
                "jobstart", "vcenter", "psm1", "powershell",
                "function", "trace", "assembled", "migration",
                OUTPUT_FILE.lower(),
            ])
            trace_test.set_attribute(
                "cca.test.t1_has_eva_content", has_eva_content,
            )
            assert has_eva_content, (
                f"Response doesn't mention EVA content: "
                f"{r1.content[:300]}"
            )

            # ── Turn 2: Code integrity validation ──
            # CCA reads both the assembled file and original sources,
            # compares function bodies to prove they match exactly.
            msg2 = (
                "Now I need you to validate the assembled file. Open "
                f"{OUTPUT_PATH} and compare at least 5 key functions "
                "against their original source files in /workspace/EVA/code/. "
                "Check that the function bodies are IDENTICAL — no "
                "modifications, no missing lines, no added lines. Report "
                "which functions you checked and whether each one matches "
                "exactly."
            )
            r2 = cca.chat(msg2, session_id=sid, idle_timeout=300)
            evaluate_response(r2, msg2, trace_test, judge_model, "coder")

            trace_test.set_attribute("cca.test.t2_response", r2.content[:500])
            assert r2.content, "Turn 2 returned empty"

            # Must have used file tools to actually read and compare
            iters2 = r2.metadata.get("tool_iterations", 0)
            trace_test.set_attribute("cca.test.t2_iters", iters2)
            assert iters2 >= 1, (
                f"Agent didn't use tools to compare files (iters={iters2}). "
                f"Response: {r2.content[:200]}"
            )

            tool_names_2 = r2.tool_names
            trace_test.set_attribute("cca.test.t2_tools", str(tool_names_2))

            # Response should mention specific function names (proves it checked)
            content2 = r2.content.lower()
            has_func_names = any(w in content2 for w in [
                "searchvm", "addvmfromtemplate", "invoke-orchestration",
                "format-vmbuild", "jobstart", "connect-",
                "function", "match", "identical", "verified", "same",
            ])
            trace_test.set_attribute(
                "cca.test.t2_has_func_names", has_func_names,
            )
            assert has_func_names, (
                f"Response doesn't mention function names or validation: "
                f"{r2.content[:300]}"
            )

            # Should contain positive validation words
            has_positive = any(w in content2 for w in [
                "match", "identical", "same", "verified", "correct",
                "intact", "unchanged", "exact",
            ])
            trace_test.set_attribute(
                "cca.test.t2_positive_validation", has_positive,
            )
            assert has_positive, (
                f"Response doesn't confirm code integrity: "
                f"{r2.content[:300]}"
            )

            # Should NOT report differences (negative check)
            reports_diff = any(w in content2 for w in [
                "differ", "mismatch", "modified", "changed",
                "missing lines", "added lines",
            ])
            trace_test.set_attribute(
                "cca.test.t2_reports_diff", reports_diff,
            )
            # Advisory — track but don't fail (the LLM might use these
            # words while saying "no differences found")

            # ── Turn 3: Final summary ──
            msg3 = (
                "Give me a final summary: how many functions were assembled, "
                "from how many source files, and confirm the output file "
                "path and size."
            )
            r3 = cca.chat(msg3, session_id=sid, idle_timeout=120)
            evaluate_response(r3, msg3, trace_test, judge_model, "coder")

            trace_test.set_attribute("cca.test.t3_response", r3.content[:500])
            assert r3.content, "Turn 3 returned empty"

            # Response should reference the output path
            content3 = r3.content.lower()
            has_output_ref = any(w in content3 for w in [
                "eva-migration", "eva-standalone-orchestration",
                OUTPUT_FILE.lower(), "migration",
            ])
            trace_test.set_attribute(
                "cca.test.t3_has_output_ref", has_output_ref,
            )
            assert has_output_ref, (
                f"Response doesn't mention output file: "
                f"{r3.content[:300]}"
            )

            # Response should mention counts
            has_counts = any(w in content3 for w in [
                "function", "file", "source", "assembled",
                "lines", "bytes", "size",
            ])
            trace_test.set_attribute(
                "cca.test.t3_has_counts", has_counts,
            )
            assert has_counts, (
                f"Response doesn't mention function/file counts: "
                f"{r3.content[:300]}"
            )

        finally:
            tracker.cleanup()
