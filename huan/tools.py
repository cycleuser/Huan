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
                    "recursive": {
                        "type": "boolean",
                        "description": "Recursively crawl entire site (default: single page only).",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "huan_update_sites",
            "description": (
                "Incrementally update one or more configured websites. Only "
                "content not already saved locally is downloaded. Requires a "
                "sites config that maps each site to its URL, local save path "
                "and adapter type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sites": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Site keys to update (omit for all configured sites).",
                    },
                    "config_path": {
                        "type": "string",
                        "description": "Path to sites.json config (default: ~/.config/huan/sites.json).",
                    },
                    "proxy": {
                        "type": "string",
                        "description": "Override proxy for this run.",
                    },
                    "min_delay": {
                        "type": "number",
                        "description": "Minimum delay between requests in seconds.",
                        "default": 2.0,
                    },
                    "max_delay": {
                        "type": "number",
                        "description": "Maximum delay between requests in seconds.",
                        "default": 6.0,
                    },
                },
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

    if name == "huan_update_sites":
        from .api import update_sites

        result = update_sites(**arguments)
        return result.to_dict()

    raise ValueError(f"Unknown tool: {name}")
