# Using Promptly with Cline

[Cline](https://cline.bot) is a popular open-source autonomous coding agent extension for VS Code (and compatible editors). It has a dedicated **OpenAI Compatible** provider mode built for exactly this kind of setup: pointing it at any API that speaks the OpenAI Chat Completions format.

## 1. Get a Promptly API key

If you don't already have one, go to `https://promptlyapi.com`, create an account, and you'll receive an API key by email.

## 2. Install Cline

Install the **Cline** extension from the VS Code Marketplace (or your editor's equivalent extension marketplace).

## 3. Configure the OpenAI Compatible provider

Open Cline's settings (gear icon in the Cline panel) and set:

- **API Provider:** `OpenAI Compatible`
- **Base URL:** `https://promptlyapi.com/v1`
- **API Key:** your Promptly key (`sk-...`)
- **Model:** `default`

## 4. Set model configuration

Cline's OpenAI Compatible provider lets you fill in model metadata manually since it has no way to discover it automatically. Set:

- **Context Window:** `65536`
- **Max Output Tokens:** a reasonable ceiling for your use, e.g. `8192`
- **Image Support:** off (the current backend is text-only)
- **Computer Use / tool calling:** on, if you want Cline's agentic file-editing and command features to work

Click **Verify** (or equivalent) to confirm the connection works before starting a task.

## What you're actually talking to

- **Model:** whichever model is currently loaded (query `/v1/models`); currently a Qwen3 reasoning model
- **Reasoning:** the model thinks by default and returns its chain-of-thought in `reasoning_content`; those thinking tokens bill the same as regular output. Disable thinking by sending `chat_template_kwargs: {"enable_thinking": false}`.

## Notes

- Promptly ignores whatever `model` field you send and always serves whichever model is currently loaded, so the `default` model ID above will keep working if the backend changes.
- Cline's OpenAI Compatible provider forwards your request body largely as-is, so extra fields like `chat_template_kwargs` reach the backend. (A top-level `reasoning_effort` field is ignored by the current Qwen model; to set reasoning depth pass `chat_template_kwargs: {"reasoning_effort": "low|medium|high|xhigh"}`, and use `enable_thinking` as above to turn thinking off.)
- Check your token balance any time at `https://promptlyapi.com/dashboard?key=sk-your-key-here`.
