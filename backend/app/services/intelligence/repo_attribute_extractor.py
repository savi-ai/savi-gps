"""Deterministic extraction of repository attributes from common manifest files."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ExtractedAttribute:
    key: str
    label: str
    value: str
    source_file: Optional[str] = None
    line_start: Optional[int] = None
    confidence: str = "high"


def _read_text(root: Path, rel: str, max_bytes: int = 200_000) -> Optional[str]:
    path = root / rel
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
    except OSError:
        return None


def _find_file(root: Path, names: List[str]) -> Optional[str]:
    for name in names:
        p = root / name
        if p.is_file():
            return name
    for p in root.rglob("*"):
        if p.is_file() and p.name in names:
            return str(p.relative_to(root)).replace("\\", "/")
    return None


def extract_attributes(clone_path: str, definitions: List[Dict]) -> List[ExtractedAttribute]:
    """Extract attributes using heuristics + optional definition hints."""
    root = Path(clone_path)
    if not root.is_dir():
        return []

    results: List[ExtractedAttribute] = []
    seen_keys = set()

    def add(attr: ExtractedAttribute) -> None:
        if attr.key not in seen_keys and attr.value:
            seen_keys.add(attr.key)
            results.append(attr)

    # Java version from pom.xml
    pom = _find_file(root, ["pom.xml"])
    if pom:
        text = _read_text(root, pom)
        if text:
            m = re.search(r"<java\.version>([^<]+)</java\.version>", text)
            if not m:
                m = re.search(r"<maven\.compiler\.(?:source|release)>([^<]+)</", text)
            if m:
                add(ExtractedAttribute("java_version", "Java Version", m.group(1).strip(), pom, confidence="high"))

    # Node version
    pkg = _find_file(root, ["package.json"])
    if pkg:
        text = _read_text(root, pkg)
        if text:
            try:
                data = json.loads(text)
                engines = data.get("engines", {})
                node = engines.get("node") or data.get("volta", {}).get("node")
                if node:
                    add(ExtractedAttribute("node_version", "Node.js Version", str(node), pkg, confidence="high"))
            except json.JSONDecodeError:
                pass

    # Python version
    for rel in ["pyproject.toml", ".python-version", "runtime.txt"]:
        found = _find_file(root, [rel.split("/")[-1]])
        if not found:
            continue
        text = _read_text(root, found)
        if not text:
            continue
        m = re.search(r"python_requires\s*=\s*[\"']([^\"']+)", text)
        if not m:
            m = re.search(r"^([23]\.\d+(?:\.\d+)?)", text.strip())
        if m:
            add(ExtractedAttribute("python_version", "Python Version", m.group(1), found, confidence="high"))
            break

    # Golden / base Docker image
    dockerfile = _find_file(root, ["Dockerfile", "dockerfile"])
    if dockerfile:
        text = _read_text(root, dockerfile)
        if text:
            for i, line in enumerate(text.splitlines(), 1):
                if line.strip().upper().startswith("FROM "):
                    image = line.strip().split(None, 1)[1].split("#")[0].strip()
                    add(ExtractedAttribute("base_docker_image", "Base Docker Image", image, dockerfile, i, "high"))
                    add(ExtractedAttribute("golden_image", "Golden Image", image, dockerfile, i, "high"))
                    break

    # Go version
    gomod = _find_file(root, ["go.mod"])
    if gomod:
        text = _read_text(root, gomod)
        if text:
            m = re.search(r"^go\s+(\S+)", text, re.MULTILINE)
            if m:
                add(ExtractedAttribute("go_version", "Go Version", m.group(1), gomod, confidence="high"))

    # Database hints
    for rel in ["docker-compose.yml", "docker-compose.yaml", ".env.example"]:
        found = _find_file(root, [rel])
        if not found:
            continue
        text = (_read_text(root, found) or "").lower()
        for db, label in [("postgres", "PostgreSQL"), ("mysql", "MySQL"), ("mongodb", "MongoDB"), ("redis", "Redis")]:
            if db in text:
                add(ExtractedAttribute("database_type", "Database Type", label, found, confidence="medium"))
                break

    # Match tenant-defined keys with simple file grep
    for defn in definitions:
        key = defn.get("key", "")
        if not key or key in seen_keys:
            continue
        hint = (defn.get("extraction_hint") or "").lower()
        label = defn.get("label", key)
        if "dockerfile" in hint or key == "golden_image":
            continue  # already handled
        if "pom" in hint or "java" in key:
            continue

    return results
