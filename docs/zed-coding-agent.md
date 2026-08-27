# Zed coding agent

Promptly exposes an OpenAI-compatible chat completions endpoint, so Zed can use it as a coding-assistant backend.

## Recommended deployment baseline

For a single developer using the service interactively, start with:

- Context size: 262,144 tokens (the full context the deployed model and server are configured for)
- Slots: 1

Keep slots at 1 unless you have concurrent users or concurrent agent jobs.

## Current deployed Promptly backend

As of this documentation update, Promptly is pointed at:

- Model: `Qwen3.8-27B-Q8_0.gguf`
- Context window: 262,144 tokens
- Slots: 1
- Default reasoning effort: `medium` (the model is a hybrid thinking/instruct model; thinking tokens count against your balance)

This is the baseline the repo and site should reflect until the deployment changes.

## Example Zed provider values

Zed's exact settings UI varies a bit by version, but the values you want are the same: an OpenAI-compatible provider pointed at Promptly.

```json
{
  "provider": "openai-compatible",
  "base_url": "https://promptlyapi.com/v1",
  "api_key": "env:PROMPTLY_API_KEY",
  "model": "Qwen3.8-27B-Q8_0.gguf",
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

- Full 262,144 context
- 1 slot
- low temperature
- `reasoning_effort: medium` (the server default; lower it to `low` or `none` for latency-sensitive edits, or raise it to `high` for harder problems)

That is the most conservative choice and usually the best first pass for a coding assistant.