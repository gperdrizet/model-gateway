"""
Async proxy: forwards requests to llama-server and extracts token usage.

Privacy guarantee: request and response bodies are streamed through without
being stored. Only the integer token counts from the final `usage` field
are returned to the caller for metering.
"""

import json
import os
from typing import AsyncIterator

import httpx

LLAMA_BASE_URL = os.environ["LLAMA_BASE_URL"].rstrip("/")
LLAMA_API_KEY = os.environ["LLAMA_API_KEY"]

# Shared async client — connection pooling across requests
_client = httpx.AsyncClient(
    base_url=LLAMA_BASE_URL,
    timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=5.0),
)


def _inject_usage_tracking(body: dict) -> dict:
    """
    For streaming requests, inject stream_options.include_usage = true so
    llama-server sends a final chunk with token counts.
    """
    if body.get("stream"):
        opts = body.get("stream_options") or {}
        opts["include_usage"] = True
        body = {**body, "stream_options": opts}
    return body


async def proxy_request(
    method: str,
    path: str,
    headers: dict,
    body: dict | None,
) -> tuple[httpx.Response, int, int]:
    """
    Forward a non-streaming request to llama-server.

    Returns (response, input_tokens, output_tokens).
    The response is returned as-is for FastAPI to relay to the client.
    """
    forward_headers = {
        k: v for k, v in headers.items()
        if k.lower() not in ("host", "authorization", "content-length")
    }
    forward_headers["Authorization"] = f"Bearer {LLAMA_API_KEY}"

    response = await _client.request(
        method,
        path,
        headers=forward_headers,
        content=json.dumps(body).encode() if body is not None else None,
    )

    input_tokens, output_tokens = 0, 0
    try:
        data = response.json()
        usage = data.get("usage") or {}
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
    except Exception:
        pass

    return response, input_tokens, output_tokens


async def proxy_stream(
    method: str,
    path: str,
    headers: dict,
    body: dict,
) -> AsyncIterator[tuple[bytes, int, int]]:
    """
    Forward a streaming request to llama-server.

    Yields raw SSE chunks as bytes. The final tuple yielded has non-zero
    token counts parsed from the last data chunk containing a `usage` field.

    Usage:
        async for chunk, in_tok, out_tok in proxy_stream(...):
            yield chunk   # relay to client
            # in_tok / out_tok are non-zero only on the final chunk
    """
    body = _inject_usage_tracking(body)

    forward_headers = {
        k: v for k, v in headers.items()
        if k.lower() not in ("host", "authorization", "content-length")
    }
    forward_headers["Authorization"] = f"Bearer {LLAMA_API_KEY}"

    input_tokens, output_tokens = 0, 0

    async with _client.stream(
        method,
        path,
        headers=forward_headers,
        content=json.dumps(body).encode(),
    ) as response:
        async for chunk in response.aiter_bytes():
            # Try to extract usage from this chunk before yielding
            in_tok, out_tok = _parse_sse_usage(chunk)
            if in_tok or out_tok:
                input_tokens, output_tokens = in_tok, out_tok

            yield chunk, 0, 0

    # Yield a zero-byte sentinel carrying the final token counts
    yield b"", input_tokens, output_tokens


def _parse_sse_usage(chunk: bytes) -> tuple[int, int]:
    """
    Extract token counts from an SSE chunk if it contains a usage field.
    Returns (0, 0) if not found or not parseable.
    """
    try:
        text = chunk.decode("utf-8", errors="ignore")
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                continue
            data = json.loads(payload)
            usage = data.get("usage")
            if usage:
                return (
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
    except Exception:
        pass
    return 0, 0
