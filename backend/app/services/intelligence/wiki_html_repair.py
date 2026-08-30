"""Repair / harden standalone wiki HTML layouts.

LLM-generated wiki_site.html sometimes emits extra ``</div>`` tags that close the
``.container`` early. In browsers that pops ``<main>`` out of the flex layout, so
later sections render as ``body > section`` without ``margin-left`` and slide
under the fixed TOC sidebar.
"""
from __future__ import annotations

import re
from typing import Optional

_LAYOUT_GUARD_MARK = "/* savi-wiki-layout-guard */"

_LAYOUT_GUARD_CSS = """
        /* savi-wiki-layout-guard */
        aside { z-index: 30; }
        main {
            margin-left: 280px !important;
            max-width: calc(100% - 280px);
            box-sizing: border-box;
        }
        /* Escaped sections after a premature </div> that closed .container/main */
        body > section[id] {
            margin-left: 280px !important;
            padding: 32px 48px;
            max-width: calc(100% - 280px);
            box-sizing: border-box;
        }
        body > section[id] table {
            display: block;
            max-width: 100%;
            overflow-x: auto;
        }
"""


def harden_wiki_layout_css(html: str) -> str:
    """Inject CSS so content never slides under a fixed wiki TOC."""
    if not html or _LAYOUT_GUARD_MARK in html:
        return html

    if "</style>" in html:
        return html.replace("</style>", _LAYOUT_GUARD_CSS + "\n        </style>", 1)

    # No stylesheet — insert a minimal one before </head> or at top
    block = f"<style>\n{_LAYOUT_GUARD_CSS}\n</style>\n"
    if "</head>" in html:
        return html.replace("</head>", block + "</head>", 1)
    return block + html


def _strip_excess_closing_divs_before_sections(html: str) -> str:
    """Remove ``</div>`` that would close below ``main`` while sections remain."""
    main_open = html.find("<main")
    main_close = html.find("</main>")
    if main_open < 0 or main_close < 0 or main_close <= main_open:
        return html

    body = html[main_open:main_close]
    # Count div open/close in main; if more closes than opens, drop trailing extras
    # before each </section> boundary.
    opens = len(re.findall(r"<div\b", body, flags=re.I))
    closes = len(re.findall(r"</div\s*>", body, flags=re.I))
    excess = closes - opens
    if excess <= 0:
        return html

    # Drop excess </div> that appear immediately before </section>
    def _trim(match: re.Match[str]) -> str:
        nonlocal excess
        chunk = match.group(0)
        while excess > 0 and re.search(r"</div\s*>\s*$", chunk, flags=re.I):
            chunk = re.sub(r"</div\s*>\s*$", "", chunk, count=1, flags=re.I)
            excess -= 1
        return chunk

    repaired_body = re.sub(
        r"(?:</div\s*>\s*)+</section>",
        _trim,
        body,
        flags=re.I,
    )
    return html[:main_open] + repaired_body + html[main_close:]


def repair_wiki_site_html(html: Optional[str]) -> str:
    """Harden CSS and lightly repair unbalanced divs in wiki HTML."""
    if not html:
        return ""
    fixed = _strip_excess_closing_divs_before_sections(html)
    return harden_wiki_layout_css(fixed)
