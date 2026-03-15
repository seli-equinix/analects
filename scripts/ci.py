#!/usr/bin/env python3
"""CCA Test Runner — GitLab CI + Phoenix integration.

Trigger, monitor, and debug individual CCA tests via GitLab pipelines.
Each test runs in its own pipeline for clean tracking and isolation.

Usage:
    python scripts/ci.py run <test-name>      # Trigger + wait + show result
    python scripts/ci.py status               # Show recent pipeline results
    python scripts/ci.py logs <test-name>     # Show logs from last run
    python scripts/ci.py retry <pipeline-id>  # Retry a failed pipeline
    python scripts/ci.py list                 # Available test names
    python scripts/ci.py cancel <pipeline-id> # Cancel a running pipeline

Examples:
    python scripts/ci.py run eva-code-trace
    python scripts/ci.py run all-coder
    python scripts/ci.py status
    python scripts/ci.py logs eva-code-trace
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
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

# All available test names (must match RUN_TEST values in .gitlab-ci.yml)
TESTS = {
    "user": [
        "new-user-onboarding",
        "profile-crud",
        "returning-user-memory",
    ],
    "websearch": [
        "web-search-flow",
    ],
    "coder": [
        "bash-execution",
        "code-edit-flow",
        "code-intelligence",
        "code-trace",
        "codebase-search",
        "document-workflow",
        "rule-lifecycle",
        "workspace-indexing",
    ],
    "integration": [
        "cross-session-recall",
        "eva-code-trace",
        "infra-inspection",
        "knowledge-pipeline",
        "routing-edge-cases",
        "security-edge-cases",
        "tool-isolation",
    ],
}

ALL_TESTS = [t for group in TESTS.values() for t in group]
GROUPS = [f"all-{g}" for g in TESTS.keys()] + ["all"]


def _api(method: str, path: str, data: Any = None) -> Any:
    """Make a GitLab API request."""
    url = f"{GITLAB_API}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {
        "PRIVATE-TOKEN": TOKEN,
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"{RED}API error {e.code}: {body[:300]}{RESET}")
        sys.exit(1)


def _status_icon(status: str) -> str:
    """Return colored icon for GitLab job/pipeline status."""
    icons = {
        "success": f"{GREEN}PASS{RESET}",
        "failed": f"{RED}FAIL{RESET}",
        "running": f"{CYAN}RUN {RESET}",
        "pending": f"{YELLOW}WAIT{RESET}",
        "created": f"{DIM}IDLE{RESET}",
        "canceled": f"{DIM}SKIP{RESET}",
        "skipped": f"{DIM}SKIP{RESET}",
        "manual": f"{DIM}MAN {RESET}",
    }
    return icons.get(status, status[:4])


# ── Commands ──


def cmd_run(test_name: str) -> None:
    """Trigger a pipeline for a specific test and wait for completion."""
    if test_name not in ALL_TESTS and test_name not in GROUPS and test_name != "build":
        print(f"{RED}Unknown test: {test_name}{RESET}")
        print(f"Run 'list' to see available tests.")
        sys.exit(1)

    print(f"{BOLD}Triggering: {test_name}{RESET}")
    pipeline = _api("POST", f"/projects/{PROJECT_ID}/pipeline", {
        "ref": "main",
        "variables": [{"key": "RUN_TEST", "value": test_name}],
    })
    pid = pipeline["id"]
    web_url = pipeline["web_url"]
    print(f"Pipeline:  {web_url}")
    print(f"Phoenix:   {PHOENIX_URL}")
    print()

    # Poll for completion
    start = time.time()
    last_status = ""
    while True:
        p = _api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}")
        status = p["status"]

        if status != last_status:
            elapsed = time.time() - start
            print(f"  {_status_icon(status)}  {status:12s}  ({elapsed:.0f}s)")
            last_status = status

        if status in ("success", "failed", "canceled", "skipped"):
            break

        time.sleep(5)

    elapsed = time.time() - start
    print()

    # Show job results
    jobs = _api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/jobs?per_page=100")
    test_jobs = [j for j in jobs if j["stage"] == "test"]

    if not test_jobs:
        # Only health-check ran (or build)
        for j in jobs:
            dur = j.get("duration") or 0
            print(f"  {_status_icon(j['status'])}  {j['name']:35s}  {dur:.0f}s")
    else:
        for j in sorted(test_jobs, key=lambda x: x["name"]):
            dur = j.get("duration") or 0
            print(f"  {_status_icon(j['status'])}  {j['name']:35s}  {dur:.0f}s")

    print(f"\n{BOLD}Total: {elapsed:.0f}s{RESET}")

    # If failed, show the failing job's log tail
    failed_jobs = [j for j in test_jobs if j["status"] == "failed"]
    if not failed_jobs:
        failed_jobs = [j for j in jobs if j["status"] == "failed"]

    for j in failed_jobs:
        print(f"\n{RED}{'─' * 60}{RESET}")
        print(f"{RED}FAILED: {j['name']}{RESET}")
        print(f"{RED}{'─' * 60}{RESET}")
        _show_job_log(j["id"], tail=80)

    # Exit with appropriate code
    sys.exit(0 if status == "success" else 1)


def cmd_status() -> None:
    """Show recent pipeline results."""
    pipelines = _api("GET", f"/projects/{PROJECT_ID}/pipelines?per_page=20")

    if not pipelines:
        print("No pipelines found.")
        return

    print(f"{BOLD}Recent CCA test pipelines:{RESET}\n")
    print(f"  {'ID':>5s}  {'STATUS':6s}  {'TEST':35s}  {'DURATION':>8s}  {'WHEN'}")
    print(f"  {'─' * 75}")

    for p in pipelines:
        pid = p["id"]
        status = _status_icon(p["status"])

        # Get the RUN_TEST variable from pipeline variables
        try:
            pvars = _api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/variables")
            run_test = ""
            for v in pvars:
                if v["key"] == "RUN_TEST":
                    run_test = v["value"]
                    break
        except Exception:
            run_test = "?"

        # Duration from jobs
        jobs = _api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/jobs?per_page=50")
        total_dur = sum(j.get("duration") or 0 for j in jobs)
        dur_str = f"{total_dur:.0f}s" if total_dur > 0 else "-"

        # Time ago
        created = p.get("created_at", "")
        time_str = created[:16].replace("T", " ") if created else ""

        print(f"  {pid:>5d}  {status}  {run_test:35s}  {dur_str:>8s}  {time_str}")

    print(f"\n  Pipeline URL: {GITLAB_URL}/root/cca-tests/-/pipelines")
    print(f"  Phoenix URL:  {PHOENIX_URL}")


def cmd_logs(test_name: str) -> None:
    """Show logs from the last run of a specific test."""
    # Find the most recent pipeline that ran this test
    pipelines = _api("GET", f"/projects/{PROJECT_ID}/pipelines?per_page=20")

    for p in pipelines:
        pid = p["id"]
        try:
            pvars = _api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/variables")
            run_test = ""
            for v in pvars:
                if v["key"] == "RUN_TEST":
                    run_test = v["value"]
                    break
            if run_test != test_name:
                continue
        except Exception:
            continue

        # Found the pipeline — get the test job
        jobs = _api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}/jobs?per_page=50")
        job_name = f"test-{test_name}"
        target_job = None
        for j in jobs:
            if j["name"] == job_name or (j["stage"] == "test" and test_name in j["name"]):
                target_job = j
                break

        if not target_job:
            # Show any test-stage job
            test_jobs = [j for j in jobs if j["stage"] == "test"]
            if test_jobs:
                target_job = test_jobs[0]

        if target_job:
            print(f"{BOLD}Logs: {target_job['name']} (pipeline {pid}, {target_job['status']}){RESET}\n")
            _show_job_log(target_job["id"])
            return
        else:
            print(f"No test job found in pipeline {pid}")
            return

    print(f"{RED}No pipeline found for test: {test_name}{RESET}")


def cmd_retry(pipeline_id: str) -> None:
    """Retry a failed pipeline."""
    pid = int(pipeline_id)
    result = _api("POST", f"/projects/{PROJECT_ID}/pipelines/{pid}/retry")
    print(f"Retried pipeline {pid}: {result.get('web_url', '')}")
    print("Waiting for completion...")
    # Re-poll
    while True:
        p = _api("GET", f"/projects/{PROJECT_ID}/pipelines/{pid}")
        if p["status"] in ("success", "failed", "canceled"):
            print(f"Result: {_status_icon(p['status'])}  {p['status']}")
            break
        time.sleep(5)


def cmd_cancel(pipeline_id: str) -> None:
    """Cancel a running pipeline."""
    pid = int(pipeline_id)
    result = _api("POST", f"/projects/{PROJECT_ID}/pipelines/{pid}/cancel")
    print(f"Canceled pipeline {pid}: {result.get('status', '')}")


def cmd_list() -> None:
    """List all available test names."""
    print(f"{BOLD}Available CCA tests:{RESET}\n")
    for group, tests in TESTS.items():
        print(f"  {CYAN}{group}:{RESET}")
        for t in tests:
            print(f"    {t}")
    print(f"\n  {CYAN}Groups:{RESET}")
    for g in GROUPS:
        print(f"    {g}")
    print(f"\n  {CYAN}Special:{RESET}")
    print(f"    build                (rebuild test Docker image)")
    print(f"\n{DIM}Usage: make test NAME=<test-name>{RESET}")


def _show_job_log(job_id: int, tail: Optional[int] = None) -> None:
    """Print job log (full or last N lines)."""
    url = f"{GITLAB_API}/projects/{PROJECT_ID}/jobs/{job_id}/trace"
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": TOKEN})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        log_text = resp.read().decode(errors="replace")
        if tail:
            lines = log_text.splitlines()
            lines = lines[-tail:]
            log_text = "\n".join(lines)
        print(log_text)
    except Exception as e:
        print(f"{RED}Failed to fetch log: {e}{RESET}")


# ── Main ──

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "run":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} run <test-name>")
            sys.exit(1)
        cmd_run(sys.argv[2])

    elif cmd == "status":
        cmd_status()

    elif cmd == "logs":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} logs <test-name>")
            sys.exit(1)
        cmd_logs(sys.argv[2])

    elif cmd == "retry":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} retry <pipeline-id>")
            sys.exit(1)
        cmd_retry(sys.argv[2])

    elif cmd == "cancel":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} cancel <pipeline-id>")
            sys.exit(1)
        cmd_cancel(sys.argv[2])

    elif cmd == "list":
        cmd_list()

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
