"""
HTML-based PDF generation pipeline.
Uses Playwright (headless Chromium) to render HTML to PDF with native
RTL, KaTeX math, Highlight.js code highlighting, and Mermaid diagrams.
"""

from .converter import render_html_to_pdf
from .prompt_builder import build_html_prompt, build_html_prompt_for_pdf

__all__ = ['render_html_to_pdf', 'build_html_prompt', 'build_html_prompt_for_pdf']
