"""Shared test configuration."""

import os

# Endpoint tests that mock the router/LLM still pass the API-key gate;
# a placeholder is enough because no real provider call is made in tests.
os.environ.setdefault("DEEPSEEK_API_KEY", "test-dummy-key")
