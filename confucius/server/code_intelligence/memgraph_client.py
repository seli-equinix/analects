# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""Async Memgraph client for CCA code intelligence.

Thin async wrapper around the neo4j async driver provided by BackendClients.
Ported from MCP's memgraph_adapter.py — same Cypher queries, but async
and using the shared driver instead of a synchronous singleton.

Graph Schema (shared with MCP):
- (:File {path, project, language, indexed_at})
- (:Function {name, qualified_name, file_path, language, project, signature, ...})
- (:Class {name, file_path, language, project, line_start})
- (:Module {name, project})

Relationships:
- (Function)-[:DEFINED_IN]->(File)
- (Function)-[:CALLS]->(Function)
- (Function)-[:IMPORTS]->(Module)
- (Function)-[:BELONGS_TO]->(Class)
- (Class)-[:DEFINED_IN]->(File)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Python builtins that should not create graph nodes
_PYTHON_BUILTINS = frozenset({
    "print", "len", "range", "int", "str", "float", "bool", "list", "dict",
    "set", "tuple", "type", "isinstance", "issubclass", "hasattr", "getattr",
    "setattr", "delattr", "super", "property", "staticmethod", "classmethod",
    "open", "input", "repr", "hash", "id", "abs", "min", "max", "sum",
    "sorted", "reversed", "enumerate", "zip", "map", "filter", "any", "all",
    "next", "iter", "format", "vars", "dir", "help", "callable", "hex", "oct",
    "bin", "ord", "chr", "bytes", "bytearray", "memoryview", "object",
    "round", "pow", "divmod", "complex", "frozenset", "slice",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "StopIteration", "OSError",
    "FileNotFoundError", "NotImplementedError", "ImportError",
})


def _normalize_callee_name(callee_name: str, language: str) -> Optional[str]:
    """Normalize a callee name before creating CALLS edges.

    Returns the normalized name, or None if the call should be skipped.
    """
    if not callee_name or not callee_name.strip():
        return None

    callee_name = callee_name.strip()

    if language != "python":
        return callee_name

    if callee_name.startswith(("self.", "cls.")):
        remainder = callee_name.split(".", 1)[1]
        if "." in remainder:
            return None
        callee_name = remainder

    if "." in callee_name:
        return None

    if callee_name in _PYTHON_BUILTINS:
        return None

    if len(callee_name) < 2:
        return None

    return callee_name


