"""
WebSocket handler for OpenClaw task output streaming.
Subscribes to Redis Pub/Sub channel ``openclaw:task:{task_id}``
and forwards events to the connected WebSocket client.

Mirrors the pattern established by ``copilot_handler.py``.
"""

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from starlette.websockets import WebSocketState

from app.core.redis import RedisClient


class OpenClawWebSocketHandler:
    """Handles per-task WebSocket connections for real-time output."""

    def _is_connected(self, ws: WebSocket) -> bool:
        try:
            return ws.client_state == WebSocketState.CONNECTED
        except Exception:
            return False

    async def _safe_send(self, ws: WebSocket, text: str, task_id: str) -> bool:
        if not self._is_connected(ws):
            return False
        try:
            await ws.send_text(text)
            return True
        except WebSocketDisconnect:
            logger.info(f"OpenClaw WS disconnected while sending: task_id={task_id}")
            return False
        except RuntimeError as e:
            if "not connected" in str(e).lower() or "accept" in str(e).lower():
                return False
            raise
        except Exception as e:
            logger.error(f"OpenClaw WS send error: task_id={task_id}, {e}")
            return False

    async def handle_connection(self, ws: WebSocket, task_id: str) -> None:
        if not RedisClient.is_available():
            try:
                await ws.close(code=1011, reason="Redis not available")
            except Exception:
                pass
            return

        try:
            await ws.accept()
        except Exception as e:
            logger.error(f"Failed to accept OpenClaw WS: task_id={task_id}, {e}")
            return

        logger.info(f"OpenClaw WS connected: task_id={task_id}")

        pubsub = None
        channel = f"openclaw:task:{task_id}"

        try:
            redis_client = RedisClient.get_client()
            if not redis_client:
                try:
                    if self._is_connected(ws):
                        await ws.close(code=1011, reason="Redis client not available")
                except Exception:
                    pass
                return

            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel)

            while self._is_connected(ws):
                try:
                    redis_task = asyncio.create_task(
                        asyncio.wait_for(pubsub.get_message(), timeout=1.0)
                    )
                    ws_task = asyncio.create_task(
                        asyncio.wait_for(ws.receive_text(), timeout=1.0)
                    )

                    done, pending = await asyncio.wait(
                        [redis_task, ws_task], return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in pending:
                        t.cancel()
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass

                    if redis_task in done:
                        try:
                            message = await redis_task
                            if message and message.get("type") == "message":
                                try:
                                    event = json.loads(message["data"])
                                    sent = await self._safe_send(
                                        ws, json.dumps(event, ensure_ascii=False), task_id
                                    )
                                    if not sent:
                                        break
                                    if event.get("type") in ("done", "error", "cancelled"):
                                        try:
                                            await ws.close(code=1000, reason="Task finished")
                                        except Exception:
                                            pass
                                        break
                                except json.JSONDecodeError as e:
                                    logger.error(f"Bad Redis message for task {task_id}: {e}")
                        except asyncio.TimeoutError:
                            pass
                        except Exception as e:
                            logger.error(f"Redis read error for task {task_id}: {e}")
                            if not self._is_connected(ws):
                                break

                    if ws_task in done:
                        try:
                            client_msg = await ws_task
                            if client_msg:
                                try:
                                    msg_data = json.loads(client_msg)
                                    if msg_data.get("type") == "ping":
                                        sent = await self._safe_send(
                                            ws, json.dumps({"type": "pong"}), task_id
                                        )
                                        if not sent:
                                            break
                                except json.JSONDecodeError:
                                    pass
                        except asyncio.TimeoutError:
                            pass
                        except WebSocketDisconnect:
                            break
                        except Exception as e:
                            err = str(e).lower()
                            if "not connected" in err or "accept" in err:
                                break
                            if not self._is_connected(ws):
                                break

                except WebSocketDisconnect:
                    break
                except Exception as e:
                    err = str(e).lower()
                    if "not connected" in err or "accept" in err:
                        break
                    if not self._is_connected(ws):
                        break
                    await asyncio.sleep(0.1)

        except WebSocketDisconnect:
            logger.info(f"OpenClaw WS disconnected: task_id={task_id}")
        except Exception as e:
            logger.error(f"OpenClaw WS error: task_id={task_id}, {e}")
            try:
                if self._is_connected(ws):
                    await ws.close(code=1011)
            except Exception:
                pass
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception as e:
                    logger.warning(f"Error cleaning up OpenClaw Pub/Sub: {e}")


openclaw_handler = OpenClawWebSocketHandler()
