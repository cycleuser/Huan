"""
huan - Web Page to Markdown Converter

A command-line tool that converts web pages to Markdown files,
preserving the site's URL structure as a local folder hierarchy.
"""

__version__ = "0.2.0"
__author__ = "huan contributors"

from .core import SiteCrawler, main

__all__ = ["SiteCrawler", "main", "__version__"]
