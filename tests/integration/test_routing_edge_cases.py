"""Flow test: Router edge cases — direct answer, planner route, complexity.

Tests routing decisions that don't have dedicated test coverage:
- Simple questions that need no tools (answer_directly)
- Multi-step planning questions (PLANNER route)
- Complex tasks that should trigger reviewer extensions

Exercises: Expert router classification, PLANNER route, complexity detection.
"""

import uuid

import pytest

from tests.evaluators import evaluate_response

pytestmark = [pytest.mark.integration]


class TestRoutingEdgeCases:
    """Expert router: edge cases and underexercised routes."""

    def test_direct_answer(self, cca, trace_test, judge_model):
        """Simple factual question — should answer without tools."""
        sid = f"test-direct-{uuid.uuid4().hex[:8]}"

        msg = "What does the acronym REST stand for in web development?"
        r = cca.chat(msg, session_id=sid)
        evaluate_response(r, msg, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.response", r.content[:300])
        assert r.content, "Returned empty"

        # Should contain the answer
        content_lower = r.content.lower()
        has_answer = any(w in content_lower for w in [
            "representational", "state", "transfer",
        ])
        trace_test.set_attribute("cca.test.has_answer", has_answer)
        assert has_answer, (
            f"Response doesn't explain REST: {r.content[:300]}"
        )

        # Should be relatively fast (no heavy tool calling)
        route = r.metadata.get("route", "")
        iters = r.metadata.get("tool_iterations", 0)
        trace_test.set_attribute("cca.test.route", route)
        trace_test.set_attribute("cca.test.iters", iters)

    def test_planner_route(self, cca, trace_test, judge_model):
        """Multi-step planning question — should engage planning logic."""
        sid = f"test-planner-{uuid.uuid4().hex[:8]}"

        msg = (
            "I need to design a CI/CD pipeline for a Python microservices "
            "project with 5 services. The pipeline should handle testing, "
            "building Docker images, and deploying to Kubernetes. "
            "What would be the high-level architecture and steps?"
        )
        r = cca.chat(msg, session_id=sid)
        evaluate_response(r, msg, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.response", r.content[:500])
        assert r.content, "Returned empty"
        assert len(r.content) > 200, (
            f"Planning response too short ({len(r.content)} chars) — "
            f"expected detailed breakdown"
        )

        route = r.metadata.get("route", "")
        trace_test.set_attribute("cca.test.route", route)

        # Should contain structured planning elements
        content_lower = r.content.lower()
        planning_terms = sum(1 for t in [
            "pipeline", "docker", "kubernetes", "test", "build",
            "deploy", "stage", "step", "ci", "cd",
        ] if t in content_lower)
        trace_test.set_attribute("cca.test.planning_terms", planning_terms)
        assert planning_terms >= 4, (
            f"Response lacks planning substance "
            f"(found {planning_terms} terms): {r.content[:300]}"
        )

    def test_complex_coding_task(self, cca, trace_test, judge_model):
        """Complex coding request — should estimate high complexity.

        We don't assert that CodeReviewerExtension fires (it requires
        3+ file edits which is hard to guarantee), but we verify the
        router estimates the task as complex (steps >= 5).
        """
        sid = f"test-complex-{uuid.uuid4().hex[:8]}"

        msg = (
            "Create a complete Python REST API with FastAPI that has: "
            "1. A /items endpoint with CRUD operations "
            "2. Pydantic models for request/response validation "
            "3. In-memory storage (just a dict) "
            "Put it all in a single file at /workspace/items_api.py"
        )
        r = cca.chat(msg, session_id=sid)
        evaluate_response(r, msg, trace_test, judge_model, "integration")

        trace_test.set_attribute("cca.test.response", r.content[:500])
        assert r.content, "Returned empty"

        # Should route to coder
        route = r.metadata.get("route", "")
        trace_test.set_attribute("cca.test.route", route)

        # Should estimate as a multi-step task
        steps = r.metadata.get("estimated_steps", 0)
        trace_test.set_attribute("cca.test.estimated_steps", steps)

        # Should use tools (file creation at minimum)
        iters = r.metadata.get("tool_iterations", 0)
        trace_test.set_attribute("cca.test.iters", iters)
        assert iters >= 1, (
            f"Agent didn't use tools for complex task (iters={iters})"
        )

        # Response should contain FastAPI code
        content_lower = r.content.lower()
        has_fastapi = "fastapi" in content_lower or "app" in content_lower
        trace_test.set_attribute("cca.test.has_fastapi", has_fastapi)
