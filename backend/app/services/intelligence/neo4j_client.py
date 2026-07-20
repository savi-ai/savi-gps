"""Optional Neo4j client for L2/L3 graph storage (Phase 4)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import logger

_driver = None


def is_neo4j_enabled() -> bool:
    return bool(settings.NEO4J_URI and settings.NEO4J_PASSWORD)


def get_driver():
    global _driver
    if not is_neo4j_enabled():
        return None
    if _driver is None:
        try:
            from neo4j import GraphDatabase

            _driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER or "neo4j", settings.NEO4J_PASSWORD),
            )
            _driver.verify_connectivity()
            logger.info("Neo4j connection established")
        except Exception as e:
            logger.warning(f"Neo4j unavailable: {e}")
            _driver = None
    return _driver


def run_query(cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    driver = get_driver()
    if not driver:
        return []
    db = settings.NEO4J_DATABASE or "neo4j"
    try:
        with driver.session(database=db) as session:
            result = session.run(cypher, parameters or {})
            return [dict(record) for record in result]
    except Exception as e:
        logger.warning(f"Neo4j query failed: {e}")
        return []


def close_driver() -> None:
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        except Exception:
            pass
        _driver = None
