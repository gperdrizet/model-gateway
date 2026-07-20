# Zed coding agent

Promptly exposes an OpenAI-compatible chat completions endpoint, so Zed can use it as a coding-assistant backend.

## Recommended deployment baseline

For a single developer using the service interactively, start with:

- Context size: 32,768 tokens
- Slots: 1

That gives you enough room for normal editor-driven coding tasks without paying extra latency or memory for concurrency you do not need yet. Keep slots at 1 unless you have concurrent users or concurrent agent jobs.

## Current deployed Promptly backend

As of this documentation update, Promptly is pointed at:

- Model: `gpt-oss-20b-mxfp4.gguf`
- Context window: 32,768 tokens
- Slots: 1

This is the baseline the repo and site should reflect until the deployment changes.

## Example Zed provider values

Zed's exact settings UI varies a bit by version, but the values you want are the same: an OpenAI-compatible provider pointed at Promptly.

```json
{
  "provider": "openai-compatible",
  "base_url": "https://promptlyapi.com/v1",
  "api_key": "env:PROMPTLY_API_KEY",
  "model": "gpt-oss-20b-mxfp4.gguf",
  "temperature": 0.2,
  "max_output_tokens": 4096
}
```

Notes:

- Promptly accepts `POST /v1/chat/completions` and `POST /v1/responses`.
- Promptly ignores the `model` field and serves whichever backend model is currently loaded.
- If you switch the backend model later, you usually do not need to change the editor config.

## Good default for today

If you are using the current single-user Promptly deployment, this is the simplest setup to start with:

- 32k context
- 1 slot
- low temperature

That is the most conservative choice and usually the best first pass for a coding assistant.