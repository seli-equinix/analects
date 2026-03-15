#!/usr/bin/env python3
"""CCA Interactive Test Dashboard.

Run, monitor, and track all CCA tests from one place.
Pulls status from GitLab (environments + pipelines) and Phoenix (traces).

Usage:
    python scripts/dashboard.py              # Interactive mode
    python scripts/dashboard.py --status     # Print status and exit
    python scripts/dashboard.py history <name>  # Show run history for one test

Examples:
    python scripts/dashboard.py              # Launch interactive dashboard
    python scripts/dashboard.py --status     # Quick status check
    python scripts/dashboard.py history eva-code-trace
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Optional

# ── Configuration ──

GITLAB_URL = "http://192.168.4.204:8929"
GITLAB_API = f"{GITLAB_URL}/api/v4"
PROJECT_ID = 4
TOKEN = "glpat-eZyXT0lQhgPgjkxOprDD8m86MQp1OjEH.01.0w0yemn3j"
PHOENIX_URL = "http://192.168.4.204:6006"

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ── Test Metadata ──
# Static metadata extracted from test docstrings.
# Order defines the numbering in the dashboard.

TESTS = OrderedDict([
    # ── User ──
    ("new-user-onboarding", {
        "cat": "user",
        "turns": 4,
        "exercises": "user_id, profile, notes, preference recall",
        "file": "tests/user/test_new_user_onboarding.py",
    }),
    ("profile-crud", {
        "cat": "user",
        "turns": 5,
        "exercises": "profile CRUD, cascade delete",
        "file": "tests/user/test_profile_crud.py",
    }),
    ("returning-user-memory", {
        "cat": "user",
        "turns": 6,
        "exercises": "fact recall, fact overwrite, accumulation",
        "file": "tests/user/test_returning_user_memory.py",
    }),
    # ── Websearch ──
    ("web-search-flow", {
        "cat": "websearch",
        "turns": 4,
        "exercises": "web_search, fetch_url, multi-source",
        "file": "tests/websearch/test_web_search_flow.py",
    }),
    # ── Coder ──
    ("bash-execution", {
        "cat": "coder",
        "turns": 4,
        "exercises": "bash_tool, str_replace_editor, user recall",
        "file": "tests/coder/test_bash_execution.py",
    }),
    ("code-edit-flow", {
        "cat": "coder",
        "turns": 3,
        "exercises": "str_replace_editor (create/edit), bash (run)",
        "file": "tests/coder/test_code_edit_flow.py",
    }),
    ("code-intelligence", {
        "cat": "coder",
        "turns": 3,
        "exercises": "call_graph, orphan_functions, dependencies",
        "file": "tests/coder/test_code_intelligence.py",
    }),
    ("code-trace", {
        "cat": "coder",
        "turns": 3,
        "exercises": "trace_execution, assemble_traced_code",
        "file": "tests/coder/test_code_trace.py",
    }),
    ("codebase-search", {
        "cat": "coder",
        "turns": 2,
        "exercises": "search_codebase, search_knowledge",
        "file": "tests/coder/test_codebase_search.py",
    }),
    ("document-workflow", {
        "cat": "coder",
        "turns": 3,
        "exercises": "upload_doc, search, promote to knowledge",
        "file": "tests/coder/test_document_workflow.py",
    }),
    ("rule-lifecycle", {
        "cat": "coder",
        "turns": 2,
        "exercises": "create/list/request/delete rule",
        "file": "tests/coder/test_rule_lifecycle.py",
    }),
    ("workspace-indexing", {
        "cat": "coder",
        "turns": 3,
        "exercises": "index_workspace, search_codebase, search_knowledge",
        "file": "tests/coder/test_workspace_indexing.py",
    }),
    # ── Integration ──
    ("cross-session-recall", {
        "cat": "integration",
        "turns": 4,
        "exercises": "NoteObserver, past_insights, cross-session",
        "file": "tests/integration/test_cross_session_recall.py",
    }),
    ("eva-code-trace", {
        "cat": "integration",
        "turns": 3,
        "exercises": "search, trace, assemble (EVA PowerShell)",
        "file": "tests/integration/test_eva_code_trace.py",
    }),
    ("infra-inspection", {
        "cat": "integration",
        "turns": 4,
        "exercises": "bash (docker, curl, ssh), INFRA route",
        "file": "tests/integration/test_infra_inspection_flow.py",
    }),
    ("knowledge-pipeline", {
        "cat": "integration",
        "turns": 2,
        "exercises": "facts, notes, memory REST, NoteObserver",
        "file": "tests/integration/test_knowledge_pipeline.py",
    }),
    ("routing-edge-cases", {
        "cat": "integration",
        "turns": 6,
        "exercises": "router, PLANNER, CODER, INFRA routes",
        "file": "tests/integration/test_routing_edge_cases.py",
    }),
    ("security-edge-cases", {
        "cat": "integration",
        "turns": 4,
        "exercises": "anon identity, SSRF, scheme, no-results",
        "file": "tests/integration/test_security_edge_cases.py",
    }),
    ("tool-isolation", {
        "cat": "integration",
        "turns": 1,
        "exercises": "route tool boundary enforcement",
        "file": "tests/integration/test_tool_isolation.py",
    }),
])

TEST_NAMES = list(TESTS.keys())


# ── API Helpers ──


def _gitlab_api(method: str, path: str, data: Any = None) -> Any:
    """Make a GitLab API request."""
    url = f"{GITLAB_API}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {
        "PRIVATE-TOKEN": TOKEN,
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except Exception:
        return None


def _phoenix_graphql(query: str) -> Any:
    """Query Phoenix GraphQL API."""
    url = f"{PHOENIX_URL}/graphql"
    body = json.dumps({"query": query}).encode()
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        return result.get("data", {})
    except Exception:
        return {}


def _time_ago(iso_str: str) -> str:
    """Convert ISO timestamp to 'Xh ago' / 'Xd ago' string."""
    if not iso_str:
        return ""
    try:
        # Parse ISO format — handle with or without timezone
        ts_str = iso_str.replace("Z", "+00:00")
        if "+" not in ts_str and ts_str.count("-") <= 2:
            ts_str += "+00:00"
        dt = datetime.fromisoformat(ts_str)
        now = datetime.now(timezone.utc)
        delta = now - dt
        secs = delta.total_seconds()
        if secs < 60:
            return "just now"
        elif secs < 3600:
            return f"{int(secs / 60)}m ago"
        elif secs < 86400:
            return f"{int(secs / 3600)}h ago"
        else:
            return f"{int(secs / 86400)}d ago"
    except Exception:
        return iso_str[:16]


# ── Data Fetching ──


def _fetch_pipeline_status() -> dict[str, dict]:
    """Fetch per-test status from GitLab pipeline history.

    Returns: {test_name: {status, last_run, runs_pass, runs_total, duration, commit}}
    """
    result: dict[str, dict] = {}

    pipelines = _gitlab_api("GET", f"/projects/{PROJECT_ID}/pipelines?per_page=100")
    if not pipelines:
        return result

    # Build per-test history from pipeline variables
    for p in pipelines:
        pid = p["id"]
        pvars = _gitlab_api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/variables")
        if not pvars:
            continue

        run_test = ""
        for v in pvars:
            if v["key"] == "RUN_TEST":
                run_test = v["value"]
                break

        if not run_test or run_test not in TEST_NAMES:
            continue

        if run_test not in result:
            result[run_test] = {
                "status": p["status"],
                "last_run": p.get("created_at", ""),
                "runs_pass": 0,
                "runs_total": 0,
                "duration": 0,
                "commit": p.get("sha", "")[:7] if p.get("sha") else "",
                "pipeline_id": pid,
            }

        entry = result[run_test]
        entry["runs_total"] += 1
        if p["status"] == "success":
            entry["runs_pass"] += 1

        # Get duration for the most recent run
        if entry["pipeline_id"] == pid:
            jobs = _gitlab_api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/jobs?per_page=50")
            if jobs:
                test_jobs = [j for j in jobs if j["stage"] == "test"]
                if test_jobs:
                    entry["duration"] = sum(j.get("duration") or 0 for j in test_jobs)

    return result


def _fetch_phoenix_projects() -> dict[str, dict]:
    """Fetch per-test Phoenix project stats.

    Returns: {test_name: {traces, tokens}}
    """
    result: dict[str, dict] = {}

    data = _phoenix_graphql("""{
        projects(first: 100) {
            edges { node {
                name
                traceCount
                tokenCountTotal
            }}
        }
    }""")

    edges = data.get("projects", {}).get("edges", [])
    for edge in edges:
        node = edge.get("node", {})
        name = node.get("name", "")
        # Match "test/<test-name>" pattern
        if name.startswith("test/"):
            test_name = name[5:]  # strip "test/"
            result[test_name] = {
                "traces": node.get("traceCount", 0),
                "tokens": node.get("tokenCountTotal", 0),
            }

    return result


# ── Display ──


def _display_dashboard(pipeline_data: dict, phoenix_data: dict) -> None:
    """Print the numbered test dashboard."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'═' * 78}")
    print(f"  {BOLD}CCA Test Dashboard{RESET}                                        {DIM}{now}{RESET}")
    print(f"{'═' * 78}\n")

    print(f"  {'#':>3s}  {'TEST':<28s}  {'STATUS':8s}  {'LAST RUN':10s}  {'RUNS':6s}  {'EXERCISES'}")
    print(f"  {'─' * 74}")

    current_cat = None
    for idx, (name, meta) in enumerate(TESTS.items(), 1):
        cat = meta["cat"]
        if cat != current_cat:
            current_cat = cat
            print(f"  {CYAN}{cat.upper()}{RESET}")

        # Pipeline status
        pdata = pipeline_data.get(name, {})
        status_str = pdata.get("status", "")
        if status_str == "success":
            status_display = f"{GREEN}PASS{RESET}    "
        elif status_str == "failed":
            status_display = f"{RED}FAIL{RESET}    "
        elif status_str in ("running", "pending"):
            status_display = f"{YELLOW}RUN{RESET}     "
        else:
            status_display = f"{DIM}  -  {RESET}   "

        last_run = _time_ago(pdata.get("last_run", ""))
        if not last_run:
            last_run = f"{DIM}never{RESET}"

        runs_pass = pdata.get("runs_pass", 0)
        runs_total = pdata.get("runs_total", 0)
        if runs_total > 0:
            runs_str = f"{runs_pass}/{runs_total}"
        else:
            runs_str = f"{DIM}0{RESET}"

        exercises = meta["exercises"]
        # Truncate exercises to fit
        if len(exercises) > 40:
            exercises = exercises[:37] + "..."

        print(f"  {idx:>3d}  {name:<28s}  {status_display}{last_run:>10s}  {runs_str:>6s}  {exercises}")

    # Summary
    tested = sum(1 for n in TEST_NAMES if n in pipeline_data)
    passing = sum(1 for n in TEST_NAMES if pipeline_data.get(n, {}).get("status") == "success")
    failing = sum(1 for n in TEST_NAMES if pipeline_data.get(n, {}).get("status") == "failed")
    never = len(TEST_NAMES) - tested

    print(f"\n  {BOLD}Summary:{RESET} {tested}/{len(TEST_NAMES)} tested | "
          f"{GREEN}{passing} passing{RESET} | "
          f"{RED}{failing} failing{RESET} | "
          f"{DIM}{never} never run{RESET}")

    print(f"\n  {DIM}GitLab:  {GITLAB_URL}/root/cca-tests/-/environments{RESET}")
    print(f"  {DIM}Phoenix: {PHOENIX_URL}{RESET}")


