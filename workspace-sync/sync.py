#!/usr/bin/env python3
"""Workspace-Sync: Clone/pull repos defined in config.toml.

Reads [[workspace.repos]] from config.toml, resolves credentials,
clones missing repos, periodically pulls source repos, and triggers
CCA re-index when changes are detected.

Re-reads config.toml every sync cycle so adding/removing repos or
changing branches takes effect without restarting the container.

Environment variables:
    CCA_CONFIG_PATH  — Path to config.toml (default: /etc/cca/config.toml)
    CCA_URL          — CCA server URL (default: http://localhost:8500)
    GITLAB_PASS, GITHUB_TOKEN, etc. — Secrets referenced by ${VAR} in credentials
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import tomllib
import urllib.request
from typing import Any

# ── Logging ──
# Structured logging matching CCA's format: timestamp | LEVEL | name | message
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("workspace-sync")

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
            log.warning("env var ${%s} not set, using empty string", var)
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
        log.error("git %s failed: %s", " ".join(args), r.stderr.strip())
    return r.returncode == 0, r.stdout.strip()


def build_clone_url(repo: dict, credentials: dict[str, dict]) -> str | None:
    """Build an authenticated clone URL from repo + credential config."""
    cred_id = repo.get("credential", "")
    cred = credentials.get(cred_id)
    if not cred:
        log.error(
            "[%s] credential '%s' not found — check [[workspace.credentials]] in config.toml",
            repo["name"], cred_id,
        )
        return None

    url = cred["url"].rstrip("/")
    user = cred.get("user", "")
    token = resolve_env_refs(cred.get("token", ""))

    if not token:
        log.warning(
            "[%s] credential '%s' resolved to empty token — clone may fail",
            repo["name"], cred_id,
        )

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
            log.info("[%s] Switching branch: %s → %s", name, current, branch)
            git("fetch", "origin", cwd=dest)
            ok, _ = git("checkout", branch, cwd=dest)
            if not ok:
                # Branch might not exist locally yet
                ok, _ = git("checkout", "-b", branch, f"origin/{branch}", cwd=dest)
                if not ok:
                    log.error(
                        "[%s] Failed to switch to branch '%s' — "
                        "branch may not exist on remote",
                        name, branch,
                    )
        return False

    clone_url = build_clone_url(repo, credentials)
    if not clone_url:
        return False

    log.info("[%s] Cloning (branch=%s, type=%s)...", name, branch, repo.get("type", "source"))
    ok, _ = git("clone", "--branch", branch, clone_url, dest)
    if not ok:
        log.error(
            "[%s] Clone failed — repo '%s' may not exist on server or branch '%s' is invalid",
            name, repo.get("repo", ""), branch,
        )
        return False

    # Migration repos: configure git user so CCA can commit/push
    if repo.get("type") == "migration":
        git("config", "user.name", "cca", cwd=dest)
        git("config", "user.email", "cca@local", cwd=dest)
        log.info("[%s] Cloned (migration mode — git user configured for CCA commits)", name)
    else:
        log.info("[%s] Cloned successfully", name)
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
            log.warning("[%s] Source repo not cloned yet, skipping pull", name)
            continue

        ok, before = git("rev-parse", "HEAD", cwd=dest)
        if not ok:
            log.error("[%s] Failed to get HEAD — git repo may be corrupt", name)
            continue

        ok, _ = git("pull", "--ff-only", cwd=dest)
        if not ok:
            log.error(
                "[%s] git pull --ff-only failed — may have local changes or "
                "upstream force-push. Manual intervention may be needed.",
                name,
            )
            continue

        ok, after = git("rev-parse", "HEAD", cwd=dest)
        if before != after:
            log.info("[%s] Updated: %s → %s", name, before[:8], after[:8])
            changed = True

    return changed


def trigger_reindex() -> None:
    """POST to CCA /workspace/reindex."""
    try:
        req = urllib.request.Request(
            f"{CCA_URL}/workspace/reindex",
            data=json.dumps({"force": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=60)
        log.info("Re-index triggered on Analects (%s)", CCA_URL)
    except urllib.error.URLError as e:
        log.error(
            "Re-index trigger failed — CCA may not be running at %s: %s",
            CCA_URL, e,
        )
    except Exception as e:
        log.error("Re-index trigger failed: %s", e)


def main() -> None:
    os.makedirs(WORKSPACE, exist_ok=True)
    log.info("Workspace-sync starting (config=%s, workspace=%s)", CONFIG_PATH, WORKSPACE)

    prev_repo_names: set[str] = set()
    first_cycle = True

    while True:
        # Re-read config every cycle — picks up added/removed repos,
        # branch changes, and interval changes without restart.
        try:
            cfg = load_config()
        except FileNotFoundError:
            if first_cycle:
                log.critical("Config file not found: %s — cannot start", CONFIG_PATH)
                sys.exit(1)
            log.warning("Config file missing (%s), retrying next cycle", CONFIG_PATH)
            time.sleep(60)
            continue
        except tomllib.TOMLDecodeError as e:
            if first_cycle:
                log.critical("Config file has invalid TOML syntax: %s", e)
                sys.exit(1)
            log.error("Config parse error (TOML syntax): %s — using previous config", e)
            time.sleep(60)
            continue
        except Exception as e:
            if first_cycle:
                log.critical("Failed to load config: %s", e)
                sys.exit(1)
            log.error("Config load error: %s — using previous config", e)
            time.sleep(60)
            continue

        ws = cfg.get("workspace", {})
        repos = ws.get("repos", [])
        interval = ws.get("sync_interval", 60)
        credentials = {c["id"]: c for c in ws.get("credentials", [])}

        if not repos:
            if first_cycle:
                log.critical(
                    "No repos defined in config.toml [[workspace.repos]] — "
                    "add at least one entry"
                )
                sys.exit(1)
            log.warning("No repos in config — all repos removed? Sleeping %ds", interval)
            prev_repo_names = set()
            time.sleep(interval)
            continue

        if not credentials:
            log.error(
                "No credentials defined in config.toml [[workspace.credentials]] — "
                "repos cannot be cloned without authentication"
            )

        current_names = {r["name"] for r in repos}

        # Validate each repo has required fields
        for repo in repos:
            if not repo.get("repo"):
                log.error("[%s] Missing 'repo' field (e.g. 'root/EVA')", repo.get("name", "?"))
            if not repo.get("credential"):
                log.error("[%s] Missing 'credential' field", repo.get("name", "?"))
            if repo.get("credential") and repo["credential"] not in credentials:
                log.error(
                    "[%s] credential '%s' not found in [[workspace.credentials]]",
                    repo.get("name", "?"), repo["credential"],
                )

        # Detect config changes (skip first cycle — everything is "added")
        if not first_cycle and prev_repo_names:
            added = current_names - prev_repo_names
            removed = prev_repo_names - current_names
            if added:
                log.info("Config change detected: repo(s) added: %s", sorted(added))
            if removed:
                log.info(
                    "Config change detected: repo(s) removed: %s "
                    "(CCA workspace monitor will clean Qdrant/Memgraph)",
                    sorted(removed),
                )

        # Clone new repos + ensure correct branches on existing
        newly_cloned = False
        for repo in repos:
            try:
                if clone_repo(repo, credentials):
                    newly_cloned = True
            except Exception as e:
                log.error("[%s] Unexpected error during clone: %s", repo.get("name", "?"), e)

        # Pull source repos
        changed = pull_source_repos(repos)

        # Trigger reindex if anything changed
        if newly_cloned or changed:
            trigger_reindex()

        # Log status on first cycle
        if first_cycle:
            source_names = sorted(r["name"] for r in repos if r.get("type") == "source")
            migration_names = sorted(r["name"] for r in repos if r.get("type") == "migration")
            log.info("Sync loop started (interval=%ds, %d repos)", interval, len(repos))
            log.info("  Source repos (auto-pull): %s", source_names)
            log.info("  Migration repos (CCA-managed): %s", migration_names)
            first_cycle = False

        prev_repo_names = current_names
        time.sleep(interval)


if __name__ == "__main__":
    main()
