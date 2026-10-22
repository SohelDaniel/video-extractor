"""
Wraps Claude's HTML body output with a complete document including
CDN dependencies for KaTeX, Highlight.js, and Mermaid.js.
"""

from pathlib import Path

# Read styles.css once at import time
_STYLES_PATH = Path(__file__).parent / "styles.css"
_STYLES_CSS = _STYLES_PATH.read_text(encoding="utf-8")


def wrap_html_body(html_body: str, language: str = 'en',
                   video_id: str = None, base_url: str = None) -> str:
    """
    Wrap Claude's HTML body content with a full HTML document.

    Args:
        html_body: Raw HTML content (no <html>/<head>/<body> tags)
        language: 'en' or 'he' — controls dir and lang attributes
        video_id: Optional video ID for citation links
        base_url: Optional base URL for citation links

    Returns:
        Complete HTML document string ready for Playwright rendering
    """
    direction = "rtl" if language == "he" else "ltr"
    lang_attr = "he" if language == "he" else "en"

    # Build citation link base if provided
    citation_script = ""
    if video_id and base_url:
        citation_script = f"""
    // Make citation timestamps clickable
    document.querySelectorAll('cite[data-timestamp]').forEach(function(cite) {{
        var ts = cite.getAttribute('data-timestamp');
        var parts = ts.split(':');
        var seconds = 0;
        for (var i = 0; i < parts.length; i++) {{
            seconds = seconds * 60 + parseInt(parts[i], 10);
        }}
        var link = document.createElement('a');
        link.href = '{base_url}/result/{video_id}?t=' + seconds;
        link.textContent = '[' + ts + ']';
        link.style.marginLeft = '4px';
        cite.appendChild(link);
    }});
"""

    return f"""<!DOCTYPE html>
<html dir="{direction}" lang="{lang_attr}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<!-- KaTeX CSS + JS -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>

<!-- Highlight.js -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/atom-one-dark.min.css">
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>

<!-- Mermaid.js -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>

<style>
{_STYLES_CSS}
</style>
</head>
<body>
{html_body}

<script>
(function() {{
    // Initialize KaTeX auto-render
    renderMathInElement(document.body, {{
        delimiters: [
            {{left: '$$', right: '$$', display: true}},
            {{left: '\\\\(', right: '\\\\)', display: false}},
            {{left: '\\\\[', right: '\\\\]', display: true}}
        ],
        throwOnError: false
    }});

    // Initialize Highlight.js
    hljs.highlightAll();

    // Initialize Mermaid
    mermaid.initialize({{ startOnLoad: false, theme: 'default' }});
    var mermaidDivs = document.querySelectorAll('.mermaid');
    if (mermaidDivs.length > 0) {{
        mermaid.init(undefined, mermaidDivs);
    }}

    {citation_script}

    // Render page citations for PDF-sourced notes
    document.querySelectorAll('cite[data-page]').forEach(function(cite) {{
        var page = cite.getAttribute('data-page');
        var span = document.createElement('span');
        span.textContent = ' [p. ' + page + ']';
        span.style.color = '#7f8c8d';
        span.style.fontSize = '0.85em';
        cite.appendChild(span);
    }});

    // Signal that all rendering is complete
    window.renderComplete = true;
}})();
</script>
</body>
</html>"""
