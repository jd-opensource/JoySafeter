"""Minimal JoySafeter REST client for the connection-matrix E2E suite.

Authenticates with a bearer token (``POST /auth/login/form``), which the API
treats as header auth and therefore exempts from CSRF — so no double-submit
token dance is needed. Every response is unwrapped from the standard
``{success, code, message, data}`` envelope.

The base URL defaults to ``http://localhost:8000`` (the API). The ``:3000`` URL
in the task is the web UI, which itself calls the API at ``:8000`` via
``NEXT_PUBLIC_API_URL``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

API_PREFIX = "/api/v1"


@dataclass
class ApiResult:
    status: int
    ok: bool
    data: Any = None
    error_code: str | None = None
    message: str | None = None
    raw: Any = None

    def require(self, *, context: str = "") -> "ApiResult":
        if not self.ok:
            raise AssertionError(
                f"JoySafeter request failed{(' ' + context) if context else ''}: "
                f"status={self.status} code={self.error_code} message={self.message} raw={self.raw!r}"
            )
        return self


@dataclass
class ResourceTracker:
    """Records created resource ids for reverse-order cleanup."""

    session_ids: list[str] = field(default_factory=list)
    group_ids: list[str] = field(default_factory=list)
    agent_ids: list[str] = field(default_factory=list)


class JoySafeterClient:
    def __init__(
        self, base_url: str, email: str, password: str, timeout: float = 30.0
    ) -> None:
        self._email = email
        self._password = password
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, follow_redirects=True
        )
        self._token: str | None = None

    # --- lifecycle ---------------------------------------------------------------

    def login(self) -> None:
        resp = self._http.post(
            f"{API_PREFIX}/auth/login/form",
            data={"username": self._email, "password": self._password},
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", body) if isinstance(body, dict) else {}
        token = data.get("access_token") or body.get("access_token")
        if not token:
            raise RuntimeError(f"login did not return an access_token: {body!r}")
        self._token = token
        self._http.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        self._http.close()

    # --- low-level ---------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> ApiResult:
        resp = self._http.request(method, f"{API_PREFIX}{path}", **kwargs)
        try:
            body = resp.json()
        except ValueError:
            return ApiResult(
                status=resp.status_code,
                ok=resp.is_success,
                raw=resp.text,
                message=resp.text[:300],
            )

        data = body.get("data") if isinstance(body, dict) else body
        error_code = None
        message = body.get("message") if isinstance(body, dict) else None
        if not resp.is_success:
            # AppError payloads carry a semantic ``code`` under data; pydantic 422s
            # carry a ``detail`` list instead.
            if isinstance(data, dict):
                error_code = data.get("code")
            if error_code is None and isinstance(body, dict):
                error_code = body.get("code")
        return ApiResult(
            status=resp.status_code,
            ok=resp.is_success,
            data=data,
            error_code=str(error_code) if error_code is not None else None,
            message=message,
            raw=body,
        )

    def get(self, path: str, **params) -> ApiResult:
        return self._request("GET", path, params=params or None)

    def post(self, path: str, json: Any = None) -> ApiResult:
        return self._request("POST", path, json=json)

    def patch(self, path: str, json: Any = None) -> ApiResult:
        return self._request("PATCH", path, json=json)

    def delete(self, path: str) -> ApiResult:
        return self._request("DELETE", path)

    # --- credentials / groups ----------------------------------------------------

    def list_model_credentials(self) -> list[dict]:
        res = self.get("/credentials", kind="model", limit=100).require(
            context="list model credentials"
        )
        payload = res.data
        items = payload.get("data") if isinstance(payload, dict) else payload
        return items or []

    def create_group(
        self,
        name: str,
        *,
        description: str = "",
        initial_members: list[dict] | None = None,
    ) -> ApiResult:
        payload: dict = {"name": name, "description": description}
        if initial_members:
            payload["initial_members"] = initial_members
        return self.post("/credential-groups", json=payload)

    def add_member(
        self,
        group_id: str,
        *,
        name: str,
        mcp_server_url: str,
        data: dict,
        auth_scheme: str,
    ) -> ApiResult:
        return self.post(
            f"/credential-groups/{group_id}/members",
            json={
                "name": name,
                "mcp_server_url": mcp_server_url,
                "data": data,
                "auth_scheme": auth_scheme,
            },
        )

    def list_members(self, group_id: str) -> list[dict]:
        res = self.get(f"/credential-groups/{group_id}/members").require(
            context="list members"
        )
        payload = res.data
        items = payload.get("data") if isinstance(payload, dict) else payload
        return items or []

    def delete_group(self, group_id: str) -> ApiResult:
        return self.delete(f"/credential-groups/{group_id}")

    def archive_group(self, group_id: str) -> ApiResult:
        return self.post(f"/credential-groups/{group_id}/archive")

    # --- agents ------------------------------------------------------------------

    def create_agent(
        self,
        *,
        name: str,
        engine_kind: str = "claude",
        mcp_servers: list[dict] | None = None,
        tools: list[dict] | None = None,
        model_credential_id: str | None = None,
        system: str | None = None,
    ) -> ApiResult:
        payload: dict = {"name": name, "engine_kind": engine_kind}
        if mcp_servers:
            payload["mcp_servers"] = mcp_servers
        if tools:
            payload["tools"] = tools
        if model_credential_id:
            payload["model_credential_id"] = model_credential_id
        if system is not None:
            payload["system"] = system
        return self.post("/agents", json=payload)

    def delete_agent(self, agent_id: str, *, force: bool = True) -> ApiResult:
        return self.delete(f"/agents/{agent_id}?force={'true' if force else 'false'}")

    # --- sessions ----------------------------------------------------------------

    def create_session(
        self,
        *,
        agent_id: str,
        credential_group_ids: list[str] | None = None,
        title: str | None = None,
    ) -> ApiResult:
        payload: dict = {
            "agent_id": agent_id,
            "credential_group_ids": credential_group_ids or [],
        }
        if title:
            payload["title"] = title
        return self.post("/sessions", json=payload)

    def get_session(self, session_id: str) -> ApiResult:
        return self.get(f"/sessions/{session_id}")

    def get_session_events(self, session_id: str, *, limit: int = 200) -> ApiResult:
        return self.get(f"/sessions/{session_id}/events", limit=limit)

    def stop_session(self, session_id: str) -> ApiResult:
        return self.post(f"/sessions/{session_id}/stop")

    def archive_session(self, session_id: str) -> ApiResult:
        return self.post(f"/sessions/{session_id}/archive")

    # --- tasks (drive a real run) ------------------------------------------------

    def create_task(
        self,
        *,
        agent_id: str,
        prompt: str,
        chat_session_id: str | None = None,
        timeout_sec: int = 600,
        max_retries: int = 0,
    ) -> ApiResult:
        payload: dict = {
            "agent_id": agent_id,
            "prompt": prompt,
            "timeout_sec": timeout_sec,
            "max_retries": max_retries,
        }
        if chat_session_id:
            payload["chat_session_id"] = chat_session_id
        return self.post("/tasks", json=payload)

    def get_task(self, task_id: str) -> ApiResult:
        return self.get(f"/tasks/{task_id}")

    # --- cleanup -----------------------------------------------------------------

    def cleanup(self, tracker: ResourceTracker) -> None:
        """Best-effort teardown. Agents are force-deleted first (which cascades
        their sessions), freeing bound groups for deletion; any untracked-agent
        sessions and the groups are then removed."""
        for aid in tracker.agent_ids:
            self.delete_agent(aid, force=True)
        for sid in tracker.session_ids:
            self.stop_session(sid)
            self.archive_session(sid)
        for gid in tracker.group_ids:
            res = self.delete_group(gid)
            if not res.ok:
                self.archive_group(gid)
