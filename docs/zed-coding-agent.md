# Using Promptly with Zed

[Zed](https://zed.dev) is a fast, open-source code editor with a built-in AI coding assistant. Zed can talk to any OpenAI-compatible API, so you can point it at Promptly and use it as your inference backend for chat, edits, and agentic coding.

## 1. Get a Promptly API key

If you don't already have one, go to `https://promptlyapi.com`, create an account, and you'll receive an API key by email. New accounts start with a free trial (100,000 tokens, 7 days).

## 2. Install Zed

Download Zed from [zed.dev/download](https://zed.dev/download) (macOS, Linux, and Windows are supported), or install it with your platform's package manager.

## 3. Add Promptly as an OpenAI-compatible provider

In Zed, open **Settings** (`Cmd+,` / `Ctrl+,`) and add an OpenAI-compatible provider pointed at Promptly. In `settings.json`, this looks like:

```json
{
  "language_models": {
    "openai_compatible": {
      "Promptly": {
        "api_url": "https://promptlyapi.com/v1",
        "available_models": [
          {
            "name": "default",
            "display_name": "Promptly",
            "max_tokens": 262144
          }
        ]
      }
    }
  }
}
```

Zed's exact settings UI and JSON schema can shift a bit between versions - if the fields above don't match what you see, search Zed's docs for "OpenAI-compatible provider" and use the same `api_url` and model values.

Set your API key via the environment variable Zed's provider setup expects (usually `PROMPTLY_API_KEY`), or paste it directly into the provider's API key field if Zed prompts for it. Don't commit your key to a repo or settings file that gets shared.

## 4. Pick the model in Zed's assistant panel

Promptly ignores whatever model name you send and always serves whichever model is currently loaded on the backend, so the `"name": "default"` placeholder above works regardless. Select "Promptly" as the provider and "default" as the model in Zed's assistant panel, then start chatting or ask it to make edits.

## What you're actually talking to

- **Model:** `Qwen3.8-27B-Q8_0.gguf`, a hybrid thinking/instruct model
- **Context window:** 262,144 tokens
- **Reasoning:** the server defaults to `reasoning_effort: medium`; thinking tokens count against your balance the same as regular output tokens

You can check the currently loaded model at any time:

```bash
curl https://promptlyapi.com/v1/models \
  -H "Authorization: Bearer sk-your-key-here"
```

## Suggested settings for interactive coding

For normal editor-driven coding work (not heavy agentic/batch use), a reasonable starting point is:

- Low temperature (e.g. `0.2`) for more predictable edits and completions
- Default `reasoning_effort` (`medium`) for most tasks; if you want faster, cheaper responses for simple edits, override it to `low` or `none` per request; for harder problems, `high`
- No need to change `max_tokens`/context settings from the default above unless you're working with unusually large files or long conversations

## Notes

- Promptly accepts `POST /v1/chat/completions` and `POST /v1/responses`; Zed uses chat completions.
- Because Promptly always serves the currently loaded backend model regardless of what you request, you don't need to update your Zed config if the backend model changes later.
- Check your token balance any time at `https://promptlyapi.com/dashboard?key=sk-your-key-here`.
