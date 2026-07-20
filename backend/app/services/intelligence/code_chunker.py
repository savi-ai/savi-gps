"""Walk repository files, chunk source text, basic secret scan gate."""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from app.core.logger import logger

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".rb", ".php",
    ".cs", ".kt", ".scala", ".swift", ".md", ".yaml", ".yml", ".json", ".toml",
    ".xml", ".html", ".css", ".scss", ".sql", ".sh", ".bash", ".dockerfile",
    ".tf", ".hcl", ".proto", ".graphql", ".vue", ".svelte",
}

SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"(?i)github[_-]?token\s*=\s*['\"][a-zA-Z0-9_\-]{20,}"), "GitHub token"),
    (re.compile(r"(?i)api[_-]?key\s*=\s*['\"][a-zA-Z0-9_\-]{16,}"), "API key assignment"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Private key"),
]

MAX_FILE_BYTES = 512_000
CHUNK_LINES = 80
CHUNK_OVERLAP = 10


@dataclass
class FileChunk:
    file_path: str
    start_line: int
    end_line: int
    content: str
    language: Optional[str]
    content_hash: str


@dataclass
class SecretFinding:
    file_path: str
    line: int
    kind: str
    snippet: str


def _language_for(path: str) -> Optional[str]:
    ext = Path(path).suffix.lower()
    if ext == ".py":
        return "python"
    if ext in (".js", ".jsx"):
        return "javascript"
    if ext in (".ts", ".tsx"):
        return "typescript"
    if ext == ".java":
        return "java"
    return ext.lstrip(".") or None


def _should_include(path: str, include: Optional[List[str]], exclude: List[str]) -> bool:
    rel = path.replace("\\", "/")
    for pattern in exclude:
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(rel), pattern):
            return False
    if include:
        return any(fnmatch.fnmatch(rel, p) for p in include)
    ext = Path(rel).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    if os.path.basename(rel).lower() in ("dockerfile", "makefile", "readme"):
        return True
    return False


def scan_for_secrets(root: str) -> List[SecretFinding]:
    findings: List[SecretFinding] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "vendor", ".venv", "venv")]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root)
            try:
                if os.path.getsize(fpath) > MAX_FILE_BYTES:
                    continue
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, start=1):
                        for pattern, kind in SECRET_PATTERNS:
                            if pattern.search(line):
                                findings.append(
                                    SecretFinding(
                                        file_path=rel,
                                        line=i,
                                        kind=kind,
                                        snippet=line.strip()[:120],
                                    )
                                )
            except OSError:
                continue
    return findings


def chunk_repository(
    root: str,
    include_globs: Optional[List[str]] = None,
    exclude_globs: Optional[List[str]] = None,
) -> Tuple[List[FileChunk], int]:
    exclude = exclude_globs or []
    chunks: List[FileChunk] = []
    loc = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "vendor", ".venv", "venv")]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root).replace("\\", "/")
            if not _should_include(rel, include_globs, exclude):
                continue
            try:
                size = os.path.getsize(fpath)
                if size > MAX_FILE_BYTES or size == 0:
                    continue
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except OSError:
                continue

            loc += len(lines)
            lang = _language_for(rel)
            if not lines:
                continue

            start = 0
            while start < len(lines):
                end = min(start + CHUNK_LINES, len(lines))
                block = "".join(lines[start:end])
                if block.strip():
                    content_hash = hashlib.sha256(block.encode("utf-8")).hexdigest()
                    chunks.append(
                        FileChunk(
                            file_path=rel,
                            start_line=start + 1,
                            end_line=end,
                            content=block,
                            language=lang,
                            content_hash=content_hash,
                        )
                    )
                if end >= len(lines):
                    break
                start = max(end - CHUNK_OVERLAP, start + 1)

    logger.info(f"Chunked repository at {root}: {len(chunks)} chunks, {loc} LOC")
    return chunks, loc
