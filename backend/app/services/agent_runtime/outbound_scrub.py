"""Outbound secret scrubbing (ADR 0010 §7) — trajectory / prompts / artifacts."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# Patterns aligned with inbound indexing; applied to outbound agent payloads.
_OUTBOUND_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"(?i)github[_-]?token\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{20,}"), "GitHub token"),
    (re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}"), "API key"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Private key"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub PAT"),
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "Anthropic key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI-style key"),
]


def scrub_text(text: str) -> Tuple[str, int]:
    """Redact secrets in text. Returns (scrubbed, finding_count)."""
    if not text:
        return text, 0
    out = text
    count = 0
    for pattern, kind in _OUTBOUND_PATTERNS:
        matches = list(pattern.finditer(out))
        if not matches:
            continue
        count += len(matches)
        out = pattern.sub(f"[REDACTED:{kind}]", out)
    return out, count


def scrub_structure(value: Any) -> Tuple[Any, int]:
    """Recursively scrub strings in dict/list payloads."""
    total = 0
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in value.items():
            cv, n = scrub_structure(v)
            cleaned[k] = cv
            total += n
        return cleaned, total
    if isinstance(value, list):
        items = []
        for v in value:
            cv, n = scrub_structure(v)
            items.append(cv)
            total += n
        return items, total
    return value, 0
