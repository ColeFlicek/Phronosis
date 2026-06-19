from __future__ import annotations

import dataclasses
import time
from datetime import datetime, timezone

from .analysis import ArchitectureAnalyzer
from .call_graph.storage import CallGraphDB


class ArchitectureService:
    """
    Coordinator for the architectural intelligence pipeline.

    Owns three concerns that do not belong in the storage layer:
    - running ArchitectureAnalyzer over raw graph data
    - persisting the snapshot (via CallGraphDB.save_project_snapshot)
    - in-memory TTL cache so repeated calls within the same process
      don't re-run 8 SQL queries and the analyzer on every request

    CallGraphDB.fetch_graph_data provides the raw SQL bundle.
    ArchitectureAnalyzer.snapshot transforms it.
    This class orchestrates.
    """

    def __init__(self, db: CallGraphDB) -> None:
        self._db = db
        self._cache: dict[str, tuple[float, dict]] = {}

    async def get_project_home(
        self, project_id: str, max_age_seconds: int = 0
    ) -> dict:
        """
        Return a full architectural snapshot for project_id.

        max_age_seconds: if > 0 and a cached result is younger than this,
        return it without re-running queries and the analyzer. 0 always
        recomputes.
        """
        if max_age_seconds > 0:
            cached = self._cache.get(project_id)
            if cached and (time.monotonic() - cached[0]) < max_age_seconds:
                return cached[1]

        data = await self._db.fetch_graph_data(project_id)
        snapshot = ArchitectureAnalyzer().snapshot(data)
        result = dataclasses.asdict(snapshot)

        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.save_project_snapshot(project_id, data.current_hashes, now_iso)

        self._cache[project_id] = (time.monotonic(), result)
        return result