def _display_history(test_name: str) -> None:
    """Show run history for one test."""
    if test_name not in TESTS:
        print(f"{RED}Unknown test: {test_name}{RESET}")
        return

    print(f"\n{BOLD}Run History: {test_name}{RESET}\n")

    # Get pipelines for this test
    pipelines = _gitlab_api("GET", f"/projects/{PROJECT_ID}/pipelines?per_page=50")
    if not pipelines:
        print(f"  {DIM}No pipelines found.{RESET}")
        return

    runs = []
    for p in pipelines:
        pid = p["id"]
        pvars = _gitlab_api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/variables")
        if not pvars:
            continue
        run_test = ""
        for v in pvars:
            if v["key"] == "RUN_TEST":
                run_test = v["value"]
                break
        if run_test != test_name:
            continue

        # Get duration
        jobs = _gitlab_api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/jobs?per_page=50")
        test_dur = 0
        if jobs:
            test_jobs = [j for j in jobs if j["stage"] == "test"]
            test_dur = sum(j.get("duration") or 0 for j in test_jobs)

        runs.append({
            "pipeline_id": pid,
            "status": p["status"],
            "commit": (p.get("sha") or "")[:7],
            "when": _time_ago(p.get("created_at", "")),
            "created": p.get("created_at", "")[:16].replace("T", " "),
            "duration": f"{test_dur:.0f}s" if test_dur > 0 else "-",
        })

    if not runs:
        print(f"  {DIM}No runs found for this test.{RESET}")
        return

    print(f"  {'#':>3s}  {'STATUS':6s}  {'COMMIT':8s}  {'WHEN':10s}  {'DURATION':>8s}  {'PIPELINE':>8s}")
    print(f"  {'─' * 55}")

    for i, r in enumerate(runs, 1):
        if r["status"] == "success":
            status = f"{GREEN}PASS{RESET}"
        elif r["status"] == "failed":
            status = f"{RED}FAIL{RESET}"
        else:
            status = r["status"][:4]

        print(f"  {i:>3d}  {status}  {r['commit']:8s}  {r['when']:>10s}  {r['duration']:>8s}  #{r['pipeline_id']}")

    # Phoenix project info
    phoenix_data = _fetch_phoenix_projects()
    px = phoenix_data.get(test_name, {})
    traces = px.get("traces", 0)

    print(f"\n  {DIM}GitLab:  {GITLAB_URL}/root/cca-tests/-/pipelines{RESET}")
    print(f"  {DIM}Phoenix: {PHOENIX_URL}  (project: test/{test_name}, {traces} traces){RESET}")


