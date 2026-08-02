"""Secret redaction for logs and error payloads."""
from __future__ import annotations

import re

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([^\s'\"]+)"), r"\1=***"),
    (re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{8,})\b"), "sk-ant-***"),
    (re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b"), "sk-***"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "AKIA***"),
    (
        re.compile(
            r"(?i)(aws_secret_access_key|bedrock_aws_secret_access_key)\s*[:=]\s*\S+"
        ),
        r"\1=***",
    ),
]


def redact_secrets(text: str | None) -> str:
    if not text:
        return ""
    out = str(text)
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out
