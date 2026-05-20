"""Cross-instance command listener via Redis pub/sub.

Subscribes to `conductor:cmd:{instance_id}` and dispatches commands
to the appropriate sandbox bridge.
"""
import asyncio
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class CommandListener:
    def __init__(self, redis_client, coordinator, bridge_registry):
        self._redis = redis_client
        self._coordinator = coordinator
        self._bridge_registry = bridge_registry
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        channel = self._coordinator.command_channel()
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        logger.info("CommandListener subscribed to %s", channel)

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
                    logger.warning("CommandListener dispatch error: %s", e)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def _dispatch(self, cmd: dict) -> None:
        action = cmd.get("action", "")
        sandbox_id_str = cmd.get("sandbox_id", "")

        if not sandbox_id_str:
            logger.warning("Command missing sandbox_id: %s", cmd)
            return

        try:
            sandbox_id = uuid.UUID(sandbox_id_str)
        except ValueError:
            logger.warning("Invalid sandbox_id in command: %s", sandbox_id_str)
            return

        bridge = await self._bridge_registry.get(sandbox_id)
        if not bridge:
            logger.debug(
                "No local bridge for sandbox %s, ignoring command", sandbox_id
            )
            return

        if action == "input":
            content = cmd.get("content", "")
            await bridge.send_control_input(content)
        elif action == "cancel":
            bridge.request_cancel()
        else:
            logger.debug("Unknown command action: %s", action)
