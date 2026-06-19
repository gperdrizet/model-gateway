# Promptly API: quick reference for AI agents

Base URL: `https://promptlyapi.com`
Auth: `Authorization: Bearer sk-<your-key>`
Protocol: OpenAI-compatible REST

Supported compatibility surfaces:
- `/v1/chat/completions` (full primary path)
- `/v1/responses` (text-generation profile)

## Chat completions

```bash
curl https://promptlyapi.com/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

The `model` field is accepted but ignored; the server uses whichever model is loaded. The actual model name is returned in the response (e.g. `gpt-oss-20b-mxfp4.gguf`).

**Context window:** 16,384 tokens per request (65,536 total across 4 parallel slots).

## Responses API (text profile)

```bash
curl https://promptlyapi.com/v1/responses \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "input": "Hello!"
  }'
```

This endpoint supports text-generation requests only. Multimodal input and tools are rejected with a clear `400` error.

## Response format

Standard OpenAI shape. Always read `choices[0].message.content`.

The loaded model is a reasoning model. Responses include a non-standard `reasoning_content` field; ignore it, it is the model's internal chain-of-thought, not the answer:

```json
{
  "choices": [{
    "finish_reason": "stop",
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Hello!",
      "reasoning_content": "The user says: \"Say hello.\" ..."
    }
  }],
  "model": "gpt-oss-20b-mxfp4.gguf",
  "usage": {
    "prompt_tokens": 70,
    "completion_tokens": 46,
    "total_tokens": 116
  }
}
```

## Streaming

Pass `"stream": true` in the request body. Responses are server-sent events (SSE), identical to the OpenAI streaming format.

## List models

```bash
curl https://promptlyapi.com/v1/models \
  -H "Authorization: Bearer sk-your-key"
```

## Error codes

| Status | Meaning |
|--------|---------|
| 401 | Missing or invalid API key |
| 402 | Token balance exhausted; purchase more at `https://promptlyapi.com/dashboard?key=sk-your-key` |
| 429 | Rate limit exceeded (120 req/min per IP, 60 req/min per key) |
| 502 | Upstream inference server error |

## Python (OpenAI SDK)

This is the current `OpenAI(...)` client pattern. Both examples below are supported.

```python
import os

from openai import OpenAI

client = OpenAI(
    base_url="https://promptlyapi.com/v1",
    api_key=os.environ["PROMPTLY_API_KEY"],
)

completion = client.chat.completions.create(
    model="default",
    messages=[{"role": "user", "content": "Hello!"}],
)

# Use .content — ignore .reasoning_content if present
print(completion.choices[0].message.content)
```

```python
import os

from openai import OpenAI

client = OpenAI(
    base_url="https://promptlyapi.com/v1",
    api_key=os.environ["PROMPTLY_API_KEY"],
)

response = client.responses.create(
    model="default",
    input="Hello!",
)

print(response.output_text)
```
