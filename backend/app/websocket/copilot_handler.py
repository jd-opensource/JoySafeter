"""
WebSocket handler for Copilot real-time streaming.
Subscribes to Redis Pub/Sub and forwards events to WebSocket clients.
"""

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from starlette.websockets import WebSocketState

from app.core.redis import RedisClient


class CopilotWebSocketHandler:
    """Handles WebSocket connections for Copilot session subscriptions."""

    def __init__(self):
        self.active_subscriptions: dict[str, asyncio.Task] = {}

    def _is_websocket_connected(self, websocket: WebSocket) -> bool:
        """
        Check if WebSocket connection is still active and connected.

        Args:
            websocket: WebSocket connection to check

        Returns:
            True if connection is active, False otherwise
        """
        try:
            # Check WebSocket state - CONNECTED means it's accepted and active
            is_connected = websocket.client_state == WebSocketState.CONNECTED
            return bool(is_connected)
        except Exception:
            # If we can't check the state, assume disconnected
            return False

    async def _safe_send_text(self, websocket: WebSocket, text: str, session_id: str) -> bool:
        """
        Safely send text to WebSocket with connection state checking.

        Args:
            websocket: WebSocket connection
            text: Text to send
            session_id: Session ID for logging

        Returns:
            True if message was sent successfully, False if connection is closed
        """
        # Check connection state before sending
        if not self._is_websocket_connected(websocket):
            logger.warning(f"WebSocket not connected, cannot send message: session_id={session_id}")
            return False

        try:
            await websocket.send_text(text)
            return True
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected while sending: session_id={session_id}")
            return False
        except RuntimeError as e:
            # Handle "WebSocket is not connected. Need to call 'accept' first." error
            if "not connected" in str(e).lower() or "accept" in str(e).lower():
                logger.warning(f"WebSocket connection lost: session_id={session_id}, error={e}")
                return False
            raise
        except Exception as e:
            logger.error(f"Error sending WebSocket message: session_id={session_id}, error={e}")
            return False

    async def handle_connection(self, websocket: WebSocket, session_id: str):
        """
        Handle WebSocket connection for Copilot session subscription.

        Args:
            websocket: WebSocket connection
            session_id: Copilot session ID to subscribe to
        """
        if not RedisClient.is_available():
            try:
                await websocket.close(code=1011, reason="Redis not available")
            except Exception:
                pass
            return

        try:
            await websocket.accept()
        except Exception as e:
            logger.error(f"Failed to accept WebSocket connection: session_id={session_id}, error={e}")
            return

        logger.info(f"Copilot WebSocket connected: session_id={session_id}")

        pubsub = None
        channel = f"copilot:session:{session_id}:pubsub"

        try:
            # Subscribe to Redis Pub/Sub channel
            # Create Redis pubsub subscriber
            redis_client = RedisClient.get_client()
            if not redis_client:
                try:
                    if self._is_websocket_connected(websocket):
                        await websocket.close(code=1011, reason="Redis client not available")
                except Exception:
                    pass
                return

            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel)

            # Note: We do NOT send existing content here to avoid duplicates.
            # The streaming process will send all content events through Pub/Sub,
            # and if users need historical content, they should load it from the database.

            # Start listening for Redis messages and handling client messages
            while self._is_websocket_connected(websocket):
                try:
                    # Create tasks for both Redis messages and WebSocket messages
                    redis_task = asyncio.create_task(asyncio.wait_for(pubsub.get_message(), timeout=1.0))
                    ws_task = asyncio.create_task(asyncio.wait_for(websocket.receive_text(), timeout=1.0))

                    # Wait for either Redis message or WebSocket message
                    done, pending = await asyncio.wait([redis_task, ws_task], return_when=asyncio.FIRST_COMPLETED)

                    # Cancel pending tasks
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass

                    # Handle Redis messages
                    if redis_task in done:
                        try:
                            message = await redis_task
                            if message and message.get("type") == "message":
                                try:
                                    # Parse and forward event to WebSocket
                                    event = json.loads(message["data"])
                                    event_json = json.dumps(event, ensure_ascii=False)

                                    # Use safe send method
                                    sent = await self._safe_send_text(websocket, event_json, session_id)
                                    if not sent:
                                        # Connection lost, exit loop
                                        logger.info(f"Connection lost while sending event: session_id={session_id}")
                                        break

                                    # Close connection if done
                                    if event.get("type") == "done":
                                        logger.info(f"Copilot session completed: session_id={session_id}")
                                        try:
                                            await websocket.close(code=1000, reason="Session completed")
                                        except Exception:
                                            pass
                                        break
                                    elif event.get("type") == "error":
                                        error_msg = event.get("message", "Unknown error")
                                        logger.error(
                                            f"Copilot session error: session_id={session_id}, error={error_msg}"
                                        )
                                        try:
                                            await websocket.close(code=1011, reason=f"Error: {error_msg}")
                                        except Exception:
                                            pass
                                        break
                                except json.JSONDecodeError as e:
                                    logger.error(f"Failed to parse Redis message: {e}")
                        except asyncio.TimeoutError:
                            # Timeout is expected, continue
                            pass
                        except Exception as e:
                            logger.error(f"Error processing Redis message: {e}")
                            # Check if connection is still valid
                            if not self._is_websocket_connected(websocket):
                                break

                    # Handle WebSocket client messages (ping/heartbeat)
                    if ws_task in done:
                        try:
                            client_message = await ws_task
                            if client_message:
                                try:
                                    msg_data = json.loads(client_message)
                                    # Respond to ping with pong
                                    if msg_data.get("type") == "ping":
                                        pong_json = json.dumps({"type": "pong"})
                                        sent = await self._safe_send_text(websocket, pong_json, session_id)
                                        if not sent:
                                            # Connection lost, exit loop
                                            break
                                except json.JSONDecodeError:
                                    # Ignore non-JSON messages
                                    pass
                        except asyncio.TimeoutError:
                            # Timeout is expected, continue
                            pass
                        except WebSocketDisconnect:
                            logger.info(f"WebSocket disconnected: session_id={session_id}")
                            break
                        except Exception as e:
                            # Check if it's a connection-related error
                            error_str = str(e).lower()
                            if "not connected" in error_str or "accept" in error_str:
                                logger.warning(f"WebSocket connection error: session_id={session_id}, error={e}")
                                break
                            logger.error(f"Error processing WebSocket message: {e}")
                            # If connection is lost, exit loop
                            if not self._is_websocket_connected(websocket):
                                break

                except WebSocketDisconnect:
                    logger.info(f"WebSocket disconnected: session_id={session_id}")
                    break
                except Exception as e:
                    # Check if it's a connection-related error
                    error_str = str(e).lower()
                    if "not connected" in error_str or "accept" in error_str:
                        logger.warning(f"WebSocket connection error in loop: session_id={session_id}, error={e}")
                        break
                    logger.error(f"Error in Pub/Sub loop: {e}")
                    # Check if connection is still valid
                    if not self._is_websocket_connected(websocket):
                        break
                    # For other exceptions, continue and try again
                    await asyncio.sleep(0.1)

        except WebSocketDisconnect:
            logger.info(f"Copilot WebSocket disconnected: session_id={session_id}")
        except Exception as e:
            logger.error(f"Copilot WebSocket error: session_id={session_id}, error={e}")
            try:
                if self._is_websocket_connected(websocket):
                    await websocket.close(code=1011)
            except Exception:
                pass
        finally:
            # Clean up
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception as e:
                    logger.warning(f"Error cleaning up Pub/Sub: {e}")


# Global handler instance
copilot_handler = CopilotWebSocketHandler()
