"""
Converts HTML to PDF using Playwright (headless Chromium).
Handles KaTeX math rendering, Highlight.js, and Mermaid.js via JS execution.
"""

import asyncio
from playwright.async_api import async_playwright

from .template import wrap_html_body


async def _render_pdf_async(html_body: str, output_path: str, language: str = 'en',
                            video_id: str = None, base_url: str = None) -> str:
    """Async implementation of HTML-to-PDF conversion."""
    full_html = wrap_html_body(html_body, language=language,
                               video_id=video_id, base_url=base_url)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # Load HTML and wait for CDN resources
        await page.set_content(full_html, wait_until='networkidle')

        # Wait for KaTeX / Highlight.js / Mermaid to finish rendering
        try:
            await page.wait_for_function(
                'window.renderComplete === true',
                timeout=30000
            )
        except Exception as e:
            print(f"[HTML→PDF] Warning: render completion wait timed out: {e}")
            # Continue anyway — partial rendering is better than nothing

        # Generate PDF
        await page.pdf(
            path=output_path,
            format='A4',
            print_background=True,
            margin={
                'top': '25mm',
                'bottom': '25mm',
                'left': '20mm',
                'right': '20mm'
            },
            display_header_footer=True,
            header_template='<span></span>',
            footer_template="""
                <div style="width: 100%; font-size: 9pt; color: rgb(149,165,166);
                            text-align: center; padding: 0 20mm;">
                    <span class="pageNumber"></span> / <span class="totalPages"></span>
                </div>
            """
        )

        await browser.close()

    return output_path


def render_html_to_pdf(html_body: str, output_path: str, language: str = 'en',
                       video_id: str = None, base_url: str = None) -> str:
    """
    Convert HTML body content to a PDF file.

    This is a synchronous wrapper around the async Playwright conversion.
    Safe to call from a daemon thread (creates its own event loop).

    Args:
        html_body: Raw HTML content from Claude (no <html>/<head>/<body> tags)
        output_path: Where to write the PDF file
        language: 'en' or 'he' — controls RTL and lang attributes
        video_id: Optional video ID for citation links
        base_url: Optional base URL for citation links

    Returns:
        The output_path string on success, or None on failure.
    """
    try:
        # Create a new event loop for this thread (daemon threads don't have one)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                _render_pdf_async(html_body, str(output_path),
                                  language=language, video_id=video_id,
                                  base_url=base_url)
            )
            return result
        finally:
            loop.close()
    except Exception as e:
        print(f"[HTML→PDF] Error rendering PDF: {e}")
        import traceback
        traceback.print_exc()
        return None
