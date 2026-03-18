#!/usr/bin/env python3
"""Workspace-Sync: Clone/pull repos defined in config.toml.

Reads [[workspace.repos]] from config.toml, resolves credentials,
clones missing repos, periodically pulls source repos, and triggers
CCA re-index when changes are detected.

Environment variables:
    CCA_CONFIG_PATH  — Path to config.toml (default: /etc/cca/config.toml)
    CCA_URL          — CCA server URL (default: http://localhost:8500)
    GITLAB_PASS, GITHUB_TOKEN, etc. — Secrets referenced by ${VAR} in credentials
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import tomllib
import urllib.request
from typing import Any

CONFIG_PATH = os.environ.get("CCA_CONFIG_PATH", "/etc/cca/config.toml")
WORKSPACE = "/workspace"
CCA_URL = os.environ.get("CCA_URL", "http://localhost:8500")

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def resolve_env_refs(value: str) -> str:
    """Replace ``${VAR}`` references with environment variable values."""
    def _replace(m: re.Match) -> str:
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            print(f"WARN: env var ${{{var}}} not set, using empty string")
            return ""
        return val
    return _ENV_VAR_RE.sub(_replace, value)


def git(*args: str, cwd: str | None = None) -> tuple[bool, str]:
    """Run a git command. Returns (success, stdout)."""
    r = subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 and r.stderr.strip():
        print(f"  git {' '.join(args)}: {r.stderr.strip()}")
    return r.returncode == 0, r.stdout.strip()


def build_clone_url(repo: dict, credentials: dict[str, dict]) -> str | None:
    """Build an authenticated clone URL from repo + credential config."""
    cred_id = repo.get("credential", "")
    cred = credentials.get(cred_id)
    if not cred:
        print(f"  ERROR: credential '{cred_id}' not found for repo '{repo['name']}'")
        return None

    url = cred["url"].rstrip("/")
    user = cred.get("user", "")
    token = resolve_env_refs(cred.get("token", ""))

    # Strip protocol, inject user:token
    if url.startswith("https://"):
        host = url[8:]
        return f"https://{user}:{token}@{host}/{repo['repo']}.git"
    elif url.startswith("http://"):
        host = url[7:]
        return f"http://{user}:{token}@{host}/{repo['repo']}.git"
    else:
        # SSH or other — return as-is with repo path
        return f"{url}/{repo['repo']}.git"


def clone_repo(repo: dict, credentials: dict[str, dict]) -> bool:
    """Clone a repo if not already present. Returns True if newly cloned."""
    name = repo["name"]
    branch = repo.get("branch", "main")
    dest = os.path.join(WORKSPACE, name)

    if os.path.isdir(os.path.join(dest, ".git")):
        # Already cloned — check if branch matches
        ok, current = git("rev-parse", "--abbrev-ref", "HEAD", cwd=dest)
        if ok and current != branch:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[{ts}] [{name}] Switching branch: {current} → {branch}")
            git("fetch", "origin", cwd=dest)
            ok, _ = git("checkout", branch, cwd=dest)
            if not ok:
                # Branch might not exist locally yet
                git("checkout", "-b", branch, f"origin/{branch}", cwd=dest)
        return False

    clone_url = build_clone_url(repo, credentials)
    if not clone_url:
        return False

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] [{name}] Cloning (branch={branch})...")
    ok, _ = git("clone", "--branch", branch, clone_url, dest)
    if not ok:
        print(f"[{ts}] [{name}] WARN: clone failed (repo may not exist yet)")
        return False

    # Migration repos: configure git user so CCA can commit/push
    if repo.get("type") == "migration":
        git("config", "user.name", "cca", cwd=dest)
        git("config", "user.email", "cca@local", cwd=dest)

    print(f"[{ts}] [{name}] Cloned successfully")
    return True


def pull_source_repos(repos: list[dict]) -> bool:
    """Pull all source repos. Returns True if any changed."""
    changed = False
    for repo in repos:
        if repo.get("type") != "source":
            continue
        name = repo["name"]
        dest = os.path.join(WORKSPACE, name)
        if not os.path.isdir(os.path.join(dest, ".git")):
            continue

        ok, before = git("rev-parse", "HEAD", cwd=dest)
        git("pull", "--ff-only", cwd=dest)
        ok, after = git("rev-parse", "HEAD", cwd=dest)

        if before != after:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[{ts}] [{name}] Updated: {before[:8]} → {after[:8]}")
            changed = True

    return changed


def trigger_reindex() -> None:
    """POST to CCA /workspace/reindex."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        req = urllib.request.Request(
            f"{CCA_URL}/workspace/reindex",
            data=json.dumps({"force": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=60)
        print(f"[{ts}] Re-index triggered")
    except Exception as e:
        print(f"[{ts}] WARN: re-index trigger failed: {e}")


def main() -> None:
    os.makedirs(WORKSPACE, exist_ok=True)

    prev_repo_names: set[str] = set()
    first_cycle = True

    while True:
        # Re-read config every cycle — picks up added/removed repos,
        # branch changes, and interval changes without restart.
        try:
            cfg = load_config()
        except FileNotFoundError:
            if first_cycle:
                print(f"ERROR: Config file not found: {CONFIG_PATH}")
                sys.exit(1)
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[{ts}] WARN: Config file missing, retrying next cycle")
            time.sleep(60)
            continue
        except Exception as e:
            if first_cycle:
                print(f"ERROR: Failed to parse config: {e}")
                sys.exit(1)
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[{ts}] WARN: Config parse error: {e}")
            time.sleep(60)
            continue

        ws = cfg.get("workspace", {})
        repos = ws.get("repos", [])
        interval = ws.get("sync_interval", 60)
        credentials = {c["id"]: c for c in ws.get("credentials", [])}

        if not repos and first_cycle:
            print("ERROR: No repos defined in config.toml [[workspace.repos]]")
            sys.exit(1)

        current_names = {r["name"] for r in repos}
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Detect config changes (skip first cycle — everything is "added")
        if not first_cycle and prev_repo_names:
            added = current_names - prev_repo_names
            removed = prev_repo_names - current_names
            if added:
                print(f"[{ts}] Config change: repo(s) added: {sorted(added)}")
            if removed:
                print(f"[{ts}] Config change: repo(s) removed: {sorted(removed)}")
                print(f"  (CCA workspace monitor will clean Qdrant/Memgraph)")

        # Clone new repos + ensure correct branches on existing
        newly_cloned = False
        for repo in repos:
            if clone_repo(repo, credentials):
                newly_cloned = True

        # Pull source repos
        changed = pull_source_repos(repos)

        # Trigger reindex if anything changed
        if newly_cloned or changed:
            trigger_reindex()

        # Log status on first cycle
        if first_cycle:
            source_names = sorted(r["name"] for r in repos if r.get("type") == "source")
            migration_names = sorted(r["name"] for r in repos if r.get("type") == "migration")
            print(f"[{ts}] Sync started (interval={interval}s)")
            print(f"  Source repos (auto-pull): {source_names}")
            print(f"  Migration repos (CCA-managed): {migration_names}")
            first_cycle = False

        prev_repo_names = current_names
        time.sleep(interval)


if __name__ == "__main__":
    main()
