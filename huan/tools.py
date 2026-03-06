"""
Huan - OpenAI function-calling tool definitions.

Provides TOOLS list and dispatch() for LLM agent integration.
"""

from __future__ import annotations

import json
from typing import Any

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "huan_archive_site",
            "description": (
                "Archive a website by converting its pages to local Markdown "
                "files, preserving the site's URL structure as a folder hierarchy. "
                "Supports multiple fetcher backends including browser-based for "
                "JavaScript-heavy sites."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Starting URL to archive.",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Output directory (default: domain name).",
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "Maximum pages to archive (null = no limit).",
                    },
                    "delay": {
                        "type": "number",
                        "description": "Seconds between requests.",
                        "default": 0.5,
                    },
                    "prefix": {
                        "type": "string",
                        "description": "Only archive URLs whose path starts with this prefix.",
                    },
                    "extractor": {
                        "type": "string",
                        "enum": ["readability", "heuristic", "full"],
                        "description": "Content extraction strategy.",
                        "default": "readability",
                    },
                    "fetcher": {
                        "type": "string",
                        "enum": ["requests", "curl", "browser", "playwright"],
                        "description": "HTTP fetcher backend.",
                        "default": "requests",
                    },
                    "proxy": {
                        "type": "string",
                        "description": "HTTP/HTTPS proxy URL.",
                    },
                    "download_images": {
                        "type": "boolean",
                        "description": "Download and localise images.",
                        "default": True,
                    },
                    "save_html": {
                        "type": "boolean",
                        "description": "Also save original HTML files.",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        },
    },
]


def dispatch(name: str, arguments: dict[str, Any] | str) -> dict:
    """Dispatch a tool call to the appropriate API function."""
    if isinstance(arguments, str):
        arguments = json.loads(arguments)

    if name == "huan_archive_site":
        from .api import archive_site

        result = archive_site(**arguments)
        return result.to_dict()

    raise ValueError(f"Unknown tool: {name}")
