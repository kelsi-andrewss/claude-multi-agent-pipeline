#!/usr/bin/env python3
"""Convert a BrainLift markdown file to a styled PDF."""

import sys
import os


def guarded_url_fetcher(url, timeout=10, ssl_context=None):
    allowed = ("https://", "http://", "data:")
    if not any(url.lower().startswith(scheme) for scheme in allowed):
        raise ValueError(f"Blocked URI scheme: {url}")
    import weasyprint
    return weasyprint.default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.md> <output.pdf>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    try:
        import markdown
    except ImportError:
        print("Missing dependency: markdown")
        print("Install: pip install markdown")
        sys.exit(1)

    try:
        import weasyprint
    except ImportError:
        print("Missing dependency: weasyprint")
        print("Install: brew install weasyprint && pip install weasyprint")
        sys.exit(1)

    if not os.path.isfile(input_path):
        print(f"Input file not found: {input_path}")
        sys.exit(1)

    with open(input_path, "r") as f:
        text = f.read()

    body = markdown.markdown(text, extensions=["tables", "extra", "toc"])

    css_path = os.path.expanduser("~/.claude/templates/brainlift.css")
    with open(css_path, "r") as f:
        css_content = f.read()

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{css_content}</style>
</head>
<body>
{body}
</body>
</html>"""

    weasyprint.HTML(string=html, base_url=os.path.dirname(os.path.abspath(input_path)), url_fetcher=guarded_url_fetcher).write_pdf(output_path)
    print(f"PDF written to {output_path}")


if __name__ == "__main__":
    main()
