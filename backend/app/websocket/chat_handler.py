"""WebSocket chat handler for real-time AI communication."""

import json
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from app.services.session_service import SessionService
from app.websocket.connection_manager import manager


class ChatHandler:
    """Handles WebSocket chat communication."""

    def __init__(self, session_service: SessionService):
        self.session_service = session_service

    async def handle_connection(self, websocket: WebSocket, session_id: str, user_id: Optional[int] = None):
        """Handle a new WebSocket connection."""
        await manager.connect(websocket, session_id, user_id)

        try:
            # Get AI adapter for this session
            ai_adapter = await self.session_service.get_ai_adapter(session_id)
            if not ai_adapter:
                await manager.send_personal_message(
                    {
                        "type": "error",
                        "content": "Session not found or inactive",
                        "session_id": session_id,
                    },
                    websocket,
                )
                return

            # Send welcome message
            await manager.send_personal_message(
                {
                    "type": "status",
                    "content": "Connected to Fix Agent",
                    "session_id": session_id,
                    "metadata": {"model": "AI Agent Ready", "tools_available": True},
                },
                websocket,
            )

            # Handle messages
            await self._handle_messages(websocket, session_id, ai_adapter)

        except Exception as e:
            logger.error(f"Error in chat handler: {e}")
            await manager.send_personal_message(
                {
                    "type": "error",
                    "content": f"Internal error: {str(e)}",
                    "session_id": session_id,
                },
                websocket,
            )

        finally:
            manager.disconnect(websocket)

    async def _handle_messages(self, websocket: WebSocket, session_id: str, ai_adapter):
        """Handle incoming WebSocket messages."""
        while True:
            try:
                # Receive message
                data = await websocket.receive_text()
                message_data = json.loads(data)

                message_type = message_data.get("type", "chat")

                if message_type == "chat":
                    await self._handle_chat_message(websocket, session_id, ai_adapter, message_data)
                elif message_type == "ping":
                    await manager.send_personal_message({"type": "pong", "session_id": session_id}, websocket)
                elif message_type == "memory_list":
                    await self._handle_memory_list(websocket, session_id, ai_adapter)
                elif message_type == "memory_read":
                    await self._handle_memory_read(websocket, session_id, ai_adapter, message_data)
                elif message_type == "memory_write":
                    await self._handle_memory_write(websocket, session_id, ai_adapter, message_data)
                else:
                    await manager.send_personal_message(
                        {
                            "type": "error",
                            "content": f"Unknown message type: {message_type}",
                            "session_id": session_id,
                        },
                        websocket,
                    )

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                await manager.send_personal_message(
                    {
                        "type": "error",
                        "content": f"Error processing message: {str(e)}",
                        "session_id": session_id,
                    },
                    websocket,
                )

    async def _handle_chat_message(
        self,
        websocket: WebSocket,
        session_id: str,
        ai_adapter,
        message_data: Dict[str, Any],
    ):
        """Handle chat message and stream AI response."""
        content = message_data.get("content", "")
        file_references = message_data.get("file_references", [])

        if not content.strip():
            await manager.send_personal_message(
                {
                    "type": "error",
                    "content": "Message content cannot be empty",
                    "session_id": session_id,
                },
                websocket,
            )
            return

        # Save user message to database
        await self.session_service.add_message(
            session_id=session_id,
            content=content,
            role="user",
            metadata={"file_references": file_references},
        )

        # Send "thinking" status
        await manager.send_personal_message(
            {
                "type": "status",
                "content": "AI is thinking...",
                "session_id": session_id,
                "metadata": {"state": "thinking"},
            },
            websocket,
        )

        try:
            # Stream AI response
            full_response = ""
            async for chunk in ai_adapter.stream_response(content, file_references):
                # Send chunk to client
                await manager.send_personal_message(chunk, websocket)

                # Collect full response for database storage
                if chunk.get("type") == "message" and chunk.get("content"):
                    full_response += chunk.get("content", "")

            # Save AI response to database
            if full_response:
                await self.session_service.add_message(
                    session_id=session_id,
                    content=full_response,
                    role="assistant",
                    metadata={"streamed": True},
                )

            # Send completion status
            await manager.send_personal_message(
                {
                    "type": "status",
                    "content": "Response complete",
                    "session_id": session_id,
                    "metadata": {"state": "complete"},
                },
                websocket,
            )

        except Exception as e:
            logger.error(f"Error in AI streaming: {e}")
            await manager.send_personal_message(
                {
                    "type": "error",
                    "content": f"AI response error: {str(e)}",
                    "session_id": session_id,
                },
                websocket,
            )

    async def _handle_memory_list(self, websocket: WebSocket, session_id: str, ai_adapter):
        """Handle memory list request."""
        try:
            memory_files = ai_adapter.get_memory_files()
            await manager.send_personal_message(
                {
                    "type": "memory_list",
                    "files": memory_files,
                    "session_id": session_id,
                },
                websocket,
            )
        except Exception as e:
            await manager.send_personal_message(
                {
                    "type": "error",
                    "content": f"Error listing memory files: {str(e)}",
                    "session_id": session_id,
                },
                websocket,
            )

    async def _handle_memory_read(
        self,
        websocket: WebSocket,
        session_id: str,
        ai_adapter,
        message_data: Dict[str, Any],
    ):
        """Handle memory file read request."""
        file_path = message_data.get("file_path", "")
        if not file_path:
            await manager.send_personal_message(
                {
                    "type": "error",
                    "content": "File path is required",
                    "session_id": session_id,
                },
                websocket,
            )
            return

        try:
            content = ai_adapter.read_memory_file(file_path)
            await manager.send_personal_message(
                {
                    "type": "memory_content",
                    "file_path": file_path,
                    "content": content,
                    "session_id": session_id,
                },
                websocket,
            )
        except Exception as e:
            await manager.send_personal_message(
                {
                    "type": "error",
                    "content": f"Error reading memory file: {str(e)}",
                    "session_id": session_id,
                },
                websocket,
            )

    async def _handle_memory_write(
        self,
        websocket: WebSocket,
        session_id: str,
        ai_adapter,
        message_data: Dict[str, Any],
    ):
        """Handle memory file write request."""
        file_path = message_data.get("file_path", "")
        content = message_data.get("content", "")

        if not file_path:
            await manager.send_personal_message(
                {
                    "type": "error",
                    "content": "File path is required",
                    "session_id": session_id,
                },
                websocket,
            )
            return

        try:
            ai_adapter.write_memory_file(file_path, content)
            await manager.send_personal_message(
                {
                    "type": "status",
                    "content": f"Memory file saved: {file_path}",
                    "session_id": session_id,
                },
                websocket,
            )
        except Exception as e:
            await manager.send_personal_message(
                {
                    "type": "error",
                    "content": f"Error writing memory file: {str(e)}",
                    "session_id": session_id,
                },
                websocket,
            )
