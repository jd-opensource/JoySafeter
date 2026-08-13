#!/usr/bin/env python3
"""
JoySafeter 第三方系统调用示例：SSE 流式获取 Agent 输出。

依赖：
  pip install requests

环境变量：
  JOYSAFETER_BASE          例如 http://joysafeter-api.joysafeter-pre.svc.cluster.local:8000/api/v1
  JOYSAFETER_API_KEY       API Key
  JOYSAFETER_AGENT_ID      agent_xxx
  JOYSAFETER_DEBUG_EVENTS    设为 1 时打印无法解析的 agent.message 原始事件
  JOYSAFETER_VERBOSE_EVENTS  设为 1 时打印所有事件/工具调用日志

运行：
  python joysafeter_run_agent_sse.py "请分析这个需求，并给出实现方案。"
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Iterable

import requests


BASE = os.getenv("JOYSAFETER_BASE", "http://<joysafeter-api-host>/api/v1").rstrip("/")
API_KEY = os.getenv("JOYSAFETER_API_KEY", "<your-api-key>")
AGENT_ID = os.getenv("JOYSAFETER_AGENT_ID", "agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111")
DEBUG_EVENTS = os.getenv("JOYSAFETER_DEBUG_EVENTS", "").lower() in {"1", "true", "yes", "on"}
VERBOSE_EVENTS = os.getenv("JOYSAFETER_VERBOSE_EVENTS", "").lower() in {"1", "true", "yes", "on"}

# 项目实际使用的输出事件见：
# backend/app/joysafeter_orchestrator_rs/src/events/mapping.rs
AGENT_MESSAGE = "agent.message"
SESSION_RUNNING = "session.status_running"
SESSION_IDLE = "session.status_idle"
SESSION_TERMINATED = "session.status_terminated"
SESSION_ERROR = "session.error"

TOOL_USE_EVENTS = {
    "agent.tool_use",
    "agent.mcp_tool_use",
    "agent.custom_tool_use",
}
TOOL_RESULT_EVENTS = {
    "agent.tool_result",
    "agent.mcp_tool_result",
}
BACKGROUND_TASK_EVENTS = {
    "agent.bg_task_started",
    "agent.bg_task_progress",
    "agent.bg_task_finished",
}
MODEL_SPAN_EVENTS = {
    "span.model_request_start",
    "span.model_request_end",
}


def log(message: str) -> None:
    # 日志走 stderr，stdout 默认只保留 agent.message 正文，方便第三方系统直接读取结果。
    print(message, file=sys.stderr, flush=True)


class JoySafeterError(RuntimeError):
    pass


def api_headers() -> dict[str, str]:
    return {
        "X-Api-Key": API_KEY,
        "Content-Type": "application/json",
    }


def unwrap_json(resp: requests.Response) -> Any:
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and body.get("success") is False:
        raise JoySafeterError(f"JoySafeter API error: {body}")
    return body.get("data") if isinstance(body, dict) and "data" in body else body


def create_session(request_id: str) -> str:
    payload = {
        "agent": AGENT_ID,
        "title": f"third-party-run-{request_id}",
        "metadata": {
            "source": "third-party",
            "request_id": request_id,
        },
    }
    resp = requests.post(f"{BASE}/sessions", headers=api_headers(), json=payload, timeout=30)
    data = unwrap_json(resp)
    return data["id"]


def send_message(session_id: str, prompt: str, request_id: str) -> None:
    payload = {
        "type": "user.message",
        "content": prompt,
    }
    headers = {
        **api_headers(),
        "Idempotency-Key": request_id,
    }
    resp = requests.post(f"{BASE}/sessions/{session_id}/events", headers=headers, json=payload, timeout=30)
    unwrap_json(resp)


def _text_parts_from_content(content: Any) -> Iterable[str]:
    """提取 JoySafeter content 文本。

    项目里 agent.message 的 payload 形态是：
      {"content": [{"type": "text", "text": "..."}]}

    user.message 也可能是：
      {"content": "..."}
    """
    if isinstance(content, str):
        yield content
        return

    if isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                yield item
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    yield text


def extract_agent_message_text(event: dict[str, Any]) -> str:
    content = event.get("content")

    # 正常 API/SSE 会把 payload 扁平化到顶层；这里兼容极少数内部调试场景。
    if content is None and isinstance(event.get("payload"), dict):
        content = event["payload"].get("content")

    return "".join(_text_parts_from_content(content))


def session_error_message(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(event.get("message"), str):
        return event["message"]
    return json.dumps(event, ensure_ascii=False)


def parse_sse_events(response: requests.Response):
    """一个轻量 SSE parser，避免额外依赖 sseclient。"""
    event_id: str | None = None
    data_lines: list[str] = []

    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue

        line = raw_line.rstrip("\r")

        # 空行表示一个 SSE event 结束
        if line == "":
            if data_lines:
                yield {
                    "id": event_id,
                    "data": "\n".join(data_lines),
                }
            event_id = None
            data_lines = []
            continue

        # 注释 / heartbeat
        if line.startswith(":"):
            continue

        if line.startswith("id:"):
            event_id = line[3:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        yield {
            "id": event_id,
            "data": "\n".join(data_lines),
        }


def stream_events(session_id: str, after_seq: int = 0) -> dict[str, Any]:
    url = f"{BASE}/sessions/{session_id}/events/stream?after_seq={after_seq}"
    headers = {
        "X-Api-Key": API_KEY,
        "Accept": "text/event-stream",
    }

    answer_parts: list[str] = []
    last_seq = after_seq

    with requests.get(url, headers=headers, stream=True, timeout=None) as resp:
        resp.raise_for_status()

        for sse in parse_sse_events(resp):
            raw_data = sse.get("data") or ""
            if not raw_data:
                continue

            try:
                event = json.loads(raw_data)
            except json.JSONDecodeError:
                log(f"[sse] non-json data: {raw_data}")
                continue

            if event.get("lagged") is True:
                raise JoySafeterError("SSE 队列发生 lagged，请用 last_seq 重连并回放 DB 事件")

            event_type = event.get("type")
            seq = event.get("seq")
            if isinstance(seq, int):
                last_seq = seq

            if VERBOSE_EVENTS:
                log(f"[event] seq={seq} type={event_type}")

            if event_type == AGENT_MESSAGE:
                text = extract_agent_message_text(event)
                if text:
                    print(text, end="", flush=True)
                    answer_parts.append(text)
                elif DEBUG_EVENTS:
                    log(f"[debug] empty agent.message raw={json.dumps(event, ensure_ascii=False)}")

            elif event_type == SESSION_RUNNING:
                if VERBOSE_EVENTS:
                    log("Agent 开始运行")

            elif event_type == SESSION_IDLE:
                if VERBOSE_EVENTS:
                    log("Agent 本轮运行结束")
                break

            elif event_type == SESSION_ERROR:
                raise JoySafeterError(f"session.error: {session_error_message(event)}")

            elif event_type == SESSION_TERMINATED:
                raise JoySafeterError(f"session terminated: {json.dumps(event, ensure_ascii=False)}")

            elif event_type in TOOL_USE_EVENTS:
                if VERBOSE_EVENTS:
                    log(f"[tool_use] {event.get('name') or ''}")

            elif event_type in TOOL_RESULT_EVENTS:
                if VERBOSE_EVENTS:
                    log("[tool_result]")

            elif event_type in BACKGROUND_TASK_EVENTS:
                desc = event.get("description") or event.get("summary") or event.get("status") or ""
                if VERBOSE_EVENTS:
                    log(f"[bg_task] {event_type} {desc}".rstrip())

            elif event_type == "agent.thinking" or event_type in MODEL_SPAN_EVENTS:
                # 这些是项目内真实事件，但不是最终回答内容；保留 [event] 行即可。
                pass

    return {
        "last_seq": last_seq,
        "answer": "".join(answer_parts),
    }


def main() -> None:
    prompt = " ".join(sys.argv[1:]).strip() or "请分析这个需求，并给出实现方案。"
    request_id = f"req-{uuid.uuid4()}"

    log(f"request_id={request_id}")

    session_id = create_session(request_id)
    log(f"session_id={session_id}")

    send_message(session_id, prompt, request_id)
    result = stream_events(session_id, after_seq=0)

    log("\n===== FINAL RESULT =====")
    log(f"session_id={session_id}")
    log(f"last_seq={result['last_seq']}")
    if not result["answer"]:
        log("未提取到 agent.message 文本；可设置 JOYSAFETER_DEBUG_EVENTS=1 查看原始事件。")
    else:
        print()


if __name__ == "__main__":
    main()
