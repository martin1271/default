#!/usr/bin/env python3
"""Convert Le_Moi-peau_員工手冊.md to a polished PDF for distribution."""

from pathlib import Path
import markdown
from markdown.extensions.toc import slugify_unicode
from weasyprint import HTML, CSS

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "Le_Moi-peau_員工手冊.md"
OUTPUT = ROOT / "Le_Moi-peau_員工手冊.pdf"

CSS_STYLES = r"""
@page {
    size: A4;
    margin: 24mm 22mm 22mm 22mm;
    @bottom-center {
        content: counter(page);
        font-family: "Noto Sans CJK TC", sans-serif;
        font-size: 9pt;
        color: #99a1ab;
    }
}

@page :first {
    @bottom-center { content: none; }
}

html { font-size: 10.5pt; }

body {
    font-family: "Noto Sans CJK TC", "Noto Sans CJK SC", "WenQuanYi Zen Hei", sans-serif;
    font-weight: 350;
    line-height: 1.85;
    color: #2a2f36;
    text-align: justify;
    letter-spacing: 0.01em;
    word-break: break-word;
}

p {
    margin: 0.5em 0 0.9em 0;
    orphans: 3;
    widows: 3;
}

/* Title block on first page */
h1 {
    font-family: "Noto Serif CJK TC", "Noto Sans CJK TC", serif;
    font-size: 28pt;
    font-weight: 700;
    margin: 0.4em 0 0.1em 0;
    padding: 0;
    border: none;
    color: #14181d;
    letter-spacing: 0.02em;
    page-break-after: avoid;
    string-set: doctitle content();
    bookmark-level: 1;
    bookmark-label: content();
}

/* The first subtitle line after h1 */
h1 + h3 {
    font-family: "Noto Sans CJK TC", sans-serif;
    font-size: 11pt;
    font-weight: 400;
    color: #6e7681;
    margin: 0 0 2.4em 0;
    padding: 0;
    letter-spacing: 0.25em;
    border: none;
}

h2 {
    font-family: "Noto Serif CJK TC", "Noto Sans CJK TC", serif;
    font-size: 18pt;
    font-weight: 700;
    margin: 2.2em 0 0.6em 0;
    padding-bottom: 0.35em;
    color: #14181d;
    border-bottom: 1.5px solid #14181d;
    page-break-after: avoid;
    page-break-before: auto;
    bookmark-level: 2;
    bookmark-label: content();
}

h3 {
    font-family: "Noto Sans CJK TC", sans-serif;
    font-size: 13.5pt;
    font-weight: 700;
    margin: 1.6em 0 0.5em 0;
    color: #1f242c;
    page-break-after: avoid;
    bookmark-level: 3;
    bookmark-label: content();
}

h4 {
    font-family: "Noto Sans CJK TC", sans-serif;
    font-size: 11.5pt;
    font-weight: 700;
    margin: 1.3em 0 0.4em 0;
    color: #2a2f36;
    page-break-after: avoid;
    bookmark-level: 4;
    bookmark-label: content();
}

/* Table of contents — first ordered list after the first h1 + h3 */
h1 ~ ol:first-of-type {
    list-style: none;
    padding: 0;
    margin: 0.5em 0 2em 0;
    counter-reset: toc;
    page-break-after: always;
}

h1 ~ ol:first-of-type > li {
    counter-increment: toc;
    margin: 0;
    padding: 0.55em 0;
    border-bottom: 1px dotted #d4d8de;
    font-size: 11.5pt;
    line-height: 1.5;
    position: relative;
}

h1 ~ ol:first-of-type > li::before {
    content: counter(toc, decimal-leading-zero);
    display: inline-block;
    width: 2.4em;
    color: #b08968;
    font-family: "Noto Serif CJK TC", serif;
    font-weight: 600;
    font-size: 11pt;
    letter-spacing: 0.05em;
}

h1 ~ ol:first-of-type > li a {
    color: #14181d;
    text-decoration: none;
    font-weight: 500;
}

ul, ol { margin: 0.4em 0 1em 0; padding-left: 1.4em; }
ul li, ol li {
    margin-bottom: 0.35em;
    line-height: 1.75;
}

ul { list-style-type: square; }
ul li::marker { color: #b08968; }

blockquote {
    margin: 1.2em 0;
    padding: 0.8em 1.2em;
    border-left: 3px solid #b08968;
    background: #faf7f3;
    color: #4a4f55;
    font-style: normal;
    line-height: 1.75;
    page-break-inside: avoid;
}
blockquote p { margin: 0.25em 0; }

table {
    border-collapse: collapse;
    margin: 1em 0 1.4em 0;
    width: 100%;
    font-size: 10pt;
    page-break-inside: avoid;
    line-height: 1.6;
}
th, td {
    border: none;
    border-bottom: 1px solid #e3e6ea;
    padding: 10px 12px;
    vertical-align: top;
    text-align: left;
}
thead th {
    background: #14181d;
    color: #fff;
    font-weight: 600;
    border: none;
    letter-spacing: 0.03em;
}
tbody tr:nth-child(even) { background: #fafbfc; }

code {
    font-family: "Noto Sans Mono CJK TC", "WenQuanYi Zen Hei Mono", monospace;
    background: #f4f5f7;
    padding: 0.1em 0.4em;
    border-radius: 3px;
    font-size: 9.5pt;
    color: #b04848;
}
pre {
    background: #f4f5f7;
    padding: 14px 16px;
    border-radius: 6px;
    overflow-x: auto;
    page-break-inside: avoid;
    font-size: 9pt;
    line-height: 1.55;
}
pre code { background: transparent; padding: 0; color: inherit; }

hr {
    border: none;
    border-top: 1px solid #e3e6ea;
    margin: 2em 0;
}

strong { color: #14181d; font-weight: 700; }
em { font-style: normal; color: #b08968; }

a { color: #14181d; text-decoration: none; }
"""


def main() -> None:
    md_text = SOURCE.read_text(encoding="utf-8")

    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "toc", "attr_list"],
        extension_configs={
            "toc": {
                "slugify": slugify_unicode,
                "permalink": False,
            }
        },
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
