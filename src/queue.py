from __future__ import annotations

import os

from redis import Redis
from rq import Queue

QUEUE_NAME = "acip-indexing"


def get_redis() -> Redis:
    """Return a Redis connection from REDIS_URL env var (default: localhost)."""
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return Redis.from_url(url)


def get_queue() -> Queue:
    """Return the ACIP indexing queue."""
    return Queue(QUEUE_NAME, connection=get_redis())
