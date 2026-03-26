from unittest.mock import MagicMock

from deepagents.backends.protocol import EditResult, FileUploadResponse, WriteResult

from app.core.agent.backends.file_tracking_proxy import FileTrackingProxy
from app.utils.file_event_emitter import FileEventEmitter


def _make_mock_backend():
    backend = MagicMock()
    backend.id = "test-sandbox"
    backend.is_started.return_value = True
    return backend


def test_write_success_emits_event():
    backend = _make_mock_backend()
    backend.write.return_value = WriteResult(path="/app/hello.py", files_update=None)
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.write("/app/hello.py", "print('hi')")
    assert result.path == "/app/hello.py"
    events = emitter.drain()
    assert len(events) == 1
    assert events[0].action == "write"
    assert events[0].path == "/app/hello.py"
    assert events[0].size == len("print('hi')".encode("utf-8"))


def test_write_error_does_not_emit():
    backend = _make_mock_backend()
    backend.write.return_value = WriteResult(error="File exists")
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.write("/app/hello.py", "x")
    assert result.error
    assert emitter.drain() == []


def test_edit_success_emits_event():
    backend = _make_mock_backend()
    backend.edit.return_value = EditResult(path="/app/hello.py", files_update=None, occurrences=1)
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.edit("/app/hello.py", "old", "new")
    assert result.path == "/app/hello.py"
    events = emitter.drain()
    assert len(events) == 1
    assert events[0].action == "edit"


def test_write_overwrite_emits_write():
    backend = _make_mock_backend()
    backend.write_overwrite.return_value = WriteResult(path="/app/a.py", files_update=None)
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    proxy.write_overwrite("/app/a.py", "content")
    events = emitter.drain()
    assert events[0].action == "write"


def test_upload_files_emits_per_file():
    backend = _make_mock_backend()
    backend.upload_files.return_value = [
        FileUploadResponse(path="/app/a.py", error=None),
        FileUploadResponse(path="/app/b.py", error="fail"),
    ]
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    proxy.upload_files([("/app/a.py", b"aa"), ("/app/b.py", b"bb")])
    events = emitter.drain()
    assert len(events) == 1
    assert events[0].path == "/app/a.py"


def test_read_delegates_without_emit():
    backend = _make_mock_backend()
    backend.read.return_value = "file content"
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.read("/app/hello.py")
    assert result == "file content"
    assert emitter.drain() == []
    backend.read.assert_called_once_with("/app/hello.py")


def test_raw_read_delegates_without_emit():
    backend = _make_mock_backend()
    backend.raw_read.return_value = "raw file content"
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.raw_read("/app/hello.py")
    assert result == "raw file content"
    assert emitter.drain() == []
    backend.raw_read.assert_called_once_with("/app/hello.py")


def test_getattr_fallback():
    backend = _make_mock_backend()
    backend.some_new_method.return_value = "ok"
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    assert proxy.some_new_method() == "ok"
