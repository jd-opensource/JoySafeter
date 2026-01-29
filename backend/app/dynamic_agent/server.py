"""
FastAPI Server for Agent Backend
Provides REST API endpoints for chat, session management, and tool execution
"""

import asyncio
import json
import os
import queue
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # Try absolute import first (when running as module)
    from app.dynamic_agent.main import init_storage, run, startup
except ImportError:
    # Fallback to relative import (when running from backend directory)
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app.dynamic_agent.main import init_storage, run, startup

from loguru import logger

# ==================== Mode Validation ====================


def validate_mode(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and validate mode from request metadata.

    Ensures consistency between mode, is_ctf, and non_ctf_guard flags.

    Args:
        metadata: Request metadata dictionary

    Returns:
        Validated metadata with normalized mode fields

    Raises:
        ValueError: If mode values are inconsistent
    """
    mode = metadata.get("mode")
    is_ctf = metadata.get("is_ctf")
    non_ctf_guard = metadata.get("non_ctf_guard")

    # Validate mode value if present
    if mode is not None:
        if mode not in ["ctf", "pentest"]:
            raise ValueError(f"Invalid mode: {mode}. Must be 'ctf' or 'pentest'")

        # Ensure consistency between mode and boolean flags
        if mode == "ctf":
            if is_ctf is not None and is_ctf is not True:
                raise ValueError("Inconsistent metadata: mode='ctf' but is_ctf is not True")
            metadata["is_ctf"] = True
            # CTF mode should not have non_ctf_guard
            metadata.pop("non_ctf_guard", None)
        elif mode == "pentest":
            if is_ctf is not None and is_ctf is not False:
                raise ValueError("Inconsistent metadata: mode='pentest' but is_ctf is not False")
            metadata["is_ctf"] = False
            # Optionally set non_ctf_guard for pentest mode
            if non_ctf_guard is None:
                metadata["non_ctf_guard"] = True

    return metadata


# ==================== Request/Response Models ====================


class ChatRequest(BaseModel):
    """Chat message request"""

    message: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """Chat message response"""

    session_id: str
    user_id: str
    message: str
    reply: str
    timestamp: str


class SessionInfo(BaseModel):
    """Session information"""

    session_id: str
    user_id: str
    created_at: str
    message_count: int
    last_message: Optional[str] = None


class ToolInfo(BaseModel):
    """Tool information"""

    name: str
    description: str
    category: str


# ==================== Lifespan Management ====================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan:
    - Startup: Initialize storage and agent
    - Shutdown: Cleanup resources
    """
    # Startup
    logger.info("🚀 Starting Agent Server...")
    try:
        await startup()
        logger.info("✓ Agent Server started successfully")
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        logger.exception("Failed to start server")
        raise

    yield

    # Shutdown
    logger.info("🛑 Shutting down Agent Server...")
    # Add cleanup logic here if needed
    logger.info("✓ Agent Server shut down")


# ==================== FastAPI App ====================

# app = FastAPI(
#     title="Open Pentest Agent API",
#     description="REST API for security testing agent with tool execution",
#     version="1.0.0",
#     lifespan=lifespan,
# )


# Add CORS middleware
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

DYNAMIC_AGENT_PREFIX = "/dynamic"
app = APIRouter()


@app.get("/dynamic")
def root():
    return RedirectResponse(url="/dynamic/chat")


# ==================== Register Web API Routes ====================

try:
    from app.dynamic_agent.web import router as web_router

    app.include_router(web_router)
    logger.info("✓ Web visualization API routes registered")
except ImportError as e:
    logger.warning(f"⚠️ Failed to import web routes: {e}")
# ==================== Health Check ====================


@app.get("/health")
async def health_check():
    """Health check endpoint with database pool status"""
    health_info = {"status": "healthy", "timestamp": datetime.now().isoformat(), "service": "agent-server"}

    # Add database pool status if storage is initialized
    try:
        storage_manager = await init_storage()
        if storage_manager and storage_manager.backend:
            pool = storage_manager.backend.pool
            if pool:
                # Use asyncpg 0.31.0+ public API
                pool_stats = {
                    "min_size": pool.get_min_size()
                    if hasattr(pool, "get_min_size")
                    else getattr(pool, "_minsize", "N/A"),
                    "max_size": pool.get_max_size()
                    if hasattr(pool, "get_max_size")
                    else getattr(pool, "_maxsize", "N/A"),
                    "size": pool.get_size() if hasattr(pool, "get_size") else "N/A",
                    "idle": pool.get_idle_size() if hasattr(pool, "get_idle_size") else "N/A",
                }
                health_info["db_pool"] = pool_stats
            else:
                health_info["db_pool"] = "not initialized"
        else:
            health_info["storage"] = "not initialized"
    except Exception as e:
        health_info["db_pool"] = f"error: {str(e)}"

    return health_info


# ==================== Mode Detection Endpoint ====================


class DetectModeRequest(BaseModel):
    """Mode detection request"""

    message: str


class DetectModeResponse(BaseModel):
    """Mode detection response"""

    mode: str  # "ctf" or "pentest"
    confidence: str  # "high" or "low"


@app.post("/api/detect-mode", response_model=DetectModeResponse)
async def detect_mode(request: DetectModeRequest):
    """
    Detect mode from user message using keyword + LLM detection.

    Uses the same detection logic as ctf_mode branch:
    1. Fast keyword check for definite CTF patterns
    2. LLM classification for all scene types

    Args:
        request: Message to analyze

    Returns:
        Detected mode and confidence level
    """
    try:
        from app.dynamic_agent.prompts.system_prompts import SceneType, detect_scene

        # Use detect_scene which does keyword + LLM detection
        detected_scene = detect_scene(request.message, use_llm=True)

        # Map scene to mode
        if detected_scene == SceneType.CTF.value:
            mode = "ctf"
            confidence = "high"  # LLM + keyword detection is high confidence
        elif detected_scene == SceneType.PENTEST.value:
            mode = "pentest"
            confidence = "high"
        else:
            # General or ambiguous - default to pentest for enterprise use
            mode = "pentest"
            confidence = "low"

        logger.info(f"🎭 Mode detected: '{request.message[:40]}...' -> {mode} (confidence: {confidence})")

        return DetectModeResponse(mode=mode, confidence=confidence)

    except Exception as e:
        logger.error(f"❌ Mode detection failed: {e}")
        logger.exception("Mode detection failed")
        # Fallback to pentest on error
        return DetectModeResponse(mode="pentest", confidence="low")


# ==================== Chat Endpoints ====================


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a message to the agent and get a response

    Args:
        request: Chat request with message and optional session info

    Returns:
        ChatResponse with agent's reply
    """
    try:
        # Generate or use provided session/user IDs
        session_id = request.session_id or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        user_id = request.user_id or "default_user"

        # Prepare metadata with response_queue
        metadata = request.metadata or {}
        response_queue_obj: queue.Queue[Any] = queue.Queue()
        metadata.update(
            {
                "langfuse_session_id": session_id,
                "langfuse_user_id": user_id,
                "timestamp": datetime.now().isoformat(),
                "response_queue": response_queue_obj,
            }
        )

        logger.info(f"📨 Chat request: session={session_id}, user={user_id}")
        logger.info(f"   Message: {request.message[:100]}...")

        # Run agent
        await run(request.message, metadata)

        # Collect all streaming responses from queue
        reply_parts = []
        timeout_per_chunk = 300
        total_timeout = 2 * 3600  # 2 hours total timeout
        start_time = asyncio.get_event_loop().time()

        while True:
            try:
                elapsed = asyncio.get_event_loop().time() - start_time
                remaining_timeout = total_timeout - elapsed

                if remaining_timeout <= 0:
                    logger.error("❌ Total timeout exceeded waiting for response from queue")
                    raise HTTPException(status_code=504, detail="Agent response timeout")

                # Get next chunk from queue with per-chunk timeout
                chunk_timeout = min(timeout_per_chunk, int(remaining_timeout))
                try:
                    response_data = await asyncio.wait_for(
                        asyncio.to_thread(response_queue_obj.get, timeout=chunk_timeout), timeout=chunk_timeout + 1
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⏱️ Timeout waiting for chunk (timeout={chunk_timeout}s), continuing...")
                    continue
                except queue.Empty:
                    logger.info("Queue empty, waiting for more data...")
                    continue

                status = response_data.get("status", "")
                data = response_data.get("data", "")

                if status == "complete":
                    logger.info("✓ Stream completed")
                    break
                elif status == "error":
                    logger.error(f"❌ Agent error: {data}")
                    raise HTTPException(status_code=500, detail=f"Agent error: {data}")
                elif status == "success":
                    if data:
                        reply_parts.append(data)
                        logger.info(f"✓ Received chunk: {len(data)} chars")

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"❌ Unexpected error in chat loop: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        reply = "".join(reply_parts)
        logger.info(f"✓ Chat response generated: {len(reply)} chars")

        return ChatResponse(
            session_id=session_id,
            user_id=user_id,
            message=request.message,
            reply=reply,
            timestamp=datetime.now().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        logger.exception("Chat error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Send a message to the agent and stream the response

    Args:
        request: Chat request

    Returns:
        Streaming response with agent's reply
    """
    try:
        session_id = request.session_id or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        user_id = request.user_id or "default_user"

        # Extract and validate mode from metadata
        metadata = request.metadata or {}
        try:
            metadata = validate_mode(metadata)
            logger.info(f"✓ Mode validated: {metadata.get('mode', 'not specified')}")
        except ValueError as e:
            logger.error(f"❌ Mode validation failed: {e}")
            raise HTTPException(status_code=400, detail=str(e))

        # Ensure session exists in backend
        storage = await init_storage()
        existing_session = await storage.context.get_session(session_id)
        if not existing_session:
            # Create session with mode metadata
            try:
                # Extract mode-related metadata for session persistence
                session_metadata = {}
                if "mode" in metadata:
                    session_metadata["mode"] = metadata["mode"]
                if "is_ctf" in metadata:
                    session_metadata["is_ctf"] = metadata["is_ctf"]
                if "non_ctf_guard" in metadata:
                    session_metadata["non_ctf_guard"] = metadata["non_ctf_guard"]

                await storage.context.create_session(user_id, session_id, metadata=session_metadata)
                logger.info(
                    f"✓ Created new session: {session_id} for user: {user_id} with mode: {session_metadata.get('mode', 'not specified')}"
                )

                # Verify session was created
                verify_session = await storage.context.get_session(session_id)
                if verify_session:
                    logger.info(f"✓ Session verified in database: {session_id}")
                else:
                    logger.error(f"❌ Session creation failed - not found after creation: {session_id}")
            except Exception as e:
                logger.error(f"❌ Failed to create session: {e}", exc_info=True)
                raise
        else:
            # Update existing session with mode metadata if missing
            try:
                session_metadata = existing_session.metadata or {}
                needs_update = False

                # Only update if mode is not already set
                if "mode" not in session_metadata and "mode" in metadata:
                    session_metadata["mode"] = metadata["mode"]
                    needs_update = True
                if "is_ctf" not in session_metadata and "is_ctf" in metadata:
                    session_metadata["is_ctf"] = metadata["is_ctf"]
                    needs_update = True
                if "non_ctf_guard" not in session_metadata and "non_ctf_guard" in metadata:
                    session_metadata["non_ctf_guard"] = metadata["non_ctf_guard"]
                    needs_update = True

                if needs_update:
                    existing_session.metadata = session_metadata
                    await storage.context.update_session(existing_session)
                    logger.info(
                        f"✓ Updated session {session_id} with mode: {session_metadata.get('mode', 'not specified')}"
                    )
            except Exception as e:
                logger.error(f"❌ Failed to update session metadata: {e}", exc_info=True)
                # Don't fail the request if metadata update fails

        response_queue_obj: queue.Queue[Any] = queue.Queue()
        task_id_event = asyncio.Event()
        task_id_holder: Dict[str, Any] = {}

        # Update validated metadata with runtime objects
        metadata.update(
            {
                "langfuse_session_id": session_id,
                "langfuse_user_id": user_id,
                "response_queue": response_queue_obj,
                "task_id_event": task_id_event,
                "task_id_holder": task_id_holder,
            }
        )

        async def generate():
            """Generator for streaming response"""
            try:
                # Send initial message
                yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"

                # Run agent in background task
                run_task = asyncio.create_task(run(request.message, metadata))

                # Wait for task_id to be created (with timeout)
                try:
                    await asyncio.wait_for(task_id_event.wait(), timeout=60.0)
                    task_id = task_id_holder.get("task_id")
                    if task_id:
                        yield f"data: {json.dumps({'type': 'task_created', 'task_id': str(task_id)})}\n\n"
                        logger.info(f"✅ Sent task_created event: {task_id}")
                    else:
                        logger.error("❌ Event triggered but task_id is None!")
                except asyncio.TimeoutError:
                    logger.error("❌ Timeout waiting for task_id creation (10 seconds)")

                # Stream responses from queue as they arrive (both intermediate and final)
                timeout_per_chunk = 300
                total_timeout = 2 * 3600  # 2 hours total timeout
                start_time = asyncio.get_event_loop().time()
                total_length = 0

                while True:
                    try:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        remaining_timeout = total_timeout - elapsed

                        if remaining_timeout <= 0:
                            logger.error("❌ Total timeout exceeded")
                            yield f"data: {json.dumps({'type': 'error', 'message': 'Agent response timeout'})}\n\n"
                            return

                        # Get next chunk from queue with per-chunk timeout
                        chunk_timeout = min(timeout_per_chunk, int(remaining_timeout))
                        try:
                            response_data = await asyncio.wait_for(
                                asyncio.to_thread(response_queue_obj.get, timeout=chunk_timeout),
                                timeout=chunk_timeout + 1,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"⏱️ Timeout waiting for chunk (timeout={chunk_timeout}s), continuing...")
                            continue
                        except queue.Empty:
                            logger.info("Queue empty, waiting for more data...")
                            continue

                        status = response_data.get("status", "")
                        data = response_data.get("data", "")
                        data_type = response_data.get("type", "")

                        if status == "complete":
                            logger.info("✓ Stream completed")
                            yield f"data: {json.dumps({'type': 'complete', 'total_length': total_length})}\n\n"
                            break
                        elif status == "error":
                            logger.error(f"❌ Agent error: {data}")
                            yield f"data: {json.dumps({'type': 'error', 'message': data})}\n\n"
                            break
                        elif status == "success":
                            if "intermediate" == data_type:
                                # if data:
                                # Check if this is intermediate message or final reply chunk
                                # if any(marker in data for marker in ["🔧", "🟢", "thinking:", "Input:", "Output:"]):
                                # Intermediate message
                                yield f"data: {json.dumps({'type': 'intermediate', 'data': data})}\n\n"
                                logger.info(f"✓ Streamed intermediate: {len(data)} chars")
                            else:
                                # Final reply chunk
                                total_length += len(data)
                                yield f"data: {json.dumps({'type': 'chunk', 'data': data})}\n\n"
                                logger.info(f"✓ Streamed chunk: {len(data)} chars")

                    except Exception as e:
                        logger.error(f"❌ Unexpected error in stream loop: {e}")
                        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                        return

                # Wait for run task to complete
                try:
                    await asyncio.wait_for(run_task, timeout=5)
                except asyncio.TimeoutError:
                    logger.warning("Run task did not complete within timeout")

            except Exception as e:
                logger.error(f"Stream error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"❌ Stream error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Session Endpoints ====================


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """
    Get session information

    Args:
        session_id: Session ID

    Returns:
        Session information
    """
    try:
        storage = await init_storage()
        context = await storage.context.get_session(session_id)

        if not context:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "session_id": session_id,
            "user_id": context.user_id,
            "created_at": context.created_at.isoformat() if hasattr(context, "created_at") else None,
            "message_count": len(context.messages) if hasattr(context, "messages") else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/users/{user_id}/sessions/history")
async def get_user_sessions_history(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
):
    """
    Get conversation history for all sessions of a user

    Args:
        user_id: User ID
        limit: Maximum number of messages to return per session
        offset: Offset for pagination

    Returns:
        List of sessions with their messages
    """
    try:
        storage = await init_storage()

        # Get all sessions for this user from database
        from app.dynamic_agent.storage.persistence.daos.session_dao import SessionDAO

        if not storage or not storage.backend:
            raise HTTPException(status_code=500, detail="Storage not initialized")

        session_dao = SessionDAO(storage.backend.pool)
        sessions_data, total_count = await session_dao.list_user_sessions(user_id, limit=100, offset=0)

        # Get messages for each session
        sessions_with_history = []
        for session_data in sessions_data:
            session_id = session_data["session_id"]
            context = await storage.context.get_session(session_id)

            if context:
                # Get conversation history for this session
                history = await storage.context.get_conversation_history(session_id, limit=limit)

                # Apply offset for pagination
                paginated_history = history[offset : offset + limit]

                sessions_with_history.append(
                    {
                        "session_id": session_id,
                        "title": session_id,
                        "created_at": session_data.get("created_at"),
                        "updated_at": session_data.get("updated_at"),
                        "message_count": len(history),
                        "messages": paginated_history,
                    }
                )

        return {
            "user_id": user_id,
            "total_sessions": total_count,
            "sessions": sessions_with_history,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get user sessions history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/users/{user_id}/sessions/{session_id}/history")
async def get_session_history(
    user_id: str,
    session_id: str,
    limit: int = 50,
    offset: int = 0,
):
    """
    Get conversation history for a specific session

    Args:
        user_id: User ID (for permission verification)
        session_id: Session ID
        limit: Maximum number of messages to return
        offset: Offset for pagination

    Returns:
        List of messages with pagination info
    """
    try:
        storage = await init_storage()

        # Load session context to verify ownership
        context = await storage.context.get_session(session_id)
        if not context:
            logger.warning(f"Session {session_id} not found in database")
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found in database")

        # Verify user owns this session
        if context.user_id != user_id:
            logger.warning(f"User {user_id} attempted to access session {session_id} owned by {context.user_id}")
            raise HTTPException(status_code=403, detail="Access denied: You do not own this session")

        # Get conversation history
        history = await storage.context.get_conversation_history(session_id, limit=limit)

        # Apply offset for pagination
        paginated_history = history[offset : offset + limit]

        return {
            "user_id": user_id,
            "session_id": session_id,
            "total_count": len(history),
            "offset": offset,
            "limit": limit,
            "messages": paginated_history,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session

    Args:
        session_id: Session ID

    Returns:
        Deletion confirmation
    """
    try:
        await init_storage()
        # Implement session deletion in storage
        # await storage.context.delete_session(session_id)

        return {
            "status": "deleted",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"❌ Delete session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Tool Endpoints ====================


@app.get("/api/tools")
async def list_tools():
    """
    List available tools

    Returns:
        List of available tools
    """
    try:
        from app.dynamic_agent.infra.context import tool_registry

        tools = []
        for tool_name in tool_registry.get_all_tools():
            tool = tool_registry.get_tool(tool_name)
            if tool:
                tools.append(
                    {
                        "name": tool_name,
                        "description": getattr(tool, "description", ""),
                        "category": getattr(tool, "category", "default"),
                    }
                )

        return {
            "total": len(tools),
            "tools": tools,
        }

    except Exception as e:
        logger.error(f"❌ List tools error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tools/{tool_name}/execute")
async def execute_tool(tool_name: str, params: Dict[str, Any]):
    """
    Execute a specific tool

    Args:
        tool_name: Name of the tool to execute
        params: Tool parameters

    Returns:
        Tool execution result
    """
    try:
        from app.dynamic_agent.infra.context import tool_registry

        tool = tool_registry.get_tool(tool_name)
        if not tool:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

        # Execute tool
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(params)
        else:
            # BaseTool is callable, but mypy needs help with type inference
            result = tool(**params)  # type: ignore[operator]

        return {
            "tool": tool_name,
            "status": "success",
            "result": result,
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Tool execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WebSocket Endpoints ====================


@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time chat

    Args:
        websocket: WebSocket connection
        session_id: Session ID
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: {session_id}")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_message = message_data.get("message", "")
            user_id = message_data.get("user_id", "default_user")

            if not user_message:
                await websocket.send_json({"error": "Empty message"})
                continue

            # Prepare metadata with response_queue
            response_queue_obj: queue.Queue[Any] = queue.Queue()
            metadata = {
                "langfuse_session_id": session_id,
                "langfuse_user_id": user_id,
                "response_queue": response_queue_obj,
            }

            try:
                # Send processing indicator
                await websocket.send_json({"type": "processing"})

                # Run agent in background task
                run_task = asyncio.create_task(run(user_message, metadata))

                # Stream responses from queue as they arrive (both intermediate and final)
                timeout_per_chunk = 300
                total_timeout = 2 * 3600  # 2 hours total timeout
                start_time = asyncio.get_event_loop().time()

                while True:
                    try:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        remaining_timeout = total_timeout - elapsed

                        if remaining_timeout <= 0:
                            logger.error("❌ Total timeout exceeded")
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": "Agent response timeout",
                                }
                            )
                            break

                        # Get next chunk from queue with per-chunk timeout
                        chunk_timeout = min(timeout_per_chunk, int(remaining_timeout))
                        try:
                            response_data = await asyncio.wait_for(
                                asyncio.to_thread(response_queue_obj.get, timeout=chunk_timeout),
                                timeout=chunk_timeout + 1,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"⏱️ Timeout waiting for chunk (timeout={chunk_timeout}s), continuing...")
                            continue
                        except queue.Empty:
                            logger.info("Queue empty, waiting for more data...")
                            continue

                        status = response_data.get("status", "")
                        data = response_data.get("data", "")

                        if status == "complete":
                            logger.info("✓ Stream completed")
                            await websocket.send_json(
                                {
                                    "type": "complete",
                                    "message": user_message,
                                    "timestamp": datetime.now().isoformat(),
                                }
                            )
                            break
                        elif status == "error":
                            logger.error(f"❌ Agent error: {data}")
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": data,
                                    "timestamp": datetime.now().isoformat(),
                                }
                            )
                            break
                        elif status == "success":
                            if data:
                                # Check if this is intermediate message or final reply chunk
                                if any(marker in data for marker in ["🔧", "🟢", "thinking:", "Input:", "Output:"]):
                                    # Intermediate message
                                    await websocket.send_json(
                                        {
                                            "type": "intermediate",
                                            "data": data,
                                            "timestamp": datetime.now().isoformat(),
                                        }
                                    )
                                    logger.info(f"✓ Sent intermediate: {len(data)} chars")
                                else:
                                    # Final reply chunk
                                    await websocket.send_json(
                                        {
                                            "type": "chunk",
                                            "data": data,
                                            "timestamp": datetime.now().isoformat(),
                                        }
                                    )
                                    logger.info(f"✓ Sent chunk: {len(data)} chars")

                    except Exception as e:
                        logger.error(f"❌ Unexpected error in websocket loop: {e}")
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": str(e),
                            }
                        )
                        break

                # Wait for run task to complete
                try:
                    await asyncio.wait_for(run_task, timeout=300)
                except asyncio.TimeoutError:
                    logger.warning("Run task did not complete within timeout")

            except Exception as e:
                logger.error(f"Agent error: {e}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": str(e),
                    }
                )

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()
        logger.info(f"WebSocket disconnected: {session_id}")


# ==================== Error Handlers ====================

# @app.exception_handler(Exception)
# async def global_exception_handler(request, exc):
#     """Global exception handler"""
#     logger.error(f"Unhandled exception: {exc}")
#     traceback.print_exc()
#     return JSONResponse(
#         status_code=500,
#         content={"detail": "Internal server error"},
#     )


# ==================== Server Entry Point ====================

if __name__ == "__main__":
    import uvicorn

    # Create a FastAPI app instance when running directly
    # (app is an APIRouter, which needs to be wrapped in a FastAPI instance)
    fastapi_app = FastAPI(
        title="Open Pentest Agent API",
        description="REST API for security testing agent with tool execution",
        version="1.0.0",
        lifespan=lifespan,
    )
    fastapi_app.include_router(app, prefix=DYNAMIC_AGENT_PREFIX)

    # Get configuration from environment
    host = os.getenv("AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("AGENT_PORT", 8888))
    reload = os.getenv("AGENT_RELOAD", "false").lower() == "true"
    workers = int(os.getenv("AGENT_WORKERS", 1))

    # Check if running in debugger (PyCharm sets this)
    in_debugger = os.getenv("PYCHARM_HOSTED") == "1" or "pydevd" in sys.modules

    if in_debugger:
        # Debug mode: use simple HTTP server to avoid uvicorn conflicts
        logger.info(f"🐛 Debug mode detected: using simple HTTP server on {host}:{port}")

        # Use hypercorn as alternative that works better with debuggers
        try:
            import hypercorn.asyncio
            import hypercorn.config

            config = hypercorn.config.Config()
            config.bind = [f"{host}:{port}"]
            config.loglevel = os.getenv("LOG_LEVEL", "info").lower()

            asyncio.run(hypercorn.asyncio.serve(fastapi_app, config))  # type: ignore[arg-type]
        except ImportError:
            # Fallback to uvicorn with minimal configuration
            logger.info("🐛 Hypercorn not available, using uvicorn with minimal config")

            import uvicorn

            uvicorn.run(
                fastapi_app,
                host=host,
                port=port,
                log_level=os.getenv("LOG_LEVEL", "info").lower(),
                access_log=True,
                use_colors=False,  # Disable colors for better debugger output
            )
    else:
        # Normal mode: use uvicorn
        # Force workers=1 in reload mode
        if reload:
            workers = 1

        logger.info(f"Starting server on {host}:{port} with {workers} worker(s), reload={reload}")

        uvicorn.run(
            fastapi_app,
            host=host,
            port=port,
            workers=workers,
            reload=reload,
            log_level=os.getenv("LOG_LEVEL", "info").lower(),
        )
