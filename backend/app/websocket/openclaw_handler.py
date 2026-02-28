"""
WebSocket handlers for OpenClaw integration.

Endpoint: /ws/openclaw/bridge/{user_id} — Bidirectional bridge to OpenClaw Gateway WS
"""

import asyncio

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.database import AsyncSessionLocal
from app.services.openclaw_instance_service import OpenClawInstanceService


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


openclaw_bridge_handler = OpenClawBridgeHandler()
