"""
Claude prompt builder for HTML output format.
Instructs Claude to output semantic HTML body content that will be
wrapped with a full document template and rendered to PDF via Playwright.
"""

HTML_FORMAT_INSTRUCTIONS = """
OUTPUT FORMAT: You must output raw HTML content for the <body> of a document.
Do NOT output <html>, <head>, or <body> tags — only the inner content.

ALLOWED HTML ELEMENTS:

1. Headings — use <h1>, <h2>, <h3>
   <h1>Main Topic Title</h1>
   <h2>Section Title</h2>
   <h3>Subsection Title</h3>

2. Paragraphs — use <p>
   <p>Body text paragraph with explanations.</p>

3. Lists — use <ul> or <ol> with <li>
   <ul>
     <li>Bullet point</li>
   </ul>
   <ol>
     <li>Numbered item</li>
   </ol>

4. Tables — use <table> with <thead> and <tbody>
   <table>
     <thead><tr><th>Header 1</th><th>Header 2</th></tr></thead>
     <tbody><tr><td>Value 1</td><td>Value 2</td></tr></tbody>
   </table>

5. Colored boxes — use <div class="box VARIANT"> where VARIANT is one of:
   concept, definition, example, note, warning, important
   <div class="box definition">
     <div class="box-title">Definition Title</div>
     <p>Content of the definition.</p>
   </div>

6. Code blocks — use <pre><code class="language-LANG">
   <pre><code class="language-python">def hello():
       print("Hello")</code></pre>

7. Math — use LaTeX delimiters (KaTeX will render them):
   Display math: $$E = mc^2$$
   Inline math: \\(x^2 + y^2 = r^2\\)
   For matrices: $$\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}$$

8. Diagrams — use Mermaid syntax:
   <div class="mermaid">
   graph TD;
     A-->B;
     B-->C;
   </div>

9. Page breaks:
   <div class="page-break"></div>

10. Citations — EVERY content section MUST include citations from the transcript:
    <cite data-timestamp="MM:SS">"exact quote from the transcript"</cite>
    Place citations after the content they support (after a paragraph, inside a box, etc.)

CITATION RULES:
- The text inside <cite> must be the speaker's actual words from the transcript.
- data-timestamp must be the timecode from the transcript (MM:SS or HH:MM:SS).
- Every paragraph, box, and list MUST have at least one citation.
- Headings should have citations when derived from lecture content.
- Page breaks and diagrams don't require citations.
"""


def _build_task_section(note_type, custom_prompt, lang_name):
    """Build the TASK section of the prompt based on note_type."""
    if note_type == 'definitions':
        return f"""TASK:
Extract ONLY key definitions, theorems, formulas, and core concepts from the transcript above.
Output the result in {lang_name} as HTML content following the format below.

- Use <div class="box definition"> for definitions.
- Use <div class="box concept"> for theorems and key concepts.
- Use display math ($$...$$) for formulas.
- Do NOT include general explanations, narrative, or examples unless they clarify a definition.
- Keep it concise: only the essential knowledge."""
    elif note_type == 'summary':
        return f"""TASK:
Create a concise summary of the lecture in {lang_name}. Highlight the main topics, key takeaways, and conclusions. Keep it brief — aim for a high-level overview, not exhaustive detail.
Output the result as HTML content following the format below."""
    elif note_type == 'custom':
        return f"""TASK:
Follow the user's custom instruction below to create notes in {lang_name} from the transcript above.
Output the result as HTML content following the format below.

USER INSTRUCTION:
{custom_prompt or 'Create lecture notes.'}

IMPORTANT: Stay faithful to the transcript content. Do not invent information not present in the video."""
    else:  # 'full' (default)
        return f"""TASK:
Create professional lecture notes in {lang_name} based on the transcript above.
Output the notes as HTML content following the format below."""


