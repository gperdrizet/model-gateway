# Promptly API gateway

Promptly is an authenticated, metered API gateway for LLM inference.

## What you get

- Email-based registration and API key delivery
- Token-metered access to inference
- User dashboard with usage and balance
- Stripe and BTCPay top-up flows
- OpenAI-compatible API surface for chat completions
- Text-focused Responses API compatibility profile

## Base URL

`https://promptlyapi.com`

## Authentication

Use a Bearer token in the `Authorization` header:

```http
Authorization: Bearer sk-<your-key>
```

## Core endpoints

- `POST /v1/chat/completions`
- `POST /v1/responses` (text profile)
- `GET /v1/models`
- `GET /health`

## Current deployment

- Model: `gpt-oss-20b-mxfp4.gguf`
- Context window: 32,768 tokens
- Slots: 1

## Example use cases

- [Zed coding agent](zed-coding-agent.md): point Zed at Promptly as an OpenAI-compatible backend for interactive coding work.

Continue with the API quickstart for copy-paste examples.
