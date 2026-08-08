#!/usr/bin/env python3
"""Render Savi CLI prompt templates (shared by claude / copilot / kiro wrappers).

Usage:
  render_prompt.py <template.txt> [--var NAME=VALUE ...]
  render_prompt.py <template.txt> --json '{"TITLE":"...","DESCRIPTION":"..."}'

Placeholders use {{NAME}} syntax. Unknown placeholders are left empty.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")


def render(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key, "")

    return _PLACEHOLDER.sub(repl, template)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path, help="Path to template .txt")
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        help="NAME=VALUE (repeatable). VALUE may be multiline via $'...'",
    )
    parser.add_argument("--json", dest="json_blob", default=None)
    parser.add_argument(
        "--file-var",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Load placeholder NAME from file PATH (truncated if large)",
    )
    parser.add_argument("--max-file-bytes", type=int, default=12000)
    args = parser.parse_args()

    if not args.template.is_file():
        print(f"Error: template not found: {args.template}", file=sys.stderr)
        return 1

    values: dict[str, str] = {}
    if args.json_blob:
        data = json.loads(args.json_blob)
        if not isinstance(data, dict):
            print("Error: --json must be an object", file=sys.stderr)
            return 1
        values.update({str(k): "" if v is None else str(v) for k, v in data.items()})

    for item in args.var:
        if "=" not in item:
            print(f"Error: --var must be NAME=VALUE, got {item!r}", file=sys.stderr)
            return 1
        name, value = item.split("=", 1)
        values[name] = value

    for item in args.file_var:
        if "=" not in item:
            print(f"Error: --file-var must be NAME=PATH, got {item!r}", file=sys.stderr)
            return 1
        name, path_s = item.split("=", 1)
        path = Path(path_s)
        if path.is_file():
            raw = path.read_bytes()[: args.max_file_bytes]
            values[name] = raw.decode("utf-8", errors="replace")
        else:
            values[name] = ""

    text = args.template.read_text(encoding="utf-8")
    sys.stdout.write(render(text, values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