def build_html_prompt(transcript_text, language='en', sampled_frames=None,
                      note_type='full', custom_prompt=None):
    """
    Build the Claude prompt requesting HTML output.

    Args:
        transcript_text: Full transcript with timestamps
        language: 'en' or 'he'
        sampled_frames: List of (timestamp, base64_image) tuples
        note_type: 'full', 'definitions', 'summary', or 'custom'
        custom_prompt: User-provided prompt (only used when note_type='custom')

    Returns:
        list of content parts for the API message (same format as json_pdf version)
    """
    content_parts = []

    # Add frames as images
    if sampled_frames:
        for ts, base64_img in sampled_frames:
            content_parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64_img
                }
            })

    lang_name = "English" if language == 'en' else "Hebrew (עברית)"
    if language == 'he':
        lang_instruction = """
LANGUAGE: Write ALL content in Hebrew (עברית).
- All headings, text, box titles, list items, and table content must be in Hebrew.
- Use English only for technical terms, code, variable names, and formulas.
"""
    else:
        lang_instruction = """
LANGUAGE: Write ALL content in English.
"""

    task_section = _build_task_section(note_type, custom_prompt, lang_name)

    prompt = f"""You are creating comprehensive, organized lecture notes from a video transcript.

TRANSCRIPT:
{transcript_text}

{task_section}

{lang_instruction}

CRITICAL INSTRUCTIONS — ACCURACY:
- Be FAITHFUL to the transcript. Write down what was actually said in the video.
- Use the speaker's own words and explanations — do not paraphrase or summarize.
- Include ALL topics, examples, and explanations from the lecture. Do not skip anything.
- Mark truly important concepts with colored box divs.
- For mathematical formulas, use LaTeX math notation: $$...$$ for display, \\(...\\) for inline.
- For matrices, use standard LaTeX: $$\\begin{{pmatrix}} 1 & 2 \\\\ 3 & 4 \\end{{pmatrix}}$$
- DO NOT add information that wasn't in the video.
- DO NOT create a "Summary" section at the end — the notes themselves ARE the comprehensive record.
- DO NOT condense multiple points into one. Each distinct point should have its own element.
- Every piece of content MUST cite the transcript with exact quotes and timestamps.

STRUCTURE GUIDELINES:
- Start with an <h1> for the main topic.
- Use <h2> for major sections/topics.
- Use <h3> for subtopics within sections.
- Use <p> for explanations and descriptions.
- Use <div class="box definition"> for formal definitions.
- Use <div class="box concept"> for key concepts the lecturer emphasizes.
- Use <div class="box example"> for examples given in the lecture.
- Use <div class="box note"> for additional observations or clarifications.
- Use <div class="box warning"> for common mistakes or pitfalls mentioned.
- Use <div class="box important"> for critical points the lecturer stresses.
- Use <ul>/<ol> for enumerated points or step-by-step processes.
- Use <table> for comparisons or structured data.
- Use $$...$$ for mathematical formulas (display) and \\(...\\) for inline math.
- Use <pre><code class="language-X"> for code shown or discussed.
- Use <div class="mermaid"> for processes, flows, or relationships described verbally.

VISUAL ELEMENTS:
- If the provided video frames show diagrams, charts, or visual aids, create corresponding Mermaid diagrams or tables.
- Create Mermaid diagrams for processes or relationships the lecturer describes.
- Use tables when the lecturer presents numerical data or comparisons.

{HTML_FORMAT_INSTRUCTIONS}

OUTPUT:
Output ONLY the HTML body content. No markdown code fences, no explanatory text before or after.
Start directly with the first HTML element (e.g., <h1>).
"""

    content_parts.append({
        "type": "text",
        "text": prompt
    })

    return content_parts


# --------------- PDF-specific prompt builder ---------------

HTML_FORMAT_INSTRUCTIONS_PDF = """
OUTPUT FORMAT: You must output raw HTML content for the <body> of a document.
Do NOT output <html>, <head>, or <body> tags — only the inner content.

ALLOWED HTML ELEMENTS:

1. Headings — use <h1>, <h2>, <h3>
   <h1>Main Topic Title</h1>
   <h2>Section Title</h2>
   <h3>Subsection Title</h3>

2. Paragraphs — use <p>
   <p>Body text paragraph with explanations.</p>

3. Lists — use <ul> or <ol> with <li>
   <ul>
     <li>Bullet point</li>
   </ul>
   <ol>
     <li>Numbered item</li>
   </ol>

4. Tables — use <table> with <thead> and <tbody>
   <table>
     <thead><tr><th>Header 1</th><th>Header 2</th></tr></thead>
     <tbody><tr><td>Value 1</td><td>Value 2</td></tr></tbody>
   </table>

5. Colored boxes — use <div class="box VARIANT"> where VARIANT is one of:
   concept, definition, example, note, warning, important
   <div class="box definition">
     <div class="box-title">Definition Title</div>
     <p>Content of the definition.</p>
   </div>

6. Code blocks — use <pre><code class="language-LANG">
   <pre><code class="language-python">def hello():
       print("Hello")</code></pre>

7. Math — use LaTeX delimiters (KaTeX will render them):
   Display math: $$E = mc^2$$
   Inline math: \\(x^2 + y^2 = r^2\\)
   For matrices: $$\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}$$

8. Diagrams — use Mermaid syntax:
   <div class="mermaid">
   graph TD;
     A-->B;
     B-->C;
   </div>

9. Page breaks:
   <div class="page-break"></div>

10. Citations — EVERY content section MUST include page citations from the source document:
    <cite data-page="N">"relevant quote or reference from the document"</cite>
    Place citations after the content they support (after a paragraph, inside a box, etc.)

CITATION RULES:
- The text inside <cite> should reference the source document content.
- data-page must be the page number (integer) where the content appears.
- Every paragraph, box, and list MUST have at least one citation.
- Headings should have citations when derived from document content.
- Page breaks and diagrams don't require citations.
"""


