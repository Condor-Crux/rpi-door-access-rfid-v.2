import asyncio
import json
from typing import AsyncGenerator

from sqlalchemy import text

from app.infrastructure.database import engine


class EventBroadcaster:
    """Cross-process pub/sub for Server-Sent Events, backed by a SQLite table.

    The previous implementation kept subscribers in an in-memory list, so it
    only worked inside a single process: an event published by one worker (or
    by the RFID poll loop) never reached SSE clients connected to another
    worker. Persisting events to a shared table and polling it means every
    process — and therefore every open browser — sees the same stream.

    publish() appends a row; subscribe() polls for rows newer than the last id
    it has seen and yields them as payload dicts for the caller to format into
    SSE frames. Rendering is deliberately left out so domain code stays
    presentation-agnostic.
    """

    def __init__(self, poll_interval: float = 1.0, retain: int = 1000) -> None:
        self._poll_interval = poll_interval
        self._retain = retain  # prune the table to roughly the last N rows

    def publish(self, event_type: str, data: dict) -> None:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO sse_events (event_type, data) VALUES (:t, :d)"),
                {"t": event_type, "d": json.dumps(data)},
            )
            # Bound table growth: drop everything older than the last `retain` rows.
            conn.execute(
                text(
                    "DELETE FROM sse_events WHERE id <= "
                    "(SELECT MAX(id) FROM sse_events) - :retain"
                ),
                {"retain": self._retain},
            )

    def _max_id(self) -> int:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT MAX(id) FROM sse_events")).scalar()
            return row or 0

    def _fetch_after(self, last_id: int) -> list[tuple[int, str, str]]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, event_type, data FROM sse_events "
                    "WHERE id > :last ORDER BY id"
                ),
                {"last": last_id},
            ).all()
        return [(r[0], r[1], r[2]) for r in rows]

    async def subscribe(self) -> AsyncGenerator[dict, None]:
        # Start from the current tail so a new subscriber only gets fresh events.
        last_id = await asyncio.to_thread(self._max_id)
        yield {"event": "ready", "data": {}}
        idle = 0.0
        while True:
            rows = await asyncio.to_thread(self._fetch_after, last_id)
            if rows:
                idle = 0.0
                for row_id, event_type, raw in rows:
                    last_id = row_id
                    yield {"event": event_type, "data": json.loads(raw)}
            else:
                # Keep the connection alive through proxies with a periodic ping.
                idle += self._poll_interval
                if idle >= 15.0:
                    idle = 0.0
                    yield {"event": "ping", "data": None}
            await asyncio.sleep(self._poll_interval)


broadcaster = EventBroadcaster()
