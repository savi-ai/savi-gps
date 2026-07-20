"""One-time migration: copy legacy temp_store analysis dirs to tenant-scoped storage.

Usage (from backend/):
  python -m app.scripts.migrate_analysis_storage
  python -m app.scripts.migrate_analysis_storage --dry-run
  python -m app.scripts.migrate_analysis_storage --tenant-id <id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.database import Repository, SessionLocal
from app.services.intelligence.analysis_storage import migrate_legacy_analysis_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy analysis artifacts to tenant storage")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without copying files")
    parser.add_argument("--tenant-id", help="Limit migration to one tenant")
    args = parser.parse_args()

    db = SessionLocal()
    migrated = 0
    skipped = 0
    try:
        query = db.query(Repository)
        if args.tenant_id:
            query = query.filter(Repository.tenant_id == args.tenant_id)

        for repo in query.all():
            if migrate_legacy_analysis_dir(repo, dry_run=args.dry_run):
                migrated += 1
            else:
                skipped += 1
    finally:
        db.close()

    mode = "would migrate" if args.dry_run else "migrated"
    print(f"Done: {mode} {migrated} repos, skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
