"""Generate .md test reports for Claude Code review.

After each test, a markdown file is created with:
- Full input/output for every turn (not truncated)
- All evaluator scores per turn
- Tools called, route, model decisions
- Backend health status

Reports are stored in reports/ and captured as GitLab CI artifacts.
Claude Code can read these to analyze test quality and suggest improvements.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# In CI: write to /reports (volume-mounted to host tests/reports/)
# Locally: write to tests/reports/ relative to this file
if os.environ.get("CI"):
    REPORTS_DIR = Path("/reports")
else:
    REPORTS_DIR = Path(__file__).parent / "reports"

# Pipeline ID from GitLab CI — used to match reports to dashboard runs
PIPELINE_ID = os.environ.get("CI_PIPELINE_ID", "local")


def generate_test_report(
    test_name: str,
    status: str,
    turns: List[tuple],
    metrics: Dict[str, Any],
    evals_per_turn: Optional[List[List[Dict]]] = None,
    backend_issues: Optional[Dict] = None,
) -> Optional[Path]:
    """Generate a .md report for a single test.

    Args:
        test_name: Test identifier (e.g., "new-user-onboarding")
        status: "PASSED" or "FAILED"
        turns: List of (user_message, agent_response) tuples
        metrics: Test metrics from span._test_metrics
        evals_per_turn: List of evaluator result lists, one per turn
        backend_issues: Any backend health issues detected during the test
    """
    try:
        REPORTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"P{PIPELINE_ID}_{test_name}_{timestamp}.md"
        filepath = REPORTS_DIR / filename

        lines: list[str] = []

        # Header
        lines.append(f"# Test Report: {test_name}")
        lines.append("")
        lines.append(f"- **Status**: {status}")
        duration_ms = metrics.get("execution_time_ms", 0)
        lines.append(f"- **Duration**: {duration_ms / 1000:.1f}s")
        lines.append(f"- **Route**: {metrics.get('route', 'unknown')}")
        lines.append(f"- **Tool Iterations**: {metrics.get('tool_iterations', 0)}")
        lines.append(f"- **Estimated Steps**: {metrics.get('estimated_steps', 0)}")
        lines.append(f"- **Timestamp**: {timestamp}")
        lines.append(f"- **Pipeline**: #{PIPELINE_ID}")
        lines.append(f"- **Turns**: {len(turns)}")

        if metrics.get("nudge_skipped"):
            lines.append("- **Nudge Skipped**: Yes (response had code)")
        if metrics.get("circuit_breaker_fired"):
            lines.append("- **Circuit Breaker**: FIRED")

        if backend_issues:
            lines.append(f"- **Backend Issues**: {backend_issues}")
        else:
            lines.append("- **Backend Issues**: None")

        lines.append("")

        # Turns
        for i, (msg, resp) in enumerate(turns, 1):
            lines.append(f"## Turn {i}/{len(turns)}")
            lines.append("")
            lines.append("### Input")
            lines.append("```")
            lines.append(msg)
            lines.append("```")
            lines.append("")
            lines.append("### Response")
            lines.append(resp if resp else "*[empty response]*")
            lines.append("")

            # Evaluations for this turn
            if evals_per_turn and i <= len(evals_per_turn):
                turn_evals = evals_per_turn[i - 1]
                if turn_evals:
                    lines.append("### Evaluations")
                    lines.append("| Evaluator | Score | Label | Detail |")
                    lines.append("|-----------|-------|-------|--------|")
                    for ev in turn_evals:
                        name = ev.get("name", "?")
                        score = ev.get("score", "?")
                        label = ev.get("label", "?")
                        detail = str(ev.get("explanation", ""))[:100]
                        lines.append(f"| {name} | {score} | {label} | {detail} |")
                    lines.append("")

            lines.append("---")
            lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Test**: {test_name}")
        lines.append(f"- **Status**: {status}")
        lines.append(f"- **Turns**: {len(turns)}")
        lines.append(f"- **Total Duration**: {duration_ms / 1000:.1f}s")
        lines.append(f"- **Route**: {metrics.get('route', 'unknown')}")
        lines.append(f"- **Tool Iterations**: {metrics.get('tool_iterations', 0)}")

        # Count eval pass/fail
        if evals_per_turn:
            total_evals = 0
            failed_evals = []
            for turn_idx, turn_evals in enumerate(evals_per_turn, 1):
                if not turn_evals:
                    continue
                for ev in turn_evals:
                    total_evals += 1
                    if ev.get("score", 1) < 1.0:
                        failed_evals.append(
                            f"Turn {turn_idx}: {ev.get('name', '?')}={ev.get('label', '?')}"
                        )
            lines.append(f"- **Total Evaluations**: {total_evals}")
            if failed_evals:
                lines.append(f"- **Failed Evaluations**: {len(failed_evals)}")
                for fe in failed_evals:
                    lines.append(f"  - {fe}")
            else:
                lines.append("- **Failed Evaluations**: 0")

        lines.append("")

        filepath.write_text("\n".join(lines))
        log.info("Generated test report: %s", filepath)
        return filepath

    except Exception as e:
        log.warning("Failed to generate test report for %s: %s", test_name, e)
        return None


def generate_session_summary(
    results: Dict[str, Dict[str, Any]],
) -> Optional[Path]:
    """Generate a session-level summary report after all tests complete.

    Args:
        results: test_name → {status, duration_s, turns, route, ...}
    """
    try:
        REPORTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        filepath = REPORTS_DIR / f"_summary_{timestamp}.md"

        passed = sum(1 for r in results.values() if r.get("status") == "PASSED")
        failed = sum(1 for r in results.values() if r.get("status") == "FAILED")
        skipped = sum(1 for r in results.values() if r.get("status") == "SKIPPED")
        total = len(results)

        lines: list[str] = []
        lines.append("# Test Session Summary")
        lines.append("")
        lines.append(f"- **Timestamp**: {timestamp}")
        lines.append(f"- **Total Tests**: {total}")
        lines.append(f"- **Passed**: {passed}")
        lines.append(f"- **Failed**: {failed}")
        if skipped:
            lines.append(f"- **Skipped**: {skipped}")
        lines.append("")

        # Results table
        lines.append("| # | Test | Status | Duration | Turns | Route |")
        lines.append("|---|------|--------|----------|-------|-------|")
        for i, (name, info) in enumerate(sorted(results.items()), 1):
            status = info.get("status", "?")
            dur = info.get("duration_s", "?")
            turns = info.get("turns", "?")
            route = info.get("route", "?")
            status_icon = "✅" if status == "PASSED" else "❌" if status == "FAILED" else "⏭️"
            lines.append(f"| {i} | {name} | {status_icon} {status} | {dur}s | {turns} | {route} |")

        lines.append("")

        # Failed tests details
        failed_tests = {k: v for k, v in results.items() if v.get("status") == "FAILED"}
        if failed_tests:
            lines.append("## Failed Tests")
            lines.append("")
            for name, info in sorted(failed_tests.items()):
                lines.append(f"### {name}")
                if info.get("error"):
                    lines.append(f"**Error**: {info['error']}")
                lines.append("")

        filepath.write_text("\n".join(lines))
        log.info("Generated session summary: %s", filepath)
        return filepath

    except Exception as e:
        log.warning("Failed to generate session summary: %s", e)
        return None


def cleanup_reports(test_name: Optional[str] = None) -> int:
    """Delete report files.

    Args:
        test_name: If given, delete only reports for this test.
                   If None, delete ALL reports.

    Returns:
        Number of files deleted.
    """
    if not REPORTS_DIR.exists():
        return 0
    count = 0
    for f in REPORTS_DIR.glob("*.md"):
        if test_name is None or f.name.startswith(f"{test_name}_"):
            f.unlink()
            count += 1
    return count
