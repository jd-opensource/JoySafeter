"""Anthropic-compatible HTTP proxy that forwards to OpenAI chat/completions."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .auth import AuthError, extract_inbound_token, mask_token
from .config import ProxySettings, SettingsError, build_openai_url
from .converters import (
    ConversionError,
    anthropic_error_payload,
    convert_anthropic_request_to_openai,
    convert_openai_models_to_anthropic,
    convert_openai_response_to_anthropic,
    extract_upstream_error_message,
)
from .streaming import OpenAIToAnthropicStreamConverter

logger = logging.getLogger(__name__)


def create_app(
    settings: ProxySettings | None = None,
    upstream_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    """Create the proxy FastAPI app.

    Use with uvicorn factory mode:
    `uvicorn proxy.app:create_app --factory --host 0.0.0.0 --port 8080`
    """
    if settings is None:
        settings = ProxySettings.from_env()

    _configure_logging(settings.log_level)

    app = FastAPI(title="OpenAI to Anthropic Proxy", version="0.1.0")
    app.state.settings = settings
    app.state.upstream_transport = upstream_transport

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models(request: Request) -> Response:
        try:
            inbound_token = extract_inbound_token(request.headers)
        except AuthError as exc:
            return _anthropic_error_response(401, str(exc), "authentication_error")

        logger.info("/v1/models request using token=%s", mask_token(inbound_token))

        settings = request.app.state.settings
        url = build_openai_url(settings.openai_base_url, "models")

        headers = _build_upstream_headers(settings, inbound_token)

        async with _new_async_client(request.app) as client:
            try:
                upstream = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                logger.exception("Upstream /v1/models request failed")
                fallback_response = _fallback_models_response(settings, f"upstream request failed: {exc}")
                if fallback_response is not None:
                    return fallback_response
                return _anthropic_error_response(502, f"Upstream request failed: {exc}", "api_error")

        if upstream.status_code >= 400:
            message = extract_upstream_error_message(upstream.text)
            fallback_response = _fallback_models_response(
                settings,
                f"upstream returned {upstream.status_code}: {message}",
            )
            if fallback_response is not None:
                return fallback_response
            return _anthropic_error_response(upstream.status_code, message, "api_error")

        try:
            upstream_json = upstream.json()
        except json.JSONDecodeError:
            fallback_response = _fallback_models_response(settings, "upstream returned invalid JSON")
            if fallback_response is not None:
                return fallback_response
            return _anthropic_error_response(502, "Upstream returned invalid JSON", "api_error")

        converted = convert_openai_models_to_anthropic(upstream_json)
        return JSONResponse(converted)

    @app.post("/v1/messages")
    async def messages(request: Request) -> Response:
        try:
            inbound_token = extract_inbound_token(request.headers)
        except AuthError as exc:
            return _anthropic_error_response(401, str(exc), "authentication_error")

        try:
            payload = await request.json()
        except Exception:
            return _anthropic_error_response(400, "Request body must be valid JSON", "invalid_request_error")

        if not isinstance(payload, dict):
            return _anthropic_error_response(400, "Request body must be a JSON object", "invalid_request_error")

        settings = request.app.state.settings

        try:
            converted = convert_anthropic_request_to_openai(payload, settings)
        except ConversionError as exc:
            return _anthropic_error_response(400, str(exc), "invalid_request_error")

        logger.info(
            "/v1/messages model=%s mapped_model=%s stream=%s token=%s",
            converted.original_model,
            converted.mapped_model,
            converted.stream,
            mask_token(inbound_token),
        )

        url = build_openai_url(settings.openai_base_url, "chat/completions")
        headers = _build_upstream_headers(settings, inbound_token)

        if converted.stream:
            return await _handle_streaming_messages(request, converted, url, headers)

        async with _new_async_client(request.app) as client:
            try:
                upstream = await client.post(
                    url,
                    headers=headers,
                    json=converted.openai_payload,
                )
            except httpx.HTTPError as exc:
                logger.exception("Upstream non-streaming request failed")
                return _anthropic_error_response(502, f"Upstream request failed: {exc}", "api_error")

        if upstream.status_code >= 400:
            message = extract_upstream_error_message(upstream.text)
            return _anthropic_error_response(upstream.status_code, message, "api_error")

        try:
            upstream_json = upstream.json()
        except json.JSONDecodeError:
            return _anthropic_error_response(502, "Upstream returned invalid JSON", "api_error")

        anthropic_response = convert_openai_response_to_anthropic(
            upstream_json,
            model_name=converted.original_model,
        )
        return JSONResponse(anthropic_response)

    return app


async def _handle_streaming_messages(
    request: Request,
    converted: Any,
    url: str,
    headers: dict[str, str],
) -> Response:
    client = _new_async_client(request.app)
    req = client.build_request(
        "POST",
        url,
        headers=headers,
        json=converted.openai_payload,
    )

    try:
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.exception("Upstream streaming request failed before response")
        return _anthropic_error_response(502, f"Upstream request failed: {exc}", "api_error")

    if upstream.status_code >= 400:
        body = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        message = extract_upstream_error_message(body.decode("utf-8", errors="ignore"))
        return _anthropic_error_response(upstream.status_code, message, "api_error")

    converter = OpenAIToAnthropicStreamConverter(model_name=converted.original_model)

    async def event_generator():
        try:
            async for line in upstream.aiter_lines():
                events = converter.consume_sse_line(line)
                for event in events:
                    yield event

            for event in converter.finalize():
                yield event
        except Exception:
            logger.exception("Failed while streaming upstream response")
            for event in converter.finalize("stop"):
                yield event
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _new_async_client(app: FastAPI) -> httpx.AsyncClient:
    settings: ProxySettings = app.state.settings
    upstream_transport: httpx.BaseTransport | None = app.state.upstream_transport
    timeout = httpx.Timeout(settings.upstream_timeout_seconds)
    return httpx.AsyncClient(timeout=timeout, transport=upstream_transport)


def _build_upstream_headers(settings: ProxySettings, inbound_token: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {inbound_token}",
        "Content-Type": "application/json",
    }

    for key, value in settings.upstream_extra_headers.items():
        if key.lower() in {"authorization", "content-type"}:
            continue
        headers[key] = value

    return headers


def _anthropic_error_response(status_code: int, message: str, error_type: str) -> JSONResponse:
    return JSONResponse(
        anthropic_error_payload(message=message, error_type=error_type),
        status_code=status_code,
    )


def _fallback_models_response(settings: ProxySettings, reason: str) -> JSONResponse | None:
    if not settings.fallback_models:
        return None

    logger.warning("Using FALLBACK_MODELS_JSON because %s", reason)
    return JSONResponse(
        {
            "data": settings.fallback_models,
            "has_more": False,
        },
        status_code=200,
    )


def _configure_logging(log_level: str) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root.setLevel(getattr(logging, log_level, logging.INFO))


if __name__ == "__main__":
    try:
        import uvicorn

        uvicorn.run(
            "proxy.app:create_app",
            factory=True,
            host="0.0.0.0",
            port=8080,
            reload=False,
        )
    except SettingsError as exc:
        raise SystemExit(f"Configuration error: {exc}")
