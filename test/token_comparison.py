#!/usr/bin/env python3
"""
Token Comparison: Raw HTML vs. Huan-converted Markdown

Fetches https://geopytool.com/installation-expert.html, converts it to
Markdown using Huan's pipeline, then compares token counts, character
counts, and size metrics between the raw HTML and the clean Markdown.

Tokenization methods used:
  1. Whitespace split (simple word count)
  2. cl100k_base (GPT-4 / GPT-3.5 tokenizer via tiktoken)
  3. Character count
  4. Byte size (UTF-8)

Usage:
    python test/token_comparison.py

Requirements:
    pip install tiktoken requests beautifulsoup4 html2text
"""

import os
import sys
import textwrap

# Ensure the project root is on sys.path so we can import huan
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import requests
from bs4 import BeautifulSoup
import html2text

# ── Try importing tiktoken for accurate GPT tokenization ────────────────
try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    print("[WARN] tiktoken not installed. Install with: pip install tiktoken")
    print("       Falling back to whitespace-based estimation only.\n")

# ── Try importing huan's preprocessing pipeline ─────────────────────────
try:
    from huan.core import (
        preprocess_math,
        SiteCrawler,
    )
    HAS_HUAN = True
except ImportError:
    HAS_HUAN = False
    print("[WARN] huan package not importable. Using basic html2text only.\n")


TARGET_URL = "https://geopytool.com/installation-expert.html"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "test", "output")


def fetch_html(url: str) -> str:
    """Fetch raw HTML from URL."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def convert_to_markdown(html: str, url: str) -> str:
    """Convert HTML to Markdown using Huan's pipeline (or basic html2text)."""
    soup = BeautifulSoup(html, "html.parser")

    # Strip boilerplate
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    if HAS_HUAN:
        # Use Huan's preprocessing pipeline
        preprocess_math(soup)
        SiteCrawler._preprocess_tables(soup)
        SiteCrawler._preprocess_code_blocks(soup)

        # Try readability extraction
        try:
            from readability import Document as ReadabilityDocument
            doc = ReadabilityDocument(html)
            readable_html = doc.summary()
            content_soup = BeautifulSoup(readable_html, "html.parser")
            preprocess_math(content_soup)
            SiteCrawler._preprocess_tables(content_soup)
            SiteCrawler._preprocess_code_blocks(content_soup)
            for tag in content_soup.find_all(["script", "style", "noscript"]):
                tag.decompose()
            soup = content_soup
        except ImportError:
            # Fallback to heuristic extraction
            soup = SiteCrawler._heuristic_extract(soup)

    # Convert with html2text
    h2t = html2text.HTML2Text()
    h2t.body_width = 0
    h2t.unicode_snob = True
    h2t.ignore_links = False
    h2t.ignore_images = False
    h2t.ignore_tables = False
    h2t.protect_links = True
    h2t.wrap_links = False
    h2t.single_line_break = False

    md_text = h2t.handle(str(soup)).strip()

    # Clean up html2text artifacts
    import re
    md_text = re.sub(r'\]\(<([^>]+)>\)', r'](\1)', md_text)
    md_text = re.sub(r'```\n__CODELANG_(\w+)__\n', r'```\1\n', md_text)

    return md_text


def strip_html_to_plaintext(html: str) -> str:
    """Strip all HTML tags, return raw visible text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def count_tokens_tiktoken(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count tokens using tiktoken (GPT-4 tokenizer)."""
    enc = tiktoken.get_encoding(encoding_name)
    return len(enc.encode(text))


def count_whitespace_words(text: str) -> int:
    """Simple whitespace-based word count."""
    return len(text.split())


def bytes_utf8(text: str) -> int:
    """UTF-8 byte size."""
    return len(text.encode("utf-8"))


def format_number(n: int) -> str:
    """Format number with thousands separator."""
    return f"{n:,}"


def format_ratio(a: int, b: int) -> str:
    """Format compression ratio a:b."""
    if b == 0:
        return "N/A"
    ratio = a / b
    return f"{ratio:.1f}x"


