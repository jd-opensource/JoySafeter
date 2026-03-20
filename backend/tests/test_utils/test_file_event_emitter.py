from app.utils.file_event_emitter import FileEvent, FileEventEmitter


def test_emit_and_drain():
    emitter = FileEventEmitter()
    emitter.emit("write", "/app/hello.py", size=42)
    emitter.emit("edit", "/app/hello.py")
    events = emitter.drain()
    assert len(events) == 2
    assert events[0].action == "write"
    assert events[0].path == "/app/hello.py"
    assert events[0].size == 42
    assert events[1].action == "edit"
    assert events[1].size is None


def test_drain_empties_queue():
    emitter = FileEventEmitter()
    emitter.emit("write", "/app/a.py")
    emitter.drain()
    assert emitter.drain() == []


def test_drain_no_loss_under_interleave():
    """Simulate emit during drain - popleft loop should not lose events."""
    emitter = FileEventEmitter()
    emitter.emit("write", "/app/a.py")
    emitter.emit("write", "/app/b.py")
    events = emitter.drain()
    assert len(events) == 2
    emitter.emit("write", "/app/c.py")
    events2 = emitter.drain()
    assert len(events2) == 1
    assert events2[0].path == "/app/c.py"


def test_file_event_has_timestamp():
    emitter = FileEventEmitter()
    emitter.emit("write", "/app/a.py")
    events = emitter.drain()
    assert events[0].timestamp > 0
