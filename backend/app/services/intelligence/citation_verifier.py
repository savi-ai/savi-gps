"""Extract and verify file-path citations in wiki markdown against indexed code chunks."""
from __future__ import annotations

import re
import uuid
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.core.database import CodeChunk, WikiClaim, WikiPage
from app.core.logger import logger

BACKTICK_CITATION_RE = re.compile(r"`([^`\n]+)`")
LINE_CITATION_RE = re.compile(r"`([^`:]+):(\d+)(?:-(\d+))?`")


def looks_like_file_path(value: str) -> bool:
    value = value.strip()
    if not value or len(value) > 260:
        return False
    if value.startswith(("http://", "https://", "mailto:")):
        return False
    if value.startswith("#") or value.endswith("/"):
        return False
    if " " in value:
        return False
    return "/" in value or "." in value


class CitationVerifier:
    def __init__(self, db: Session):
        self.db = db

    def verify_page(self, page: WikiPage) -> Dict[str, int]:
        """Extract citations from page content, verify against indexed chunks, persist claims."""
        self.db.query(WikiClaim).filter(WikiClaim.page_id == page.id).delete()

        indexed_paths = self._indexed_paths(page.repository_id)
        citations = self._extract_citations(page.content_md)

        verified = 0
        for citation_file, line_start, line_end, claim_text in citations:
            status, is_verified = self._verify_citation(
                citation_file, line_start, line_end, indexed_paths
            )
            if is_verified:
                verified += 1
            self.db.add(
                WikiClaim(
                    id=str(uuid.uuid4()),
                    page_id=page.id,
                    claim_text=claim_text,
                    citation_file=citation_file,
                    line_start=line_start,
                    line_end=line_end,
                    verified=is_verified,
                    status=status,
                )
            )

        page.total_claim_count = len(citations)
        page.verified_claim_count = verified
        self.db.flush()
        logger.info(
            f"Verified wiki page {page.slug}: {verified}/{len(citations)} citations"
        )
        return {"verified": verified, "total": len(citations)}

    def _indexed_paths(self, repository_id: str) -> Set[str]:
        rows = (
            self.db.query(CodeChunk.file_path)
            .filter(CodeChunk.repository_id == repository_id)
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    def _extract_citations(
        self, content_md: str
    ) -> List[Tuple[str, Optional[int], Optional[int], str]]:
        seen: Set[str] = set()
        citations: List[Tuple[str, Optional[int], Optional[int], str]] = []

        for match in LINE_CITATION_RE.finditer(content_md):
            path = match.group(1).strip()
            if not looks_like_file_path(path):
                continue
            line_start = int(match.group(2))
            line_end = int(match.group(3)) if match.group(3) else line_start
            key = f"{path}:{line_start}:{line_end}"
            if key in seen:
                continue
            seen.add(key)
            citations.append((path, line_start, line_end, match.group(0)))

        for match in BACKTICK_CITATION_RE.finditer(content_md):
            path = match.group(1).strip()
            if not looks_like_file_path(path):
                continue
            if ":" in path and path.rsplit(":", 1)[-1].isdigit():
                continue
            key = path
            if key in seen:
                continue
            seen.add(key)
            citations.append((path, None, None, match.group(0)))

        return citations

    def _resolve_path(self, citation_file: str, indexed_paths: Set[str]) -> Optional[str]:
        if citation_file in indexed_paths:
            return citation_file
        suffix_matches = [p for p in indexed_paths if p.endswith(citation_file)]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        basename_matches = [
            p for p in indexed_paths if p.split("/")[-1] == citation_file.split("/")[-1]
        ]
        if len(basename_matches) == 1:
            return basename_matches[0]
        return None

    def _verify_citation(
        self,
        citation_file: str,
        line_start: Optional[int],
        line_end: Optional[int],
        indexed_paths: Set[str],
    ) -> Tuple[str, bool]:
        resolved = self._resolve_path(citation_file, indexed_paths)
        if not resolved:
            return "missing_file", False

        if line_start is None:
            return "verified", True

        chunk = (
            self.db.query(CodeChunk)
            .filter(
                CodeChunk.file_path == resolved,
                CodeChunk.start_line <= line_start,
                CodeChunk.end_line >= (line_end or line_start),
            )
            .first()
        )
        if chunk:
            return "verified", True
        return "unverified", False

    def claim_dict(self, claim: WikiClaim) -> Dict:
        return {
            "id": claim.id,
            "claim_text": claim.claim_text,
            "citation_file": claim.citation_file,
            "line_start": claim.line_start,
            "line_end": claim.line_end,
            "verified": claim.verified,
            "status": claim.status,
        }
