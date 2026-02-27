"""
WebSocket handlers for OpenClaw integration.

Two endpoints:
1. /ws/openclaw/{task_id}  — Task output streaming via Redis Pub/Sub
2. /ws/openclaw/bridge/{user_id} — Bidirectional bridge to OpenClaw Gateway WS
"""

import asyncio
import json

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from starlette.websockets import WebSocketState

from app.core.database import AsyncSessionLocal
from app.core.redis import RedisClient
from app.services.openclaw_instance_service import OpenClawInstanceService


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


class OpenClawBridgeHandler:
    """Bidirectional WebSocket bridge between client and OpenClaw Gateway."""

    async def handle_bridge(self, ws: WebSocket, user_id: str) -> None:
        """Bridge client WS ↔ OpenClaw Gateway WS for real-time protocol access."""
        try:
            await ws.accept()
        except Exception as e:
            logger.error(f"Failed to accept bridge WS for user {user_id}: {e}")
            return

        # Look up the user's instance
        async with AsyncSessionLocal() as db:
            service = OpenClawInstanceService(db)
            instance = await service.get_instance_by_user(user_id)

        if not instance or instance.status != "running":
            await ws.close(code=1008, reason="No running OpenClaw instance")
            return

        gateway_ws_url = f"ws://127.0.0.1:{instance.gateway_port}"
        logger.info(f"OpenClaw bridge connecting: user={user_id} -> {gateway_ws_url}")

        try:
            async with websockets.connect(
                gateway_ws_url,
                additional_headers={"Authorization": f"Bearer {instance.gateway_token}"},
            ) as gw_ws:
                # Run two forwarding loops concurrently
                client_to_gw = asyncio.create_task(
                    self._forward_client_to_gateway(ws, gw_ws, user_id)
                )
                gw_to_client = asyncio.create_task(
                    self._forward_gateway_to_client(ws, gw_ws, user_id)
                )

                done, pending = await asyncio.wait(
                    [client_to_gw, gw_to_client],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

        except Exception as e:
            logger.error(f"OpenClaw bridge error for user {user_id}: {e}")
            try:
                await ws.close(code=1011, reason=str(e))
            except Exception:
                pass

    async def _forward_client_to_gateway(self, client_ws: WebSocket, gw_ws, user_id: str):
        try:
            while True:
                data = await client_ws.receive_text()
                await gw_ws.send(data)
        except WebSocketDisconnect:
            logger.info(f"Client disconnected from bridge: user={user_id}")
        except Exception as e:
            logger.debug(f"Client->GW bridge ended: user={user_id}, {e}")

    async def _forward_gateway_to_client(self, client_ws: WebSocket, gw_ws, user_id: str):
        try:
            async for message in gw_ws:
                if isinstance(message, str):
                    await client_ws.send_text(message)
                elif isinstance(message, bytes):
                    await client_ws.send_bytes(message)
        except WebSocketDisconnect:
            logger.info(f"Gateway disconnected from bridge: user={user_id}")
        except Exception as e:
            logger.debug(f"GW->Client bridge ended: user={user_id}, {e}")


openclaw_handler = OpenClawWebSocketHandler()
openclaw_bridge_handler = OpenClawBridgeHandler()
