"""
huan - Web Page to Markdown Converter

A command-line tool that converts web pages to Markdown files,
preserving the site's URL structure as a local folder hierarchy.
"""

__version__ = "0.2.1"
__author__ = "huan contributors"

from .core import SiteCrawler, main
from .api import ToolResult, archive_site

__all__ = ["SiteCrawler", "main", "__version__", "ToolResult", "archive_site"]
