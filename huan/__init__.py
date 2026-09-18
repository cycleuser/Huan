"""Huan - convert web pages to Markdown; optionally track whole sites."""
from __future__ import annotations

__version__ = "1.2.1"

__all__ = [
    "__version__",
    "ToolResult",
    "archive_site",
    "update_sites",
    "SiteCrawler",
    "SinglePageArchiver",
]


def __getattr__(name):
    """Lazily expose the public API without importing heavy deps eagerly."""
    if name == "ToolResult" or name == "archive_site" or name == "update_sites":
        from huan import api
        return getattr(api, name)
    if name in ("SiteCrawler", "SinglePageArchiver"):
        from huan import core
        return getattr(core, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
