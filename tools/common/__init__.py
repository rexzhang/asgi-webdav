"""Shared developer-tool infrastructure for ASGI-WebDAV (not part of the
distributed package). Only stdlib, click and python-dotenv may be imported
here — nothing from tools.perf / tools.litmus, and nothing from asgi_webdav.
"""

from tools.common.error import ToolError

__all__ = ["ToolError"]
