"""Cross-instance command listener via Redis pub/sub.

Subscribes to `conductor:cmd:{instance_id}` and dispatches commands
to the appropriate sandbox bridge. Matches Rust's spawn_command_listener
+ handle_remote_command in grpc.rs.
"""
import asyncio
import json
import logging
import uuid

from app.core.grpc.proto import conductor_pb2

logger = logging.getLogger(__name__)


class CommandListener:
    def __init__(self, redis_client, coordinator, bridge_registry):
        self._redis = redis_client
        self._coordinator = coordinator
        self._bridge_registry = bridge_registry
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        channel = self._coordinator.command_channel()
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(channel)
                logger.info("Cross-instance command listener started on channel %s", channel)
            except asyncio.CancelledError:
                await pubsub.close()
                return
            except Exception as e:
                logger.warning("Command listener: failed to connect to Redis pub/sub: %s", e)
                try:
                    await pubsub.close()
                except Exception:
                    pass
                await asyncio.sleep(5)
                continue

            try:
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode()
                        cmd = json.loads(data)
                        await self._dispatch(cmd)
                    except Exception as e:
                        logger.warning("Command listener: bad payload: %s", e)
            except asyncio.CancelledError:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
                return
            except Exception:
                pass

            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass
            logger.warning("Command listener: stream ended, reconnecting...")
            await asyncio.sleep(1)

    async def _dispatch(self, cmd: dict) -> None:
        sandbox_id_str = cmd.get("sandbox_id", "")
        if not sandbox_id_str:
            logger.warning("Command listener: invalid sandbox_id: %s", sandbox_id_str)
            return

        try:
            sandbox_id = uuid.UUID(sandbox_id_str)
        except ValueError:
            logger.warning("Command listener: invalid sandbox_id: %s", sandbox_id_str)
            return

        bridge = await self._bridge_registry.get(sandbox_id)
        if not bridge:
            logger.warning(
                "Command listener: no bridge for sandbox %s", sandbox_id
            )
            return

        cmd_type = cmd.get("type", "")
        if cmd_type == "input":
            content = cmd.get("content", "")
            msg = conductor_pb2.OrchestratorMessage(
                input=conductor_pb2.SendInput(content=content)
            )
            try:
                bridge.runner_tx.put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning("Command listener: runner_tx full for sandbox %s", sandbox_id)
                return
            bridge.confirmation_event.set()
            logger.info("Executed remote command: sandbox=%s type=input", sandbox_id)
        elif cmd_type == "shutdown":
            reason = cmd.get("reason", "remote shutdown")
            msg = conductor_pb2.OrchestratorMessage(
                shutdown=conductor_pb2.Shutdown(reason=reason)
            )
            try:
                bridge.runner_tx.put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning("Command listener: runner_tx full for sandbox %s", sandbox_id)
                return
            logger.info("Executed remote command: sandbox=%s type=shutdown", sandbox_id)
        else:
            logger.warning("Command listener: unknown command type: %s", cmd_type)