def _build_task_section_pdf(note_type, custom_prompt, lang_name):
    """Build the TASK section for PDF-based note generation."""
    if note_type == 'definitions':
        return f"""TASK:
Extract ONLY key definitions, theorems, formulas, and core concepts from the document above.
Output the result in {lang_name} as HTML content following the format below.

- Use <div class="box definition"> for definitions.
- Use <div class="box concept"> for theorems and key concepts.
- Use display math ($$...$$) for formulas.
- Do NOT include general explanations, narrative, or examples unless they clarify a definition.
- Keep it concise: only the essential knowledge."""
    elif note_type == 'summary':
        return f"""TASK:
Create a concise summary of the document in {lang_name}. Highlight the main topics, key takeaways, and conclusions. Keep it brief — aim for a high-level overview, not exhaustive detail.
Output the result as HTML content following the format below."""
    elif note_type == 'custom':
        return f"""TASK:
Follow the user's custom instruction below to create notes in {lang_name} from the document above.
Output the result as HTML content following the format below.

USER INSTRUCTION:
{custom_prompt or 'Create notes from the document.'}

IMPORTANT: Stay faithful to the document content. Do not invent information not present in the source."""
    else:  # 'full' (default)
        return f"""TASK:
Create professional, comprehensive notes in {lang_name} based on the document above.
Output the notes as HTML content following the format below."""


def build_html_prompt_for_pdf(pdf_base64, language='en', note_type='full', custom_prompt=None, sampled_pages=None):
    """
    Build the Claude prompt for PDF-based note generation.

    Args:
        pdf_base64: Base64-encoded PDF file content
        language: 'en' or 'he'
        note_type: 'full', 'definitions', 'summary', or 'custom'
        custom_prompt: User-provided prompt (only used when note_type='custom')
        sampled_pages: List of (page_number, base64_image) tuples from sample_pdf_pages()

    Returns:
        list of content parts for the API message
    """
    content_parts = []

    # PDF document block — placed FIRST per Anthropic best practices
    content_parts.append({
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": pdf_base64
        }
    })

    # Page screenshots — placed after document block for visual context
    if sampled_pages:
        for page_num, base64_img in sampled_pages:
            content_parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64_img
                }
            })

    lang_name = "English" if language == 'en' else "Hebrew (עברית)"
    if language == 'he':
        lang_instruction = """
LANGUAGE: Write ALL content in Hebrew (עברית).
- All headings, text, box titles, list items, and table content must be in Hebrew.
- Use English only for technical terms, code, variable names, and formulas.
"""
    else:
        lang_instruction = """
LANGUAGE: Write ALL content in English.
"""

    task_section = _build_task_section_pdf(note_type, custom_prompt, lang_name)

    prompt = f"""You are creating comprehensive, organized notes from a PDF document.

{task_section}

{lang_instruction}

CRITICAL INSTRUCTIONS — ACCURACY:
- Be FAITHFUL to the document. Write down what is actually presented in the source material.
- Use the document's own words and explanations — do not paraphrase or summarize excessively.
- Include ALL topics, examples, and explanations from the document. Do not skip anything.
- Mark truly important concepts with colored box divs.
- For mathematical formulas, use LaTeX math notation: $$...$$ for display, \\(...\\) for inline.
- For matrices, use standard LaTeX: $$\\begin{{pmatrix}} 1 & 2 \\\\ 3 & 4 \\end{{pmatrix}}$$
- DO NOT add information that wasn't in the document.
- DO NOT create a "Summary" section at the end — the notes themselves ARE the comprehensive record.
- DO NOT condense multiple points into one. Each distinct point should have its own element.
- Every piece of content MUST cite the source document with page numbers.

STRUCTURE GUIDELINES:
- Start with an <h1> for the main topic.
- Use <h2> for major sections/topics.
- Use <h3> for subtopics within sections.
- Use <p> for explanations and descriptions.
- Use <div class="box definition"> for formal definitions.
- Use <div class="box concept"> for key concepts.
- Use <div class="box example"> for examples given in the document.
- Use <div class="box note"> for additional observations or clarifications.
- Use <div class="box warning"> for common mistakes or pitfalls mentioned.
- Use <div class="box important"> for critical points.
- Use <ul>/<ol> for enumerated points or step-by-step processes.
- Use <table> for comparisons or structured data.
- Use $$...$$ for mathematical formulas (display) and \\(...\\) for inline math.
- Use <pre><code class="language-X"> for code shown or discussed.
- Use <div class="mermaid"> for processes, flows, or relationships described in the document.

VISUAL ELEMENTS:
- Page screenshots from the document are provided as images above. Use these to understand
  diagrams, charts, figures, handwritten content, and visual elements.
- Create corresponding Mermaid diagrams or tables to reproduce visual aids in the notes.
- Use tables when the document presents numerical data or comparisons.

{HTML_FORMAT_INSTRUCTIONS_PDF}

OUTPUT:
Output ONLY the HTML body content. No markdown code fences, no explanatory text before or after.
Start directly with the first HTML element (e.g., <h1>).
"""

    content_parts.append({
        "type": "text",
        "text": prompt
    })

    return content_parts
