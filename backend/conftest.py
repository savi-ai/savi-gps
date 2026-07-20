"""Root conftest.py — sets up environment for all backend tests.

Sets a dummy ANTHROPIC_API_KEY so that modules which instantiate LLM clients
at import time (e.g. sop_agent) don't crash during test collection.
Also stubs the `anthropic` package if it's not installed.
"""
import os
import sys
from unittest.mock import MagicMock

# Set dummy API key BEFORE any app modules are imported
os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy-key")

# Stub the anthropic SDK if not installed
if "anthropic" not in sys.modules:
    sys.modules["anthropic"] = MagicMock()
