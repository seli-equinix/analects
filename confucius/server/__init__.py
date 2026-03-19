# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""Analects HTTP Server — Agent-as-a-Model Endpoint.

Provides an OpenAI-compatible /v1/chat/completions API that internally
runs CCA's full agent loop (AnthropicLLMOrchestrator + extensions).
"""

__version__ = "0.1.0"
