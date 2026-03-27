# Typed Chat Parser Routing Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure the typed chat transport parser keeps skewed frames from falling through as unknown, while keeping ping/legacy resume/stop dispatch stable.

**Architecture:** Normalize typed transport names inside `parse_client_frame`, validate `chat.start` unconditionally, and let `ChatWsHandler` dispatch both typed and legacy frames without regressing ping handling.

**Tech Stack:** FastAPI WebSocket, asyncio, pytest, dataclasses.

---

### Task 1: Parser validation and normalization

**Files:** `backend/app/websocket/chat_protocol.py`, `backend/tests/test_api/test_chat_protocol.py`

- [ ] **Step 1: Add parser regression tests**

```python
def test_parse_ping_frame_bypasses_error():
    parsed = parse_client_frame({"type": "ping"})
    assert isinstance(parsed, dict)
    assert parsed["type"] == "ping"


def test_parse_chat_start_without_input_raises():
    with pytest.raises(ChatProtocolError) as exc:
        parse_client_frame({"type": "chat.start", "request_id": "req-bad"})
    assert "input" in exc.value.message.lower()


def test_parse_chat_resume_and_stop_return_dicts():
    assert parse_client_frame({"type": "chat.resume", "request_id": "req-r"}).get("type") == "chat.resume"
    assert parse_client_frame({"type": "chat.stop", "request_id": "req-s"}).get("type") == "chat.stop"
```

- [ ] **Step 2: Run parser tests to capture failure**
  Run: `SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_protocol.py -k "parse_ping_frame_bypasses_error or parse_chat_start_without_input_raises" -v`
  Expected: FAIL because `parse_client_frame` currently raises for ping or skips chat.start validation.

- [ ] **Step 3: Implement parser normalization**

```python
if frame_type == "chat.start":
    return _parse_chat_start_frame(frame)
if frame_type == "chat.resume":
    return frame
if frame_type == "chat.stop":
    return frame
if frame_type == "ping":
    return frame
if frame_type == "chat" and isinstance(frame.get("input"), dict):
    return _parse_chat_start_frame(frame)
raise ChatProtocolError(...)
```

and update `_parse_chat_start_frame` to raise when the `input` envelope is missing or not a dict.

- [ ] **Step 4: Re-run parser tests**
  Run: `SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_protocol.py -v` → expect PASS.

### Task 2: Handler routing for typed frames

**Files:** `backend/app/websocket/chat_ws_handler.py`, `backend/tests/test_api/test_chat_ws_handler.py`

- [ ] **Step 1: Add handler tests for typed resume/stop routing**

```python
@pytest.mark.asyncio
async def test_typed_resume_routes_to_resume_handler():
    handler, _ = make_handler()
    with patch.object(handler, "_handle_resume") as mock_resume:
        await handler._handle_frame(json.dumps({"type": "chat.resume", "request_id": "req", "thread_id": "t", "command": {}}))
    mock_resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_typed_stop_routes_to_stop_handler():
    handler, _ = make_handler()
    with patch.object(handler, "_handle_stop") as mock_stop:
        await handler._handle_frame(json.dumps({"type": "chat.stop", "request_id": "req"}))
    mock_stop.assert_awaited_once()
```

- [ ] **Step 2: Run handler tests to see failure**
  Run: `SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_ws_handler.py -k "typed_resume_routes_to_resume_handler or typed_stop_routes_to_stop_handler" -v`
  Expected: FAIL because typed frames currently hit the unknown-frame branch.

- [ ] **Step 3: Update handler dispatch logic**

```python
frame_type = parsed_frame.get("type")
if frame_type in {"chat.resume", "resume"}:
    await self._handle_resume(parsed_frame)
    return
if frame_type in {"chat.stop", "stop"}:
    await self._handle_stop(parsed_frame)
    return
if frame_type == "ping":
    await self._send({"type": "pong"})
    return
```

- [ ] **Step 4: Re-run handler tests**
  Run: `SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_ws_handler.py::test_ping_returns_pong backend/tests/test_api/test_chat_ws_handler.py -v` → expect PASS.

### Task 3: Cross-file verification

**Files:** same as above

- [ ] **Step 1: Run combined regression tests**
  Run: `SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_protocol.py backend/tests/test_api/test_chat_ws_handler.py -v`
  Expect: PASS.

- [ ] **Step 2: Capture test output and note any new expectations for documentation or future follow-ups.