class MemgraphClient:
    """Async Memgraph client using the neo4j async driver from BackendClients.

    All methods accept the async driver as a parameter — no internal state
    beyond the driver reference.  This keeps it testable and avoids singletons.

    SECURITY: All Cypher queries use parameterized values ($name, $project, etc.)
    via the neo4j driver, which handles escaping.  Labels and relationship types
    are hardcoded string literals, never user-supplied.  No injection risk.
    """

    def __init__(self, driver: Any) -> None:
        """Wrap an existing neo4j.AsyncDriver."""
        self._driver = driver

    @property
    def available(self) -> bool:
        return self._driver is not None

    # ------------------------------------------------------------------
    # Write: Index a file's graph data
    # ------------------------------------------------------------------

    async def index_file_graph(
        self,
        file_path: str,
        project: str,
        language: str,
        functions: List[Dict],
    ) -> Dict[str, int]:
        """Populate graph for one file (async version of MCP's index_file_graph).

        Creates/updates File, Function, Class, Module nodes and all edges.
        """
        if not self._driver:
            return {"error": "not connected"}

        counts = {"functions": 0, "calls": 0, "imports": 0, "classes": 0}
        now = datetime.now().isoformat()

        try:
            async with self._driver.session() as session:
                # Clear existing data for this file
                await session.run(
                    "MATCH (fn:Function {file_path: $path}) DETACH DELETE fn",
                    path=file_path,
                )
                await session.run(
                    "MATCH (c:Class {file_path: $path}) DETACH DELETE c",
                    path=file_path,
                )
                await session.run(
                    "MATCH (f:File {path: $path}) DETACH DELETE f",
                    path=file_path,
                )

                # Clean up stubs that will be re-created as real nodes
                # Scoped to project to avoid corrupting other projects' stubs
                func_names = [f.get("name", "") for f in functions if f.get("name")]
                if func_names:
                    await session.run(
                        """
                        MATCH (stub:Function)
                        WHERE stub.name IN $names
                          AND stub.project = $project
                          AND (stub.file_path IS NULL OR stub.file_path = '')
                        DETACH DELETE stub
                        """,
                        names=func_names,
                        project=project,
                    )

                # Create File node
                await session.run(
                    """
                    CREATE (f:File {
                        path: $path, project: $project,
                        language: $language, indexed_at: $indexed_at
                    })
                    """,
                    path=file_path, project=project,
                    language=language, indexed_at=now,
                )

                classes_created: set[str] = set()

                for func in functions:
                    func_name = func.get("name", "")
                    if not func_name:
                        continue
                    if func.get("type") == "section":
                        continue

                    class_name = func.get("class_name", "")
                    qualified_name = f"{file_path}::{func_name}"
                    if class_name:
                        qualified_name = f"{file_path}::{class_name}.{func_name}"

                    # Create Function node + DEFINED_IN edge
                    await session.run(
                        """
                        MATCH (f:File {path: $fpath})
                        MERGE (fn:Function {qualified_name: $qname})
                        ON CREATE SET fn.name = $name, fn.file_path = $fpath,
                                      fn.language = $language, fn.project = $project,
                                      fn.signature = $signature,
                                      fn.line_start = $line_start, fn.line_end = $line_end,
                                      fn.loc = $loc, fn.is_async = $is_async,
                                      fn.return_type = $return_type
                        ON MATCH SET  fn.name = $name, fn.file_path = $fpath,
                                      fn.language = $language, fn.project = $project,
                                      fn.signature = $signature,
                                      fn.line_start = $line_start, fn.line_end = $line_end,
                                      fn.loc = $loc, fn.is_async = $is_async,
                                      fn.return_type = $return_type
                        MERGE (fn)-[:DEFINED_IN]->(f)
                        """,
                        name=func_name, qname=qualified_name, fpath=file_path,
                        language=language, project=project,
                        signature=func.get("signature", ""),
                        line_start=func.get("line_start", 0),
                        line_end=func.get("line_end", 0),
                        loc=func.get("loc", 0),
                        is_async=func.get("is_async", False),
                        return_type=func.get("return_type") or "",
                    )
                    counts["functions"] += 1

                    # Store pending calls as a list property on the Function node.
                    # CALLS edges are resolved AFTER all files are indexed via
                    # resolve_project_calls() — this avoids ordering bugs where
                    # the callee's file hasn't been indexed yet.
                    calls = func.get("calls", [])
                    if isinstance(calls, str):
                        import json
                        try:
                            calls = json.loads(calls)
                        except (json.JSONDecodeError, TypeError):
                            calls = []

                    normalized_calls = [
                        c for raw in calls
                        if (c := _normalize_callee_name(raw, language))
                        and c != func_name
                    ]
                    if normalized_calls:
                        await session.run(
                            """
                            MATCH (fn:Function {qualified_name: $qname})
                            SET fn._pending_calls = $calls
                            """,
                            qname=qualified_name, calls=normalized_calls,
                        )
                        counts["calls"] += len(normalized_calls)

                    # IMPORTS edges
                    imports = func.get("imports", [])
                    if isinstance(imports, str):
                        import json
                        try:
                            imports = json.loads(imports)
                        except (json.JSONDecodeError, TypeError):
                            imports = []

                    for imp in imports:
                        if not imp:
                            continue
                        await session.run(
                            """
                            MERGE (m:Module {name: $mod_name})
                            ON CREATE SET m.project = $project
                            WITH m
                            MATCH (fn:Function {qualified_name: $qname})
                            MERGE (fn)-[:IMPORTS]->(m)
                            """,
                            mod_name=imp, project=project, qname=qualified_name,
                        )
                        counts["imports"] += 1

                    # BELONGS_TO class
                    if class_name and class_name not in classes_created:
                        await session.run(
                            """
                            MATCH (f:File {path: $fpath})
                            CREATE (c:Class {
                                name: $cname, file_path: $fpath,
                                language: $language, project: $project,
                                line_start: $line_start
                            })
                            CREATE (c)-[:DEFINED_IN]->(f)
                            """,
                            cname=class_name, fpath=file_path,
                            language=language, project=project,
                            line_start=func.get("line_start", 0),
                        )
                        classes_created.add(class_name)
                        counts["classes"] += 1

                    if class_name:
                        await session.run(
                            """
                            MATCH (fn:Function {qualified_name: $qname})
                            MATCH (c:Class {name: $cname, file_path: $fpath})
                            MERGE (fn)-[:BELONGS_TO]->(c)
                            """,
                            qname=qualified_name, cname=class_name, fpath=file_path,
                        )

            return counts

        except Exception as e:
            logger.error("Graph indexing error for %s: %s", file_path, e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Phase 2: Resolve pending CALLS edges for an entire project
    # ------------------------------------------------------------------

    async def resolve_project_calls(self, project: str) -> Dict[str, int]:
        """Resolve all CALLS edges for a project in one pass.

        Called AFTER all files in the project have been indexed.
        Reads ``_pending_calls`` list properties from Function nodes,
        matches callee names to real Function nodes within the same
        project, and creates CALLS edges.  Handles duplicate function
        names by creating edges to ALL matching definitions.

        This replaces the old per-file call resolution which was broken
        by file indexing order and LIMIT 1 on duplicate names.
        """
        if not self._driver:
            return {"error": "not connected"}

        try:
            async with self._driver.session() as session:
                # 1. Delete all existing CALLS edges for this project
                #    (they'll be recreated from _pending_calls)
                result = await session.run(
                    """
                    MATCH (caller:Function {project: $project})-[r:CALLS]->()
                    DELETE r
                    RETURN count(r) AS deleted
                    """,
                    project=project,
                )
                record = await result.single()
                deleted = record["deleted"] if record else 0

                # 2. Resolve pending calls → CALLS edges.
                #    For each caller, UNWIND its _pending_calls list and
                #    match each callee name to ALL real Function nodes in
                #    the project (not stubs).  MERGE is idempotent.
                result = await session.run(
                    """
                    MATCH (caller:Function {project: $project})
                    WHERE caller._pending_calls IS NOT NULL
                    UNWIND caller._pending_calls AS callee_name
                    WITH caller, callee_name
                    MATCH (callee:Function {name: callee_name, project: $project})
                    WHERE callee.file_path IS NOT NULL AND callee.file_path <> ''
                    MERGE (caller)-[:CALLS]->(callee)
                    RETURN count(*) AS edges_created
                    """,
                    project=project,
                )
                record = await result.single()
                created = record["edges_created"] if record else 0

                # 3. Clean up _pending_calls properties
                await session.run(
                    """
                    MATCH (fn:Function {project: $project})
                    WHERE fn._pending_calls IS NOT NULL
                    REMOVE fn._pending_calls
                    """,
                    project=project,
                )

                # 4. Clean up orphaned unresolved stubs from old indexing
                await session.run(
                    """
                    MATCH (stub:Function)
                    WHERE stub.qualified_name STARTS WITH 'unresolved::'
                      AND stub.project = $project
                    DETACH DELETE stub
                    """,
                    project=project,
                )

                logger.info(
                    "resolve_project_calls(%s): deleted %d old edges, "
                    "created %d new edges",
                    project, deleted, created,
                )
                return {"deleted": deleted, "created": created}

        except Exception as e:
            logger.error(
                "resolve_project_calls error for %s: %s", project, e,
            )
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Read: Query operations
    # ------------------------------------------------------------------

    async def get_callers(
        self,
        function_name: str,
        project: Optional[str] = None,
        file_path: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """Find functions that call the given function."""
        if not self._driver:
            return []

        try:
            query = """
                MATCH (caller:Function)-[:CALLS]->(callee:Function)
                WHERE callee.name = $name
            """
            params: Dict[str, Any] = {"name": function_name, "limit": limit}
            if file_path:
                query += " AND callee.file_path = $file_path"
                params["file_path"] = file_path
            if project:
                query += " AND caller.project = $project"
                params["project"] = project
            query += """
                RETURN caller.name AS name,
                       caller.qualified_name AS qualified_name,
                       caller.file_path AS file_path,
                       caller.language AS language,
                       caller.project AS project,
                       caller.line_start AS line_start
                LIMIT $limit
            """

            async with self._driver.session() as session:
                result = await session.run(query, **params)
                records = await result.data()
                return records

        except Exception as e:
            logger.error("get_callers error: %s", e)
            return []

    async def get_callees(
        self,
        function_name: str,
        project: Optional[str] = None,
        file_path: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """Find functions called by the given function."""
        if not self._driver:
            return []

        try:
            query = """
                MATCH (caller:Function)-[:CALLS]->(callee:Function)
                WHERE caller.name = $name
            """
            params: Dict[str, Any] = {"name": function_name, "limit": limit}
            if file_path:
                query += " AND caller.file_path = $file_path"
                params["file_path"] = file_path
            if project:
                query += " AND caller.project = $project"
                params["project"] = project
            query += """
                RETURN callee.name AS name,
                       callee.qualified_name AS qualified_name,
                       callee.file_path AS file_path,
                       callee.language AS language,
                       callee.project AS project
                LIMIT $limit
            """

            async with self._driver.session() as session:
                result = await session.run(query, **params)
                return await result.data()

        except Exception as e:
            logger.error("get_callees error: %s", e)
            return []

    async def get_call_chain(
        self,
        function_name: str,
        depth: int = 3,
        direction: str = "out",
        project: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Traverse call graph transitively."""
        if not self._driver:
            return []

        depth = min(max(depth, 1), 10)

        try:
            if direction == "in":
                query = f"""
                    MATCH path = (caller:Function)-[:CALLS*1..{depth}]->(target:Function)
                    WHERE target.name = $name
                """
            else:
                query = f"""
                    MATCH path = (source:Function)-[:CALLS*1..{depth}]->(callee:Function)
                    WHERE source.name = $name
                """

            params: Dict[str, Any] = {"name": function_name, "limit": limit}
            if project:
                if direction == "in":
                    query += " AND caller.project = $project"
                else:
                    query += " AND source.project = $project"
                params["project"] = project

            query += """
                UNWIND relationships(path) AS rel
                WITH startNode(rel) AS from_fn, endNode(rel) AS to_fn
                RETURN DISTINCT
                    from_fn.name AS caller,
                    from_fn.file_path AS caller_file,
                    to_fn.name AS callee,
                    to_fn.file_path AS callee_file
                LIMIT $limit
            """

            async with self._driver.session() as session:
                result = await session.run(query, **params)
                return await result.data()

        except Exception as e:
            logger.error("get_call_chain error: %s", e)
            return []

    async def get_file_functions(self, file_path: str) -> List[Dict]:
        """Get all functions defined in a file."""
        if not self._driver:
            return []

        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (fn:Function)-[:DEFINED_IN]->(f:File {path: $path})
                    RETURN fn.name AS name,
                           fn.qualified_name AS qualified_name,
                           fn.signature AS signature,
                           fn.line_start AS line_start,
                           fn.line_end AS line_end,
                           fn.is_async AS is_async,
                           fn.return_type AS return_type
                    ORDER BY fn.line_start
                    """,
                    path=file_path,
                )
                return await result.data()

        except Exception as e:
            logger.error("get_file_functions error: %s", e)
            return []

    async def get_cross_file_deps(
        self, file_path: str, limit: int = 20
    ) -> List[Dict]:
        """Find files that have functions calling functions in the given file."""
        if not self._driver:
            return []

        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (caller:Function)-[:CALLS]->(callee:Function)
                          -[:DEFINED_IN]->(f:File {path: $path})
                    WHERE caller.file_path <> $path
                    RETURN caller.file_path AS dependent_file,
                           count(DISTINCT caller) AS function_count,
                           collect(DISTINCT caller.name)[..5] AS sample_functions
                    ORDER BY function_count DESC
                    LIMIT $limit
                    """,
                    path=file_path, limit=limit,
                )
                return await result.data()

        except Exception as e:
            logger.error("get_cross_file_deps error: %s", e)
            return []

    async def find_orphan_functions(
        self,
        project: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Find functions with no inbound CALLS edges (orphans)."""
        if not self._driver:
            return []

        try:
            query = """
                MATCH (fn:Function)
                WHERE NOT exists((:Function)-[:CALLS]->(fn))
                  AND fn.file_path IS NOT NULL AND fn.file_path <> ''
                  AND NOT fn.name IN ['main', '__init__', '__main__']
                  AND NOT fn.name STARTS WITH '_'
            """
            params: Dict[str, Any] = {"limit": limit}
            if project:
                query += " AND fn.project = $project"
                params["project"] = project
            if language:
                query += " AND fn.language = $language"
                params["language"] = language

            query += """
                RETURN fn.name AS name,
                       fn.qualified_name AS qualified_name,
                       fn.file_path AS file_path,
                       fn.language AS language,
                       fn.project AS project,
                       fn.signature AS signature,
                       fn.line_start AS line_start
                ORDER BY fn.project, fn.file_path, fn.line_start
                LIMIT $limit
            """

            async with self._driver.session() as session:
                result = await session.run(query, **params)
                return await result.data()

        except Exception as e:
            logger.error("find_orphan_functions error: %s", e)
            return []

    async def get_stats(self) -> Dict[str, Any]:
        """Get node and edge counts by type."""
        if not self._driver:
            return {"connected": False}

        try:
            stats: Dict[str, Any] = {"connected": True}

            async with self._driver.session() as session:
                for label in ("Function", "File", "Class", "Module"):
                    result = await session.run(
                        f"MATCH (n:{label}) RETURN count(n) AS cnt"
                    )
                    record = await result.single()
                    stats[f"{label.lower()}_count"] = record["cnt"] if record else 0

                for rel_type in ("DEFINED_IN", "CALLS", "IMPORTS", "BELONGS_TO"):
                    result = await session.run(
                        f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt"
                    )
                    record = await result.single()
                    stats[f"{rel_type.lower()}_count"] = record["cnt"] if record else 0

            return stats

        except Exception as e:
            logger.error("get_stats error: %s", e)
            return {"connected": False, "error": str(e)}

    async def clear_file(self, file_path: str) -> bool:
        """Remove all graph data for a specific file."""
        if not self._driver:
            return False

        try:
            async with self._driver.session() as session:
                await session.run(
                    "MATCH (fn:Function {file_path: $path}) DETACH DELETE fn",
                    path=file_path,
                )
                await session.run(
                    "MATCH (c:Class {file_path: $path}) DETACH DELETE c",
                    path=file_path,
                )
                await session.run(
                    "MATCH (f:File {path: $path}) DETACH DELETE f",
                    path=file_path,
                )
            return True

        except Exception as e:
            logger.error("clear_file error: %s", e)
            return False
