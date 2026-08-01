#!/usr/bin/env python3
"""Render protocol/PROTOCOL.md into web/docs.html.

Run from the repo root (or anywhere):  python3 web/build_docs.py
Requires: pip install markdown
"""

from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "protocol" / "PROTOCOL.md"
DST = ROOT / "web" / "docs.html"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IntervalClock — the protocol</title>
<link rel="stylesheet" href="style.css">
<style>
main {{ max-width: 860px; }}
main h1 {{ font-size: 1.7rem; }}
main h2 {{ border-bottom: 1px solid var(--panel2); padding-bottom: 0.3rem; margin-top: 2.2rem; }}
main table {{ border-collapse: collapse; margin: 1rem 0; display: block; overflow-x: auto; }}
main th, main td {{ border: 1px solid var(--panel2); padding: 0.4rem 0.7rem; text-align: left; }}
main pre {{ background: var(--panel); border: 1px solid var(--panel2); border-radius: 8px;
  padding: 0.9rem 1.1rem; overflow-x: auto; }}
main blockquote {{ border-left: 3px solid var(--accent); margin: 1rem 0; padding: 0.2rem 1rem;
  color: var(--muted); }}
main code {{ background: var(--panel2); border-radius: 4px; padding: 0.08em 0.35em; }}
main pre code {{ background: none; padding: 0; }}
</style>
</head>
<body>
<header>
  <h1><a href="index.html">⏱ IntervalClock</a></h1>
  <span class="tag">the protocol, v1</span>
  <nav>
    <a href="index.html">Clock</a>
    <a href="playground.html">Playground</a>
    <a href="explore.html">Explore</a>
    <a href="docs.html" class="active">Protocol</a>
  </nav>
</header>
<main>
{body}
</main>
<footer>normative source: <code>protocol/PROTOCOL.md</code> — this page is generated
by <code>web/build_docs.py</code></footer>
</body>
</html>
"""


def main() -> None:
    body = markdown.markdown(
        SRC.read_text(),
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    DST.write_text(TEMPLATE.format(body=body))
    print(f"wrote {DST} ({DST.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
