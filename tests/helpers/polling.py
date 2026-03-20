"""Polling helpers for async CCA subsystems.

NoteObserver and FactExtractor are fire-and-forget async tasks.
Instead of fixed sleeps, these helpers poll with backend health
checks — if a backend is down, they fail fast with a clear error
instead of waiting the full timeout.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.cca_client import CCAClient


def wait_for_notes(
    cca: CCAClient,
    query: str,
    user_id: str | None = None,
    max_wait: int = 60,
    interval: int = 3,
) -> list[dict]:
    """Poll ``GET /v1/notes/search`` until results appear or timeout.

    Checks backend health on each poll — if vLLM or CCA goes down,
    fails immediately with a descriptive error instead of waiting
    the full max_wait.

    Args:
        cca: CCAClient instance.
        query: Search query for notes.
        user_id: Optional user filter.
        max_wait: Total seconds to wait before giving up.
        interval: Seconds between polls.

    Returns:
        List of note dicts, or empty list on timeout.

    Raises:
        RuntimeError: If a backend is unhealthy during polling.
    """
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval

        # Check backends every 4th poll (~12s) to avoid overhead
        if elapsed % (interval * 4) == 0:
            issues = cca.check_backends()
            if issues:
                raise RuntimeError(
                    f"Backend unhealthy during note polling "
                    f"(waited {elapsed}s): {issues}"
                )

        notes = cca.search_notes(query, user_id=user_id)
        if notes:
            return notes

    return []