def main():
    print("=" * 70)
    print("  Token Comparison: Raw HTML vs. Huan Markdown Conversion")
    print(f"  Target: {TARGET_URL}")
    print("=" * 70)

    # ── Step 1: Fetch HTML ────────────────────────────────────────────
    print("\n[1] Fetching HTML...")
    raw_html = fetch_html(TARGET_URL)
    print(f"    Fetched {len(raw_html):,} characters of HTML.")

    # ── Step 2: Convert to Markdown ───────────────────────────────────
    print("[2] Converting to Markdown...")
    markdown = convert_to_markdown(raw_html, TARGET_URL)
    print(f"    Produced {len(markdown):,} characters of Markdown.")

    # ── Step 3: Also get plaintext for comparison ─────────────────────
    plaintext = strip_html_to_plaintext(raw_html)

    # ── Step 4: Save outputs ──────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    html_path = os.path.join(OUTPUT_DIR, "page_raw.html")
    md_path = os.path.join(OUTPUT_DIR, "page_converted.md")
    txt_path = os.path.join(OUTPUT_DIR, "page_plaintext.txt")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(raw_html)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(plaintext)

    print(f"    Saved to: {OUTPUT_DIR}/")

    # ── Step 5: Compute metrics ───────────────────────────────────────
    print("[3] Computing metrics...\n")

    metrics = {
        "Raw HTML": raw_html,
        "Plaintext (tags stripped)": plaintext,
        "Markdown (Huan)": markdown,
    }

    results = {}
    for label, text in metrics.items():
        row = {
            "chars": len(text),
            "bytes": bytes_utf8(text),
            "words": count_whitespace_words(text),
        }
        if HAS_TIKTOKEN:
            row["tokens_cl100k"] = count_tokens_tiktoken(text)
        else:
            row["tokens_cl100k"] = int(row["words"] * 1.3)  # Rough estimate
        results[label] = row

    # ── Step 6: Print comparison table ────────────────────────────────
    html_r = results["Raw HTML"]
    md_r = results["Markdown (Huan)"]
    txt_r = results["Plaintext (tags stripped)"]

    token_method = "cl100k_base (tiktoken)" if HAS_TIKTOKEN else "estimated (words * 1.3)"

    print("-" * 70)
    print(f"  {'Metric':<30} {'Raw HTML':>14} {'Markdown':>14} {'Ratio':>8}")
    print("-" * 70)
    print(f"  {'Characters':<30} {format_number(html_r['chars']):>14} {format_number(md_r['chars']):>14} {format_ratio(html_r['chars'], md_r['chars']):>8}")
    print(f"  {'UTF-8 Bytes':<30} {format_number(html_r['bytes']):>14} {format_number(md_r['bytes']):>14} {format_ratio(html_r['bytes'], md_r['bytes']):>8}")
    print(f"  {'Whitespace Words':<30} {format_number(html_r['words']):>14} {format_number(md_r['words']):>14} {format_ratio(html_r['words'], md_r['words']):>8}")
    tokens_label = f"Tokens ({token_method})"
    print(f"  {tokens_label:<30} {format_number(html_r['tokens_cl100k']):>14} {format_number(md_r['tokens_cl100k']):>14} {format_ratio(html_r['tokens_cl100k'], md_r['tokens_cl100k']):>8}")
    print("-" * 70)

    print(f"\n  Plaintext reference (HTML tags stripped, no structure):")
    print(f"    Characters: {format_number(txt_r['chars']):>14}")
    print(f"    Tokens:     {format_number(txt_r['tokens_cl100k']):>14}")

    # ── Step 7: Token savings summary ─────────────────────────────────
    html_tokens = html_r["tokens_cl100k"]
    md_tokens = md_r["tokens_cl100k"]
    saved_tokens = html_tokens - md_tokens
    saved_pct = (saved_tokens / html_tokens * 100) if html_tokens > 0 else 0

    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Raw HTML tokens:      {format_number(html_tokens)}")
    print(f"  Markdown tokens:      {format_number(md_tokens)}")
    print(f"  Tokens saved:         {format_number(saved_tokens)} ({saved_pct:.1f}%)")
    print(f"  Compression ratio:    {format_ratio(html_tokens, md_tokens)}")
    print(f"  Token counting:       {token_method}")
    print(f"{'=' * 70}")

    # ── Step 8: Generate Markdown comparison table ────────────────────
    table_path = os.path.join(OUTPUT_DIR, "comparison_table.md")
    table_md = textwrap.dedent(f"""\
    # Token Comparison: Raw HTML vs. Huan Markdown

    **Source URL**: {TARGET_URL}

    **Token counting method**: {token_method}

    ## Detailed Comparison

    | Metric | Raw HTML | Markdown (Huan) | Compression Ratio |
    |--------|----------|-----------------|-------------------|
    | Characters | {format_number(html_r['chars'])} | {format_number(md_r['chars'])} | {format_ratio(html_r['chars'], md_r['chars'])} |
    | UTF-8 Bytes | {format_number(html_r['bytes'])} | {format_number(md_r['bytes'])} | {format_ratio(html_r['bytes'], md_r['bytes'])} |
    | Whitespace Words | {format_number(html_r['words'])} | {format_number(md_r['words'])} | {format_ratio(html_r['words'], md_r['words'])} |
    | Tokens | {format_number(html_r['tokens_cl100k'])} | {format_number(md_r['tokens_cl100k'])} | {format_ratio(html_r['tokens_cl100k'], md_r['tokens_cl100k'])} |

    ## Plaintext Reference (tags stripped, no structure preserved)

    | Metric | Value |
    |--------|-------|
    | Characters | {format_number(txt_r['chars'])} |
    | Tokens | {format_number(txt_r['tokens_cl100k'])} |

    ## Summary

    - **Tokens saved**: {format_number(saved_tokens)} ({saved_pct:.1f}% reduction)
    - **Compression ratio**: {format_ratio(html_tokens, md_tokens)} (HTML tokens / Markdown tokens)
    - Markdown conversion removes structural noise (nav, scripts, ads, layout markup) while preserving content structure (headings, lists, code blocks, emphasis).
    - The resulting Markdown is directly suitable for RAG chunking, LLM context injection, and knowledge base indexing.
    """)

    with open(table_path, "w", encoding="utf-8") as f:
        f.write(table_md)
    print(f"\n  Comparison table saved to: {table_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
