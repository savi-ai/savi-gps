"""Sync GraphIndex to Neo4j (optional — no-op when Neo4j unavailable)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logger import logger
from app.services.intelligence.neo4j_client import get_driver, is_neo4j_enabled

if TYPE_CHECKING:
    from app.core.database import Repository
    from app.services.intelligence.structural_extractor import GraphIndex


def sync_graph_to_neo4j(
    repository: "Repository",
    index_run_id: str,
    graph: "GraphIndex",
) -> bool:
    if not is_neo4j_enabled() or not graph.symbols:
        return False

    driver = get_driver()
    if not driver:
        return False

    repo_id = repository.id
    tenant_id = repository.tenant_id

    try:
        with driver.session() as session:
            session.execute_write(
                _write_graph,
                repo_id,
                tenant_id,
                repository.name,
                repository.github_full_name or repository.name,
                index_run_id,
                graph,
            )
        logger.info(
            f"Neo4j graph synced for {repository.name}: "
            f"{len(graph.symbols)} symbols, {len(graph.edges)} edges"
        )
        return True
    except Exception as e:
        logger.warning(f"Neo4j graph sync failed: {e}")
        return False


def _write_graph(tx, repo_id, tenant_id, name, full_name, index_run_id, graph):
    tx.run(
        """
        MERGE (r:Repository {id: $repo_id})
        SET r.tenant_id = $tenant_id, r.name = $name, r.full_name = $full_name
        WITH r
        MERGE (run:IndexRun {id: $run_id})
        SET run.completed_at = datetime()
        MERGE (r)-[:INDEXED_BY]->(run)
        """,
        repo_id=repo_id,
        tenant_id=tenant_id,
        name=name,
        full_name=full_name,
        run_id=index_run_id,
    )

    for sym in graph.symbols:
        tx.run(
            """
            MATCH (r:Repository {id: $repo_id})
            MERGE (f:File {path: $file_path, repository_id: $repo_id})
            SET f.language = $language
            MERGE (r)-[:CONTAINS]->(f)
            MERGE (s:Symbol {qualified_name: $qname, repository_id: $repo_id})
            SET s.name = $name, s.kind = $kind, s.file_path = $file_path,
                s.start_line = $start_line
            MERGE (f)-[:DEFINES]->(s)
            """,
            repo_id=repo_id,
            file_path=sym.file_path,
            language=sym.language,
            qname=sym.qualified_name,
            name=sym.name,
            kind=sym.kind,
            start_line=sym.start_line,
        )

    for edge in graph.edges:
        if edge.edge_type != "CALLS":
            continue
        tx.run(
            """
            MATCH (src:Symbol {qualified_name: $source, repository_id: $repo_id})
            MERGE (tgt:Symbol {qualified_name: $target, repository_id: $repo_id})
            ON CREATE SET tgt.name = split($target, '.')[-1], tgt.kind = 'unknown'
            MERGE (src)-[c:CALLS]->(tgt)
            SET c.source_file = $source_file, c.source_line = $source_line
            """,
            repo_id=repo_id,
            source=edge.source,
            target=edge.target,
            source_file=edge.source_file,
            source_line=edge.source_line,
        )
