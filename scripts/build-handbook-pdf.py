#!/usr/bin/env python3
"""Convert Le_Moi-peau_員工手冊.md to a PDF for distribution."""

from pathlib import Path
import markdown
from weasyprint import HTML, CSS

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "Le_Moi-peau_員工手冊.md"
OUTPUT = ROOT / "Le_Moi-peau_員工手冊.pdf"

CSS_STYLES = """
@page {
    size: A4;
    margin: 22mm 18mm 22mm 18mm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-family: "WenQuanYi Zen Hei", sans-serif;
        font-size: 9pt;
        color: #888;
    }
}

html { font-size: 11pt; }

body {
    font-family: "WenQuanYi Zen Hei", "Noto Sans CJK TC", sans-serif;
    line-height: 1.7;
    color: #1f2328;
}

h1 {
    font-size: 22pt;
    margin: 0 0 0.4em 0;
    padding-bottom: 0.3em;
    border-bottom: 2px solid #1f2328;
    page-break-after: avoid;
}

h2 {
    font-size: 16pt;
    margin-top: 1.6em;
    margin-bottom: 0.5em;
    padding-bottom: 0.2em;
    border-bottom: 1px solid #d0d7de;
    page-break-after: avoid;
    page-break-before: auto;
}

h3 {
    font-size: 13pt;
    margin-top: 1.3em;
    margin-bottom: 0.4em;
    page-break-after: avoid;
}

h4 {
    font-size: 11.5pt;
    margin-top: 1.1em;
    margin-bottom: 0.3em;
    page-break-after: avoid;
}

p, li { font-size: 11pt; }

ul, ol { margin: 0.4em 0 0.8em 1.4em; padding-left: 0.4em; }
li { margin-bottom: 0.25em; }

blockquote {
    margin: 0.8em 0;
    padding: 0.5em 1em;
    border-left: 4px solid #6e7781;
    background: #f6f8fa;
    color: #4a4f55;
    font-style: italic;
}

table {
    border-collapse: collapse;
    margin: 0.7em 0 1em 0;
    width: 100%;
    font-size: 10.5pt;
    page-break-inside: avoid;
}
th, td {
    border: 1px solid #d0d7de;
    padding: 6px 10px;
    vertical-align: top;
    text-align: left;
}
th { background: #f1f3f5; font-weight: 600; }

code {
    font-family: "WenQuanYi Zen Hei Mono", monospace;
    background: #f6f8fa;
    padding: 0 0.25em;
    border-radius: 3px;
    font-size: 10pt;
}
pre {
    background: #f6f8fa;
    padding: 10px 12px;
    border-radius: 5px;
    overflow-x: auto;
    page-break-inside: avoid;
    font-size: 9.5pt;
}
pre code { background: transparent; padding: 0; }

hr {
    border: none;
    border-top: 1px solid #d0d7de;
    margin: 1.5em 0;
}

strong { color: #0b1320; }

a { color: #0969da; text-decoration: none; }
"""


def main() -> None:
    md_text = SOURCE.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
    )
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <title>Le Moi-peau 員工手冊</title>
</head>
<body>
{html_body}
</body>
</html>
"""
    HTML(string=html_doc, base_url=str(ROOT)).write_pdf(
        str(OUTPUT),
        stylesheets=[CSS(string=CSS_STYLES)],
    )
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