# ── Interactive Mode ──


def _run_test(test_name: str) -> None:
    """Run a test via ci.py (subprocess so live output works)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ci_script = os.path.join(script_dir, "ci.py")
    try:
        subprocess.run(
            [sys.executable, ci_script, "run", test_name],
            check=False,
        )
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted. Test may still be running in GitLab.{RESET}")


def _interactive_loop() -> None:
    """Main interactive loop: display → prompt → run/history → repeat."""
    while True:
        # Fetch data
        print(f"\n{DIM}Fetching status from GitLab + Phoenix...{RESET}", end="", flush=True)
        pipeline_data = _fetch_pipeline_status()
        phoenix_data = _fetch_phoenix_projects()
        # Clear the "Fetching..." line
        print("\r" + " " * 50 + "\r", end="", flush=True)

        _display_dashboard(pipeline_data, phoenix_data)

        print(f"\n  {BOLD}[#]{RESET} Run test   {BOLD}[h #]{RESET} History   "
              f"{BOLD}[a]{RESET} Run all   {BOLD}[r]{RESET} Refresh   {BOLD}[q]{RESET} Quit")

        try:
            choice = input(f"\n  {BOLD}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not choice:
            continue
        elif choice.lower() == "q":
            break
        elif choice.lower() == "r":
            continue  # Refresh — loop back to fetch + display
        elif choice.lower() == "a":
            _run_test("all")
            input(f"\n  {DIM}Press Enter to return to dashboard...{RESET}")
        elif choice.lower().startswith("h ") or choice.lower().startswith("h"):
            # History: "h 7" or "h7" or "h eva-code-trace"
            rest = choice[1:].strip()
            if rest.isdigit():
                idx = int(rest)
                if 1 <= idx <= len(TEST_NAMES):
                    _display_history(TEST_NAMES[idx - 1])
                else:
                    print(f"  {RED}Invalid number. Use 1-{len(TEST_NAMES)}.{RESET}")
                    continue
            elif rest in TESTS:
                _display_history(rest)
            else:
                print(f"  {RED}Usage: h <number> or h <test-name>{RESET}")
                continue
            input(f"\n  {DIM}Press Enter to return to dashboard...{RESET}")
        elif choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(TEST_NAMES):
                test_name = TEST_NAMES[idx - 1]
                print(f"\n  Running: {BOLD}{test_name}{RESET}  (#{idx})\n")
                _run_test(test_name)
                input(f"\n  {DIM}Press Enter to return to dashboard...{RESET}")
            else:
                print(f"  {RED}Invalid number. Use 1-{len(TEST_NAMES)}.{RESET}")
        elif choice in TESTS:
            # Also accept test name directly
            print(f"\n  Running: {BOLD}{choice}{RESET}\n")
            _run_test(choice)
            input(f"\n  {DIM}Press Enter to return to dashboard...{RESET}")
        else:
            print(f"  {RED}Unknown command. Type a number, 'h #', 'a', 'r', or 'q'.{RESET}")


# ── Main ──


def main() -> None:
    if len(sys.argv) >= 2:
        if sys.argv[1] == "--status":
            pipeline_data = _fetch_pipeline_status()
            phoenix_data = _fetch_phoenix_projects()
            _display_dashboard(pipeline_data, phoenix_data)
            return

        if sys.argv[1] == "history":
            if len(sys.argv) < 3:
                print(f"Usage: {sys.argv[0]} history <test-name>")
                sys.exit(1)
            _display_history(sys.argv[2])
            return

        print(f"Unknown argument: {sys.argv[1]}")
        print(__doc__)
        sys.exit(1)

    _interactive_loop()


if __name__ == "__main__":
    main()
