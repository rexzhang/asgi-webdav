"""The shared infrastructure-failure exception for the developer tools."""

from __future__ import annotations


class ToolError(Exception):
    """Infrastructure failure that maps to exit code 2."""
