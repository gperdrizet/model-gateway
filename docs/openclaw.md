# Using Promptly with OpenClaw

[OpenClaw](https://openclaw.ai) is an open-source personal AI assistant that runs on your own machine and meets you in the chat apps you already use (WhatsApp, Telegram, Discord, Slack, Signal, iMessage, and more). It connects to a range of hosted and local model providers through one Gateway - you can point that Gateway at Promptly.

## 1. Get a Promptly API key

If you don't already have one, go to `https://promptlyapi.com`, create an account, and you'll receive an API key by email.

## 2. Install OpenClaw

```bash
# macOS / Linux / WSL2
curl -fsSL https://openclaw.ai/install.sh | bash
```

```powershell
# Windows PowerShell
iwr -useb https://openclaw.ai/install.ps1 | iex
```

Then run onboarding:

```bash
openclaw onboard --install-daemon
```

Complete the onboarding wizard. See OpenClaw's [getting started guide](https://docs.openclaw.ai/start/getting-started) for channel setup (WhatsApp, Telegram, etc.) beyond model configuration.

## 3. Add Promptly as a custom model provider

Promptly isn't one of OpenClaw's built-in provider plugins, but OpenClaw supports arbitrary OpenAI-compatible endpoints through `models.providers` - the same mechanism it documents for local proxies like LM Studio and vLLM. Add this to your OpenClaw config:

```json5
{
  agents: {
    defaults: {
      model: { primary: "promptly/default" },
    },
  },
  models: {
    mode: "merge",
    providers: {
      promptly: {
        baseUrl: "https://promptlyapi.com/v1",
        apiKey: "${PROMPTLY_API_KEY}",
        api: "openai-completions",
        models: [
          {
            id: "default",
            name: "Promptly (Qwen3.8-27B)",
            reasoning: true,
            contextWindow: 262144,
            maxTokens: 8192,
          },
        ],
      },
    },
  },
}
```

Set `PROMPTLY_API_KEY` in your environment (or OpenClaw's `env.vars`) rather than hardcoding the key in config.

## 4. Verify and select the model

```bash
openclaw models list
openclaw models set promptly/default
```

`openclaw models list` should show `promptly/default` in the catalog. `openclaw models set` makes it the primary model without overwriting other provider config.

## What you're actually talking to

- **Model:** `Qwen3.8-27B-Q8_0.gguf`, a hybrid thinking/instruct model
- **Context window:** 262,144 tokens
- **Reasoning:** Promptly defaults to `reasoning_effort: medium` server-side; thinking tokens count against your balance the same as output tokens

## Reasoning effort

Promptly's server default (`medium`) applies automatically. Whether you can override `reasoning_effort` per request from OpenClaw's side depends on whether its generic `openai-completions` provider path forwards extra body fields the way it does `params.chat_template_kwargs` for the bundled vLLM provider - check OpenClaw's [model providers reference](https://docs.openclaw.ai/concepts/model-providers) for the current behavior if you need to change this. Overriding server-side isn't necessary for normal use.

## Notes

- Promptly ignores whatever `id` you send and always serves whichever model is currently loaded, so `"id": "default"` above will keep working if the backend model changes.
- Check your token balance any time at `https://promptlyapi.com/dashboard?key=sk-your-key-here`.
- OpenClaw's security model treats inbound messages (from WhatsApp, Telegram, etc.) as untrusted input by default - see OpenClaw's [security guide](https://docs.openclaw.ai/gateway/security) before connecting other users or exposing your Gateway remotely. This is independent of Promptly and applies regardless of which model provider you use.
