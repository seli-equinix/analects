"""Flow test: Infrastructure route — Docker and service management.

Journey: ask about running containers → ask about service health →
verify the agent uses bash commands with the expanded INFRA allowlist.

Exercises: bash_tool (docker, curl, systemctl), INFRASTRUCTURE route.
"""

import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.integration]


class TestInfraRoute:
    """INFRASTRUCTURE route: Docker queries and service health checks."""

    def test_infra_docker_query(self, cca, trace_test, judge_model):
        """Ask about running Docker containers — should route to INFRA."""
        tracker = cca.tracker()
        sid = f"test-infra-docker-{uuid.uuid4().hex[:8]}"
        tracker.track_session(sid)

        try:
            msg = (
                "What Docker containers are running on this system right now? "
                "Give me a quick summary of their names and status."
            )
            r = cca.chat(msg, session_id=sid)
            evaluate_response(r, msg, trace_test, judge_model, "integration")

            trace_test.set_attribute("cca.test.response", r.content[:500])
            assert r.content, "Returned empty"

            # Should have used tools (bash with docker)
            iters = r.metadata.get("tool_iterations", 0)
            trace_test.set_attribute("cca.test.iters", iters)
            assert iters >= 1, (
                f"Agent didn't use tools (iters={iters}). "
                f"Response: {r.content[:200]}"
            )

            # Should route to infrastructure (or coder — both have docker)
            route = r.metadata.get("route", "")
            trace_test.set_attribute("cca.test.route", route)

            # Response should mention containers or Docker output
            content_lower = r.content.lower()
            has_docker_info = any(w in content_lower for w in [
                "container", "running", "image", "docker", "status",
                "up ", "exited", "healthy",
            ])
            trace_test.set_attribute("cca.test.has_docker_info", has_docker_info)
            assert has_docker_info, (
                f"Response doesn't contain Docker info: {r.content[:300]}"
            )

        finally:
            tracker.cleanup()

    def test_infra_service_check(self, cca, trace_test, judge_model):
        """Ask about a service's health — should use curl or systemctl."""
        tracker = cca.tracker()
        sid = f"test-infra-health-{uuid.uuid4().hex[:8]}"
        tracker.track_session(sid)

        try:
            msg = (
                "Check if the Redis service on this machine is running "
                "and responding. What port is it on?"
            )
            r = cca.chat(msg, session_id=sid)
            evaluate_response(r, msg, trace_test, judge_model, "integration")

            trace_test.set_attribute("cca.test.response", r.content[:500])
            assert r.content, "Returned empty"

            iters = r.metadata.get("tool_iterations", 0)
            trace_test.set_attribute("cca.test.iters", iters)
            assert iters >= 1, (
                f"Agent didn't use tools for service check (iters={iters})"
            )

            # Should mention Redis, port, or status
            content_lower = r.content.lower()
            has_service_info = any(w in content_lower for w in [
                "redis", "6379", "running", "pong", "connected",
                "port", "service", "active",
            ])
            trace_test.set_attribute("cca.test.has_service_info", has_service_info)
            assert has_service_info, (
                f"Response doesn't contain service info: {r.content[:300]}"
            )

        finally:
            tracker.cleanup()
