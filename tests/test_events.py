import asyncio

import pytest
from sqlalchemy import create_engine, text

import app.core.events as events_module
from app.core.events import EventBroadcaster


@pytest.fixture
def broadcaster(tmp_path, monkeypatch):
    """A broadcaster backed by an isolated on-disk SQLite db.

    An on-disk (not :memory:) db is essential: the whole point of the table is
    that independent connections — i.e. separate processes/workers — share the
    same event stream. Each engine.connect() here stands in for a worker.
    """
    db_path = tmp_path / "events.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE sse_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_type VARCHAR NOT NULL, data TEXT NOT NULL, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        ))
    monkeypatch.setattr(events_module, "engine", engine)
    return EventBroadcaster(poll_interval=0.01)


async def _next(agen, timeout=2.0):
    return await asyncio.wait_for(agen.__anext__(), timeout=timeout)


def test_subscriber_starts_at_tail(broadcaster):
    """Events published before subscribing are not replayed — live stream only."""
    async def scenario():
        broadcaster.publish("swipe", {"x": "old"})
        agen = broadcaster.subscribe()
        assert (await _next(agen))["event"] == "ready"
        broadcaster.publish("swipe", {"x": "new"})
        evt = await _next(agen)
        assert evt == {"event": "swipe", "data": {"x": "new"}}
        await agen.aclose()

    asyncio.run(scenario())


def test_event_fans_out_to_all_subscribers(broadcaster):
    """One publish reaches every open subscriber (every browser)."""
    async def scenario():
        a, b = broadcaster.subscribe(), broadcaster.subscribe()
        assert (await _next(a))["event"] == "ready"
        assert (await _next(b))["event"] == "ready"
        broadcaster.publish("kpi", {"total": 7})
        ea, eb = await _next(a), await _next(b)
        assert ea == eb == {"event": "kpi", "data": {"total": 7}}
        await a.aclose()
        await b.aclose()

    asyncio.run(scenario())


def test_cross_process_delivery(broadcaster):
    """An event written via a separate engine connection still reaches the
    subscriber — the table is the shared channel, not in-process memory."""
    async def scenario():
        agen = broadcaster.subscribe()
        assert (await _next(agen))["event"] == "ready"
        # Simulate a different worker: write straight to the table on its own conn.
        with events_module.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO sse_events (event_type, data) VALUES ('swipe', '{\"who\": \"worker-2\"}')")
            )
        evt = await _next(agen)
        assert evt == {"event": "swipe", "data": {"who": "worker-2"}}
        await agen.aclose()

    asyncio.run(scenario())


def test_ordering_preserved(broadcaster):
    """Multiple events between polls arrive in publish order."""
    async def scenario():
        agen = broadcaster.subscribe()
        assert (await _next(agen))["event"] == "ready"
        for i in range(3):
            broadcaster.publish("swipe", {"n": i})
        got = [(await _next(agen))["data"]["n"] for _ in range(3)]
        assert got == [0, 1, 2]
        await agen.aclose()

    asyncio.run(scenario())


def test_retention_prunes_old_rows(broadcaster):
    """The table is bounded to roughly the last `retain` rows."""
    broadcaster._retain = 5
    for i in range(20):
        broadcaster.publish("swipe", {"n": i})
    with events_module.engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM sse_events")).scalar()
    assert count <= 6  # last `retain` rows plus the freshly inserted one
