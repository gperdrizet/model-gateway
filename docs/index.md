# Promptly API gateway

Promptly is an authenticated, metered API gateway for LLM inference.

## What you get

- Email-based registration and API key delivery
- Token-metered access to inference
- User dashboard with usage and balance
- Stripe and BTCPay top-up flows (planned; not yet available to users)
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

The deployed model and its runtime limits (context window, slots) change as the backend is tuned, so query them live rather than relying on a fixed value:

- Current model name: `GET /v1/models`
- Reasoning: the model thinks by default and returns its chain-of-thought in a non-standard `reasoning_content` field. On the current Qwen model, disable thinking with `chat_template_kwargs: {"enable_thinking": false}`.

## Example use cases

- [Using Zed with Promptly](zed-coding-agent.md): set up the Zed editor's AI assistant to use Promptly as its backend.
- [Using Cline with Promptly](cline.md): configure the Cline autonomous coding agent extension for VS Code.
- [Using GitHub Copilot Chat with Promptly](copilot-vscode.md): add Promptly as a Bring Your Own Key model in VS Code's Copilot Chat.
- [Using OpenClaw with Promptly](openclaw.md): point your OpenClaw personal assistant at Promptly.

Continue with the API quickstart for copy-paste examples.
