"""
Clone a repo at a specific commit and optionally ACIP-index it for Path B runs.

Each call creates a fresh isolated directory — safe for parallel task runs.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .loader import BenchmarkTask

# Cache of indexed commits: base_commit → ACIP project_id
# Avoids re-indexing the same commit if multiple tasks share it.
_indexed_commits: dict[str, str] = {}


@dataclass
class RepoContext:
    task: BenchmarkTask
    repo_path: str           # absolute path to checked-out repo
    project_id: str          # ACIP project_id (Path B only)
    acip_indexed: bool       # True if ACIP index was built


def setup_repo(
    task: BenchmarkTask,
    *,
    acip_index: bool = False,
    acip_dsn: str = "",
    workdir: str | None = None,
) -> RepoContext:
    """
    Clone the repo at base_commit into a temp directory.

    acip_index: if True, index the checkout with ACIP for Path B.
    acip_dsn:   Postgres DSN for ACIP (falls back to DATABASE_URL env var).
    workdir:    parent directory for the checkout; uses a new temp dir if None.
    """
    parent = workdir or tempfile.mkdtemp(prefix="acip-bench-")
    repo_path = os.path.join(parent, task.instance_id)

    org, name = task.repo.split("/")
    clone_url = f"https://github.com/{org}/{name}.git"

    print(f"[setup] cloning {task.repo}@{task.base_commit[:8]} → {repo_path}")
    subprocess.run(
        ["git", "clone", "--quiet", clone_url, repo_path],
        check=True,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", task.base_commit],
        cwd=repo_path,
        check=True,
    )

    project_id = ""
    indexed = False

    if acip_index:
        project_id = _ensure_indexed(task, repo_path, acip_dsn)
        indexed = True

    return RepoContext(
        task=task,
        repo_path=repo_path,
        project_id=project_id,
        acip_indexed=indexed,
    )


def _ensure_indexed(task: BenchmarkTask, repo_path: str, dsn: str) -> str:
    """Index the repo with ACIP; reuse if same commit was already indexed."""
    import asyncio
    commit = task.base_commit
    if commit in _indexed_commits:
        print(f"[setup] reusing ACIP index for {commit[:8]}")
        return _indexed_commits[commit]

    project_id = f"bench-{task.instance_id}"
    print(f"[setup] ACIP indexing {repo_path} as project '{project_id}'")

    async def _index():
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.call_graph.storage import CallGraphDB
        from src.embeddings.embedder import EmbeddingStore
        from src.embeddings.pipeline import EmbeddingPipeline
        from src.indexer import Indexer

        resolved_dsn = dsn or os.getenv("DATABASE_URL", "postgresql://acip:acip@localhost/acip")
        db = await CallGraphDB.create(resolved_dsn)
        embeddings = await EmbeddingStore.create(db)
        pipeline = EmbeddingPipeline(db, embeddings)
        indexer = Indexer(db, pipeline)
        result = await indexer.index_project(repo_path, project_id=project_id)
        await db.close()
        print(f"[setup] indexed {result.get('functions_indexed', 0)} functions")

    asyncio.run(_index())
    _indexed_commits[commit] = project_id
    return project_id


def cleanup_repo(ctx: RepoContext) -> None:
    """Remove the cloned repo directory."""
    import shutil
    if os.path.exists(ctx.repo_path):
        shutil.rmtree(ctx.repo_path)
        print(f"[setup] cleaned up {ctx.repo_path}")
